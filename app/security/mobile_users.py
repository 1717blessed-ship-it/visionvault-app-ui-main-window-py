"""Cuentas de vendedores y autorización temporal previa al enlace móvil."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import re
import secrets
import sqlite3
import threading


PASSWORD_ITERATIONS = 310_000
MIN_PASSWORD_LENGTH = 10
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
LINK_TOKEN_MINUTES = 10
_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,40}$")
_DUMMY_SALT = bytes.fromhex("970ff471b3e91d33c6d47ef3df4dc7ab")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _hash_password(password: str, salt: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, int(iterations)
    ).hex()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_username(username: str) -> str:
    value = str(username or "").strip()
    if not _USERNAME_PATTERN.fullmatch(value):
        raise ValueError(
            "El usuario debe tener entre 3 y 40 caracteres y usar solo "
            "letras, números, punto, guion o guion bajo."
        )
    return value


def validate_password(password: str) -> str:
    value = str(password or "")
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres."
        )
    if len(value) > 200:
        raise ValueError("La contraseña es demasiado larga.")
    if not any(char.isalpha() for char in value) or not any(
        char.isdigit() for char in value
    ):
        raise ValueError("La contraseña debe incluir letras y números.")
    return value


@dataclass(frozen=True)
class MobileUser:
    id: int
    username: str
    display_name: str
    active: bool
    failed_attempts: int
    locked_until: str
    last_login_at: str
    created_at: str
    updated_at: str
    device_count: int = 0


@dataclass(frozen=True)
class LoginResult:
    success: bool
    message: str
    link_token: str = ""
    expires_in: int = 0
    user: MobileUser | None = None


class MobileUserRepository:
    """Administra vendedores sin almacenar contraseñas ni tokens en claro."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self._lock = threading.RLock()
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self._lock:
            self.connection.execute(
                """CREATE TABLE IF NOT EXISTS mobile_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    display_name TEXT NOT NULL DEFAULT '',
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    password_iterations INTEGER NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    failed_attempts INTEGER NOT NULL DEFAULT 0,
                    locked_until TEXT DEFAULT '',
                    last_login_at TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            self.connection.execute(
                """CREATE TABLE IF NOT EXISTS mobile_link_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    used INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES mobile_users(id)
                )"""
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_mobile_link_tokens_lookup "
                "ON mobile_link_tokens(token_hash, used, expires_at)"
            )
            device_table = self.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'mobile_devices'"
            ).fetchone()
            if device_table:
                device_columns = {
                    str(row[1])
                    for row in self.connection.execute(
                        "PRAGMA table_info(mobile_devices)"
                    )
                }
                if "user_id" not in device_columns:
                    self.connection.execute(
                        "ALTER TABLE mobile_devices ADD COLUMN user_id INTEGER"
                    )
                self.connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_mobile_devices_user "
                    "ON mobile_devices(user_id, active)"
                )
            self.connection.commit()

    def list_users(self) -> list[MobileUser]:
        with self._lock:
            has_devices = bool(
                self.connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                    "AND name = 'mobile_devices'"
                ).fetchone()
            )
            device_count_sql = (
                "(SELECT COUNT(*) FROM mobile_devices d "
                "WHERE d.user_id = u.id AND d.active = 1)"
                if has_devices
                else "0"
            )
            rows = self.connection.execute(
                f"""SELECT u.*, {device_count_sql} AS device_count
                      FROM mobile_users u
                     ORDER BY u.active DESC, u.display_name COLLATE NOCASE,
                              u.username COLLATE NOCASE"""
            ).fetchall()
        return [self._to_user(row) for row in rows]

    def get_user(self, user_id: int) -> MobileUser | None:
        return next(
            (user for user in self.list_users() if user.id == int(user_id)), None
        )

    def create_user(
        self, username: str, display_name: str, password: str
    ) -> MobileUser:
        clean_username = normalize_username(username)
        clean_name = str(display_name or "").strip()[:120] or clean_username
        clean_password = validate_password(password)
        salt = secrets.token_bytes(16)
        password_hash = _hash_password(
            clean_password, salt, PASSWORD_ITERATIONS
        )
        now = _now()
        with self._lock:
            try:
                cursor = self.connection.execute(
                    """INSERT INTO mobile_users(
                           username, display_name, password_hash, password_salt,
                           password_iterations, active, created_at, updated_at
                       ) VALUES(?, ?, ?, ?, ?, 1, ?, ?)""",
                    (
                        clean_username,
                        clean_name,
                        password_hash,
                        salt.hex(),
                        PASSWORD_ITERATIONS,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("Ese nombre de usuario ya existe.") from error
            self.connection.commit()
            user_id = int(cursor.lastrowid)
        user = self.get_user(user_id)
        if user is None:
            raise RuntimeError("No se pudo recuperar el vendedor creado.")
        return user

    def reset_password(self, user_id: int, password: str) -> None:
        clean_password = validate_password(password)
        salt = secrets.token_bytes(16)
        password_hash = _hash_password(
            clean_password, salt, PASSWORD_ITERATIONS
        )
        now = _now()
        with self._lock:
            if self._user_row_locked(user_id) is None:
                raise ValueError("El vendedor seleccionado ya no existe.")
            self.connection.execute(
                """UPDATE mobile_users
                      SET password_hash = ?, password_salt = ?,
                          password_iterations = ?, failed_attempts = 0,
                          locked_until = '', updated_at = ?
                    WHERE id = ?""",
                (
                    password_hash,
                    salt.hex(),
                    PASSWORD_ITERATIONS,
                    now,
                    int(user_id),
                ),
            )
            self._revoke_sessions_locked(user_id)
            self.connection.commit()

    def set_active(self, user_id: int, active: bool) -> MobileUser:
        now = _now()
        with self._lock:
            if self._user_row_locked(user_id) is None:
                raise ValueError("El vendedor seleccionado ya no existe.")
            self.connection.execute(
                """UPDATE mobile_users
                      SET active = ?, failed_attempts = 0, locked_until = '',
                          updated_at = ?
                    WHERE id = ?""",
                (int(bool(active)), now, int(user_id)),
            )
            if not active:
                self._revoke_sessions_locked(user_id)
            self.connection.commit()
        user = self.get_user(user_id)
        if user is None:
            raise RuntimeError("No se pudo recuperar el vendedor actualizado.")
        return user

    def unlock(self, user_id: int) -> None:
        with self._lock:
            if self._user_row_locked(user_id) is None:
                raise ValueError("El vendedor seleccionado ya no existe.")
            self.connection.execute(
                """UPDATE mobile_users
                      SET failed_attempts = 0, locked_until = '', updated_at = ?
                    WHERE id = ?""",
                (_now(), int(user_id)),
            )
            self.connection.commit()

    def authenticate(self, username: str, password: str) -> LoginResult:
        raw_username = str(username or "").strip()
        raw_password = str(password or "")
        if len(raw_username) > 80 or len(raw_password) > 200:
            return LoginResult(False, "Usuario o contraseña incorrectos.")
        now = datetime.now()
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM mobile_users WHERE username = ? COLLATE NOCASE",
                (raw_username,),
            ).fetchone()

            # Mantiene un costo similar aunque el usuario no exista.
            if row is None:
                _hash_password(raw_password, _DUMMY_SALT, PASSWORD_ITERATIONS)
                return LoginResult(False, "Usuario o contraseña incorrectos.")

            if not bool(row["active"]):
                _hash_password(
                    raw_password,
                    bytes.fromhex(str(row["password_salt"])),
                    int(row["password_iterations"]),
                )
                return LoginResult(False, "La cuenta está deshabilitada.")

            locked_until = str(row["locked_until"] or "")
            if locked_until:
                try:
                    if datetime.fromisoformat(locked_until) > now:
                        return LoginResult(
                            False,
                            "Cuenta bloqueada temporalmente. Intentá nuevamente más tarde.",
                        )
                except ValueError:
                    pass

            candidate_hash = _hash_password(
                raw_password,
                bytes.fromhex(str(row["password_salt"])),
                int(row["password_iterations"]),
            )
            valid = secrets.compare_digest(
                candidate_hash, str(row["password_hash"])
            )
            if not valid:
                attempts = int(row["failed_attempts"] or 0) + 1
                new_locked_until = ""
                if attempts >= MAX_LOGIN_ATTEMPTS:
                    new_locked_until = (
                        now + timedelta(minutes=LOCKOUT_MINUTES)
                    ).isoformat(timespec="seconds")
                    attempts = 0
                self.connection.execute(
                    """UPDATE mobile_users
                          SET failed_attempts = ?, locked_until = ?, updated_at = ?
                        WHERE id = ?""",
                    (
                        attempts,
                        new_locked_until,
                        now.isoformat(timespec="seconds"),
                        int(row["id"]),
                    ),
                )
                self.connection.commit()
                message = (
                    "Cuenta bloqueada temporalmente. Intentá nuevamente más tarde."
                    if new_locked_until
                    else "Usuario o contraseña incorrectos."
                )
                return LoginResult(False, message)

            link_token = secrets.token_urlsafe(32)
            expires_at = (
                now + timedelta(minutes=LINK_TOKEN_MINUTES)
            ).isoformat(timespec="seconds")
            now_text = now.isoformat(timespec="seconds")
            self.connection.execute(
                """UPDATE mobile_users
                      SET failed_attempts = 0, locked_until = '',
                          last_login_at = ?, updated_at = ?
                    WHERE id = ?""",
                (now_text, now_text, int(row["id"])),
            )
            self.connection.execute(
                """INSERT INTO mobile_link_tokens(
                       user_id, token_hash, used, created_at, expires_at
                   ) VALUES(?, ?, 0, ?, ?)""",
                (int(row["id"]), _hash_token(link_token), now_text, expires_at),
            )
            self.connection.execute(
                "DELETE FROM mobile_link_tokens "
                "WHERE used = 1 OR expires_at < ?",
                (now_text,),
            )
            self.connection.commit()
        user = self.get_user(int(row["id"]))
        return LoginResult(
            True,
            "Credenciales válidas.",
            link_token=link_token,
            expires_in=LINK_TOKEN_MINUTES * 60,
            user=user,
        )

    def validate_link_token(self, token: str) -> MobileUser | None:
        token_hash = _hash_token(str(token or ""))
        now = _now()
        with self._lock:
            row = self.connection.execute(
                """SELECT u.id
                     FROM mobile_link_tokens t
                     JOIN mobile_users u ON u.id = t.user_id
                    WHERE t.token_hash = ? AND t.used = 0
                      AND t.expires_at >= ? AND u.active = 1""",
                (token_hash, now),
            ).fetchone()
        return self.get_user(int(row["id"])) if row else None

    def claim_link_token(self, token: str) -> MobileUser | None:
        token_hash = _hash_token(str(token or ""))
        now = _now()
        with self._lock:
            row = self.connection.execute(
                """SELECT t.id, u.id AS user_id
                     FROM mobile_link_tokens t
                     JOIN mobile_users u ON u.id = t.user_id
                    WHERE t.token_hash = ? AND t.used = 0
                      AND t.expires_at >= ? AND u.active = 1""",
                (token_hash, now),
            ).fetchone()
            if not row:
                return None
            cursor = self.connection.execute(
                "UPDATE mobile_link_tokens SET used = 1 WHERE id = ? AND used = 0",
                (int(row["id"]),),
            )
            self.connection.commit()
            if cursor.rowcount != 1:
                return None
            user_id = int(row["user_id"])
        return self.get_user(user_id)

    def _user_row_locked(self, user_id: int):
        return self.connection.execute(
            "SELECT * FROM mobile_users WHERE id = ?", (int(user_id),)
        ).fetchone()

    def _revoke_sessions_locked(self, user_id: int) -> None:
        self.connection.execute(
            "UPDATE mobile_link_tokens SET used = 1 WHERE user_id = ?",
            (int(user_id),),
        )
        has_devices = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'mobile_devices'"
        ).fetchone()
        if has_devices:
            self.connection.execute(
                """UPDATE mobile_devices
                      SET active = 0, session_token_hash = NULL,
                          session_expires_at = NULL
                    WHERE user_id = ?""",
                (int(user_id),),
            )

    @staticmethod
    def _to_user(row) -> MobileUser:
        keys = set(row.keys())
        return MobileUser(
            id=int(row["id"]),
            username=str(row["username"]),
            display_name=str(row["display_name"] or ""),
            active=bool(row["active"]),
            failed_attempts=int(row["failed_attempts"] or 0),
            locked_until=str(row["locked_until"] or ""),
            last_login_at=str(row["last_login_at"] or ""),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            device_count=int(row["device_count"] or 0)
            if "device_count" in keys
            else 0,
        )
