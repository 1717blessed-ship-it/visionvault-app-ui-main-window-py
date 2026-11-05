"""Registro ordenado de migraciones de Doccione Studio."""

from __future__ import annotations

import sqlite3

from app.database.maintenance import Migration


def _stabilization_metadata(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS app_health_events (
            id INTEGER PRIMARY KEY, component TEXT NOT NULL, level TEXT NOT NULL,
            message TEXT NOT NULL, details_json TEXT DEFAULT '{}', created_at TEXT NOT NULL)"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_app_health_events_created ON app_health_events(created_at DESC)"
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS order_state_history (
            id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL,
            previous_status TEXT NOT NULL, new_status TEXT NOT NULL,
            actor TEXT DEFAULT '', source TEXT DEFAULT 'desktop', reason TEXT DEFAULT '',
            changed_at TEXT NOT NULL)"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_order_state_history_order ON order_state_history(order_id, changed_at DESC)"
    )


def _operational_indexes(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_active_status_updated ON orders(is_archived, status, updated_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_order_jobs_order_status ON order_jobs(order_id, status)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_order_payments_paid_at ON order_payments(paid_at DESC)"
    )


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _normalize_price_rule_catalog_keys(connection: sqlite3.Connection) -> None:
    """Permite reglas manuales sin clave y conserva unicidad para claves reales."""
    columns = list(connection.execute("PRAGMA table_info(price_rules)"))
    if not columns:
        return

    catalog_column = next((column for column in columns if column[1] == "catalog_key"), None)
    if catalog_column is None:
        return

    duplicate = connection.execute(
        """SELECT catalog_key
             FROM price_rules
            WHERE catalog_key IS NOT NULL AND TRIM(catalog_key) <> ''
            GROUP BY catalog_key
           HAVING COUNT(*) > 1
            LIMIT 1"""
    ).fetchone()
    if duplicate:
        raise RuntimeError(
            f"No se puede normalizar price_rules: la clave de catálogo {duplicate[0]!r} está duplicada."
        )

    index_sql: list[str] = []
    for _sequence, name, unique, _origin, _partial in connection.execute("PRAGMA index_list(price_rules)"):
        indexed_columns = [row[2] for row in connection.execute(f"PRAGMA index_info({_quote_identifier(name)})")]
        if unique and indexed_columns == ["catalog_key"]:
            continue
        sql_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?", (name,)
        ).fetchone()
        if sql_row and sql_row[0]:
            index_sql.append(str(sql_row[0]))

    definitions: list[str] = []
    column_names: list[str] = []
    for _cid, name, column_type, not_null, default, primary_key in columns:
        quoted_name = _quote_identifier(str(name))
        definition = quoted_name
        if column_type:
            definition += f" {column_type}"
        if primary_key:
            definition += " PRIMARY KEY"
        if not_null and not primary_key:
            definition += " NOT NULL"
        if name == "catalog_key":
            definition += " DEFAULT NULL"
        elif default is not None:
            definition += f" DEFAULT {default}"
        definitions.append(definition)
        column_names.append(quoted_name)

    temporary_table = "price_rules_stabilized"
    connection.execute(f"DROP TABLE IF EXISTS {_quote_identifier(temporary_table)}")
    connection.execute(
        f"CREATE TABLE {_quote_identifier(temporary_table)} ({', '.join(definitions)})"
    )
    select_expressions = [
        (
            "CASE WHEN catalog_key IS NULL OR TRIM(catalog_key) = '' "
            "THEN NULL ELSE catalog_key END"
        )
        if column[1] == "catalog_key"
        else _quote_identifier(str(column[1]))
        for column in columns
    ]
    connection.execute(
        f"INSERT INTO {_quote_identifier(temporary_table)} ({', '.join(column_names)}) "
        f"SELECT {', '.join(select_expressions)} FROM price_rules"
    )
    connection.execute("DROP TABLE price_rules")
    connection.execute(
        f"ALTER TABLE {_quote_identifier(temporary_table)} RENAME TO price_rules"
    )
    for sql in index_sql:
        connection.execute(sql)
    connection.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_price_rules_catalog_key
               ON price_rules(catalog_key)
            WHERE catalog_key IS NOT NULL AND TRIM(catalog_key) <> ''"""
    )


def _order_distribution_policy(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(order_jobs)")}
    if "distribution_policy" not in columns:
        connection.execute("ALTER TABLE order_jobs ADD COLUMN distribution_policy TEXT NOT NULL DEFAULT 'legacy'")


def application_migrations() -> tuple[Migration, ...]:
    from app.services.delivery_readiness import install_delivery_guards
    return (
        Migration(2026081301, "stabilization metadata and state audit", _stabilization_metadata),
        Migration(2026081302, "operational query indexes", _operational_indexes),
        Migration(2026081303, "normalize price rule catalog keys", _normalize_price_rule_catalog_keys),
        Migration(2026102301, "explicit order design distribution policy", _order_distribution_policy),
        Migration(2026102302, "guard verified total delivery", install_delivery_guards),
    )
