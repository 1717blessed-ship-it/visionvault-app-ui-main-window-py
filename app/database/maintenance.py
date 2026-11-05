"""Mantenimiento seguro de SQLite: integridad, respaldos y migraciones."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable


MigrationAction = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True, order=True)
class Migration:
    version: int
    name: str
    apply: MigrationAction


class DatabaseMaintenance:
    """Opera copias consistentes incluso cuando la base usa WAL."""

    def __init__(self, connection: sqlite3.Connection, database_path: str | Path, backup_dir: str | Path | None = None):
        self.connection = connection
        self.database_path = Path(database_path)
        self.backup_dir = Path(backup_dir) if backup_dir else self.database_path.parent / "backups" / "automatic"

    def integrity_check(self, *, quick: bool = True) -> tuple[bool, str]:
        pragma = "quick_check" if quick else "integrity_check"
        rows = self.connection.execute(f"PRAGMA {pragma}").fetchall()
        messages = [str(row[0]) for row in rows]
        valid = bool(messages) and all(message.casefold() == "ok" for message in messages)
        return valid, " · ".join(messages) if messages else "SQLite no devolvió un resultado."

    def assert_healthy(self) -> None:
        valid, detail = self.integrity_check()
        if not valid:
            raise RuntimeError(f"La base de datos no superó el control de integridad: {detail}")

    def has_backup_today(self) -> bool:
        if not self.backup_dir.exists():
            return False
        prefix = f"visionvault_daily_{datetime.now():%Y%m%d}_"
        return any(path.is_file() for path in self.backup_dir.glob(prefix + "*.db"))

    def create_backup(self, reason: str = "manual") -> Path:
        """Usa la API backup de SQLite para incluir correctamente el WAL."""
        self.assert_healthy()
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        safe_reason = "".join(character if character.isalnum() else "_" for character in reason.strip().lower()).strip("_") or "manual"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        destination = self.backup_dir / f"visionvault_{safe_reason}_{timestamp}.db"
        partial = destination.with_suffix(".partial")
        self.connection.commit()
        target = sqlite3.connect(partial)
        try:
            self.connection.backup(target)
            target.commit()
            check = target.execute("PRAGMA quick_check").fetchone()
            if not check or str(check[0]).casefold() != "ok":
                raise RuntimeError(f"El respaldo no superó el control de integridad: {check[0] if check else 'sin resultado'}")
        finally:
            target.close()
        partial.replace(destination)
        return destination

    def ensure_daily_backup(self, *, keep: int = 14) -> Path | None:
        """Crea como máximo una copia diaria y conserva las más recientes."""
        created = None
        if not self.has_backup_today():
            created = self.create_backup("daily")
        backups = sorted(self.backup_dir.glob("visionvault_*.db"), key=lambda path: path.stat().st_mtime, reverse=True)
        for old in backups[max(1, int(keep)):]:
            try:
                old.unlink()
            except OSError:
                pass
        return created


class MigrationRunner:
    """Registra cada migración exactamente una vez y dentro de una transacción."""

    def __init__(self, connection: sqlite3.Connection, maintenance: DatabaseMaintenance):
        self.connection = connection
        self.maintenance = maintenance
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY, name TEXT NOT NULL,
                applied_at TEXT NOT NULL, execution_ms REAL NOT NULL DEFAULT 0)"""
        )
        self.connection.commit()

    def applied_versions(self) -> set[int]:
        return {int(row[0]) for row in self.connection.execute("SELECT version FROM schema_migrations")}

    def apply_all(self, migrations: Iterable[Migration], *, backup_before: bool = True) -> list[int]:
        pending = [migration for migration in sorted(migrations) if migration.version not in self.applied_versions()]
        if not pending:
            return []
        self.maintenance.assert_healthy()
        if backup_before and not self.maintenance.has_backup_today():
            self.maintenance.create_backup(f"pre_migration_{pending[0].version}")
        applied: list[int] = []
        for migration in pending:
            started = datetime.now()
            savepoint = f"migration_{migration.version}"
            self.connection.execute(f"SAVEPOINT {savepoint}")
            try:
                migration.apply(self.connection)
                elapsed_ms = (datetime.now() - started).total_seconds() * 1000
                self.connection.execute(
                    "INSERT INTO schema_migrations(version,name,applied_at,execution_ms) VALUES(?,?,?,?)",
                    (migration.version, migration.name, datetime.now().isoformat(timespec="seconds"), elapsed_ms),
                )
                self.connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            except Exception:
                self.connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self.connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            applied.append(migration.version)
        self.connection.commit()
        self.maintenance.assert_healthy()
        return applied
