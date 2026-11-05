import sqlite3

import pytest

from app.database.database import ImageDatabase
from app.database.maintenance import DatabaseMaintenance, Migration, MigrationRunner
from app.database.migrations import application_migrations


def test_sqlite_backup_is_consistent_and_contains_wal_changes(tmp_path):
    path = tmp_path / "source.db"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)")
    connection.execute("INSERT INTO sample(value) VALUES('guardado')")
    connection.commit()

    manager = DatabaseMaintenance(connection, path, tmp_path / "backups")
    backup = manager.create_backup("manual")

    copy = sqlite3.connect(backup)
    assert copy.execute("SELECT value FROM sample").fetchone()[0] == "guardado"
    assert copy.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    copy.close()
    connection.close()


def test_migrations_are_versioned_idempotent_and_transactional(tmp_path):
    path = tmp_path / "migrations.db"
    connection = sqlite3.connect(path)
    manager = DatabaseMaintenance(connection, path, tmp_path / "backups")
    runner = MigrationRunner(connection, manager)

    migration = Migration(1, "create sample", lambda conn: conn.execute("CREATE TABLE sample(id INTEGER)"))
    assert runner.apply_all((migration,), backup_before=False) == [1]
    assert runner.apply_all((migration,), backup_before=False) == []
    assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1

    def broken(conn):
        conn.execute("CREATE TABLE should_rollback(id INTEGER)")
        raise RuntimeError("falló")

    with pytest.raises(RuntimeError, match="falló"):
        runner.apply_all((Migration(2, "broken", broken),), backup_before=False)
    assert connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='should_rollback'"
    ).fetchone() is None
    connection.close()


def test_existing_image_database_creates_one_daily_backup_and_tracks_migrations(tmp_path):
    path = tmp_path / "visionvault.db"
    first = ImageDatabase(path)
    first.close()

    second = ImageDatabase(path)
    backups = list((tmp_path / "backups" / "automatic").glob("visionvault_daily_*.db"))
    versions = second.connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    assert len(backups) == 1
    assert [row[0] for row in versions] == [2026081301, 2026081302, 2026081303, 2026102301, 2026102302]
    second.close()


def test_price_rules_allow_unnamed_manual_rules_but_keep_catalog_keys_unique(tmp_path):
    database = ImageDatabase(tmp_path / "visionvault.db")

    database.connection.execute("INSERT INTO price_rules(price) VALUES(100)")
    database.connection.execute("INSERT INTO price_rules(price) VALUES(200)")
    database.connection.execute(
        "INSERT INTO price_rules(price, catalog_key) VALUES(300, 'catalog-test-key')"
    )
    assert database.connection.execute(
        "SELECT COUNT(*) FROM price_rules WHERE catalog_key IS NULL"
    ).fetchone()[0] >= 2

    with pytest.raises(sqlite3.IntegrityError):
        database.connection.execute(
            "INSERT INTO price_rules(price, catalog_key) VALUES(400, 'catalog-test-key')"
        )
    database.connection.rollback()
    database.close()


def test_price_rule_migration_preserves_legacy_rows_and_indexes(tmp_path):
    connection = sqlite3.connect(tmp_path / "legacy.db")
    connection.execute(
        """CREATE TABLE price_rules (
            id INTEGER PRIMARY KEY, price REAL NOT NULL,
            active INTEGER DEFAULT 1, catalog_key TEXT DEFAULT '',
            UNIQUE(catalog_key))"""
    )
    connection.execute("CREATE INDEX idx_price_rules_active ON price_rules(active)")
    connection.execute("INSERT INTO price_rules(price) VALUES(100)")
    connection.execute(
        "INSERT INTO price_rules(price, catalog_key) VALUES(200, 'legacy-catalog-key')"
    )

    migration = next(item for item in application_migrations() if item.version == 2026081303)
    migration.apply(connection)

    assert connection.execute("SELECT COUNT(*) FROM price_rules").fetchone()[0] == 2
    assert connection.execute(
        "SELECT catalog_key FROM price_rules WHERE price = 100"
    ).fetchone()[0] is None
    assert connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_price_rules_active'"
    ).fetchone()
    connection.execute("INSERT INTO price_rules(price) VALUES(300)")
    connection.execute("INSERT INTO price_rules(price) VALUES(400)")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO price_rules(price, catalog_key) VALUES(500, 'legacy-catalog-key')"
        )
    connection.close()
