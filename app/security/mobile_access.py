"""Persistencia y evaluación de la whitelist de acceso a la API móvil."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import ipaddress
import json
import logging
import sqlite3
import threading
import time
from typing import Any


logger = logging.getLogger(__name__)

WHITELIST_SETTING_KEY = "mobile_api.ip_whitelist_enabled"
DEFAULTS_SEEDED_SETTING_KEY = "mobile_api.ip_whitelist_defaults_seeded"
DEFAULT_MOBILE_NETWORKS: tuple[tuple[str, str], ...] = (
    ("127.0.0.1", "Este equipo (IPv4)"),
    ("::1", "Este equipo (IPv6)"),
    ("192.168.0.0/16", "Red privada 192.168.x.x"),
    ("10.0.0.0/8", "Red privada 10.x.x.x"),
    ("172.16.0.0/12", "Red privada 172.16–172.31"),
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_ip_rule(value: str) -> str:
    """Valida y normaliza una IP individual o una red CIDR."""
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Ingresá una dirección IP o un rango CIDR.")
    try:
        if "/" in raw:
            return ipaddress.ip_network(raw, strict=False).with_prefixlen
        return ipaddress.ip_address(raw).compressed
    except ValueError as error:
        raise ValueError(
            "La dirección no es válida. Usá una IP (por ejemplo 203.0.113.8) "
            "o un rango CIDR (por ejemplo 192.168.1.0/24)."
        ) from error


@dataclass(frozen=True)
class MobileIPRule:
    id: int
    ip_address: str
    description: str
    active: bool
    created_at: str
    updated_at: str
    last_matched_at: str


class MobileAccessRepository:
    """Administra reglas persistentes y mantiene un snapshot rápido para la API."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self._lock = threading.RLock()
        self._enabled = False
        self._networks: tuple[
            tuple[int, str, ipaddress.IPv4Network | ipaddress.IPv6Network], ...
        ] = ()
        self._last_match_write: dict[int, float] = {}
        self._audit_throttle: dict[tuple[str, str, str], float] = {}
        self.ensure_schema()
        self.reload()

    def ensure_schema(self) -> None:
        """Instala la estructura de forma idempotente, incluso en bases de prueba."""
        now = _now()
        with self._lock:
            self.connection.execute(
                """CREATE TABLE IF NOT EXISTS app_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            self.connection.execute(
                """CREATE TABLE IF NOT EXISTS mobile_ip_whitelist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ip_address TEXT NOT NULL UNIQUE,
                    description TEXT DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_matched_at TEXT DEFAULT ''
                )"""
            )
            columns = {
                str(row[1])
                for row in self.connection.execute(
                    "PRAGMA table_info(mobile_ip_whitelist)"
                )
            }
            if "last_matched_at" not in columns:
                self.connection.execute(
                    "ALTER TABLE mobile_ip_whitelist "
                    "ADD COLUMN last_matched_at TEXT DEFAULT ''"
                )
            self.connection.execute(
                """CREATE TABLE IF NOT EXISTS mobile_security_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    ip_address TEXT DEFAULT '',
                    endpoint TEXT DEFAULT '',
                    details TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                )"""
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_mobile_security_audit_created "
                "ON mobile_security_audit(created_at DESC)"
            )
            self.connection.execute(
                """INSERT OR IGNORE INTO app_settings(
                       setting_key, setting_value, updated_at
                   ) VALUES(?, 'false', ?)""",
                (WHITELIST_SETTING_KEY, now),
            )
            seeded = self.connection.execute(
                "SELECT setting_value FROM app_settings WHERE setting_key = ?",
                (DEFAULTS_SEEDED_SETTING_KEY,),
            ).fetchone()
            if not seeded:
                for address, description in DEFAULT_MOBILE_NETWORKS:
                    self.connection.execute(
                        """INSERT OR IGNORE INTO mobile_ip_whitelist(
                               ip_address, description, active, created_at, updated_at
                           ) VALUES(?, ?, 0, ?, ?)""",
                        (address, description, now, now),
                    )
                self.connection.execute(
                    """INSERT INTO app_settings(
                           setting_key, setting_value, updated_at
                       ) VALUES(?, 'true', ?)""",
                    (DEFAULTS_SEEDED_SETTING_KEY, now),
                )
            self.connection.commit()

    def reload(self) -> None:
        """Recarga el snapshot evaluado por los hilos HTTP."""
        with self._lock:
            setting = self.connection.execute(
                "SELECT setting_value FROM app_settings WHERE setting_key = ?",
                (WHITELIST_SETTING_KEY,),
            ).fetchone()
            enabled = bool(
                setting and str(setting[0]).strip().casefold() in {"1", "true", "yes"}
            )
            parsed: list[
                tuple[int, str, ipaddress.IPv4Network | ipaddress.IPv6Network]
            ] = []
            for row in self.connection.execute(
                """SELECT id, ip_address
                     FROM mobile_ip_whitelist
                    WHERE active = 1
                    ORDER BY id"""
            ):
                address = str(row["ip_address"] if hasattr(row, "keys") else row[1])
                rule_id = int(row["id"] if hasattr(row, "keys") else row[0])
                try:
                    network = ipaddress.ip_network(
                        address if "/" in address else f"{address}/32"
                        if ":" not in address
                        else f"{address}/128",
                        strict=False,
                    )
                except ValueError:
                    logger.error(
                        "Ignoring invalid mobile whitelist rule id=%s address=%s",
                        rule_id,
                        address,
                    )
                    continue
                parsed.append((rule_id, address, network))
            self._enabled = enabled
            self._networks = tuple(parsed)

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @property
    def active_rule_count(self) -> int:
        with self._lock:
            return len(self._networks)

    def list_rules(self) -> list[MobileIPRule]:
        with self._lock:
            rows = self.connection.execute(
                """SELECT id, ip_address, description, active, created_at,
                          updated_at, COALESCE(last_matched_at, '') AS last_matched_at
                     FROM mobile_ip_whitelist
                    ORDER BY active DESC, ip_address COLLATE NOCASE"""
            ).fetchall()
        return [
            MobileIPRule(
                id=int(row["id"]),
                ip_address=str(row["ip_address"]),
                description=str(row["description"] or ""),
                active=bool(row["active"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
                last_matched_at=str(row["last_matched_at"] or ""),
            )
            for row in rows
        ]

    def get_rule(self, rule_id: int) -> MobileIPRule | None:
        return next((rule for rule in self.list_rules() if rule.id == int(rule_id)), None)

    def add_rule(
        self, ip_address: str, description: str = "", active: bool = True
    ) -> MobileIPRule:
        normalized = normalize_ip_rule(ip_address)
        clean_description = str(description or "").strip()[:240]
        now = _now()
        with self._lock:
            try:
                cursor = self.connection.execute(
                    """INSERT INTO mobile_ip_whitelist(
                           ip_address, description, active, created_at, updated_at
                       ) VALUES(?, ?, ?, ?, ?)""",
                    (normalized, clean_description, int(active), now, now),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("Esa IP o red ya está en la whitelist.") from error
            self._write_audit_locked(
                "rule_added",
                ip_address=normalized,
                details={"description": clean_description, "active": bool(active)},
            )
            self.connection.commit()
            rule_id = int(cursor.lastrowid)
            self.reload()
        rule = self.get_rule(rule_id)
        if rule is None:
            raise RuntimeError("No se pudo recuperar la regla guardada.")
        return rule

    def update_rule(
        self,
        rule_id: int,
        ip_address: str,
        description: str = "",
        active: bool = True,
    ) -> MobileIPRule:
        normalized = normalize_ip_rule(ip_address)
        clean_description = str(description or "").strip()[:240]
        now = _now()
        with self._lock:
            current = self._row_for_rule_locked(rule_id)
            if current is None:
                raise ValueError("La regla seleccionada ya no existe.")
            if (
                self._enabled
                and bool(current["active"])
                and not active
                and self._active_count_locked() <= 1
            ):
                raise ValueError(
                    "No podés desactivar la última regla mientras la whitelist está activa."
                )
            try:
                self.connection.execute(
                    """UPDATE mobile_ip_whitelist
                          SET ip_address = ?, description = ?, active = ?, updated_at = ?
                        WHERE id = ?""",
                    (
                        normalized,
                        clean_description,
                        int(active),
                        now,
                        int(rule_id),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("Esa IP o red ya está en la whitelist.") from error
            self._write_audit_locked(
                "rule_updated",
                ip_address=normalized,
                details={"description": clean_description, "active": bool(active)},
            )
            self.connection.commit()
            self.reload()
        rule = self.get_rule(rule_id)
        if rule is None:
            raise RuntimeError("No se pudo recuperar la regla actualizada.")
        return rule

    def set_rule_active(self, rule_id: int, active: bool) -> MobileIPRule:
        rule = self.get_rule(rule_id)
        if rule is None:
            raise ValueError("La regla seleccionada ya no existe.")
        return self.update_rule(
            rule.id, rule.ip_address, rule.description, active=bool(active)
        )

    def delete_rule(self, rule_id: int) -> None:
        with self._lock:
            current = self._row_for_rule_locked(rule_id)
            if current is None:
                raise ValueError("La regla seleccionada ya no existe.")
            if (
                self._enabled
                and bool(current["active"])
                and self._active_count_locked() <= 1
            ):
                raise ValueError(
                    "No podés eliminar la última regla mientras la whitelist está activa."
                )
            address = str(current["ip_address"])
            self.connection.execute(
                "DELETE FROM mobile_ip_whitelist WHERE id = ?", (int(rule_id),)
            )
            self._write_audit_locked("rule_deleted", ip_address=address)
            self.connection.commit()
            self.reload()

    def set_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        now = _now()
        with self._lock:
            if enabled and self._active_count_locked() == 0:
                raise ValueError(
                    "Activá al menos una IP o red antes de habilitar la whitelist."
                )
            self.connection.execute(
                """INSERT INTO app_settings(setting_key, setting_value, updated_at)
                   VALUES(?, ?, ?)
                   ON CONFLICT(setting_key) DO UPDATE SET
                       setting_value = excluded.setting_value,
                       updated_at = excluded.updated_at""",
                (WHITELIST_SETTING_KEY, "true" if enabled else "false", now),
            )
            self._write_audit_locked(
                "whitelist_enabled" if enabled else "whitelist_disabled",
                details={"active_rules": self._active_count_locked()},
            )
            self.connection.commit()
            self.reload()

    def is_allowed(self, client_ip: str, endpoint: str = "") -> bool:
        """Evalúa IP/CIDR. Si la whitelist está activa y vacía, bloquea."""
        clean_ip = str(client_ip or "").strip()
        with self._lock:
            if not self._enabled:
                return True
            try:
                address = ipaddress.ip_address(clean_ip)
            except ValueError:
                self._audit_throttled_locked(
                    "invalid_client_ip", clean_ip, endpoint, {"reason": "parse_error"}
                )
                return False
            for rule_id, _rule_text, network in self._networks:
                if address.version == network.version and address in network:
                    self._record_match_locked(rule_id)
                    return True
            self._audit_throttled_locked("whitelist_blocked", clean_ip, endpoint)
            return False

    def audit_event(
        self,
        event_type: str,
        *,
        ip_address: str = "",
        endpoint: str = "",
        details: dict[str, Any] | str | None = None,
        throttle_seconds: float = 60.0,
    ) -> None:
        """Registra un evento operativo sin guardar secretos de autenticación."""
        with self._lock:
            if throttle_seconds > 0:
                self._audit_throttled_locked(
                    event_type,
                    ip_address,
                    endpoint,
                    details,
                    throttle_seconds=throttle_seconds,
                )
            else:
                self._write_audit_locked(
                    event_type,
                    ip_address=ip_address,
                    endpoint=endpoint,
                    details=details,
                )
                self.connection.commit()

    def recent_audit_events(self, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = min(500, max(1, int(limit)))
        with self._lock:
            rows = self.connection.execute(
                """SELECT id, event_type, ip_address, endpoint, details, created_at
                     FROM mobile_security_audit
                    ORDER BY id DESC
                    LIMIT ?""",
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _row_for_rule_locked(self, rule_id: int):
        return self.connection.execute(
            "SELECT * FROM mobile_ip_whitelist WHERE id = ?", (int(rule_id),)
        ).fetchone()

    def _active_count_locked(self) -> int:
        return int(
            self.connection.execute(
                "SELECT COUNT(*) FROM mobile_ip_whitelist WHERE active = 1"
            ).fetchone()[0]
        )

    def _record_match_locked(self, rule_id: int) -> None:
        now_monotonic = time.monotonic()
        if now_monotonic - self._last_match_write.get(rule_id, 0.0) < 60:
            return
        self._last_match_write[rule_id] = now_monotonic
        self.connection.execute(
            "UPDATE mobile_ip_whitelist SET last_matched_at = ? WHERE id = ?",
            (_now(), int(rule_id)),
        )
        self.connection.commit()

    def _audit_throttled_locked(
        self,
        event_type: str,
        ip_address: str,
        endpoint: str,
        details: dict[str, Any] | str | None = None,
        *,
        throttle_seconds: float = 60.0,
    ) -> None:
        key = (str(event_type), str(ip_address), str(endpoint))
        now_monotonic = time.monotonic()
        if now_monotonic - self._audit_throttle.get(key, 0.0) < throttle_seconds:
            return
        self._audit_throttle[key] = now_monotonic
        self._write_audit_locked(
            event_type,
            ip_address=ip_address,
            endpoint=endpoint,
            details=details,
        )
        self.connection.commit()

    def _write_audit_locked(
        self,
        event_type: str,
        *,
        ip_address: str = "",
        endpoint: str = "",
        details: dict[str, Any] | str | None = None,
    ) -> None:
        if isinstance(details, dict):
            clean_details = json.dumps(
                details, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
        else:
            clean_details = str(details or "")
        self.connection.execute(
            """INSERT INTO mobile_security_audit(
                   event_type, ip_address, endpoint, details, created_at
               ) VALUES(?, ?, ?, ?, ?)""",
            (
                str(event_type)[:80],
                str(ip_address or "")[:80],
                str(endpoint or "")[:240],
                clean_details[:1000],
                _now(),
            ),
        )
