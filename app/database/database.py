import json
import sqlite3
import shutil
import difflib
import re
import unicodedata
import threading
import logging
import uuid
import math
from pathlib import Path
from decimal import Decimal
from dataclasses import asdict

from costos.models.cost_component import CostComponent
from costos.models.cost_condition import CostCondition
from costos.models.cost_rule import CostRule
from costos.models.variable_cost_component import VariableCostComponent
from costos.models.variable_cost_model import VariableCostModel, build_product_key
from costos.services.cost_calculator import CostCalculator
from costos.services.variable_cost_calculator import VariableCostCalculator
from app.database.maintenance import DatabaseMaintenance, MigrationRunner
from app.database.migrations import application_migrations
from app.diagnostics import record_health
from app.database.order_transaction import OrderConnection

logger = logging.getLogger(__name__)


DOCCIONE_PRICE_CATALOG_KEY = "precio_catalogo_doccione_2026_07_15"
MANUAL_PRIORITY_VALUES = {"Sin prisa": 0, "Baja": 1, "Media": 2, "Alta": 3, "Urgente": 4}
DELIVERED_ORDER_STATUSES = frozenset({"entregado", "terminado"})
SELLER_NAME = "Francisco Franco Salguero"
# Francisco ya percibe sueldo fijo; la comisión es un incentivo adicional y
# no una distribución principal de la ganancia del pedido.
SELLER_COMMISSION_PERCENT = 10.0


def _manual_priority_value(value) -> int:
    if isinstance(value, str) and value.strip() in MANUAL_PRIORITY_VALUES:
        return MANUAL_PRIORITY_VALUES[value.strip()]
    try:
        return min(4, max(0, int(value or 0)))
    except (TypeError, ValueError):
        return 0


def _is_delivered_order_status(value) -> bool:
    return str(value or "").strip().casefold() in DELIVERED_ORDER_STATUSES


def _seller_commission_percent(assigned_to: object) -> float:
    """Devuelve la participación pactada para el vendedor del pedido."""
    return (
        SELLER_COMMISSION_PERCENT
        if str(assigned_to or "").strip().casefold() == SELLER_NAME.casefold()
        else 0.0
    )

# Valores iniciales extraídos de la lista de precios entregada por Doccione.
# Se instalan una sola vez y luego siguen siendo reglas totalmente editables.
DOCCIONE_PRICE_CATALOG: tuple[tuple[str, str, int, float, str, int, str], ...] = (
    *( ("Resina 3D Premium", f"{size}cm", 1, price, "unitario", 1, "") for size, price in ((29, 17000), (25, 13000), (20, 10000), (18, 8000), (15, 7000), (14, 5500), (12, 4500), (10, 3500), (7, 2500), (5, 1500)) ),
    ("Resina 3D Premium", "5cm", 5, 7000, "pack", 5, "Pack de 5 unidades"),
    ("Resina 3D Premium", "5cm", 10, 13000, "pack", 10, "Pack de 10 unidades"),
    ("Resina 3D Premium", "5cm", 20, 24000, "pack", 20, "Pack de 20 unidades"),
    *( ("Vinilo Full Color HD", f"{size}cm", 1, price, "unitario", 1, "") for size, price in ((29, 5000), (25, 4200), (20, 3000), (18, 2500), (15, 1800), (12, 1200), (10, 900), (8, 700), (7, 500), (5, 400)) ),
    *( ("Vinilo Full Color Perlado Premium", f"{size}cm", 1, price, "unitario", 1, "") for size, price in ((29, 6000), (25, 5000), (20, 3600), (18, 3000), (15, 2150), (12, 1500), (10, 1100), (8, 850), (7, 650), (5, 500)) ),
    *( ("Vinilo Full Color HD", "5cm", minimum, price, "unitario", 1, "Precio por cantidad · 5 cm") for minimum, price in ((1, 400), (10, 350), (20, 300), (100, 280), (200, 260), (500, 240), (1000, 220)) ),
    *( ("Vinilo Full Color HD - Programa emprendedor", "5cm", minimum, price, "unitario", 1, note) for minimum, price, note in ((100, 260, "Incluye hasta 10 preparaciones de archivos"), (500, 220, "Incluye hasta 50 preparaciones de archivos"), (1000, 200, "Incluye hasta 100 preparaciones de archivos")) ),
    *( ("Vinilo Ploteado", f"{size}cm", 1, price, "unitario", 1, "") for size, price in ((29, 3500), (25, 3000), (20, 2600), (17, 2200), (15, 1800), (14, 1600), (12, 1300), (10, 1000), (8, 700), (7, 500), (5, 300)) ),
    *( ("Vinilo Premium", f"{size}cm", 1, price, "unitario", 1, "") for size, price in ((29, 6000), (25, 5000), (20, 3600), (18, 3000), (15, 2150), (12, 1500), (10, 1100), (8, 850), (7, 650), (5, 500)) ),
    ("Plancha A4 - Vinilo Blanco Full Color", "A4", 1, 6000, "fijo", 1, "Incluye impresión, armado y troquelado"),
    # Cada plancha es una unidad facturable; el precio debe multiplicarse por
    # la cantidad solicitada antes de aplicar cualquier descuento general.
    ("Plancha A4 - Diseño Único", "A4", 1, 5000, "unitario", 1, "Plancha personalizada"),
    ("Plancha A4 - Vinilos Especiales", "A4", 1, 7000, "fijo", 1, "Plancha personalizada"),
)


class ImageDatabase:
    def __init__(
        self,
        db_path: str | Path = "visionvault.db",
        *,
        defer_automatic_maintenance: bool = False,
    ):
        self.db_path = Path(db_path)
        self._thread_connections = threading.local()

        try:
            from datetime import datetime

            eff = Path(db_path).resolve()
            exists = eff.exists()
            size = eff.stat().st_size if exists else 0
            mtime = datetime.fromtimestamp(eff.stat().st_mtime).isoformat(timespec="seconds") if exists else ""
        except Exception:
            eff = Path(db_path)
            exists = False
            size = 0
            mtime = ""
        logger.info(
            "Base de datos configurada",
            extra={"component": "database", "event": "configured"},
        )
        logger.debug("DB path=%s exists=%s size=%s mtime=%s", eff, exists, size, mtime)

        self._thread_connections.conn = self._create_connection()
        self._thread_connections.conn.row_factory = sqlite3.Row
        self._thread_connections.conn.execute("PRAGMA journal_mode=WAL")
        self._thread_connections.conn.execute("PRAGMA busy_timeout = 30000")
        self.maintenance = DatabaseMaintenance(self.connection, self.db_path)
        self.last_automatic_backup: str = ""
        self.automatic_maintenance_pending = bool(
            defer_automatic_maintenance and exists and size > 0
        )
        if exists and size > 0:
            if not defer_automatic_maintenance:
                self.run_automatic_maintenance()
        self._search_cache: dict[tuple, list[dict]] = {}
        self._count_cache: dict[tuple, int] = {}
        self._fuzzy_vocabulary_cache: tuple[int, set[str]] | None = None
        self._visual_search_cache: tuple[int, list[dict]] | None = None
        self._images_by_paths_cache: dict[tuple[str, ...], list[dict]] = {}

        if exists and size > 0:
            job_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(order_jobs)")}
            if job_columns and "distribution_policy" not in job_columns:
                self.maintenance.create_backup("pre_order_distribution_policy")
            if job_columns and not self.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name='order_delivery_readiness'"
            ).fetchone():
                self.maintenance.create_backup("pre_verified_delivery")
        self._initialize_schema()
        self.applied_migrations = MigrationRunner(self.connection, self.maintenance).apply_all(
            application_migrations(),
            # Una base existente ya fue respaldada por el preflight diario;
            # una base nueva no necesita copiarse antes de su primera versión.
            backup_before=bool(exists and size > 0),
        )
        record_health(
            self.connection,
            "database",
            "INFO",
            "Base lista para operar",
            {
                "path": str(eff),
                "automatic_backup": self.last_automatic_backup,
                "maintenance_pending": self.automatic_maintenance_pending,
                "applied_migrations": self.applied_migrations,
            },
        )

    def run_automatic_maintenance(self) -> str:
        """Verifica SQLite y crea el respaldo diario en el hilo que la invoque.

        La conexión es local por hilo, por lo que la aplicación de escritorio
        puede ejecutar este control después de mostrar su primera ventana sin
        compartir un objeto ``sqlite3.Connection`` con Tk.
        """
        maintenance = DatabaseMaintenance(self.connection, self.db_path)
        maintenance.assert_healthy()
        automatic_backup = maintenance.ensure_daily_backup(keep=14)
        self.last_automatic_backup = str(automatic_backup or "")
        self.automatic_maintenance_pending = False
        return self.last_automatic_backup

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30, factory=OrderConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    @property
    def connection(self) -> sqlite3.Connection:
        if not hasattr(self._thread_connections, 'conn'):
            self._thread_connections.conn = self._create_connection()
        return self._thread_connections.conn

    @property
    def event_repo(self):
        # Outbox rows must use the same per-thread transaction as the order.
        from app.events.event_repository import EventRepository
        repo = getattr(self._thread_connections, 'event_repo', None)
        if repo is None or repo.conn is not self.connection:
            repo = EventRepository(self.connection)
            self._thread_connections.event_repo = repo
        return repo

    @event_repo.setter
    def event_repo(self, repository):
        self._thread_connections.event_repo = repository

    def _initialize_schema(self) -> None:
        # Ensure the schema exists on the first connection for this database.
        self.connection.execute("PRAGMA database_list")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS images (
                path TEXT PRIMARY KEY, name TEXT NOT NULL, extension TEXT NOT NULL,
                size INTEGER NOT NULL, modified REAL NOT NULL, caption TEXT DEFAULT '',
                recognized_text TEXT DEFAULT ''
            )"""
        )
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(images)")}
        if "recognized_text" not in columns:
            self.connection.execute("ALTER TABLE images ADD COLUMN recognized_text TEXT DEFAULT ''")
        if "category" not in columns:
            self.connection.execute("ALTER TABLE images ADD COLUMN category TEXT DEFAULT ''")
        if "visual_score" not in columns:
            self.connection.execute("ALTER TABLE images ADD COLUMN visual_score REAL DEFAULT -1")
        for column, definition in (
            ("visual_signature", "TEXT DEFAULT ''"),
            ("visual_signature_modified", "REAL DEFAULT -1"),
        ):
            if column not in columns:
                self.connection.execute(f"ALTER TABLE images ADD COLUMN {column} {definition}")
        # Métricas de la silueta real para el Constructor de planchas.
        for column, definition in (
            ("visible_width", "INTEGER DEFAULT 0"),
            ("visible_height", "INTEGER DEFAULT 0"),
            ("visible_long_side", "INTEGER DEFAULT 0"),
            ("visible_ratio", "REAL DEFAULT 0"),
            ("plancha_metric_modified", "REAL DEFAULT -1"),
        ):
            if column not in columns:
                self.connection.execute(f"ALTER TABLE images ADD COLUMN {column} {definition}")
        # Los diseños ingresan privados y solo pasan a Biblioteca por decisión
        # explícita del usuario; los originales nunca se modifican.
        for column, definition in (
            ("design_client", "TEXT DEFAULT ''"),
            ("design_order_id", "INTEGER"),
            ("is_favorite", "INTEGER DEFAULT 0"),
            ("is_private", "INTEGER DEFAULT 1"),
            ("is_reusable", "INTEGER DEFAULT 0"),
            ("import_status", "TEXT DEFAULT 'Pendiente'"),
        ):
            if column not in columns:
                self.connection.execute(f"ALTER TABLE images ADD COLUMN {column} {definition}")
        self.connection.execute("CREATE TABLE IF NOT EXISTS tags (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE)")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS image_tags (
                image_path TEXT NOT NULL, tag_id INTEGER NOT NULL,
                PRIMARY KEY (image_path, tag_id),
                FOREIGN KEY (image_path) REFERENCES images(path),
                FOREIGN KEY (tag_id) REFERENCES tags(id)
            )"""
        )
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_image_tags_path ON image_tags(image_path)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_image_tags_tag ON image_tags(tag_id)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_images_modified ON images(modified DESC)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_images_category ON images(category)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_images_name_nocase ON images(name COLLATE NOCASE)")
        self.connection.execute(
            """CREATE INDEX IF NOT EXISTS idx_images_mobile_catalog
               ON images(is_reusable, is_private, name COLLATE NOCASE)"""
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS visual_similarities (
                query_path TEXT NOT NULL, candidate_path TEXT NOT NULL, score REAL NOT NULL,
                query_modified REAL NOT NULL, candidate_modified REAL NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(query_path, candidate_path)
            )"""
        )
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_visual_similarities_query ON visual_similarities(query_path, score DESC)")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS visual_search_runs (
                cache_key TEXT PRIMARY KEY, query_path TEXT NOT NULL,
                query_modified REAL NOT NULL, candidate_fingerprint TEXT NOT NULL,
                options_json TEXT NOT NULL, matches_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS ai_results (
                image_path TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
                modified REAL NOT NULL, result TEXT NOT NULL,
                PRIMARY KEY (image_path, provider, model)
            )"""
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS dismissed_ai_tags (
                image_path TEXT NOT NULL,
                tag TEXT NOT NULL COLLATE NOCASE,
                PRIMARY KEY (image_path, tag)
            )"""
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS sticker_processing_jobs (
                id TEXT PRIMARY KEY, source_path TEXT NOT NULL, status TEXT NOT NULL,
                engine TEXT DEFAULT '', analysis TEXT DEFAULT '{}',
                quality_status TEXT DEFAULT '', quality_notes TEXT DEFAULT '[]',
                profile TEXT DEFAULT '{}', artifacts TEXT DEFAULT '{}', category TEXT DEFAULT '',
                tags TEXT DEFAULT '[]', duplicate_path TEXT DEFAULT '', duplicate_score REAL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )"""
        )
        sticker_job_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(sticker_processing_jobs)")}
        if "analysis" not in sticker_job_columns:
            self.connection.execute("ALTER TABLE sticker_processing_jobs ADD COLUMN analysis TEXT DEFAULT '{}'")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS sticker_artifacts (
                job_id TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL,
                PRIMARY KEY(job_id, kind),
                FOREIGN KEY(job_id) REFERENCES sticker_processing_jobs(id)
            )"""
        )
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_sticker_jobs_status ON sticker_processing_jobs(status, updated_at DESC)")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS plancha_usage (
                id INTEGER PRIMARY KEY,
                image_path TEXT NOT NULL,
                client TEXT DEFAULT '', order_number TEXT DEFAULT '',
                size_cm REAL NOT NULL, quantity INTEGER NOT NULL,
                used_at TEXT NOT NULL, source TEXT NOT NULL
            )"""
        )
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_plancha_usage_path ON plancha_usage(image_path)")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY,
                client TEXT NOT NULL, whatsapp TEXT DEFAULT '', order_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Nuevo', material TEXT DEFAULT '',
                size TEXT DEFAULT '', quantity INTEGER DEFAULT 0, price REAL DEFAULT 0,
                observations TEXT DEFAULT '', created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, order_concept TEXT DEFAULT '',
                order_description TEXT DEFAULT ''
            )"""
        )
        # Etapa 1 de Pedidos: se conserva el texto de cliente original por
        # compatibilidad y se suma una ficha reutilizable de cliente.
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL, whatsapp TEXT DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )"""
        )
        self.connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_clients_identity "
            "ON clients(name COLLATE NOCASE, whatsapp)"
        )
        # Migrar columna client_type si no existe (Particular / Empresa / Revendedor / VIP)
        client_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(clients)")}
        if "client_type" not in client_columns:
            self.connection.execute("ALTER TABLE clients ADD COLUMN client_type TEXT DEFAULT 'Particular'")
        order_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(orders)")}
        for column, definition in (
            ("client_id", "INTEGER"),
            ("pending_reason", "TEXT DEFAULT ''"),
            ("is_archived", "INTEGER DEFAULT 0"),
            ("last_autosave_at", "TEXT DEFAULT ''"),
            ("delivery_date", "TEXT DEFAULT ''"),
            ("print_priority", "INTEGER DEFAULT 0"),
            ("order_concept", "TEXT DEFAULT ''"),
            ("order_description", "TEXT DEFAULT ''"),
            ("complaint_notes", "TEXT DEFAULT ''"),
            # Presupuesto: se guardan valores simples y trazables. La regla de
            # precio, si se usa, solo propone un importe; nunca reemplaza uno
            # confirmado por el usuario.
            ("discount_percent", "REAL DEFAULT 0"),
            ("extra_services", "TEXT DEFAULT ''"),
            ("budget_total", "REAL DEFAULT 0"),
            ("paid_amount", "REAL DEFAULT 0"),
            ("payment_status", "TEXT DEFAULT 'Pendiente'"),
            ("assigned_to", "TEXT DEFAULT ''"),
            # Comisión comercial: solo se aplica cuando el pedido tiene un
            # vendedor asignado. Se conserva el porcentaje pactado en el
            # pedido para que los cambios futuros no alteren ventas históricas.
            ("seller_commission_percent", "REAL DEFAULT 0"),
            ("seller_commission_amount", "REAL DEFAULT 0"),
            # Identidad del vendedor móvil que creó el pedido. Es distinta de
            # ``assigned_to``: asignar producción no transfiere su propiedad.
            ("creator_device_id", "INTEGER"),
            # Un pedido de stickers puede formar parte de un pedido comercial
            # más amplio (por ejemplo, anillado + stickers) sin mezclar los
            # trabajos, las planchas ni sus respectivos flujos de producción.
            ("parent_order_id", "INTEGER"),
            # Costos desglosados — sincronizados desde order_jobs
            ("cost_mp",    "REAL DEFAULT 0"),   # Materia Prima
            ("cost_mo",    "REAL DEFAULT 0"),   # Mano de Obra
            ("cost_cf",    "REAL DEFAULT 0"),   # Carga Fabril
            ("cost_total", "REAL DEFAULT 0"),   # M.P + M.O + C.F
            ("margin",     "REAL DEFAULT 0"),   # budget_total − cost_total
            # Preserva la eliminación intencional de todos los trabajos.
            ("order_jobs_deleted", "INTEGER DEFAULT 0"),
        ):
            if column not in order_columns:
                self.connection.execute(f"ALTER TABLE orders ADD COLUMN {column} {definition}")
        # La urgencia es operativa: deja de aplicar cuando el pedido ya fue
        # entregado. También normaliza registros creados por versiones
        # anteriores que conservaron su prioridad después del cierre.
        self.connection.execute(
            """UPDATE orders
               SET print_priority = 0
               WHERE COALESCE(print_priority, 0) != 0
                 AND LOWER(TRIM(COALESCE(status, ''))) IN ('entregado', 'terminado')"""
        )
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(order_date DESC)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_orders_parent ON orders(parent_order_id)")
        # Un pedido puede reunir varios trabajos. El resumen histórico del
        # pedido se conserva en `orders` para no romper planchas, cobros ni
        # pantallas existentes; estos ítems son el detalle operativo.
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS order_jobs (
                id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT 'Trabajo',
                material TEXT DEFAULT '', size TEXT DEFAULT '',
                quantity INTEGER NOT NULL DEFAULT 1,
                subtotal REAL NOT NULL DEFAULT 0,
                discount_percent REAL NOT NULL DEFAULT 0,
                extra_services TEXT DEFAULT '', status TEXT DEFAULT 'Pendiente',
                notes TEXT DEFAULT '', sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                FOREIGN KEY(order_id) REFERENCES orders(id)
            )"""
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_order_jobs_order ON order_jobs(order_id, sort_order, id)"
        )
        # Migrar columnas de costos en order_jobs si no existen
        order_job_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(order_jobs)")}
        for column, definition in (
            ("cost_mp",    "REAL DEFAULT 0"),
            ("cost_mo",    "REAL DEFAULT 0"),
            ("cost_cf",    "REAL DEFAULT 0"),
            ("cost_total", "REAL DEFAULT 0"),
            # Fotocopias y terminaciones: snapshot de precios
            ("base_price", "REAL DEFAULT 0"),
            ("discount_amount", "REAL DEFAULT 0"),
            ("surcharge_amount", "REAL DEFAULT 0"),
            ("final_price", "REAL DEFAULT 0"),
            ("is_urgent", "INTEGER DEFAULT 0"),
            ("manual_price", "REAL DEFAULT NULL"),
            ("price_calculation_json", "TEXT DEFAULT '{}'"),
            ("unit_kind", "TEXT DEFAULT ''"),
        ):
            if column not in order_job_columns:
                self.connection.execute(f"ALTER TABLE order_jobs ADD COLUMN {column} {definition}")
        
        # Tabla de reglas de costos — permite calcular M.P, M.O y C.F de forma independiente
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS cost_rules (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                condition TEXT DEFAULT '',
                material TEXT DEFAULT '',
                
                -- Materia Prima: puede ser % del precio O fijo + por unidad
                cost_mp_mode TEXT DEFAULT 'percent',
                cost_mp_percent REAL DEFAULT 0,
                cost_mp_fixed REAL DEFAULT 0,
                cost_mp_unit REAL DEFAULT 0,
                
                -- Mano de Obra: puede ser % del precio O fijo + por unidad  
                cost_mo_mode TEXT DEFAULT 'percent',
                cost_mo_percent REAL DEFAULT 0,
                cost_mo_fixed REAL DEFAULT 0,
                cost_mo_unit REAL DEFAULT 0,
                
                -- Carga Fabril: puede ser % del precio O fijo + por unidad
                cost_cf_mode TEXT DEFAULT 'percent',
                cost_cf_percent REAL DEFAULT 0,
                cost_cf_fixed REAL DEFAULT 0,
                cost_cf_unit REAL DEFAULT 0,
                components_json TEXT DEFAULT '[]',
                
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        cost_rule_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(cost_rules)")}
        if "components_json" not in cost_rule_columns:
            self.connection.execute("ALTER TABLE cost_rules ADD COLUMN components_json TEXT DEFAULT '[]'")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS order_designs (
                order_id INTEGER NOT NULL, image_path TEXT NOT NULL, quantity INTEGER DEFAULT 1,
                size_cm REAL DEFAULT 5.0, rotation INTEGER DEFAULT 0,
                PRIMARY KEY(order_id, image_path),
                FOREIGN KEY(order_id) REFERENCES orders(id)
            )"""
        )
        design_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(order_designs)")}
        for column, definition in (
            ("status", "TEXT DEFAULT 'Pendiente'"),
            ("source", "TEXT DEFAULT ''"),
            ("creator_status", "TEXT DEFAULT 'Pendiente'"),
            ("creator_queued_at", "TEXT DEFAULT ''"),
        ):
            if column not in design_columns:
                self.connection.execute(f"ALTER TABLE order_designs ADD COLUMN {column} {definition}")
        # Recupera pedidos móviles creados antes de que `source` fuese
        # persistido. La leyenda y la carpeta son datos generados por Studio,
        # no rutas informadas por el dispositivo.
        self.connection.execute(
            """UPDATE order_designs
               SET source = 'mobile'
               WHERE COALESCE(source, '') = ''
                 AND (
                     LOWER(image_path) LIKE '%mobile_uploads%'
                     OR EXISTS (
                         SELECT 1 FROM images
                         WHERE images.path = order_designs.image_path
                           AND LOWER(COALESCE(images.caption, '')) = 'imagen recibida desde doccione mobile'
                     )
                 )"""
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS order_drafts (
                order_id INTEGER PRIMARY KEY, draft_json TEXT NOT NULL,
                saved_at TEXT NOT NULL,
                FOREIGN KEY(order_id) REFERENCES orders(id)
            )"""
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS order_events (
                id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL,
                event_type TEXT NOT NULL, message TEXT NOT NULL,
                data_json TEXT DEFAULT '', created_at TEXT NOT NULL,
                FOREIGN KEY(order_id) REFERENCES orders(id)
            )"""
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_order_events_order ON order_events(order_id, id DESC)"
        )
        # Las versiones anteriores solo guardaban la autoría móvil dentro del
        # evento JSON. Se recupera una vez para no perder pedidos del vendedor.
        legacy_mobile_events = self.connection.execute(
            """SELECT order_id, data_json
               FROM order_events
               WHERE event_type IN (
                   'order.created.mobile_catalog',
                   'order.created.mobile_pos',
                   'order.created.mobile_stickers'
               )
                 AND EXISTS (
                     SELECT 1 FROM orders
                     WHERE orders.id = order_events.order_id
                       AND orders.creator_device_id IS NULL
                 )
               ORDER BY id"""
        ).fetchall()
        for event in legacy_mobile_events:
            try:
                creator_device_id = int(json.loads(event["data_json"] or "{}").get("device_id"))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            self.connection.execute(
                """UPDATE orders
                   SET creator_device_id = ?
                   WHERE id = ? AND creator_device_id IS NULL""",
                (creator_device_id, event["order_id"]),
            )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_creator_device "
            "ON orders(creator_device_id, updated_at, id)"
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS order_payments (
                id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL,
                amount REAL NOT NULL, method TEXT DEFAULT '', note TEXT DEFAULT '',
                paid_at TEXT NOT NULL, created_at TEXT NOT NULL,
                FOREIGN KEY(order_id) REFERENCES orders(id)
            )"""
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_order_payments_order ON order_payments(order_id, paid_at DESC)"
        )
        payment_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(order_payments)")}
        for column, definition in (
            ("cancelled_at", "TEXT DEFAULT ''"),
            ("cancellation_reason", "TEXT DEFAULT ''"),
            ("idempotency_key", "TEXT DEFAULT ''"),
        ):
            if column not in payment_columns:
                self.connection.execute(f"ALTER TABLE order_payments ADD COLUMN {column} {definition}")
        self.connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_order_payments_idempotency "
            "ON order_payments(order_id, idempotency_key) WHERE idempotency_key <> ''"
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS order_previews (
                id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL, plancha_id INTEGER,
                preview_path TEXT NOT NULL, created_at TEXT NOT NULL,
                FOREIGN KEY(order_id) REFERENCES orders(id),
                FOREIGN KEY(plancha_id) REFERENCES plancha_projects(id)
            )"""
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_order_previews_order ON order_previews(order_id, created_at DESC)"
        )
        # Photoshop trabaja siempre sobre esta copia de trabajo, jamás sobre el
        # PNG original indexado en la biblioteca.
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS design_preparations (
                id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL,
                original_path TEXT NOT NULL, work_path TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'En edición', source_modified REAL DEFAULT 0,
                work_modified REAL DEFAULT 0, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, confirmed_at TEXT DEFAULT '',
                discarded_at TEXT DEFAULT '', note TEXT DEFAULT '',
                FOREIGN KEY(order_id) REFERENCES orders(id)
            )"""
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_design_preparations_order ON design_preparations(order_id, id DESC)"
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                description TEXT DEFAULT '', created_at TEXT NOT NULL
            )"""
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS image_collections (
                image_path TEXT NOT NULL, collection_id INTEGER NOT NULL,
                PRIMARY KEY(image_path, collection_id),
                FOREIGN KEY(collection_id) REFERENCES collections(id)
            )"""
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS price_rules (
                id INTEGER PRIMARY KEY, material TEXT DEFAULT '', size TEXT DEFAULT '',
                min_quantity INTEGER DEFAULT 1, price REAL NOT NULL,
                extra_service TEXT DEFAULT '', discount_percent REAL DEFAULT 0,
                active INTEGER DEFAULT 1, price_mode TEXT DEFAULT 'fijo',
                pack_quantity INTEGER DEFAULT 1, catalog_key TEXT DEFAULT NULL
            )"""
        )
        price_rule_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(price_rules)")}
        for column, definition in (
            ("price_mode",  "TEXT DEFAULT 'fijo'"),
            ("pack_quantity", "INTEGER DEFAULT 1"),
            ("catalog_key", "TEXT DEFAULT ''"),
            ("cost_model_id", "INTEGER DEFAULT NULL"),
            ("variable_cost_model_id", "INTEGER DEFAULT NULL"),
            ("outdated", "INTEGER DEFAULT 0"),
            ("source_updated_at", "TEXT DEFAULT ''"),
            ("last_synced_at", "TEXT DEFAULT ''"),
            ("manually_overridden", "INTEGER DEFAULT 0"),
            ("image_path", "TEXT DEFAULT ''"),
        ):
            if column not in price_rule_columns:
                self.connection.execute(f"ALTER TABLE price_rules ADD COLUMN {column} {definition}")

        # Migración: renombrar cost_model_id a variable_cost_model_id si existe
        if "cost_model_id" in price_rule_columns and "variable_cost_model_id" not in price_rule_columns:
            try:
                self.connection.execute("ALTER TABLE price_rules RENAME COLUMN cost_model_id TO variable_cost_model_id")
            except Exception:
                # Si falla el renombrado, agregar la nueva columna solo si no existe
                price_rule_columns_after = {row[1] for row in self.connection.execute("PRAGMA table_info(price_rules)")}
                if "variable_cost_model_id" not in price_rule_columns_after:
                    self.connection.execute("ALTER TABLE price_rules ADD COLUMN variable_cost_model_id INTEGER DEFAULT NULL")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_price_rules_catalog ON price_rules(catalog_key)")
        
        # Fotocopias y terminaciones: configuración de recargos y descuentos
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS fotocopia_config (
                id INTEGER PRIMARY KEY,
                urgent_surcharge_percent REAL DEFAULT 30.0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS fotocopia_quantity_discounts (
                id INTEGER PRIMARY KEY,
                product_type TEXT NOT NULL,
                min_quantity INTEGER NOT NULL,
                max_quantity INTEGER,
                discount_percent REAL NOT NULL,
                active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_fotocopia_discounts_type ON fotocopia_quantity_discounts(product_type, min_quantity)"
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS plancha_projects (
                id INTEGER PRIMARY KEY, order_id INTEGER, name TEXT NOT NULL,
                client_color TEXT DEFAULT '', material TEXT DEFAULT '', project_json TEXT NOT NULL,
                approval_status TEXT DEFAULT 'Borrador', created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, FOREIGN KEY(order_id) REFERENCES orders(id)
            )"""
        )
        plancha_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(plancha_projects)")}
        for column, definition in (
            ("project_path", "TEXT DEFAULT ''"),
            ("final_png_path", "TEXT DEFAULT ''"),
            ("print_status", "TEXT DEFAULT 'No lista'"),
            ("print_error", "TEXT DEFAULT ''"),
            ("print_updated_at", "TEXT DEFAULT ''"),
            ("approval_preview_path", "TEXT DEFAULT ''"),
            ("approval_requested_at", "TEXT DEFAULT ''"),
            ("approval_decision_at", "TEXT DEFAULT ''"),
            ("approval_note", "TEXT DEFAULT ''"),
            # Producción: campos de tracking para el módulo Producción
            ("usuario", "TEXT DEFAULT ''"),
            ("production_status", "TEXT DEFAULT 'borrador'"),
            ("print_count", "INTEGER DEFAULT 0"),
            ("error_count", "INTEGER DEFAULT 0"),
            ("last_printed_at", "TEXT DEFAULT ''"),
            ("preview_path", "TEXT DEFAULT ''"),
            ("previous_production_status", "TEXT DEFAULT ''"),
            # Vista previa para cliente
            ("client_preview_path", "TEXT DEFAULT ''"),
            ("client_preview_bg_type", "TEXT DEFAULT ''"),
            ("client_preview_bg_value", "TEXT DEFAULT ''"),
            ("client_preview_updated_at", "TEXT DEFAULT ''"),
            # Paginación: agrupación de planchas múltiples
            ("plancha_set_id", "TEXT DEFAULT ''"),
            ("plancha_number", "INTEGER DEFAULT 1"),
            ("total_planchas", "INTEGER DEFAULT 1"),
            # Datos de la persona cuando la plancha se crea fuera de un pedido.
            ("person_name", "TEXT DEFAULT ''"),
            ("person_phone", "TEXT DEFAULT ''"),
            ("workspace_format", "TEXT DEFAULT 'a4'"),
            ("continuous_confirmed", "INTEGER DEFAULT 0"),
        ):
            if column not in plancha_columns:
                self.connection.execute(f"ALTER TABLE plancha_projects ADD COLUMN {column} {definition}")
        # Manifiesto productivo. Las planchas históricas quedan válidas aunque
        # no tengan filas: nunca se infiere procedencia desde un JSON ambiguo.
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS plancha_item_assignments (
                id INTEGER PRIMARY KEY,
                plancha_id INTEGER NOT NULL,
                item_id TEXT NOT NULL,
                requested_unit_key TEXT NOT NULL,
                order_id INTEGER NOT NULL,
                order_job_id INTEGER NOT NULL,
                order_design_line_id TEXT DEFAULT '',
                image_path TEXT DEFAULT '',
                copy_number INTEGER NOT NULL DEFAULT 1,
                unit_kind TEXT NOT NULL DEFAULT 'item',
                quantity REAL NOT NULL DEFAULT 1,
                state TEXT NOT NULL DEFAULT 'prepared',
                prepared_at TEXT NOT NULL,
                printed_at TEXT DEFAULT '',
                finished_at TEXT DEFAULT '',
                released_at TEXT DEFAULT '',
                updated_at TEXT NOT NULL,
                UNIQUE(plancha_id, item_id),
                FOREIGN KEY(plancha_id) REFERENCES plancha_projects(id),
                FOREIGN KEY(order_id) REFERENCES orders(id),
                FOREIGN KEY(order_job_id) REFERENCES order_jobs(id)
            )"""
        )
        self.connection.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_plancha_assignment_active_unit
               ON plancha_item_assignments(requested_unit_key)
               WHERE state <> 'released'"""
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_plancha_assignment_job ON plancha_item_assignments(order_job_id, state)"
        )
        assignment_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(plancha_item_assignments)")}
        if "order_design_line_id" not in assignment_columns:
            self.connection.execute("ALTER TABLE plancha_item_assignments ADD COLUMN order_design_line_id TEXT DEFAULT ''")
        # Migración: asignar production_status basado en el estado actual.
        # Evitar el escaneo completo cuando no existen filas pendientes.
        _pending_planchas = self.connection.execute(
            "SELECT 1 FROM plancha_projects "
            "WHERE production_status = 'borrador' OR production_status IS NULL LIMIT 1"
        ).fetchone()
        if _pending_planchas:
            self.connection.execute(
                """UPDATE plancha_projects SET production_status = CASE
                    WHEN COALESCE(final_png_path, '') = '' AND COALESCE(project_path, '') = '' THEN 'borrador'
                    WHEN COALESCE(final_png_path, '') = '' THEN 'guardada'
                    WHEN print_status = 'Impresa' THEN 'impresa'
                    ELSE 'lista'
                END
                WHERE production_status = 'borrador' OR production_status IS NULL"""
            )
        # Producciones continuas: solo conservan referencias a planchas A4
        # guardadas. No duplican ni modifican los PNG originales.
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS continuous_productions (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'Hoja', width_cm REAL NOT NULL DEFAULT 21,
                length_cm REAL NOT NULL DEFAULT 29.7, material TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Pendiente', production_json TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )"""
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_continuous_productions_status "
            "ON continuous_productions(status, updated_at DESC)"
        )
        for column, definition in (
            ("print_status", "TEXT DEFAULT 'No lista'"),
            ("printed_planchas", "INTEGER DEFAULT 0"),
            ("total_planchas", "INTEGER DEFAULT 0"),
        ):
            if column not in order_columns:
                self.connection.execute(f"ALTER TABLE orders ADD COLUMN {column} {definition}")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS print_jobs (
                id INTEGER PRIMARY KEY, plancha_id INTEGER NOT NULL, order_id INTEGER,
                parent_job_id INTEGER, user_name TEXT DEFAULT '', printer_name TEXT NOT NULL,
                configuration_json TEXT NOT NULL, copies INTEGER NOT NULL DEFAULT 1,
                priority INTEGER NOT NULL DEFAULT 0, delivery_date TEXT DEFAULT '', final_png_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Pendiente', spool_job_id INTEGER,
                error_message TEXT DEFAULT '', created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, printed_at TEXT DEFAULT '',
                FOREIGN KEY(plancha_id) REFERENCES plancha_projects(id),
                FOREIGN KEY(order_id) REFERENCES orders(id)
            )"""
        )
        print_job_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(print_jobs)")}
        if "delivery_date" not in print_job_columns:
            self.connection.execute("ALTER TABLE print_jobs ADD COLUMN delivery_date TEXT DEFAULT ''")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_print_jobs_status ON print_jobs(status, priority DESC, created_at)")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS print_history (
                id INTEGER PRIMARY KEY, print_job_id INTEGER NOT NULL, plancha_id INTEGER NOT NULL,
                order_id INTEGER, user_name TEXT DEFAULT '', printer_name TEXT NOT NULL,
                configuration_json TEXT NOT NULL, copies INTEGER NOT NULL,
                status TEXT NOT NULL, message TEXT DEFAULT '', final_png_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(print_job_id) REFERENCES print_jobs(id)
            )"""
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS variable_cost_models (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                product_id INTEGER DEFAULT NULL,
                product_name TEXT DEFAULT '',
                category TEXT DEFAULT '',
                active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS variable_cost_components (
                id INTEGER PRIMARY KEY,
                model_id INTEGER NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                category TEXT DEFAULT '',
                origin TEXT DEFAULT 'manual',
                source_id INTEGER DEFAULT NULL,
                calc_mode TEXT DEFAULT 'per_unit',
                quantity REAL DEFAULT 0,
                unit_value REAL DEFAULT 0,
                waste_pct REAL DEFAULT 0,
                unit TEXT DEFAULT '',
                percentage_base TEXT DEFAULT '',
                amount REAL DEFAULT 0,
                sort_order INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(model_id) REFERENCES variable_cost_models(id) ON DELETE CASCADE
            )"""
        )
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_vcm_product ON variable_cost_models(product_id)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_vcc_model ON variable_cost_components(model_id)")

        # ── Migración: columnas faltantes para costos variables ────────────
        vcm_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(variable_cost_models)")}
        for column, definition in (
            ("product_key", "TEXT DEFAULT ''"),
            ("outdated", "INTEGER DEFAULT 0"),
        ):
            if column not in vcm_columns:
                self.connection.execute(f"ALTER TABLE variable_cost_models ADD COLUMN {column} {definition}")

        vcc_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(variable_cost_components)")}
        for column, definition in (
            ("source_updated_at", "TEXT DEFAULT ''"),
            ("last_synced_at", "TEXT DEFAULT ''"),
            ("manually_overridden", "INTEGER DEFAULT 0"),
        ):
            if column not in vcc_columns:
                self.connection.execute(f"ALTER TABLE variable_cost_components ADD COLUMN {column} {definition}")

        # Índices adicionales para costos variables
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_vcm_product_key ON variable_cost_models(product_key)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_vcm_active ON variable_cost_models(active)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_vcc_source ON variable_cost_components(source_id)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_vcc_active ON variable_cost_components(active)")
        # Un solo modelo activo por product_key (índice parcial único)
        self.connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_vcm_unique_active_key "
            "ON variable_cost_models(product_key) WHERE active = 1 AND product_key != ''"
        )

        # ── Migraciones de esquema (ejecutar antes de crear EventRepository) ──
        self._migrate_order_clients()
        self._migrate_order_jobs()
        self._migrate_mobile_devices()
        self._migrate_pairing_codes()
        self._migrate_sync_indexes()
        self._migrate_commercial_pricing()
        self._migrate_productive_plancha_costs()
        self._migrate_mobile_security()
        self._migrate_mobile_order_idempotency()
        self.install_doccione_price_catalog()
        self.install_commercial_price_catalog()
        self._repair_legacy_unique_design_plancha_totals()
        self.install_fotocopia_price_catalog()
        self.connection.commit()

        # ── Crear tablas de WhatsApp ──
        from app.whatsapp.repository import create_whatsapp_tables
        create_whatsapp_tables(self.connection)

        # ── Crear EventRepository después de todas las migraciones ──
        from app.events.event_repository import EventRepository
        self.event_repo = EventRepository(self.connection)
        self._restore_recognized_text_from_ai_results()
        self._setup_sticker_search_index()

    def _restore_recognized_text_from_ai_results(self) -> None:
        """Recupera OCR de análisis anteriores al campo de búsqueda actual."""
        rows = self.connection.execute(
            """SELECT images.path, ai_results.result
                 FROM images JOIN ai_results ON ai_results.image_path = images.path
                WHERE ai_results.modified = images.modified
                  AND COALESCE(images.recognized_text, '') = ''"""
        )
        recovered = []
        seen_paths = set()
        for path, raw_result in rows:
            if path in seen_paths:
                continue
            seen_paths.add(path)
            try:
                text = " ".join(str(json.loads(raw_result).get("text") or "").split())
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if text:
                recovered.append((text, path))
        if recovered:
            self.connection.executemany(
                "UPDATE images SET recognized_text = ? WHERE path = ?", recovered
            )

    def _setup_sticker_search_index(self) -> None:
        """Crea el índice de texto que usa la biblioteca.

        FTS5 evita recorrer etiquetas y pedidos completos cada vez que se pulsa
        una tecla. ``unicode61`` además hace que ``seleccion`` encuentre
        ``Selección`` sin pedir al usuario que escriba los acentos exactos.
        """
        self._sticker_search_fts = False
        try:
            # Las bases creadas antes de incluir OCR tenían un índice FTS sin
            # esta columna. Se puede recrear sin perder datos: es un índice
            # derivado de ``images`` e ``image_tags``.
            index_columns = {
                row[1] for row in self.connection.execute("PRAGMA table_info(sticker_search)")
            }
            if index_columns and "recognized_text" not in index_columns:
                self.connection.execute("DROP TABLE sticker_search")
            self.connection.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS sticker_search USING fts5("
                "image_path UNINDEXED, caption, tags, category, design_client, recognized_text, "
                "tokenize='unicode61 remove_diacritics 2')"
            )
            indexed = self.connection.execute("SELECT COUNT(*) FROM sticker_search").fetchone()[0]
            images = self.connection.execute("SELECT COUNT(*) FROM images").fetchone()[0]
            if indexed != images:
                self.connection.execute("DELETE FROM sticker_search")
                self.connection.execute(
                    """INSERT INTO sticker_search(image_path, caption, tags, category, design_client, recognized_text)
                       SELECT images.path, images.caption,
                              COALESCE(GROUP_CONCAT(tags.name, ' '), ''),
                              images.category, images.design_client, images.recognized_text
                       FROM images
                       LEFT JOIN image_tags ON image_tags.image_path = images.path
                       LEFT JOIN tags ON tags.id = image_tags.tag_id
                       GROUP BY images.path"""
                )
            self.connection.commit()
            self._sticker_search_fts = True
        except sqlite3.OperationalError:
            # Algunas instalaciones antiguas de SQLite no incluyen FTS5. La
            # búsqueda clásica sigue disponible en ese caso.
            self._sticker_search_fts = False

    def _refresh_sticker_search_entry(self, image_path: str) -> None:
        """Sincroniza un diseño puntual; las ediciones no obligan a reindexar."""
        if not getattr(self, "_sticker_search_fts", False):
            return
        row = self.connection.execute(
            """SELECT images.path, images.caption, images.category, images.design_client, images.recognized_text,
                      COALESCE(GROUP_CONCAT(tags.name, ' '), '') AS tags
               FROM images LEFT JOIN image_tags ON image_tags.image_path = images.path
               LEFT JOIN tags ON tags.id = image_tags.tag_id
               WHERE images.path = ? GROUP BY images.path""",
            (image_path,),
        ).fetchone()
        self.connection.execute("DELETE FROM sticker_search WHERE image_path = ?", (image_path,))
        if row:
            self.connection.execute(
                "INSERT INTO sticker_search(image_path, caption, tags, category, design_client, recognized_text) VALUES(?, ?, ?, ?, ?, ?)",
                (row["path"], row["caption"], row["tags"], row["category"], row["design_client"], row["recognized_text"]),
            )

    @staticmethod
    def _fts_query(query: str) -> str:
        # Una palabra por prefijo: rápido al escribir y sin permitir que el
        # texto de usuario altere la sintaxis de FTS.
        tokens = re.findall(r"[\wÀ-ÿ]+", query)
        return " AND ".join(f"{token}*" for token in tokens)

    def _migrate_commercial_pricing(self) -> None:
        """Añade el catálogo comercial sin alterar los pedidos ni reglas existentes."""
        from datetime import datetime

        # Una copia recuperable sólo se crea al migrar una base existente.
        has_catalog = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='products'"
        ).fetchone()
        if not has_catalog and self.db_path.exists() and self.db_path.stat().st_size:
            backup = self.db_path.with_suffix(self.db_path.suffix + ".before_commercial_pricing.bak")
            if not backup.exists():
                self.connection.commit()
                shutil.copy2(self.db_path, backup)

        self.connection.execute("""CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        product_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(products)")}
        for column, definition in (
            ("description", "TEXT DEFAULT ''"),
            ("category", "TEXT DEFAULT ''"),
            ("image_path", "TEXT DEFAULT ''"),
            ("base_price", "REAL DEFAULT NULL"),
        ):
            if column not in product_columns:
                self.connection.execute(f"ALTER TABLE products ADD COLUMN {column} {definition}")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS product_variants (
            id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL, code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL, line TEXT DEFAULT '', material TEXT DEFAULT '', size TEXT DEFAULT '',
            modality TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products(id))""")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS price_lists (
            id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_variants_product ON product_variants(product_id)")
        price_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(price_rules)")}
        for column, definition in (
            ("product_id", "INTEGER"), ("variant_id", "INTEGER"), ("price_list_id", "INTEGER"),
            ("max_quantity", "INTEGER"), ("priority", "INTEGER NOT NULL DEFAULT 0"),
            ("rule_name", "TEXT DEFAULT ''"), ("preparation_limit", "INTEGER"),
        ):
            if column not in price_columns:
                self.connection.execute(f"ALTER TABLE price_rules ADD COLUMN {column} {definition}")
        job_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(order_jobs)")}
        for column, definition in (
            ("product_id", "INTEGER"), ("variant_id", "INTEGER"), ("price_list_id", "INTEGER"),
            ("price_rule_id", "INTEGER"), ("unit_price_snapshot", "REAL"),
            ("fixed_price_snapshot", "REAL"), ("product_name_snapshot", "TEXT DEFAULT ''"),
            ("variant_name_snapshot", "TEXT DEFAULT ''"), ("price_list_name_snapshot", "TEXT DEFAULT ''"),
            ("price_rule_name_snapshot", "TEXT DEFAULT ''"), ("calculation_type", "TEXT DEFAULT ''"),
            ("material_snapshot", "TEXT DEFAULT ''"), ("size_snapshot", "TEXT DEFAULT ''"),
            ("manual_override", "INTEGER NOT NULL DEFAULT 0"), ("manual_override_reason", "TEXT DEFAULT ''"),
            ("calculated_at", "TEXT DEFAULT ''"),
        ):
            if column not in job_columns:
                self.connection.execute(f"ALTER TABLE order_jobs ADD COLUMN {column} {definition}")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_price_rules_match ON price_rules(product_id, variant_id, price_list_id, active)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_order_jobs_price_rule ON order_jobs(price_rule_id)")

    def _migrate_productive_plancha_costs(self) -> None:
        """Agrega datos productivos A4 sin recalcular ni alterar pedidos históricos."""
        from datetime import datetime

        has_schema = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'order_job_production_estimates'"
        ).fetchone()
        if not has_schema and self.db_path.exists() and self.db_path.stat().st_size:
            backup = self.db_path.with_suffix(self.db_path.suffix + ".before_productive_plancha_costs.bak")
            if not backup.exists():
                self.connection.commit()
                shutil.copy2(self.db_path, backup)

        order_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(orders)")}
        for column, definition in (
            ("commercial_cost", "REAL DEFAULT 0"),
            ("commercial_cost_kind", "TEXT DEFAULT ''"),
            ("final_cost", "REAL DEFAULT 0"),
            ("final_margin", "REAL DEFAULT 0"),
        ):
            if column not in order_columns:
                self.connection.execute(f"ALTER TABLE orders ADD COLUMN {column} {definition}")

        job_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(order_jobs)")}
        for column, definition in (
            ("base_price_snapshot", "REAL DEFAULT 0"),
            ("suggested_price_snapshot", "REAL DEFAULT 0"),
            ("applied_price_snapshot", "REAL DEFAULT 0"),
            ("productive_cost", "REAL DEFAULT 0"),
            ("commercial_cost_allocated", "REAL DEFAULT 0"),
            ("final_cost", "REAL DEFAULT 0"),
            ("productive_margin", "REAL DEFAULT 0"),
            ("final_margin", "REAL DEFAULT 0"),
            ("productive_classification", "TEXT DEFAULT ''"),
            ("production_mode", "TEXT DEFAULT ''"),
            ("price_source", "TEXT DEFAULT 'legacy'"),
            ("manual_price_snapshot", "REAL"),
        ):
            if column not in job_columns:
                self.connection.execute(f"ALTER TABLE order_jobs ADD COLUMN {column} {definition}")

        design_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(order_designs)")}
        for column, definition in (
            ("order_job_id", "INTEGER"),
            ("estimated_design_minutes", "REAL DEFAULT 0"),
        ):
            if column not in design_columns:
                self.connection.execute(f"ALTER TABLE order_designs ADD COLUMN {column} {definition}")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_order_designs_job ON order_designs(order_job_id)")
        self._migrate_order_designs_nominal_size()
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS order_design_job_links (
                id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL,
                order_job_id INTEGER NOT NULL,
                image_path TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                size_cm REAL NOT NULL DEFAULT 5.0,
                rotation INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(order_job_id,image_path,size_cm,rotation),
                FOREIGN KEY(order_id) REFERENCES orders(id),
                FOREIGN KEY(order_job_id) REFERENCES order_jobs(id)
            )"""
        )
        # Tabla aditiva v2: conserva intacta la relación histórica, pero permite
        # dos líneas del mismo trabajo con idéntico archivo y configuración.
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS order_design_demand_lines (
                id INTEGER PRIMARY KEY, design_line_id TEXT NOT NULL UNIQUE,
                order_id INTEGER NOT NULL, order_job_id INTEGER NOT NULL,
                image_path TEXT NOT NULL, quantity INTEGER NOT NULL DEFAULT 1,
                size_cm REAL NOT NULL DEFAULT 5.0, rotation INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                FOREIGN KEY(order_id) REFERENCES orders(id),
                FOREIGN KEY(order_job_id) REFERENCES order_jobs(id)
            )"""
        )
        demand_count = self.connection.execute("SELECT COUNT(*) FROM order_design_demand_lines").fetchone()[0]
        if not demand_count:
            legacy_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(order_design_job_links)")}
            for legacy in self.connection.execute("SELECT * FROM order_design_job_links").fetchall():
                data = dict(legacy)
                line_id = str(data.get("design_line_id") or f"legacy-design-line-{data['id']}")
                self.connection.execute(
                    """INSERT OR IGNORE INTO order_design_demand_lines(
                           design_line_id,order_id,order_job_id,image_path,quantity,size_cm,rotation,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (line_id, data["order_id"], data["order_job_id"], data["image_path"], data["quantity"],
                     data["size_cm"], data["rotation"], data["created_at"], data["updated_at"]),
                )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_order_design_demand_order ON order_design_demand_lines(order_id,order_job_id)"
        )
        demand_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(order_design_demand_lines)")}
        for column, definition in (
            ("unit_kind", "TEXT DEFAULT ''"),
            ("packing_mode", "TEXT DEFAULT ''"),
            ("workspace_format", "TEXT DEFAULT 'a4'"),
        ):
            if column not in demand_columns:
                self.connection.execute(f"ALTER TABLE order_design_demand_lines ADD COLUMN {column} {definition}")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS production_batches (
                id INTEGER PRIMARY KEY, batch_key TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'prepared',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                cancelled_at TEXT DEFAULT ''
            )"""
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS production_batch_planchas (
                batch_id INTEGER NOT NULL, plancha_id INTEGER NOT NULL UNIQUE,
                group_key TEXT NOT NULL, plancha_number INTEGER NOT NULL,
                PRIMARY KEY(batch_id,plancha_id),
                FOREIGN KEY(batch_id) REFERENCES production_batches(id),
                FOREIGN KEY(plancha_id) REFERENCES plancha_projects(id)
            )"""
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_order_design_job_links_order ON order_design_job_links(order_id,order_job_id)"
        )
        self.connection.execute("""CREATE TABLE IF NOT EXISTS order_job_production_estimates (
            order_job_id INTEGER PRIMARY KEY, unique_designs INTEGER NOT NULL DEFAULT 1,
            production_mode TEXT NOT NULL DEFAULT 'individual', design_minutes REAL DEFAULT 0,
            design_minutes_json TEXT DEFAULT '[]',
            print_minutes REAL DEFAULT 0, cut_minutes REAL DEFAULT 0,
            productive_surcharge REAL DEFAULT 0, additional_services REAL DEFAULT 0,
            authorized_discount REAL DEFAULT 0, additional_materials REAL DEFAULT 0,
            waste_cost REAL DEFAULT 0, valid_productive_exception INTEGER DEFAULT 0,
            calculated_at TEXT DEFAULT '', FOREIGN KEY(order_job_id) REFERENCES order_jobs(id))""")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS order_job_internal_incidents (
            id INTEGER PRIMARY KEY, order_job_id INTEGER NOT NULL, kind TEXT NOT NULL DEFAULT '',
            description TEXT DEFAULT '', extra_minutes REAL DEFAULT 0, cost REAL DEFAULT 0,
            created_at TEXT NOT NULL, FOREIGN KEY(order_job_id) REFERENCES order_jobs(id))""")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_order_job_incidents_job ON order_job_internal_incidents(order_job_id, id DESC)")
        estimate_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(order_job_production_estimates)")}
        if "design_minutes_json" not in estimate_columns:
            self.connection.execute("ALTER TABLE order_job_production_estimates ADD COLUMN design_minutes_json TEXT DEFAULT '[]'")

        defaults = {
            "productive_plancha_a4.base_price": "5000",
            "productive_plancha_a4.standard_design_minutes": "10",
            "productive_plancha_a4.standard_print_minutes": "10",
            "productive_plancha_a4.standard_cut_minutes": "10",
            "productive_plancha_a4.additional_design_block_minutes": "10",
            "productive_plancha_a4.additional_design_block_rate": "1000",
            "productive_plancha_a4.standard_target_cost": "2000",
            "productive_plancha_a4.standard_raw_material_cost": "635",
            "productive_plancha_a4.standard_overhead_cost": "465",
            "productive_plancha_a4.labor_hour_rate": "1800",
            "productive_plancha_a4.commercial_cost_first_purchase": "500",
            "productive_plancha_a4.commercial_cost_recurrent": "300",
            "productive_plancha_a4.batch_efficiency_enabled": "0",
            "productive_plancha_a4.batch_print_setup_minutes": "10",
            "productive_plancha_a4.batch_print_incremental_minutes": "1",
            "productive_plancha_a4.batch_cut_setup_minutes": "10",
            "productive_plancha_a4.batch_cut_incremental_minutes": "1",
        }
        now = datetime.now().isoformat(timespec="seconds")
        for key, value in defaults.items():
            self.connection.execute(
                "INSERT INTO app_settings(setting_key, setting_value, updated_at) VALUES(?, ?, ?) ON CONFLICT(setting_key) DO NOTHING",
                (key, value, now),
            )

    def _repair_legacy_unique_design_plancha_totals(self) -> None:
        """Repara trabajos pendientes guardados cuando Diseño Único era fijo.

        Sólo alcanza registros cuyo total coincide exactamente con el cálculo
        fijo anterior (una sola plancha con su descuento). Así no modifica
        precios manuales ni pedidos que ya se cotizaron correctamente.
        """
        rule = self.connection.execute(
            """SELECT price FROM price_rules
                 WHERE active = 1 AND material = 'Plancha A4 - Diseño Único'
                   AND size = 'A4' ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        if not rule:
            return
        unit_price = float(rule["price"] or 0)
        if unit_price <= 0:
            return
        rows = self.connection.execute(
            """SELECT j.id, j.order_id, j.quantity, j.subtotal,
                      COALESCE(j.discount_percent, 0) AS discount_percent
                 FROM order_jobs j
                 JOIN orders o ON o.id = j.order_id
                 WHERE j.quantity > 1
                   AND TRIM(j.material) = 'Plancha A4 - Diseño Único'
                   AND LOWER(TRIM(COALESCE(o.status, ''))) NOT IN ('entregado', 'terminado')"""
        ).fetchall()
        for row in rows:
            discount_factor = 1 - max(0.0, min(100.0, float(row["discount_percent"] or 0))) / 100
            old_total = round(unit_price * discount_factor, 2)
            if abs(float(row["subtotal"] or 0) - old_total) > 0.01:
                continue
            corrected_total = round(unit_price * int(row["quantity"]) * discount_factor, 2)
            delta = corrected_total - float(row["subtotal"] or 0)
            self.connection.execute("UPDATE order_jobs SET subtotal = ? WHERE id = ?", (corrected_total, row["id"]))
            self.connection.execute(
                """UPDATE orders SET price = COALESCE(price, 0) + ?,
                       budget_total = COALESCE(budget_total, 0) + ? WHERE id = ?""",
                (delta, delta, row["order_id"]),
            )

    def install_commercial_price_catalog(self) -> int:
        """Carga reglas oficiales con claves estables, sin sobrescribir ediciones manuales."""
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        products = (("sticker_troquelado", "Stickers Individuales Vinilo Blanco Sublimable HD"), ("sticker_plotteado", "Sticker o vinilo plotteado"),
                    ("sticker_vinilo_especial", "Stickers Individuales Vinilo Especial"),
                    ("impresiones_fotograficas", "Impresiones fotogr\u00e1ficas"),
                    ("plancha_a4", "Plancha personalizada A4"), ("tarjeta_personalizada", "Tarjeta personalizada"),
                    ("sticker_doming", "Sticker doming"), ("servicio_diseno", "Servicio de diseño"),
                    ("servicio_impresion", "Servicio de impresión"), ("servicio_corte", "Servicio de corte"))
        for code, name in products:
            self.connection.execute("INSERT INTO products(code, name, created_at, updated_at) VALUES(?, ?, ?, ?) ON CONFLICT(code) DO NOTHING", (code, name, now, now))
        self.connection.execute(
            "UPDATE products SET name = ?, updated_at = ? WHERE code = ? AND name = ?",
            ("Stickers Individuales Vinilo Blanco Sublimable HD", now, "sticker_troquelado", "Sticker troquelado"),
        )
        self.connection.execute(
            "UPDATE products SET name = ?, updated_at = ? WHERE code = ?",
            ("Impresiones A4", now, "impresiones_fotograficas"),
        )
        self.connection.execute(
            """UPDATE products
                  SET base_price = CASE WHEN COALESCE(base_price, 0) IN (0, 1500) THEN 1400 ELSE base_price END,
                      description = CASE WHEN TRIM(COALESCE(description, '')) = '' THEN ? ELSE description END,
                      updated_at = ?
                WHERE code = ?""",
            (
                "Impresiones A4 con precio unitario decreciente seg\u00fan la cantidad.",
                now,
                "impresiones_fotograficas",
            ),
        )
        # La ficha se incorporó inicialmente al catálogo comercial con otro
        # código. La opción histórica del formulario es ``plastificado_a4``;
        # conservamos ese código para que los pedidos existentes y el selector
        # apunten a una única ficha.
        self.connection.execute(
            "UPDATE products SET active = 0, updated_at = ? WHERE code = ?",
            (now, "poster_plastificado_a4"),
        )
        self.connection.execute(
            "UPDATE price_rules SET active = 0 WHERE catalog_key LIKE 'commercial_poster_plastificado_a4_%'",
        )
        lists = (("general", "Precios generales"), ("pedidos", "Precios de pedidos"),
                 ("programa_emprendedor_doccione", "Programa Emprendedor Doccione"))
        for code, name in lists:
            self.connection.execute("INSERT INTO price_lists(code, name, created_at, updated_at) VALUES(?, ?, ?, ?) ON CONFLICT(code) DO NOTHING", (code, name, now, now))
        # Las bases creadas antes del catálogo comercial usaban "General" para
        # la misma lista predeterminada. Unificamos el rótulo sin alterar su ID
        # ni las reglas que ya la referencian.
        self.connection.execute(
            "UPDATE price_lists SET name = ?, updated_at = ? WHERE code = ? AND name = ?",
            ("Precios generales", now, "general", "General"),
        )
        # Las reglas heredadas no tenían lista vinculada y la interfaz las
        # presenta como "Precios generales". Las asociamos a esa misma lista
        # para evitar que aparezca como una segunda categoría visual.
        self.connection.execute(
            "UPDATE price_rules SET price_list_id = (SELECT id FROM price_lists WHERE code = ?) "
            "WHERE price_list_id IS NULL",
            ("general",),
        )
        product_ids = {r["code"]: r["id"] for r in self.connection.execute("SELECT id, code FROM products")}
        list_ids = {r["code"]: r["id"] for r in self.connection.execute("SELECT id, code FROM price_lists")}
        self.connection.execute(
            "UPDATE price_rules SET product_id = ? WHERE material = ?",
            (product_ids["sticker_troquelado"], "Vinilo Full Color HD"),
        )
        self.connection.execute(
            "UPDATE price_rules SET product_id = ? WHERE material IN (?, ?)",
            (product_ids["sticker_vinilo_especial"], "Vinilo Premium", "Vinilo Full Color Perlado Premium"),
        )
        self.connection.execute(
            "UPDATE price_rules SET product_id = ? WHERE material LIKE ?",
            (product_ids["impresiones_fotograficas"], "Papel fotogr%fico A4"),
        )
        self.connection.execute(
            "UPDATE products SET active = 0, updated_at = ? WHERE code IN (?, ?, ?)",
            (now, "impresion_fotografica_1_unidad", "folletos_fotograficos_4_unidades", "tarjetas_presentacion_fotograficas_10_unidades"),
        )
        self.connection.execute(
            """UPDATE price_rules SET active = 0
                 WHERE catalog_key LIKE 'doccione_2026_07_15_%'
                   AND material IN ('Vinilo Full Color HD', 'Vinilo Ploteado',
                                    'Vinilo Premium', 'Resina 3D Premium')"""
        )
        rules = []
        def add(key, product, material, size, minimum, maximum, price, mode="unitario", pack=1, price_list="general", preparation=None):
            rules.append((key, product_ids[product], material, size, minimum, maximum, price, mode, pack, list_ids[price_list], preparation))
        for size, price in ((5,400),(7,500),(8,700),(10,900),(12,1200),(15,1800),(18,2500),(20,3000),(25,4200),(29,5000)):
            add(f"sticker_full_color_standard_{size}cm", "sticker_troquelado", "Vinilo Full Color HD", f"{size}cm", 1, None, price)
        for size, price in ((5,500),(7,650),(8,850),(10,1100),(12,1500),(15,2150),(18,3000),(20,3600),(25,5000),(29,6000)):
            add(f"sticker_premium_{size}cm", "sticker_vinilo_especial", "Vinilo Premium", f"{size}cm", 1, None, price)
        for size, price in ((5,300),(7,500),(8,700),(10,1000),(12,1300),(14,1600),(15,1800),(17,2200),(20,2600),(25,3000),(29,3500)):
            add(f"sticker_plotteado_{size}cm", "sticker_plotteado", "Vinilo Ploteado", f"{size}cm", 1, None, price)
        for minimum, maximum, price in ((1,9,400),(10,19,350),(20,99,300),(100,199,280),(200,499,260),(500,999,240),(1000,None,220)):
            add(f"sticker_full_color_5cm_{minimum}", "sticker_troquelado", "Vinilo Full Color HD", "5cm", minimum, maximum, price)
        for minimum, maximum, price, limit in ((100,499,260,10),(500,999,220,50),(1000,None,200,100)):
            add(f"emprendedor_full_color_5cm_{minimum}", "sticker_troquelado", "Vinilo Full Color HD", "5cm", minimum, maximum, price, price_list="programa_emprendedor_doccione", preparation=limit)
        for minimum, maximum, price in ((1,23,250),(24,79,200),(80,None,150)):
            add(f"tarjeta_personalizada_{minimum}", "tarjeta_personalizada", "Tarjeta personalizada", "", minimum, maximum, price)
        # Impresiones A4: escala comercial automática por cantidad.
        for minimum, maximum, price in ((1,4,1400),(5,9,1350),(10,24,1300),(25,49,1250),(50,None,1200)):
            add(
                f"impresion_fotografica_a4_{minimum}",
                "impresiones_fotograficas",
                "Impresi\u00f3n A4",
                "A4",
                minimum,
                maximum,
                price,
            )
        # Cada unidad es una plancha independiente: el importe debe crecer
        # cuando se solicitan varias planchas del mismo diseño.
        add("plancha_a4_diseno_unico", "plancha_a4", "Vinilo estándar", "A4", 1, None, 5000, "unitario")
        add("plancha_a4_combinada_estandar", "plancha_a4", "Vinilo blanco full color", "A4", 1, None, 6000, "fijo")
        add("plancha_a4_combinada_especial", "plancha_a4", "Vinilo especial", "A4", 1, None, 7000, "fijo")
        # Servicio separado de la impresión: una unidad equivale al diseño
        # simple necesario para una plancha A4. Sigue siendo editable desde
        # Comercial > Precios como cualquier otra regla.
        add("diseno_simple_a4", "servicio_diseno", "Diseño simple", "A4", 1, None, 300, "unitario")
        add("impresion_a4", "servicio_impresion", "Impresión", "A4", 1, None, 300, "unitario")
        add("corte_a4", "servicio_corte", "Corte", "A4", 1, None, 300, "unitario")
        for size, price in ((5,1500),(7,2500),(10,3500),(12,4500),(14,5500),(15,7000),(18,8000),(20,10000),(25,13000),(29,17000)):
            add(f"doming_{size}cm_individual", "sticker_doming", "Resina 3D Premium", f"{size}cm", 1, None, price)
        for quantity, total in ((5,7000),(10,13000),(20,24000)):
            add(f"doming_5cm_pack_{quantity}", "sticker_doming", "Resina 3D Premium", "5cm", quantity, quantity, total, "pack", quantity)
        for key, product_id, material, size, minimum, maximum, price, mode, pack, list_id, limit in rules:
            catalog_key = f"commercial_{key}"
            if self.connection.execute("SELECT 1 FROM price_rules WHERE catalog_key = ?", (catalog_key,)).fetchone():
                continue
            self.connection.execute("""INSERT INTO price_rules(product_id, material, size, min_quantity, max_quantity, price,
                price_mode, pack_quantity, price_list_id, preparation_limit, priority, rule_name, catalog_key, active)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 100, ?, ?, 1)""",
                (product_id, material, size, minimum, maximum, price, mode, pack, list_id, limit, key.replace("_", " ").title(), catalog_key))
        # Actualiza las escalas de Impresiones A4 que ya existían antes de este
        # cambio de lista, conservando sus claves estables.
        for catalog_key, minimum, maximum, price in (
            ("commercial_impresion_fotografica_a4_1", 1, 4, 1400),
            ("commercial_impresion_fotografica_a4_5", 5, 9, 1350),
            ("commercial_impresion_fotografica_a4_10", 10, 24, 1300),
            ("commercial_impresion_fotografica_a4_25", 25, 49, 1250),
            ("commercial_impresion_fotografica_a4_50", 50, None, 1200),
        ):
            self.connection.execute(
                """UPDATE price_rules SET min_quantity = ?, max_quantity = ?,
                       price = ?, price_mode = 'unitario', active = 1
                     WHERE catalog_key = ?""",
                (minimum, maximum, price, catalog_key),
            )
        # Corrige instalaciones ya inicializadas sin pisar una regla editada:
        # sólo migra el valor original entregado por el catálogo.
        self.connection.execute(
            """UPDATE price_rules SET price_mode = 'unitario'
                 WHERE catalog_key = 'commercial_plancha_a4_diseno_unico'
                   AND price = 5000 AND price_mode = 'fijo'"""
        )
        # La regla histórica que usa el formulario de pedidos se instalaba
        # como precio fijo. Se conserva el importe configurado por el usuario
        # (por ejemplo, $4.000), pero cada plancha debe cobrarse por unidad.
        self.connection.execute(
            """UPDATE price_rules SET price_mode = 'unitario'
                 WHERE catalog_key LIKE 'doccione_2026_07_15_%'
                   AND material = 'Plancha A4 - Diseño Único'
                   AND size = 'A4' AND price_mode = 'fijo'"""
        )
        return len(rules)

    def install_fotocopia_price_catalog(self) -> int:
        """Carga reglas de precios iniciales para Fotocopias y terminaciones."""
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        
        # Insertar configuración inicial de recargo urgente (30%)
        self.connection.execute(
            """INSERT INTO fotocopia_config(id, urgent_surcharge_percent, created_at, updated_at) 
               VALUES(1, 30.0, ?, ?) 
               ON CONFLICT(id) DO UPDATE SET urgent_surcharge_percent = 30.0, updated_at = ?""",
            (now, now, now)
        )
        
        # Insertar productos de fotocopias y terminaciones
        products = (
            ("fotocopia_bn_simple", "Fotocopia B/N Simple"),
            ("fotocopia_bn_doble", "Fotocopia B/N Doble Faz"),
            ("fotocopia_color_simple", "Fotocopia Color Simple"),
            ("fotocopia_color_doble", "Fotocopia Color Doble Faz"),
            ("anillado_chico", "Anillado Chico"),
            ("anillado_mediano", "Anillado Mediano"),
            ("anillado_grande", "Anillado Grande"),
            ("plastificado_a4", "Plastificado A4"),
            ("hoja_fotografica_plastificada", "Hoja Fotográfica Plastificada"),
            ("impresion_fotografica_1_unidad", "Impresion Fotografica (1 Unidad)"),
            ("folletos_fotograficos_4_unidades", "Folletos Fotográficos (4 unidades)"),
            ("tarjetas_presentacion_fotograficas_10_unidades", "Tarjetas Presentacion Fotograficas (10 Unidades)"),
        )
        
        # Eliminar producto antiguo si existe
        self.connection.execute("DELETE FROM products WHERE code = 'impresion_fotografica_a4'")
        for code, name in products:
            self.connection.execute(
                "INSERT INTO products(code, name, created_at, updated_at) VALUES(?, ?, ?, ?) ON CONFLICT(code) DO NOTHING",
                (code, name, now, now)
            )
        self.connection.execute(
            """UPDATE products
                  SET name = ?,
                      base_price = CASE WHEN COALESCE(base_price, 0) = 0 THEN 2500 ELSE base_price END,
                      description = CASE WHEN TRIM(COALESCE(description, '')) = '' THEN ? ELSE description END,
                      updated_at = ?
                WHERE code = ?""",
            (
                "P\u00f3ster plastificado A4",
                "A4 (21 \u00d7 29,7 cm). Precios por cantidad sujetos a un mismo dise\u00f1o o dise\u00f1os enviados en alta calidad. Dise\u00f1os personalizados se cotizan por separado.",
                now,
                "plastificado_a4",
            ),
        )
        
        # Obtener IDs de productos
        product_ids = {r["code"]: r["id"] for r in self.connection.execute("SELECT id, code FROM products")}
        # Sustituye los tres productos históricos de impresión fotográfica por
        # la única ficha comercial ``Impresiones fotográficas`` y sus escalas.
        self.connection.execute(
            """UPDATE price_rules SET active = 0
                 WHERE catalog_key IN (
                    'impresion_fotografica_1_unidad',
                    'folletos_fotograficos_4_unidades',
                    'tarjetas_presentacion_fotograficas_10_unidades'
                 )"""
        )
        
        # Insertar reglas de precio iniciales
        rules = []
        def add(key, product, material, size, minimum, maximum, price, mode="unitario"):
            rules.append((key, product_ids[product], material, size, minimum, maximum, price, mode))
        
        # Fotocopias
        add("fotocopia_bn_simple", "fotocopia_bn_simple", "Papel A4", "", 1, None, 50)
        add("fotocopia_bn_doble", "fotocopia_bn_doble", "Papel A4", "", 1, None, 80)
        add("fotocopia_color_simple", "fotocopia_color_simple", "Papel A4", "", 1, None, 120)
        add("fotocopia_color_doble", "fotocopia_color_doble", "Papel A4", "", 1, None, 180)
        
        # Anillados (precio por unidad, incluye tapas)
        add("anillado_chico", "anillado_chico", "Espiral Chico", "", 1, None, 1200)
        add("anillado_mediano", "anillado_mediano", "Espiral Mediano", "", 1, None, 1800)
        add("anillado_grande", "anillado_grande", "Espiral Grande", "", 1, None, 2500)
        add("hoja_fotografica_plastificada", "hoja_fotografica_plastificada", "Hoja Fotográfica", "A4", 1, None, 2500)
        # Escala comercial de la hoja fotográfica plastificada. Se conserva
        # separada del plastificado A4 básico para que ambos productos no
        # compartan reglas ni precios.
        for minimum, maximum, price in (
            (1, 4, 2500), (5, 9, 2400), (10, 24, 2300),
            (25, 49, 2200), (50, None, 2100),
        ):
            add(
                f"hoja_fotografica_plastificada_{minimum}",
                "hoja_fotografica_plastificada",
                "Póster plastificado",
                "A4 (21 × 29,7 cm)",
                minimum,
                maximum,
                price,
            )
        
        # Pósters plastificados A4. Desde 10 unidades se cotiza manualmente:
        # sin regla para ese tramo, la aplicación no inventa un importe.
        for minimum, maximum, price in (
            (1, None, 1500),
        ):
            add(
                f"plastificado_a4_{minimum}",
                "plastificado_a4",
                "Plastificado A4",
                "A4 (21 \u00d7 29,7 cm)",
                minimum,
                maximum,
                price,
            )

        # Migrar únicamente la regla histórica que conserva el precio original.
        self.connection.execute(
            """UPDATE price_rules SET active = 0
                 WHERE catalog_key = 'plastificado_a4' AND price = 1500"""
        )
        # Migra las escalas que se instalaron en versiones anteriores, sin
        # duplicar reglas en las bases que ya estaban en uso.
        poster_tiers = (
            ("plastificado_a4_1", 1, None, 1500),
        )
        self.connection.execute(
            """UPDATE price_rules SET active = 0
                 WHERE catalog_key LIKE 'plastificado_a4_%'
                   AND catalog_key <> 'plastificado_a4_1'"""
        )
        for catalog_key, minimum, maximum, price in poster_tiers:
            self.connection.execute(
                """UPDATE price_rules
                      SET product_id = ?, material = ?, size = ?, min_quantity = ?,
                          max_quantity = ?, price = ?, price_mode = 'unitario',
                          pack_quantity = 1, active = 1
                    WHERE catalog_key = ?""",
                (
                    product_ids["plastificado_a4"], "Plastificado A4", "A4 (21 \u00d7 29,7 cm)",
                    minimum, maximum, price, catalog_key,
                ),
            )
        # El tramo 2–4 pertenecía a la escala anterior; queda retirado.
        self.connection.execute(
            "UPDATE price_rules SET active = 0 WHERE catalog_key = 'plastificado_a4_2'"
        )
        
        # Insertar reglas en price_rules
        for key, product_id, material, size, minimum, maximum, price, mode in rules:
            catalog_key = key  # Use key directly as catalog_key (key already includes product type)
            if self.connection.execute("SELECT 1 FROM price_rules WHERE catalog_key = ?", (catalog_key,)).fetchone():
                continue
            self.connection.execute(
                """INSERT INTO price_rules(product_id, material, size, min_quantity, max_quantity, price,
                   price_mode, pack_quantity, catalog_key, active)
                   VALUES(?, ?, ?, ?, ?, ?, ?, 1, ?, 1)""",
                (product_id, material, size, minimum, maximum, price, mode, catalog_key)
            )
        
        return len(rules)

    @staticmethod
    def _clean_order_job(job: dict | None, position: int = 0) -> dict:
        """Normaliza un trabajo antes de persistirlo en un pedido."""
        job = job or {}
        try:
            quantity = max(1, int(job.get("quantity", 1) or 1))
        except (TypeError, ValueError):
            quantity = 1
        try:
            subtotal = max(0.0, float(str(job.get("subtotal", job.get("price", 0)) or 0).replace(",", ".")))
        except (TypeError, ValueError):
            subtotal = 0.0
        try:
            discount = min(100.0, max(0.0, float(str(job.get("discount_percent", 0) or 0).replace(",", "."))))
        except (TypeError, ValueError):
            discount = 0.0

        def _safe_float(val) -> float:
            try:
                return max(0.0, float(str(val or 0).replace(",", ".")))
            except (TypeError, ValueError):
                return 0.0

        def _optional_float(val) -> float | None:
            if val is None or val == "":
                return None
            return _safe_float(val)

        title = str(job.get("title", "") or "").strip() or f"Producto {position + 1}"
        return {
            "id": job.get("id"), "title": title,
            "distribution_policy": str(job.get("distribution_policy") or "legacy"),
            "unit_kind": str(job.get("unit_kind", "") or "").strip().casefold()
            if str(job.get("unit_kind", "") or "").strip().casefold() in {"item", "sheet"} else "",
            "material": str(job.get("material", "") or "").strip(),
            "size": str(job.get("size", "") or "").strip(),
            "quantity": quantity, "subtotal": round(subtotal, 2),
            "discount_percent": discount,
            "extra_services": str(job.get("extra_services", "") or "").strip(),
            "status": str(job.get("status", "Pendiente") or "Pendiente").strip() or "Pendiente",
            "notes": str(job.get("notes", "") or "").strip(),
            "sort_order": position,
            # Costos desglosados — pueden venir de suggest_price o ingresarse manualmente
            "cost_mp":    round(_safe_float(job.get("cost_mp", 0)),    2),
            "cost_mo":    round(_safe_float(job.get("cost_mo", 0)),    2),
            "cost_cf":    round(_safe_float(job.get("cost_cf", 0)),    2),
            "cost_total": round(_safe_float(job.get("cost_total", 0)), 2),
            # Los valores de catálogo son opcionales para mantener pedidos antiguos.
            "product_id": job.get("product_id"), "variant_id": job.get("variant_id"),
            "price_list_id": job.get("price_list_id"), "price_rule_id": job.get("price_rule_id"),
            "unit_price_snapshot": _safe_float(job.get("unit_price_snapshot", 0)),
            "fixed_price_snapshot": _safe_float(job.get("fixed_price_snapshot", 0)),
            "manual_override": int(bool(job.get("manual_override", False))),
            "manual_override_reason": str(job.get("manual_override_reason", "") or "").strip(),
            # Snapshots: un presupuesto/pedido confirmado no depende de reglas futuras.
            "base_price_snapshot": _safe_float(job.get("base_price_snapshot", job.get("base_price", 0))),
            "suggested_price_snapshot": _safe_float(job.get("suggested_price_snapshot", job.get("suggested_price", job.get("subtotal", 0)))),
            "applied_price_snapshot": _optional_float(job.get("applied_price_snapshot", job.get("applied_price"))),
            "manual_price_snapshot": _optional_float(job.get("manual_price_snapshot", job.get("manual_price"))),
            "price_source": str(job.get("price_source", "suggested") or "suggested"),
            "productive_cost": _safe_float(job.get("productive_cost", 0)),
            "commercial_cost_allocated": _safe_float(job.get("commercial_cost_allocated", 0)),
            "final_cost": _safe_float(job.get("final_cost", 0)),
            "productive_margin": _safe_float(job.get("productive_margin", 0)),
            "final_margin": _safe_float(job.get("final_margin", 0)),
            "productive_classification": str(job.get("productive_classification", "") or ""),
            "production_mode": str(job.get("production_mode", "") or ""),
            "production_estimate": dict(job.get("production_estimate") or {}),
        }

    def _write_order_jobs(self, order_id: int, jobs: list[dict], now: str) -> list[dict]:
        """Reemplaza el detalle dentro de la transacción que guarda el pedido."""
        clean_jobs = [self._clean_order_job(job, position) for position, job in enumerate(jobs)]
        if not clean_jobs:
            clean_jobs = [self._clean_order_job({}, 0)]
        supplied_ids = {int(job["id"]) for job in clean_jobs if job.get("id") is not None}
        for job in clean_jobs:
            if job.get("id") is None:
                continue
            produced = float(self.connection.execute(
                """SELECT COALESCE(SUM(quantity),0) FROM plancha_item_assignments
                   WHERE order_job_id=? AND state<>'released'""",
                (int(job["id"]),),
            ).fetchone()[0] or 0)
            if float(job["quantity"]) < produced:
                raise ValueError(
                    f"No se puede reducir el trabajo #{job['id']} a {job['quantity']}: "
                    f"ya hay {produced:g} unidad(es) reservadas, impresas o terminadas. "
                    "Conservá la cantidad histórica y registrá el ajuste como una línea nueva."
                )
        existing_ids = {int(row[0]) for row in self.connection.execute(
            "SELECT id FROM order_jobs WHERE order_id=?", (order_id,)
        )}
        if len(supplied_ids) != sum(job.get("id") is not None for job in clean_jobs) or not supplied_ids <= existing_ids:
            raise ValueError("Los trabajos deben ser únicos y pertenecer al pedido.")
        for job in clean_jobs:
            original = jobs[job["sort_order"]] if job["sort_order"] < len(jobs) else {}
            if job.get("id") is not None and "distribution_policy" not in original:
                policy = self.connection.execute("SELECT distribution_policy FROM order_jobs WHERE id=?", (job["id"],)).fetchone()
                if policy:
                    job["distribution_policy"] = policy[0]
            if job["distribution_policy"] not in {"legacy", "complete", "partial"}:
                raise ValueError("La política de distribución no es válida.")
        for obsolete_id in existing_ids - supplied_ids:
            history = self.connection.execute(
                "SELECT 1 FROM plancha_item_assignments WHERE order_job_id=? LIMIT 1",
                (obsolete_id,),
            ).fetchone()
            if history:
                raise ValueError(f"No se puede quitar el trabajo #{obsolete_id}: conserva historial productivo.")
            self.connection.execute("DELETE FROM order_jobs WHERE id=?", (obsolete_id,))
        for job in clean_jobs:
            if job.get("id") is not None:
                previous = dict(self.connection.execute("SELECT * FROM order_jobs WHERE id=?", (job["id"],)).fetchone())
                commercial_keys = ("product_id", "variant_id", "subtotal", "cost_total", "price_rule_id")
                if any(previous.get(key) != job.get(key) for key in commercial_keys):
                    self.connection.execute(
                        "INSERT INTO order_events(order_id,event_type,message,data_json,created_at) VALUES(?,?,?,?,?)",
                        (order_id, "Trabajo comercial", f"Cambio comercial del trabajo #{job['id']}", json.dumps({
                            "order_job_id": job["id"], "origin": "order_editor",
                            "before": {key: previous.get(key) for key in commercial_keys},
                            "after": {key: job.get(key) for key in commercial_keys},
                        }, ensure_ascii=False), now),
                    )
                self.connection.execute("UPDATE order_jobs SET distribution_policy=? WHERE id=?", (job["distribution_policy"], job["id"]))
                self.connection.execute(
                    """UPDATE order_jobs SET title=?,material=?,size=?,quantity=?,unit_kind=?,subtotal=?,discount_percent=?,
                       extra_services=?,status=?,notes=?,sort_order=?,cost_mp=?,cost_mo=?,cost_cf=?,cost_total=?,
                       product_id=?,variant_id=?,price_list_id=?,price_rule_id=?,unit_price_snapshot=?,fixed_price_snapshot=?,
                       manual_override=?,manual_override_reason=?,base_price_snapshot=?,suggested_price_snapshot=?,
                       applied_price_snapshot=?,manual_price_snapshot=?,price_source=?,productive_cost=?,
                       commercial_cost_allocated=?,final_cost=?,productive_margin=?,final_margin=?,
                       productive_classification=?,production_mode=?,updated_at=? WHERE id=? AND order_id=?""",
                    (job["title"], job["material"], job["size"], job["quantity"], job["unit_kind"], job["subtotal"],
                     job["discount_percent"], job["extra_services"], job["status"], job["notes"],
                     job["sort_order"], job["cost_mp"], job["cost_mo"], job["cost_cf"], job["cost_total"],
                     job["product_id"], job["variant_id"], job["price_list_id"], job["price_rule_id"],
                     job["unit_price_snapshot"], job["fixed_price_snapshot"], job["manual_override"],
                     job["manual_override_reason"], job["base_price_snapshot"], job["suggested_price_snapshot"],
                     job["applied_price_snapshot"], job["manual_price_snapshot"], job["price_source"],
                     job["productive_cost"], job["commercial_cost_allocated"], job["final_cost"],
                     job["productive_margin"], job["final_margin"], job["productive_classification"],
                     job["production_mode"], now, int(job["id"]), order_id),
                )
                continue
            cursor = self.connection.execute(
                """INSERT INTO order_jobs(order_id, title, material, size, quantity, unit_kind, subtotal,
                   discount_percent, extra_services, status, notes, sort_order,
                   cost_mp, cost_mo, cost_cf, cost_total,
                   product_id, variant_id, price_list_id, price_rule_id, unit_price_snapshot,
                   fixed_price_snapshot, manual_override, manual_override_reason,
                   base_price_snapshot, suggested_price_snapshot, applied_price_snapshot, manual_price_snapshot, price_source,
                   productive_cost, commercial_cost_allocated, final_cost, productive_margin, final_margin,
                   productive_classification, production_mode, created_at, updated_at)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    order_id, job["title"], job["material"], job["size"], job["quantity"],
                    job["unit_kind"], job["subtotal"], job["discount_percent"], job["extra_services"],
                    job["status"], job["notes"], job["sort_order"],
                    job["cost_mp"], job["cost_mo"], job["cost_cf"], job["cost_total"],
                    job["product_id"], job["variant_id"], job["price_list_id"], job["price_rule_id"],
                    job["unit_price_snapshot"], job["fixed_price_snapshot"], job["manual_override"],
                    job["manual_override_reason"], job["base_price_snapshot"], job["suggested_price_snapshot"],
                    job["applied_price_snapshot"], job["manual_price_snapshot"], job["price_source"],
                    job["productive_cost"], job["commercial_cost_allocated"], job["final_cost"],
                    job["productive_margin"], job["final_margin"], job["productive_classification"], job["production_mode"], now, now,
                ),
            )
            job["id"] = int(cursor.lastrowid)
            self.connection.execute("UPDATE order_jobs SET distribution_policy=? WHERE id=?", (job["distribution_policy"], job["id"]))
            try:
                jobs[job["sort_order"]]["id"] = job["id"]
            except (IndexError, TypeError):
                pass
            estimate = job["production_estimate"]
            if estimate:
                self.connection.execute(
                    """INSERT INTO order_job_production_estimates(order_job_id, unique_designs, production_mode,
                       design_minutes, design_minutes_json, print_minutes, cut_minutes, productive_surcharge, additional_services,
                       authorized_discount, additional_materials, waste_cost, valid_productive_exception, calculated_at)
                       VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(order_job_id) DO UPDATE SET unique_designs=excluded.unique_designs,
                       production_mode=excluded.production_mode, design_minutes=excluded.design_minutes, design_minutes_json=excluded.design_minutes_json,
                       print_minutes=excluded.print_minutes, cut_minutes=excluded.cut_minutes,
                       productive_surcharge=excluded.productive_surcharge, additional_services=excluded.additional_services,
                       authorized_discount=excluded.authorized_discount, calculated_at=excluded.calculated_at""",
                    (job["id"],
                     int(estimate.get("unique_designs", 1) or 1), str(estimate.get("production_mode", "individual") or "individual"),
                     float(estimate.get("design_minutes", 0) or 0), json.dumps(estimate.get("design_minutes_list") or []), float(estimate.get("print_minutes", 0) or 0),
                     float(estimate.get("cut_minutes", 0) or 0), float(estimate.get("productive_surcharge", 0) or 0),
                     float(estimate.get("additional_services", 0) or 0), float(estimate.get("authorized_discount", 0) or 0),
                     float(estimate.get("additional_materials", 0) or 0), float(estimate.get("waste_cost", 0) or 0),
                     int(bool(estimate.get("valid_productive_exception", False))), now),
                )
        return clean_jobs

    @staticmethod
    def allocate_commercial_cost(total: float, jobs: list[dict]) -> list[float]:
        """Distribuye centavos exactamente: aplicado, sugerido y luego uniforme."""
        total_cents = int(round(max(0.0, float(total or 0)) * 100))
        if not jobs:
            return []
        def amounts(key):
            return [max(0.0, float(job.get(key) or 0)) for job in jobs]
        weights = amounts("applied_price_snapshot")
        if not any(weights):
            weights = amounts("suggested_price_snapshot")
        if not any(weights):
            weights = [1.0] * len(jobs)
        weight_total = sum(weights)
        allocations = [int(total_cents * weight / weight_total) for weight in weights]
        allocations[-1] += total_cents - sum(allocations)
        return [value / 100 for value in allocations]

    def _refresh_order_commercial_cost(self, order_id: int) -> None:
        """Guarda un único costo comercial de pedido y su desglose analítico."""
        order = self.connection.execute("SELECT client_id FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not order:
            return
        prior = self.connection.execute(
            "SELECT COUNT(*) FROM orders WHERE client_id = ? AND id <> ?", (order["client_id"], order_id)
        ).fetchone()[0]
        settings = self.productive_plancha_a4_settings()
        kind = "recurrent" if prior else "first_purchase"
        total = float(settings.get("commercial_cost_recurrent" if prior else "commercial_cost_first_purchase", 300 if prior else 500))
        jobs = self.order_jobs(order_id)
        allocations = self.allocate_commercial_cost(total, jobs)
        for job, allocated in zip(jobs, allocations):
            self.connection.execute("UPDATE order_jobs SET commercial_cost_allocated = ? WHERE id = ?", (allocated, job["id"]))
        productive_total = self.connection.execute("SELECT COALESCE(SUM(cost_total), 0) FROM order_jobs WHERE order_id = ?", (order_id,)).fetchone()[0]
        self.connection.execute(
            "UPDATE orders SET commercial_cost = ?, commercial_cost_kind = ?, final_cost = ?, final_margin = budget_total - ? WHERE id = ?",
            (total, kind, float(productive_total or 0) + total, float(productive_total or 0) + total, order_id),
        )

    def _sync_order_from_jobs(self, order_id: int, now: str) -> None:
        """Actualiza el resumen compatible del pedido desde sus trabajos."""
        rows = [dict(row) for row in self.connection.execute(
            "SELECT * FROM order_jobs WHERE order_id = ? ORDER BY sort_order, id", (order_id,)
        )]
        if not rows:
            return
        order = self.order(order_id) or {}
        subtotal     = round(sum(float(job.get("subtotal") or 0) for job in rows), 2)
        # Los descuentos individuales por trabajo ya no se usan; el descuento se aplica al pedido
        total        = subtotal
        total_quantity = sum(max(1, int(job.get("quantity") or 1)) for job in rows)
        # Costos desglosados — suma de todos los trabajos
        cost_mp    = round(sum(float(job.get("cost_mp")    or 0) for job in rows), 2)
        cost_mo    = round(sum(float(job.get("cost_mo")    or 0) for job in rows), 2)
        cost_cf    = round(sum(float(job.get("cost_cf")    or 0) for job in rows), 2)
        commission_pct = _seller_commission_percent(order.get("assigned_to"))
        commission = round(max(0.0, total - cost_mp - cost_mo - cost_cf) * commission_pct / 100, 2)
        cost_total = round(cost_mp + cost_mo + cost_cf + commission, 2)
        margin     = round(total - cost_total, 2)
        one_job    = len(rows) == 1
        material   = rows[0].get("material", "") if one_job else f"{len(rows)} trabajos"
        size       = rows[0].get("size", "")     if one_job else "Varios"
        services   = rows[0].get("extra_services", "") if one_job else ""
        self.connection.execute(
            """UPDATE orders SET material = ?, size = ?, quantity = ?, price = ?,
               discount_percent = 0, extra_services = ?, budget_total = ?,
               cost_mp = ?, cost_mo = ?, cost_cf = ?, seller_commission_percent = ?, seller_commission_amount = ?, cost_total = ?, margin = ?,
               updated_at = ?
               WHERE id = ?""",
            (material, size, total_quantity, subtotal, services, total,
             cost_mp, cost_mo, cost_cf, commission_pct, commission, cost_total, margin,
             now, order_id),
        )

    def _migrate_order_jobs(self) -> None:
        """Los pedidos creados antes del detalle se conservan como un único trabajo."""
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        rows = self.connection.execute(
            """SELECT orders.* FROM orders
               LEFT JOIN order_jobs ON order_jobs.order_id = orders.id
               WHERE order_jobs.id IS NULL
                 AND COALESCE(orders.order_jobs_deleted, 0) = 0"""
        ).fetchall()
        for row in rows:
            order = dict(row)
            self._write_order_jobs(
                int(order["id"]),
                [{
                    "title": "Trabajo principal", "material": order.get("material", ""),
                    "size": order.get("size", ""), "quantity": order.get("quantity", 1),
                    "subtotal": order.get("price", 0), "discount_percent": order.get("discount_percent", 0),
                    "extra_services": order.get("extra_services", ""), "status": order.get("status", "Nuevo"),
                    "notes": order.get("observations", ""),
                }],
                now,
            )

    def create_order(self, client: str, whatsapp: str = "", order_date: str = "", **values) -> int:
        """Crea un pedido sin asociar ni mover archivos."""
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        client = client.strip()
        whatsapp = whatsapp.strip()
        client_id = self._ensure_client(client, whatsapp, now)
        raw_jobs = values.pop("jobs", None)
        if raw_jobs is None:
            raw_jobs = [{
                "title": values.get("job_title") or "Trabajo principal",
                "material": values.get("material", ""), "size": values.get("size", ""),
                "quantity": values.get("quantity", 1), "subtotal": values.get("price", 0),
                "discount_percent": values.get("discount_percent", 0),
                "extra_services": values.get("extra_services", ""), "status": values.get("status", "Nuevo"),
            }]
        jobs = [self._clean_order_job(job, position) for position, job in enumerate(raw_jobs)]
        if not jobs:
            jobs = [self._clean_order_job({}, 0)]
        first = jobs[0]
        try:
            priority = _manual_priority_value(values.get("print_priority", 0))
        except (TypeError, ValueError):
            priority = 0
        if _is_delivered_order_status(values.get("status")):
            priority = 0
        
        # Si se proporciona order_date con fecha y hora completa, usarla; si no, usar created_at
        if order_date and len(order_date) > 10:
            # Es una fecha con hora (ISO format completo)
            final_order_date = order_date
        elif order_date:
            # Es solo una fecha, mantener por compatibilidad
            final_order_date = order_date
        else:
            # No se proporcionó, usar el timestamp completo de creación
            final_order_date = now
            
        with self.connection:
            cursor = self.connection.execute(
                """INSERT INTO orders(client, whatsapp, client_id, order_date, status, material, size,
                   quantity, price, discount_percent, extra_services, budget_total, assigned_to, seller_commission_percent,
                   observations, pending_reason, delivery_date, print_priority, order_concept,
                   order_description, created_at, updated_at, last_autosave_at)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    client, whatsapp, client_id, final_order_date, values.get("status", "Nuevo"),
                    first["material"], first["size"], first["quantity"], first["subtotal"],
                    first["discount_percent"], first["extra_services"], 0, values.get("assigned_to", ""),
                    _seller_commission_percent(values.get("assigned_to")),
                    values.get("observations", "").strip(), values.get("pending_reason", "").strip(),
                    values.get("delivery_date", "").strip(), priority,
                    str(values.get("order_concept", "") or "").strip(),
                    str(values.get("order_description", "") or "").strip(),
                    now, now, now,
                ),
            )
            order_id = int(cursor.lastrowid)
            self._write_order_jobs(order_id, jobs, now)
            self._sync_order_from_jobs(order_id, now)
            self._refresh_order_commercial_cost(order_id)
        self.add_order_event(order_id, "Pedido", f"Pedido creado con {len(jobs)} trabajo(s).")
        try:
            total = sum(float(j.get("subtotal", 0) or 0) for j in jobs)  # Los descuentos individuales ya no se usan
            self.event_repo.publish_event(
                event_type="order.created",
                priority="high",
                title=f"Nuevo pedido",
                message=f"Pedido #{order_id} · {client} · ${total:,.0f}",
                entity_type="order",
                entity_id=order_id,
                payload={"client_name": client, "total": round(total, 2)},
            )
        except Exception:
            pass
        return order_id

    def create_order_with_details(self, client: str, whatsapp: str = "", order_date: str = "",
                                  *, jobs: list[dict], designs: list[dict] | None = None, **values) -> int:
        """Crea cabecera, trabajos y demanda usando el mismo guardado que la edición.

        ``order_job_index`` vincula cada diseño con el trabajo del formulario antes
        de que SQLite le asigne un id. Ante un error se elimina el alta incompleta.
        """
        order_id = self.create_order(client, whatsapp=whatsapp, order_date=order_date, jobs=jobs, **values)
        try:
            persisted_jobs = self.order_jobs(order_id)
            draft_designs = [dict(item) for item in (designs or [])]
            for design in draft_designs:
                index = design.pop("order_job_index", None)
                if index is not None:
                    try:
                        design["order_job_id"] = persisted_jobs[int(index)]["id"]
                    except (IndexError, TypeError, ValueError):
                        raise ValueError("El diseño referencia un trabajo que ya no existe.")
            snapshot = dict(self.order(order_id) or {})
            snapshot.update(values)
            snapshot.update({"client": client, "whatsapp": whatsapp, "order_date": order_date})
            self.save_order_snapshot(order_id, snapshot, draft_designs, persisted_jobs)
            return order_id
        except Exception:
            self.delete_order(order_id)
            raise

    def _migrate_order_clients(self) -> None:
        """Vincula pedidos antiguos sin modificar sus datos visibles."""
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        rows = self.connection.execute(
            "SELECT id, client, whatsapp FROM orders WHERE client_id IS NULL"
        ).fetchall()
        for row in rows:
            client_id = self._ensure_client(row["client"], row["whatsapp"], now)
            self.connection.execute("UPDATE orders SET client_id = ? WHERE id = ?", (client_id, row["id"]))

    def _migrate_mobile_devices(self) -> None:
        """Agrega columnas de session token a mobile_devices si no existen."""
        # La tabla mobile_devices la crea EventRepository.create_tables() después
        # de esta migración. Si aún no existe, no hay nada que migrar.
        table_exists = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mobile_devices'"
        ).fetchone()
        if not table_exists:
            return
        # Verificar columnas existentes
        existing_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(mobile_devices)")}
        
        # Agregar columnas faltantes de forma idempotente
        # SQLite no permite agregar columnas UNIQUE con ALTER TABLE, así que agregamos sin UNIQUE
        for column, definition in (
            ("user_id", "INTEGER"),
            ("session_token_hash", "TEXT"),
            ("session_expires_at", "TEXT"),
            ("session_last_used_at", "TEXT"),
            ("app_version", "TEXT DEFAULT ''"),
        ):
            if column not in existing_columns:
                self.connection.execute(f"ALTER TABLE mobile_devices ADD COLUMN {column} {definition}")
        
        # Crear índice único para session_token_hash DESPUÉS de agregar la columna
        # Esto garantiza unicidad y evita el error "no such column"
        self.connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_mobile_devices_session ON mobile_devices(session_token_hash)")
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_mobile_devices_user "
            "ON mobile_devices(user_id, active)"
        )

    def _migrate_pairing_codes(self) -> None:
        """Migra pairing_codes de código en texto plano a hash SHA-256."""
        # La tabla pairing_codes la crea EventRepository.create_tables() después
        # de esta migración. Si aún no existe, no hay nada que migrar.
        table_exists = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pairing_codes'"
        ).fetchone()
        if not table_exists:
            return
        # Verificar si la columna code_hash existe
        existing_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(pairing_codes)")}
        
        if "code_hash" not in existing_columns:
            # La tabla tiene la estructura antigua con 'code' en texto plano
            # Crear tabla nueva con hash
            self.connection.execute(
                """CREATE TABLE IF NOT EXISTS pairing_codes_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code_hash TEXT NOT NULL UNIQUE,
                    installation_id TEXT NOT NULL DEFAULT 'studio-principal',
                    used INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )"""
            )
            
            # Migrar datos existentes calculando el hash
            import hashlib
            rows = self.connection.execute("SELECT * FROM pairing_codes").fetchall()
            for row in rows:
                code_hash = hashlib.sha256(row["code"].encode()).hexdigest()
                self.connection.execute(
                    """INSERT INTO pairing_codes_new 
                       (code_hash, installation_id, used, created_at, expires_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (code_hash, row["installation_id"], row["used"], row["created_at"], row["expires_at"])
                )
            
            # Reemplazar tabla antigua
            self.connection.execute("DROP TABLE pairing_codes")
            self.connection.execute("ALTER TABLE pairing_codes_new RENAME TO pairing_codes")

    def _migrate_mobile_order_idempotency(self) -> None:
        """Evita que un reintento del móvil duplique un pedido ya recibido."""
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(orders)")}
        if "mobile_request_id" not in columns:
            self.connection.execute("ALTER TABLE orders ADD COLUMN mobile_request_id TEXT")
        self.connection.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_mobile_request
               ON orders(creator_device_id, mobile_request_id)
               WHERE mobile_request_id IS NOT NULL"""
        )

    def _migrate_mobile_security(self) -> None:
        """Crea tablas para seguridad de acceso externo (whitelist de IPs)."""
        from datetime import datetime
        from app.security.mobile_access import (
            DEFAULTS_SEEDED_SETTING_KEY,
            DEFAULT_MOBILE_NETWORKS,
            WHITELIST_SETTING_KEY,
        )

        now = datetime.now().isoformat(timespec="seconds")

        # Tabla para whitelist de IPs
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
        whitelist_columns = {
            row[1]
            for row in self.connection.execute(
                "PRAGMA table_info(mobile_ip_whitelist)"
            )
        }
        if "last_matched_at" not in whitelist_columns:
            self.connection.execute(
                "ALTER TABLE mobile_ip_whitelist "
                "ADD COLUMN last_matched_at TEXT DEFAULT ''"
            )

        # Configuración para habilitar/deshabilitar whitelist
        self.connection.execute(
            """INSERT OR IGNORE INTO app_settings(
                   setting_key, setting_value, updated_at
               ) VALUES(?, 'false', ?)""",
            (WHITELIST_SETTING_KEY, now),
        )

        # Agregar IPs locales una sola vez. Quedan inactivas hasta que la
        # persona confirme qué redes corresponden a su instalación.
        defaults_seeded = self.connection.execute(
            "SELECT setting_value FROM app_settings WHERE setting_key = ?",
            (DEFAULTS_SEEDED_SETTING_KEY,),
        ).fetchone()
        if not defaults_seeded:
            for ip, desc in DEFAULT_MOBILE_NETWORKS:
                self.connection.execute(
                    """INSERT OR IGNORE INTO mobile_ip_whitelist(ip_address, description, active, created_at, updated_at)
                       VALUES (?, ?, 0, ?, ?)""",
                    (ip, desc, now, now),
                )
            self.connection.execute(
                """INSERT INTO app_settings(setting_key, setting_value, updated_at)
                   VALUES(?, 'true', ?)""",
                (DEFAULTS_SEEDED_SETTING_KEY, now),
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

    def _migrate_sync_indexes(self) -> None:
        """Agrega índices compuestos (updated_at, id) para sincronización incremental."""
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_updated_id ON orders(updated_at, id)"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_order_jobs_updated_id ON order_jobs(updated_at, id)"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_clients_updated_id ON clients(updated_at, id)"
        )

    def _ensure_client(self, name: str, whatsapp: str, now: str | None = None) -> int:
        from datetime import datetime

        name, whatsapp = (name or "").strip(), (whatsapp or "").strip()
        now = now or datetime.now().isoformat(timespec="seconds")
        row = self.connection.execute(
            "SELECT id FROM clients WHERE name = ? COLLATE NOCASE AND whatsapp = ?",
            (name, whatsapp),
        ).fetchone()
        if row:
            self.connection.execute("UPDATE clients SET updated_at = ? WHERE id = ?", (now, row[0]))
            return int(row[0])
        cursor = self.connection.execute(
            "INSERT INTO clients(name, whatsapp, created_at, updated_at) VALUES(?, ?, ?, ?)",
            (name, whatsapp, now, now),
        )
        return int(cursor.lastrowid)

    def update_client_type(self, client_id: int, client_type: str) -> None:
        """Actualiza la categoría del cliente (Particular / Empresa / Revendedor / VIP)."""
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        self.connection.execute(
            "UPDATE clients SET client_type = ?, updated_at = ? WHERE id = ?",
            (client_type, now, client_id),
        )
        self.connection.commit()

    def update_client(self, client_id: int, name: str, whatsapp: str, client_type: str) -> None:
        """Actualiza una ficha y refleja sus datos en los pedidos vinculados."""
        from datetime import datetime

        name, whatsapp = (name or "").strip(), (whatsapp or "").strip()
        client_type = (client_type or "Particular").strip() or "Particular"
        if not name:
            raise ValueError("El nombre del cliente es obligatorio.")
        duplicate = self.connection.execute(
            "SELECT id FROM clients WHERE name = ? COLLATE NOCASE AND whatsapp = ? AND id <> ?",
            (name, whatsapp, client_id),
        ).fetchone()
        if duplicate:
            raise ValueError("Ya existe otro cliente con el mismo nombre y WhatsApp.")
        now = datetime.now().isoformat(timespec="seconds")
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE clients SET name = ?, whatsapp = ?, client_type = ?, updated_at = ? WHERE id = ?",
                (name, whatsapp, client_type, now, client_id),
            )
            if not cursor.rowcount:
                raise ValueError("La ficha del cliente ya no existe.")
            self.connection.execute(
                "UPDATE orders SET client = ?, whatsapp = ?, updated_at = ? WHERE client_id = ?",
                (name, whatsapp, now, client_id),
            )

    def clients_with_order_summary(self, query: str = "") -> list[dict]:
        """Devuelve las fichas de clientes junto con un resumen de sus pedidos."""
        clauses: list[str] = []
        params: list[str] = []
        if query.strip():
            term = f"%{query.strip().lower()}%"
            clauses.append("(LOWER(c.name) LIKE ? OR LOWER(COALESCE(c.whatsapp, '')) LIKE ?)")
            params.extend((term, term))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.connection.execute(
            """SELECT c.*, COUNT(o.id) AS order_count,
                       COALESCE(SUM(COALESCE(o.budget_total, o.price, 0)), 0) AS total_billed,
                       MAX(COALESCE(o.order_date, o.created_at)) AS last_order_at
                 FROM clients AS c
                 LEFT JOIN orders AS o ON o.client_id = c.id
                 %s
                 GROUP BY c.id
                 ORDER BY c.name COLLATE NOCASE, c.id""" % where,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def client_detail(self, client_id: int) -> dict | None:
        row = self.connection.execute(
            """SELECT c.*, COUNT(o.id) AS order_count,
                       COALESCE(SUM(COALESCE(o.budget_total, o.price, 0)), 0) AS total_billed,
                       MAX(COALESCE(o.order_date, o.created_at)) AS last_order_at
                 FROM clients AS c
                 LEFT JOIN orders AS o ON o.client_id = c.id
                 WHERE c.id = ?
                 GROUP BY c.id""",
            (client_id,),
        ).fetchone()
        return dict(row) if row else None

    def client_orders(self, client_id: int) -> list[dict]:
        rows = self.connection.execute(
            """SELECT id, order_date, created_at, status, material, quantity,
                       COALESCE(budget_total, price, 0) AS total
                 FROM orders WHERE client_id = ?
                 ORDER BY COALESCE(order_date, created_at) DESC, id DESC""",
            (client_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def delete_client(self, client_id: int) -> int:
        """Elimina una ficha, conservando los pedidos históricos sin vínculo a ella."""
        with self.connection:
            self.connection.execute("UPDATE orders SET client_id = NULL WHERE client_id = ?", (client_id,))
            cursor = self.connection.execute("DELETE FROM clients WHERE id = ?", (client_id,))
        return int(cursor.rowcount)

    def orders(self, status: str | tuple[str, ...] | list[str] | None = None, query: str = "", pending_only: bool = False) -> list[dict]:
        """Devuelve la lista operativa sin tocar precios ni otros módulos."""
        sql = """
            SELECT orders.*, COALESCE(clients.name, orders.client) AS client_name,
                   COALESCE(clients.client_type, 'Particular') AS client_type,
                   COALESCE(metrics.design_count, 0) AS design_count,
                   COALESCE(metrics.assigned_quantity, 0) AS assigned_quantity,
                   COALESCE(metrics.confirmed_count, 0) AS confirmed_count,
                   COALESCE(plancha_counts.total, 0) AS plancha_count,
                   COALESCE(job_financials.budget_total,
                       orders.price * (1 - COALESCE(orders.discount_percent, 0) / 100.0)
                   ) AS current_budget_total,
                   COALESCE(payment_totals.paid_amount, 0) AS current_paid_amount
            FROM orders
            LEFT JOIN clients ON clients.id = orders.client_id
            LEFT JOIN (
                SELECT order_id, COUNT(*) AS design_count,
                       SUM(quantity) AS assigned_quantity,
                       SUM(CASE WHEN status = 'Confirmado' THEN 1 ELSE 0 END) AS confirmed_count
                FROM order_designs GROUP BY order_id
            ) AS metrics ON metrics.order_id = orders.id
            LEFT JOIN (
                SELECT order_id, COUNT(*) AS total FROM plancha_projects GROUP BY order_id
            ) AS plancha_counts ON plancha_counts.order_id = orders.id
            LEFT JOIN (
                SELECT order_id,
                       SUM(subtotal) AS budget_total
                FROM order_jobs GROUP BY order_id
            ) AS job_financials ON job_financials.order_id = orders.id
            LEFT JOIN (
                SELECT order_id, SUM(amount) AS paid_amount
                FROM order_payments
                WHERE COALESCE(cancelled_at, '') = ''
                GROUP BY order_id
            ) AS payment_totals ON payment_totals.order_id = orders.id
        """
        clauses: list[str] = ["COALESCE(orders.is_archived, 0) = 0"]
        params: list[str] = []
        if status:
            statuses = (status,) if isinstance(status, str) else tuple(status)
            if len(statuses) == 1:
                clauses.append("orders.status = ?")
            else:
                clauses.append("orders.status IN (" + ", ".join("?" for _ in statuses) + ")")
            params.extend(statuses)
        if pending_only:
            # Incluir pedidos activos que pueden recibir diseños.  También
            # excluimos ``Archivado`` por compatibilidad con registros creados
            # antes de que el archivado usara la bandera ``is_archived``.
            clauses.append("orders.status NOT IN ('Finalizado', 'Entregado', 'Terminado', 'Cancelado', 'Archivado')")
        if query.strip():
            term = f"%{query.strip().lower()}%"
            clauses.append(
                "(" 
                "LOWER(COALESCE(clients.name, orders.client)) LIKE ? OR "
                "LOWER(COALESCE(orders.whatsapp, '')) LIKE ? OR "
                "LOWER(COALESCE(orders.material, '')) LIKE ? OR "
                "LOWER(COALESCE(orders.status, '')) LIKE ? OR "
                "EXISTS (SELECT 1 FROM order_designs od "
                "JOIN image_tags it ON it.image_path = od.image_path "
                "JOIN tags t ON t.id = it.tag_id "
                "WHERE od.order_id = orders.id AND LOWER(t.name) LIKE ?)"
                ")"
            )
            params.extend([term] * 5)
        sql += " WHERE " + " AND ".join(clauses) + " ORDER BY orders.order_date DESC, orders.id DESC"
        return [dict(row) for row in self.connection.execute(sql, params)]

    def order(self, order_id: int) -> dict | None:
        return next((item for item in self.orders() if item["id"] == order_id), None)

    def pending_orders(self) -> list[dict]:
        return self.orders(pending_only=True)

    def set_order_parent(self, order_id: int, parent_order_id: int | None) -> bool:
        """Vincula un pedido operativo a otro pedido principal del cliente."""
        from datetime import datetime

        order_id = int(order_id)
        if parent_order_id is not None:
            parent_order_id = int(parent_order_id)
            if parent_order_id == order_id:
                raise ValueError("Un pedido no puede vincularse consigo mismo.")
            parent = self.connection.execute(
                "SELECT id FROM orders WHERE id = ?", (parent_order_id,)
            ).fetchone()
            if not parent:
                raise ValueError("El pedido principal indicado no existe.")
        cursor = self.connection.execute(
            "UPDATE orders SET parent_order_id = ?, updated_at = ? WHERE id = ?",
            (parent_order_id, datetime.now().isoformat(timespec="seconds"), order_id),
        )
        self.connection.commit()
        return bool(cursor.rowcount)

    def update_order_status(self, order_id: int, status: str) -> None:
        from app.domain.order_states import OrderStateService

        OrderStateService(self.connection).transition(
            order_id,
            status,
            source="desktop",
            reason="Cambio desde la ficha del pedido",
        )

    def update_order_priority(self, order_id: int, print_priority: int) -> dict:
        from datetime import datetime

        print_priority = min(4, max(0, int(print_priority or 0)))
        now = datetime.now().isoformat(timespec="seconds")
        self.connection.execute(
            "UPDATE orders SET print_priority = ?, updated_at = ? WHERE id = ?",
            (print_priority, now, order_id),
        )
        self.connection.commit()
        self.add_order_event(order_id, "Prioridad", f"Prioridad actualizada a: {print_priority}.")
        row = self.connection.execute(
            "SELECT id, print_priority, updated_at FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        return dict(row) if row else {"id": order_id, "print_priority": print_priority, "updated_at": now}

    def update_job_fields(self, order_id: int, job_id: int, quantity: int | None = None, size: str | None = None) -> dict:
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        job = self.connection.execute(
            "SELECT id, order_id, quantity, size FROM order_jobs WHERE id = ? AND order_id = ?",
            (job_id, order_id),
        ).fetchone()
        if not job:
            raise ValueError("Trabajo no encontrado en este pedido.")
        new_quantity = max(1, int(quantity if quantity is not None else job["quantity"]))
        new_size = str(size if size is not None else job["size"]).strip()
        self.connection.execute(
            "UPDATE order_jobs SET quantity = ?, size = ?, updated_at = ? WHERE id = ?",
            (new_quantity, new_size, now, job_id),
        )
        self._sync_order_from_jobs(order_id, now)
        self.connection.commit()
        self.add_order_event(order_id, "Trabajo", f"Trabajo #{job_id}: cantidad={new_quantity}, tamaño={new_size}.")
        row = self.connection.execute(
            "SELECT id, quantity, size, updated_at FROM order_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return dict(row) if row else {"id": job_id, "quantity": new_quantity, "size": new_size, "updated_at": now}

    def mark_order_delivered(self, order_id: int) -> dict:
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        order = self.connection.execute(
            "SELECT id, status FROM orders WHERE id = ? AND is_archived = 0", (order_id,)
        ).fetchone()
        if not order:
            raise ValueError("Pedido no encontrado o archivado.")
        current = order["status"]
        if current == "Entregado":
            raise ValueError("El pedido ya está marcado como Entregado.")
        with self.connection:
            from app.services.delivery_readiness import assert_deliverable
            self.connection.execute("UPDATE orders SET id=id WHERE id=?", (order_id,))
            assert_deliverable(self.connection, order_id)
            self.connection.execute(
                "UPDATE order_jobs SET status = 'Entregado', updated_at = ? WHERE order_id = ?",
                (now, order_id),
            )
            self.connection.execute(
                """UPDATE orders
                   SET status = 'Entregado', updated_at = ?, print_priority = 0
                   WHERE id = ?""",
                (now, order_id),
            )
        self.add_order_event(order_id, "Entrega", f"Pedido marcado como Entregado (estado anterior: {current}).")
        try:
            self.event_repo.publish_event(
                event_type="order.delivered",
                priority="high",
                title="Pedido entregado",
                message=f"Pedido #{order_id} marcado como Entregado",
                entity_type="order",
                entity_id=order_id,
                payload={"old_status": current},
            )
        except Exception:
            pass
        row = self.connection.execute(
            "SELECT id, status, updated_at FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        return dict(row) if row else {"id": order_id, "status": "Entregado", "updated_at": now}

    def archive_order(self, order_id: int) -> None:
        """Marca el pedido como Archivado sin eliminar ningún dato."""
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE orders SET is_archived = 1, status = 'Archivado', updated_at = ? "
                "WHERE id = ? AND COALESCE(is_archived, 0) = 0",
                (now, order_id),
            )
        if cursor.rowcount:
            self.add_order_event(order_id, "Archivo", "Pedido archivado.")

    def delete_order(self, order_id: int) -> None:
        """Elimina permanentemente el pedido y todos sus registros relacionados."""
        from datetime import datetime
        with self.connection:
            for table in (
                "order_events", "order_payments", "plancha_item_assignments",
                "order_design_job_links", "order_designs",
                "order_jobs", "order_drafts", "order_snapshots", "order_previews",
                "plancha_print_queue",
            ):
                try:
                    self.connection.execute(
                        f"DELETE FROM {table} WHERE order_id = ?", (order_id,)
                    )
                except Exception:
                    pass
            self.connection.execute("DELETE FROM orders WHERE id = ?", (order_id,))

    def save_order_draft(self, order_id: int, values: dict, designs: list[dict], jobs: list[dict] | None = None) -> None:
        """Guarda una recuperación inmediata antes del autoguardado definitivo."""
        from datetime import datetime
        import json

        payload = json.dumps({"values": values, "designs": designs, "jobs": jobs}, ensure_ascii=False)
        now = datetime.now().isoformat(timespec="seconds")
        self.connection.execute(
            """INSERT INTO order_drafts(order_id, draft_json, saved_at) VALUES(?, ?, ?)
               ON CONFLICT(order_id) DO UPDATE SET draft_json = excluded.draft_json, saved_at = excluded.saved_at""",
            (order_id, payload, now),
        )
        self.connection.commit()

    def order_draft(self, order_id: int) -> dict | None:
        import json

        row = self.connection.execute(
            "SELECT draft_json, saved_at FROM order_drafts WHERE order_id = ?", (order_id,)
        ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row["draft_json"])
            payload["saved_at"] = row["saved_at"]
            return payload
        except (TypeError, ValueError):
            return None

    def discard_order_draft(self, order_id: int) -> None:
        self.connection.execute("DELETE FROM order_drafts WHERE order_id = ?", (order_id,))
        self.connection.commit()

    def save_order_snapshot(self, order_id: int, values: dict, designs: list[dict], jobs: list[dict] | None = None,
                            discard_draft: bool = True) -> None:
        """Actualiza ficha y diseños en una sola operación reversible desde la UI."""
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        client = str(values.get("client", "")).strip()
        if not client:
            raise ValueError("Indicá el cliente del pedido.")
        whatsapp = str(values.get("whatsapp", "")).strip()
        quantity = max(0, int(values.get("quantity", 0) or 0))
        try:
            print_priority = _manual_priority_value(values.get("print_priority", 0))
        except (TypeError, ValueError):
            print_priority = 0
        status = str(values.get("status", "Nuevo") or "Nuevo")
        if _is_delivered_order_status(status):
            print_priority = 0
        try:
            price = max(0.0, float(str(values.get("price", 0) or 0).replace(",", ".")))
        except (TypeError, ValueError):
            price = 0.0
        try:
            discount_percent = min(100.0, max(0.0, float(str(values.get("discount_percent", 0) or 0).replace(",", "."))))
        except (TypeError, ValueError):
            discount_percent = 0.0
        commission_percent = _seller_commission_percent(values.get("assigned_to"))
        budget_total = round(price * (1 - discount_percent / 100), 2)
        existing_design_metadata = {
            row["image_path"]: dict(row)
            for row in self.connection.execute(
                """SELECT image_path, source, creator_status, creator_queued_at, order_job_id
                   FROM order_designs WHERE order_id = ?""",
                (order_id,),
            )
        }
        existing_demand_lines = {
            str(row["design_line_id"]): dict(row)
            for row in self.connection.execute(
                """SELECT design_line_id,image_path,size_cm,quantity,unit_kind,packing_mode,workspace_format
                   FROM order_design_demand_lines WHERE order_id=?""",
                (order_id,),
            )
        }
        incoming_line_ids = {str(design.get("design_line_id") or "") for design in designs}
        for removed_line_id in set(existing_demand_lines) - incoming_line_ids:
            active = self.connection.execute(
                """SELECT 1 FROM plancha_item_assignments
                   WHERE order_design_line_id=? AND state<>'released' LIMIT 1""",
                (removed_line_id,),
            ).fetchone()
            if active:
                raise ValueError(
                    "No se puede quitar una línea que ya tiene unidades reservadas o producidas. "
                    "Conservála para mantener su trazabilidad."
                )
        sole_job_id = None
        with self.connection:
            client_id = self._ensure_client(client, whatsapp, now)
            if status.strip().casefold() in {"entregado", "terminado", "completado"}:
                previous_status = self.connection.execute("SELECT status FROM orders WHERE id=?", (order_id,)).fetchone()
                if previous_status and previous_status[0] != status:
                    from app.services.delivery_readiness import assert_deliverable
                    assert_deliverable(self.connection, order_id)
            self.connection.execute(
                """UPDATE orders SET client = ?, whatsapp = ?, client_id = ?,
                   status = ?, material = ?, size = ?, quantity = ?, price = ?, discount_percent = ?,
                   extra_services = ?, budget_total = ?, assigned_to = ?, seller_commission_percent = ?, observations = ?,
                   pending_reason = ?, delivery_date = ?, print_priority = ?, order_date = ?,
                   order_concept = ?, order_description = ?, complaint_notes = ?, last_autosave_at = ?, updated_at = ? WHERE id = ?""",
                (
                    client, whatsapp, client_id,
                    status, str(values.get("material", "")).strip(), str(values.get("size", "")).strip(),
                    quantity, price, discount_percent, str(values.get("extra_services", "")).strip(),
                    budget_total, str(values.get("assigned_to", "")).strip(), commission_percent, str(values.get("observations", "")).strip(),
                    str(values.get("pending_reason", "")).strip(), str(values.get("delivery_date", "")).strip(),
                    print_priority, str(values.get("order_date", "") or "").strip(),
                    str(values.get("order_concept", "") or "").strip(),
                    str(values.get("order_description", "") or "").strip(),
                    str(values.get("complaint_notes", "") or "").strip(),
                    now, now, order_id,
                ),
            )
            if jobs is not None:
                self._write_order_jobs(order_id, jobs, now)
                self.connection.execute("UPDATE orders SET order_jobs_deleted = 0 WHERE id = ?", (order_id,))
            persisted_job_ids = [
                int(job["id"]) for job in (jobs or [])
                if job.get("id") is not None and str(job.get("id")).isdigit()
            ]
            sole_job_id = persisted_job_ids[0] if len(persisted_job_ids) == 1 else None
            jobs_by_id = {int(job["id"]): job for job in self.order_jobs(order_id)}
            if not persisted_job_ids:
                sole_job_id = next(iter(jobs_by_id)) if len(jobs_by_id) == 1 else None
            line_ids = [str(d["design_line_id"]) for d in designs if d.get("design_line_id")]
            if len(line_ids) != len(set(line_ids)):
                raise ValueError("La misma línea de diseño no puede distribuirse dos veces.")
            distributed: dict[int, int] = {}
            for design in designs:
                if int(design.get("quantity", 1) or 0) <= 0:
                    raise ValueError("La cantidad de cada diseño debe ser mayor que cero.")
                linked = design.get("order_job_id") or sole_job_id
                if linked is None and design.get("order_job_index") is not None and jobs is not None:
                    try:
                        linked = jobs[int(design["order_job_index"])].get("id")
                    except (IndexError, TypeError, ValueError):
                        linked = None
                if linked is not None:
                    linked = int(linked)
                    if linked not in jobs_by_id:
                        raise ValueError("El diseño referencia un trabajo ajeno al pedido.")
                    job_unit = jobs_by_id[linked].get("unit_kind")
                    if design.get("unit_kind") and job_unit and design["unit_kind"] != job_unit:
                        raise ValueError("La unidad del diseño debe coincidir con la del trabajo.")
                    distributed[linked] = distributed.get(linked, 0) + max(1, int(design.get("quantity", 1) or 1))
            for job_id, assigned in distributed.items():
                requested = int(jobs_by_id.get(job_id, {}).get("quantity") or 0)
                if requested and assigned > requested:
                    raise ValueError(
                        f"Los diseños del trabajo '{jobs_by_id[job_id].get('title') or job_id}' distribuyen "
                        f"{assigned} unidades, pero el trabajo solicita {requested}."
                    )
            for job_id, job in jobs_by_id.items():
                if job.get("distribution_policy") == "complete" and distributed.get(job_id, 0) != int(job["quantity"]):
                    raise ValueError(f"La distribución completa de '{job['title']}' debe coincidir con la cantidad solicitada.")
            self.connection.execute("DELETE FROM order_designs WHERE order_id = ?", (order_id,))
            self.connection.execute("DELETE FROM order_design_job_links WHERE order_id = ?", (order_id,))
            self.connection.execute("DELETE FROM order_design_demand_lines WHERE order_id = ?", (order_id,))
            inserted_paths: set[str] = set()
            for design in designs:
                path = str(design.get("image_path", "")).strip()
                if not path:
                    continue
                previous = existing_design_metadata.get(path, {})
                quantity_value = max(1, int(design.get("quantity", 1) or 1))
                size_value = float(design.get("size_cm", 5.0) or 5.0)
                rotation_value = int(design.get("rotation", 0) or 0)
                linked_job_id = design.get("order_job_id", previous.get("order_job_id")) or sole_job_id
                if linked_job_id is None and design.get("order_job_index") is not None and jobs is not None:
                    try:
                        linked_job_id = jobs[int(design["order_job_index"])].get("id")
                    except (IndexError, TypeError, ValueError):
                        linked_job_id = None
                line_id = str(design.get("design_line_id") or "")
                if line_id:
                    old_line = existing_demand_lines.get(line_id)
                    if old_line and (
                        str(old_line["image_path"]) != path
                        or abs(float(old_line["size_cm"] or 0) - size_value) > 0.000001
                    ):
                        produced = self.connection.execute(
                            """SELECT 1 FROM plancha_item_assignments
                               WHERE order_design_line_id=? AND state IN ('printed','finished') LIMIT 1""",
                            (line_id,),
                        ).fetchone()
                        if produced:
                            raise ValueError(
                                "La línea de diseño ya tiene producción. Para cambiar realmente el diseño o la "
                                "medida, agregá una línea nueva; el historial existente se conservará."
                            )
                    active_quantity = float(self.connection.execute(
                        """SELECT COALESCE(SUM(quantity),0) FROM plancha_item_assignments
                           WHERE order_design_line_id=? AND state<>'released'""",
                        (line_id,),
                    ).fetchone()[0] or 0)
                    if quantity_value < active_quantity:
                        raise ValueError(
                            f"No se puede reducir la línea a {quantity_value}: conserva "
                            f"{active_quantity:g} unidad(es) reservadas o producidas."
                        )
                if path not in inserted_paths:
                    self.connection.execute(
                        """INSERT INTO order_designs(
                               order_id, image_path, quantity, size_cm, rotation, status,
                               source, creator_status, creator_queued_at, order_job_id
                           ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            order_id, path, quantity_value, size_value, rotation_value,
                            str(design.get("status", "Pendiente") or "Pendiente"),
                            str(design.get("source") or previous.get("source") or ""),
                            str(design.get("creator_status") or previous.get("creator_status") or "Pendiente"),
                            str(design.get("creator_queued_at") or previous.get("creator_queued_at") or ""),
                            linked_job_id,
                        ),
                    )
                    inserted_paths.add(path)
                if linked_job_id is not None:
                    line_id = str(design.get("design_line_id") or uuid.uuid4().hex)
                    design["design_line_id"] = line_id
                    self.connection.execute(
                        """INSERT INTO order_design_job_links(
                               order_id,order_job_id,image_path,quantity,size_cm,rotation,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?)
                           ON CONFLICT(order_job_id,image_path,size_cm,rotation) DO UPDATE SET
                             quantity=excluded.quantity,updated_at=excluded.updated_at""",
                        (order_id, int(linked_job_id), path, quantity_value, size_value, rotation_value, now, now),
                    )
                    old_line = existing_demand_lines.get(line_id, {})
                    job_unit_kind = str(jobs_by_id.get(int(linked_job_id), {}).get("unit_kind") or "")
                    unit_kind = str(design.get("unit_kind") or old_line.get("unit_kind") or job_unit_kind or "")
                    packing_mode = str(design.get("packing_mode") or old_line.get("packing_mode") or "")
                    workspace_format = str(design.get("workspace_format") or old_line.get("workspace_format") or "a4")
                    self.connection.execute(
                        """INSERT INTO order_design_demand_lines(
                               design_line_id,order_id,order_job_id,image_path,quantity,size_cm,rotation,
                               unit_kind,packing_mode,workspace_format,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (line_id, order_id, int(linked_job_id), path, quantity_value,
                         size_value, rotation_value, unit_kind, packing_mode, workspace_format, now, now),
                    )
                self.connection.execute("UPDATE images SET design_order_id = ? WHERE path = ?", (order_id, path))
            if jobs is not None:
                self._sync_order_from_jobs(order_id, now)
                self._refresh_order_commercial_cost(order_id)
            if discard_draft:
                self.connection.execute("DELETE FROM order_drafts WHERE order_id = ?", (order_id,))
        # Mantiene el resumen de cobros sincronizado si se modificó el total o
        # el descuento después de haber registrado una seña.
        financials = self.order_financials(order_id)
        self.connection.execute(
            "UPDATE orders SET budget_total = ?, paid_amount = ?, payment_status = ? WHERE id = ?",
            (financials["budget_total"], financials["paid_amount"], financials["payment_status"], order_id),
        )
        self.connection.commit()

    def apply_order_draft(self, order_id: int) -> bool:
        draft = self.order_draft(order_id)
        if not draft:
            return False
        self.save_order_snapshot(order_id, draft.get("values", {}), draft.get("designs", []), draft.get("jobs"))
        return True

    def _migrate_order_designs_nominal_size(self) -> None:
        """Normaliza el legado 5.9 y actualiza el default SQLite a 5.0.

        La reconstrucción sólo ocurre en bases con el default histórico; por
        eso la migración es idempotente y no toca una base ya normalizada.
        """
        columns = list(self.connection.execute("PRAGMA table_info(order_designs)"))
        size_column = next((row for row in columns if row[1] == "size_cm"), None)
        if size_column is None:
            return
        default = str(size_column[4] or "").strip("'\"")
        self.connection.execute(
            "UPDATE order_designs SET size_cm = 5.0 WHERE ABS(COALESCE(size_cm, 5.0) - 5.9) < 0.000001"
        )
        if default not in {"5.9", "5.90"}:
            self.connection.commit()
            return

        # Todas estas columnas ya existen antes de llamar a la migración.
        names = "order_id, image_path, quantity, size_cm, rotation, status, source, creator_status, creator_queued_at, order_job_id, estimated_design_minutes"
        with self.connection:
            self.connection.execute("ALTER TABLE order_designs RENAME TO order_designs_legacy_size")
            self.connection.execute(
                """CREATE TABLE order_designs (
                    order_id INTEGER NOT NULL, image_path TEXT NOT NULL, quantity INTEGER DEFAULT 1,
                    size_cm REAL DEFAULT 5.0, rotation INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'Pendiente', source TEXT DEFAULT '',
                    creator_status TEXT DEFAULT 'Pendiente', creator_queued_at TEXT DEFAULT '',
                    order_job_id INTEGER, estimated_design_minutes REAL DEFAULT 0,
                    PRIMARY KEY(order_id, image_path),
                    FOREIGN KEY(order_id) REFERENCES orders(id)
                )"""
            )
            self.connection.execute(
                f"INSERT INTO order_designs({names}) SELECT {names} FROM order_designs_legacy_size"
            )
            self.connection.execute("DROP TABLE order_designs_legacy_size")
            self.connection.execute("CREATE INDEX IF NOT EXISTS idx_order_designs_job ON order_designs(order_job_id)")

    def link_design_to_order(
        self, order_id: int, image_path: str, quantity: int = 1,
        size_cm: float = 5.0, rotation: int = 0, status: str = "Pendiente",
        source: str = "library", order_job_id: int | None = None,
        design_line_id: str | None = None,
    ) -> None:
        from datetime import datetime
        self.connection.execute(
            """INSERT INTO order_designs(
                   order_id, image_path, quantity, size_cm, rotation, status, source, order_job_id
               ) VALUES(?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(order_id, image_path) DO UPDATE SET
               quantity=excluded.quantity, size_cm=excluded.size_cm, rotation=excluded.rotation,
               status=excluded.status,
               order_job_id=COALESCE(excluded.order_job_id, order_designs.order_job_id),
               source=CASE
                   WHEN COALESCE(order_designs.source, '') = '' THEN excluded.source
                   ELSE order_designs.source
               END""",
            (order_id, image_path, quantity, size_cm, rotation, status, source, order_job_id),
        )
        if order_job_id is not None:
            now = datetime.now().isoformat(timespec="seconds")
            stable_line_id = str(design_line_id or uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"doccione-design-line|{int(order_id)}|{int(order_job_id)}|{str(image_path).replace(chr(92), '/').casefold()}|{float(size_cm):.6f}|{int(rotation) % 360}",
            ).hex)
            self.connection.execute(
                """INSERT INTO order_design_job_links(
                       order_id,order_job_id,image_path,quantity,size_cm,rotation,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(order_job_id,image_path,size_cm,rotation) DO UPDATE SET
                     quantity=excluded.quantity,updated_at=excluded.updated_at""",
                (order_id, int(order_job_id), image_path, max(1, int(quantity)), float(size_cm),
                 int(rotation), now, now),
            )
            self.connection.execute(
                """INSERT INTO order_design_demand_lines(
                       design_line_id,order_id,order_job_id,image_path,quantity,size_cm,rotation,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(design_line_id) DO UPDATE SET
                      image_path=excluded.image_path,quantity=excluded.quantity,size_cm=excluded.size_cm,
                      rotation=excluded.rotation,updated_at=excluded.updated_at""",
                (stable_line_id, order_id, int(order_job_id), image_path, max(1, int(quantity)),
                 float(size_cm), int(rotation), now, now),
            )
        self.connection.execute("UPDATE images SET design_order_id = ? WHERE path = ?", (order_id, image_path))
        self.connection.commit()

    def order_designs(self, order_id: int) -> list[dict]:
        demand_exists = self.connection.execute(
            "SELECT 1 FROM order_design_demand_lines WHERE order_id=? LIMIT 1", (order_id,)
        ).fetchone()
        if demand_exists:
            rows = self.connection.execute(
                """SELECT lines.order_id,lines.image_path,lines.quantity,lines.size_cm,lines.rotation,
                          COALESCE(base.status,'Pendiente') AS status,COALESCE(base.source,'') AS source,
                          COALESCE(base.creator_status,'Pendiente') AS creator_status,
                          COALESCE(base.creator_queued_at,'') AS creator_queued_at,
                          COALESCE(base.estimated_design_minutes,0) AS estimated_design_minutes,
                          lines.order_job_id,lines.id AS job_design_link_id,lines.design_line_id,
                          images.name,images.tags,images.category,images.caption
                   FROM order_design_demand_lines lines
                   LEFT JOIN order_designs base
                     ON base.order_id=lines.order_id AND base.image_path=lines.image_path
                   JOIN (
                        SELECT images.path,images.name,images.category,images.caption,
                               GROUP_CONCAT(tags.name,' · ') AS tags
                        FROM images LEFT JOIN image_tags ON image_tags.image_path=images.path
                        LEFT JOIN tags ON tags.id=image_tags.tag_id GROUP BY images.path
                   ) images ON images.path=lines.image_path
                   WHERE lines.order_id=?
                   ORDER BY images.name COLLATE NOCASE,lines.order_job_id,lines.id""",
                (order_id,),
            )
            return [dict(row) for row in rows]
        link_table = "order_design_demand_lines" if demand_exists else "order_design_job_links"
        line_identity = "links.design_line_id" if demand_exists else "''"
        rows = self.connection.execute(
            f"""SELECT order_designs.order_id,order_designs.image_path,
                      COALESCE(links.quantity,order_designs.quantity) AS quantity,
                      COALESCE(links.size_cm,order_designs.size_cm) AS size_cm,
                      COALESCE(links.rotation,order_designs.rotation) AS rotation,
                      order_designs.status,order_designs.source,order_designs.creator_status,
                      order_designs.creator_queued_at,order_designs.estimated_design_minutes,
                      COALESCE(links.order_job_id,order_designs.order_job_id) AS order_job_id,
                       links.id AS job_design_link_id, {line_identity} AS design_line_id,
                      images.name, images.tags, images.category, images.caption
               FROM order_designs
               LEFT JOIN {link_table} links
                 ON links.order_id=order_designs.order_id AND links.image_path=order_designs.image_path
               JOIN (
                    SELECT images.path, images.name, images.category, images.caption,
                           GROUP_CONCAT(tags.name, ' · ') AS tags
                    FROM images LEFT JOIN image_tags ON image_tags.image_path = images.path
                    LEFT JOIN tags ON tags.id = image_tags.tag_id
                    GROUP BY images.path
               ) AS images ON images.path = order_designs.image_path
               WHERE order_designs.order_id = ?
               ORDER BY images.name COLLATE NOCASE, COALESCE(links.order_job_id,0), COALESCE(links.id,0)""",
            (order_id,),
        )
        return [dict(row) for row in rows]

    def mobile_order_images(self, order_id: int) -> list[dict]:
        """Imágenes originales enviadas por el celular para un pedido."""
        rows = self.connection.execute(
            """SELECT order_designs.*, images.name, images.caption
               FROM order_designs
               LEFT JOIN images ON images.path = order_designs.image_path
               WHERE order_designs.order_id = ?
                 AND (
                     LOWER(COALESCE(order_designs.source, '')) = 'mobile'
                     OR LOWER(order_designs.image_path) LIKE '%mobile_uploads%'
                     OR LOWER(COALESCE(images.caption, '')) = 'imagen recibida desde doccione mobile'
                 )
               ORDER BY COALESCE(images.name, order_designs.image_path) COLLATE NOCASE""",
            (order_id,),
        )
        return [dict(row) for row in rows]

    def mark_mobile_images_sent_to_creator(self, order_id: int, image_paths: list[str]) -> int:
        """Marca sólo adjuntos móviles reales como enviados al Creador."""
        from datetime import datetime

        requested = {str(path).strip() for path in image_paths if str(path).strip()}
        if not requested:
            return 0
        allowed = {
            str(image["image_path"])
            for image in self.mobile_order_images(order_id)
        }
        selected = sorted(requested & allowed)
        if not selected:
            return 0
        now = datetime.now().isoformat(timespec="seconds")
        placeholders = ", ".join("?" for _ in selected)
        with self.connection:
            cursor = self.connection.execute(
                f"""UPDATE order_designs
                    SET creator_status = 'Enviado', creator_queued_at = ?
                    WHERE order_id = ? AND image_path IN ({placeholders})""",
                (now, order_id, *selected),
            )
            self.connection.execute(
                """INSERT INTO order_events(order_id, event_type, message, data_json, created_at)
                   VALUES(?, 'stickers.creator.queued', ?, ?, ?)""",
                (
                    order_id,
                    f"{len(selected)} imagen(es) del celular enviada(s) al Creador de Stickers.",
                    json.dumps({"image_paths": selected}, ensure_ascii=False),
                    now,
                ),
            )
        return int(cursor.rowcount)

    def order_jobs(self, order_id: int) -> list[dict]:
        """Detalle de trabajos de un pedido, ordenado como lo ve el usuario."""
        rows = self.connection.execute(
            "SELECT * FROM order_jobs WHERE order_id = ? ORDER BY sort_order, id", (order_id,)
        )
        jobs = [dict(row) for row in rows]
        for job in jobs:
            estimate = self.connection.execute(
                "SELECT * FROM order_job_production_estimates WHERE order_job_id = ?", (job["id"],)
            ).fetchone()
            if estimate:
                job["production_estimate"] = dict(estimate)
        return jobs

    def replace_order_jobs(self, order_id: int, jobs: list[dict]) -> list[dict]:
        """Guarda el listado completo de trabajos y actualiza el resumen del pedido."""
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        with self.connection:
            saved = self._write_order_jobs(order_id, jobs, now)
            self.connection.execute("UPDATE orders SET order_jobs_deleted = 0 WHERE id = ?", (order_id,))
            self._sync_order_from_jobs(order_id, now)
            self._refresh_order_commercial_cost(order_id)
        self.add_order_event(order_id, "Trabajos", f"Se actualizaron {len(saved)} trabajo(s) del pedido.")
        return self.order_jobs(order_id)

    def delete_order_job(self, order_id: int, job_id: int) -> dict:
        """Elimina cualquier trabajo y sincroniza los totales del pedido."""
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        with self.connection:
            row = self.connection.execute(
                "SELECT * FROM order_jobs WHERE id = ? AND order_id = ?", (job_id, order_id)
            ).fetchone()
            if not row:
                raise ValueError("El trabajo ya no existe en este pedido.")
            job = dict(row)
            if self.connection.execute(
                "SELECT 1 FROM plancha_item_assignments WHERE order_job_id=? LIMIT 1",
                (job_id,),
            ).fetchone():
                raise ValueError("El trabajo conserva reservas o historial productivo y no puede eliminarse.")
            self.connection.execute("DELETE FROM order_design_job_links WHERE order_job_id=?", (job_id,))
            self.connection.execute("DELETE FROM order_jobs WHERE id = ? AND order_id = ?", (job_id, order_id))
            remaining = self.connection.execute(
                "SELECT id FROM order_jobs WHERE order_id = ? ORDER BY sort_order, id", (order_id,)
            ).fetchall()
            for position, remaining_job in enumerate(remaining):
                self.connection.execute(
                    "UPDATE order_jobs SET sort_order = ?, updated_at = ? WHERE id = ?",
                    (position, now, remaining_job["id"]),
                )
            if remaining:
                self._sync_order_from_jobs(order_id, now)
                self._refresh_order_commercial_cost(order_id)
            else:
                self.connection.execute(
                    """UPDATE orders
                       SET material = '', size = '', quantity = 0, price = 0,
                           discount_percent = 0, extra_services = '', budget_total = 0,
                           cost_mp = 0, cost_mo = 0, cost_cf = 0, cost_total = 0,
                           margin = 0, commercial_cost = 0, final_cost = 0,
                           final_margin = 0, order_jobs_deleted = 1, updated_at = ?
                       WHERE id = ?""",
                    (now, order_id),
                )
        self.recalculate_order_costs(order_id)
        self.add_order_event(order_id, "Trabajos", f"Se eliminó el trabajo: {job.get('title') or 'Sin nombre'}.")
        return job

    def order_jobs_summary(self, order_id: int) -> dict:
        """Resumen de ítems para listas y pantallas de pedido."""
        rows = self.order_jobs(order_id)
        subtotal = round(sum(float(job.get("subtotal") or 0) for job in rows), 2)
        total = subtotal  # Los descuentos individuales ya no se usan
        quantity = sum(max(1, int(job.get("quantity") or 1)) for job in rows)
        return {"count": len(rows), "subtotal": subtotal, "total": total, "quantity": quantity}

    # Pedido: presupuesto, cobros y actividad --------------------------
    def add_order_event(self, order_id: int, event_type: str, message: str, data: dict | None = None) -> None:
        """Registra actividad real del pedido; el autoguardado no crea ruido."""
        from datetime import datetime
        import json

        self.connection.execute(
            "INSERT INTO order_events(order_id, event_type, message, data_json, created_at) VALUES(?, ?, ?, ?, ?)",
            (order_id, event_type, message.strip(), json.dumps(data or {}, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")),
        )
        self.connection.commit()

    def order_events(self, order_id: int, limit: int = 100) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM order_events WHERE order_id = ? ORDER BY id DESC LIMIT ?", (order_id, max(1, limit))
        )
        return [dict(row) for row in rows]

    def order_financials(self, order_id: int) -> dict:
        row = self.connection.execute(
            "SELECT price, discount_percent, budget_total, paid_amount, payment_status, cost_mp, cost_mo, cost_cf, seller_commission_percent, seller_commission_amount, cost_total, margin FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        if not row:
            return {"subtotal": 0.0, "discount_percent": 0.0, "budget_total": 0.0, "paid_amount": 0.0, "pending_amount": 0.0, "payment_status": "Pendiente", "cost_mp": 0.0, "cost_mo": 0.0, "cost_cf": 0.0, "seller_commission_percent": 0.0, "seller_commission_amount": 0.0, "cost_total": 0.0, "margin": 0.0}
        paid = self.connection.execute(
            """SELECT COALESCE(SUM(amount), 0) FROM order_payments
               WHERE order_id = ? AND COALESCE(cancelled_at, '') = ''""", (order_id,)
        ).fetchone()[0]
        jobs = self.order_jobs(order_id)
        if jobs:
            subtotal = round(sum(float(job.get("subtotal") or 0) for job in jobs), 2)
            total = subtotal  # Los descuentos individuales ya no se usan; se aplica descuento global del pedido
            discount = float(row["discount_percent"] or 0)  # Descuento global del pedido
            if discount > 0:
                total = round(subtotal * (1 - discount / 100), 2)
        else:
            subtotal = float(row["price"] or 0)
            discount = float(row["discount_percent"] or 0)
            total = round(subtotal * (1 - discount / 100), 2)
        pending = max(0.0, total - float(paid or 0))
        status = "Pagado" if total > 0 and pending <= 0.009 else ("Seña recibida" if paid else "Pendiente")
        return {
            "subtotal": subtotal, 
            "discount_percent": discount, 
            "budget_total": total, 
            "paid_amount": float(paid or 0), 
            "pending_amount": pending, 
            "payment_status": status,
            "cost_mp": float(row["cost_mp"] or 0),
            "cost_mo": float(row["cost_mo"] or 0),
            "cost_cf": float(row["cost_cf"] or 0),
            "seller_commission_percent": float(row["seller_commission_percent"] or 0),
            "seller_commission_amount": float(row["seller_commission_amount"] or 0),
            "cost_total": float(row["cost_total"] or 0),
            "margin": float(row["margin"] or 0),
        }

    @staticmethod
    def _normalize_cost_mode(mode: str | None) -> str:
        """Normaliza los modos de costo a los valores internos usados por la app."""
        value = (mode or "percent").strip().lower()
        if value in {"fijo", "fixed", "fix", "f"}:
            return "fixed"
        if value in {"porcentaje", "percent", "pct", "%"}:
            return "percent"
        if value in {"por unidad", "per unit", "per_unit", "unitario", "unit", "u"}:
            return "per_unit"
        if value in {"por hora", "per hour", "per_hour", "hour", "hora", "h"}:
            return "per_hour"
        if value in {"por superficie", "per square meter", "per_square_meter", "surface", "superficie", "m2", "m²"}:
            return "per_square_meter"
        return "percent"

    def recalculate_order_costs(self, order_id: int):
        """Recalcula automáticamente los costos y el margen del pedido usando reglas de costos.
        
        Cada costo (M.P, M.O, C.F) puede calcularse de dos formas:
        - percent: porcentaje del precio de venta
        - fixed: costo fijo + costo por unidad × cantidad
        """
        order = self.order(order_id)
        if not order:
            return
        
        jobs = self.order_jobs(order_id)
        material = str(order.get("material", "")).strip()
        
        if jobs:
            # Calcular budget_total sumando trabajos y aplicando descuento global del pedido
            subtotal = round(sum(float(job.get("subtotal") or 0) for job in jobs), 2)
            discount = float(order.get("discount_percent") or 0)
            budget_total = round(subtotal * (1 - discount / 100), 2) if discount > 0 else subtotal
            quantity = sum(int(j.get("quantity", 1) or 1) for j in jobs)
        else:
            # Usar precio del pedido
            price = float(order.get("price") or 0)
            discount = float(order.get("discount_percent") or 0)
            budget_total = round(price * (1 - discount / 100), 2)
            quantity = int(order.get("quantity") or 1)
        
        rules = self.all_cost_rules()
        total_mp = 0.0
        total_mo = 0.0
        total_cf = 0.0

        for rule in rules:
            rule_material = (rule.get("material") or "").strip()
            if rule_material and material and rule_material.lower() != material.lower():
                continue

            condition = (rule.get("condition") or "").strip()
            if condition:
                try:
                    ctx = {"budget": budget_total, "quantity": quantity}
                    if not eval(condition, {"__builtins__": {}}, ctx):
                        continue
                except Exception:
                    continue

            domain_rule = self._build_cost_rule_from_model(rule)
            if not domain_rule:
                continue
            metrics = CostCalculator.calculate(
                domain_rule,
                sale_price=budget_total,
                quantity=quantity,
                hours=float(order.get("hours") or 0),
                surface=float(order.get("surface") or 0),
            )
            component_map = {component.code.lower(): component.amount for component in metrics.components}
            total_mp += float(component_map.get("mp", 0.0))
            total_mo += float(component_map.get("mo", 0.0))
            total_cf += float(component_map.get("cf", 0.0))

        commission_pct = _seller_commission_percent(order.get("assigned_to"))
        commission = round(max(0.0, budget_total - total_mp - total_mo - total_cf) * commission_pct / 100, 2)
        cost_total = round(total_mp + total_mo + total_cf + commission, 2)
        margin = round(budget_total - cost_total, 2)

        self.connection.execute(
            """UPDATE orders 
               SET cost_mp = ?, cost_mo = ?, cost_cf = ?, seller_commission_percent = ?, seller_commission_amount = ?, cost_total = ?, margin = ?, budget_total = ?
               WHERE id = ?""",
            (round(total_mp, 2), round(total_mo, 2), round(total_cf, 2), commission_pct, commission, cost_total, margin, budget_total, order_id)
        )
        self.connection.commit()

    def sales_statistics(self, month: str | None = None) -> dict:
        """Resumen comercial para un mes determinado usando presupuestos y cobros reales."""
        from datetime import datetime
        month = (month or datetime.now().strftime("%Y-%m")).strip()
        if not month:
            month = datetime.now().strftime("%Y-%m")

        def _query(m: str) -> dict:
            row = self.connection.execute(
                """
                SELECT
                    COUNT(*) AS total_orders,
                    COALESCE(SUM(CASE WHEN COALESCE(paid_amount, 0) >= budget_total - 0.009 THEN 1 ELSE 0 END), 0) AS paid_orders,
                    COALESCE(SUM(CASE WHEN COALESCE(paid_amount, 0) > 0 AND COALESCE(paid_amount, 0) < budget_total - 0.009 THEN 1 ELSE 0 END), 0) AS partial_orders,
                    COALESCE(SUM(CASE WHEN COALESCE(paid_amount, 0) <= 0.009 THEN 1 ELSE 0 END), 0) AS pending_orders,
                    COALESCE(SUM(budget_total), 0) AS budget_total,
                    COALESCE(SUM(paid_amount),  0) AS paid_amount,
                    COALESCE(SUM(cost_mp),    0) AS cost_mp,
                    COALESCE(SUM(cost_mo),    0) AS cost_mo,
                    COALESCE(SUM(cost_cf),    0) AS cost_cf,
                    COALESCE(SUM(cost_total), 0) AS cost_total
                FROM orders
                WHERE COALESCE(is_archived, 0) = 0
                  AND strftime('%Y-%m', CASE WHEN TRIM(COALESCE(order_date, '')) <> '' THEN order_date ELSE created_at END) = ?
                """,
                (m,),
            ).fetchone()
            return {
                "total_orders":   int(row["total_orders"]   or 0),
                "paid_orders":    int(row["paid_orders"]    or 0),
                "partial_orders": int(row["partial_orders"] or 0),
                "pending_orders": int(row["pending_orders"] or 0),
                "budget_total":   round(float(row["budget_total"] or 0), 2),
                "paid_amount":    round(float(row["paid_amount"]  or 0), 2),
                "cost_mp":        round(float(row["cost_mp"]      or 0), 2),
                "cost_mo":        round(float(row["cost_mo"]      or 0), 2),
                "cost_cf":        round(float(row["cost_cf"]      or 0), 2),
                "cost_total":     round(float(row["cost_total"]   or 0), 2),
            }

        # Actual
        stats = _query(month)

        # Mes anterior
        try:
            cur = datetime.strptime(month, "%Y-%m")
            prev_month_dt = datetime(cur.year + ((cur.month - 2) // 12), ((cur.month - 2) % 12) + 1, 1)
            prev_month = prev_month_dt.strftime("%Y-%m")
        except Exception:
            prev_month = None

        prev = _query(prev_month) if prev_month else {
            "budget_total": 0.0, "paid_amount": 0.0,
            "total_orders": 0, "paid_orders": 0, "partial_orders": 0, "pending_orders": 0,
            "cost_mp": 0.0, "cost_mo": 0.0, "cost_cf": 0.0, "cost_total": 0.0,
        }

        budget_total    = stats["budget_total"]
        paid_amount     = stats["paid_amount"]
        pending_amount  = round(max(0.0, budget_total - paid_amount), 2)
        collection_rate = round((paid_amount / budget_total * 100) if budget_total else 0.0, 1)

        # Costos y margen del mes
        cost_mp    = stats["cost_mp"]
        cost_mo    = stats["cost_mo"]
        cost_cf    = stats["cost_cf"]
        cost_total = stats["cost_total"]
        margin     = round(budget_total - cost_total, 2)
        margin_pct = round((margin / budget_total * 100) if budget_total else 0.0, 1)

        # Deltas vs mes anterior
        budget_delta = round(budget_total - float(prev.get("budget_total", 0) or 0), 2)
        paid_delta   = round(paid_amount   - float(prev.get("paid_amount",   0) or 0), 2)
        margin_delta = round(margin        - (float(prev.get("budget_total", 0) or 0) - float(prev.get("cost_total", 0) or 0)), 2)
        try:
            budget_delta_pct = round((budget_delta / float(prev.get("budget_total", 0)) * 100), 1) if float(prev.get("budget_total", 0)) else 0.0
        except Exception:
            budget_delta_pct = 0.0
        try:
            paid_delta_pct = round((paid_delta / float(prev.get("paid_amount", 0)) * 100), 1) if float(prev.get("paid_amount", 0)) else 0.0
        except Exception:
            paid_delta_pct = 0.0

        return {
            "month":          month,
            "total_orders":   stats["total_orders"],
            "paid_orders":    stats["paid_orders"],
            "partial_orders": stats["partial_orders"],
            "pending_orders": stats["pending_orders"],
            "budget_total":   budget_total,
            "paid_amount":    paid_amount,
            "pending_amount": pending_amount,
            "collection_rate": collection_rate,
            # Costos desglosados
            "cost_mp":        cost_mp,
            "cost_mo":        cost_mo,
            "cost_cf":        cost_cf,
            "cost_total":     cost_total,
            "margin":         margin,
            "margin_pct":     margin_pct,
            "margin_delta":   margin_delta,
            # Comparativa mes anterior
            "prev_month":          prev_month,
            "prev_budget_total":   float(prev.get("budget_total", 0) or 0),
            "prev_paid_amount":    float(prev.get("paid_amount",   0) or 0),
            "budget_delta":        budget_delta,
            "budget_delta_pct":    budget_delta_pct,
            "paid_delta":          paid_delta,
            "paid_delta_pct":      paid_delta_pct,
        }

    def register_order_payment(self, order_id: int, amount: float, method: str = "", note: str = "",
                               idempotency_key: str = "") -> dict:
        from datetime import datetime

        amount = round(float(amount), 2)
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError("El cobro debe ser mayor que cero.")
        key = str(idempotency_key or "").strip()
        now = datetime.now().isoformat(timespec="seconds")
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if not self.connection.execute("SELECT 1 FROM orders WHERE id=?", (order_id,)).fetchone():
                raise ValueError("El pedido no existe.")
            if key:
                existing = self.connection.execute(
                    "SELECT * FROM order_payments WHERE order_id=? AND idempotency_key=?", (order_id, key),
                ).fetchone()
                if existing:
                    if (float(existing['amount']), existing['method'], existing['note']) != (amount, method.strip(), note.strip()):
                        raise ValueError("La clave de pago ya fue utilizada con datos incompatibles.")
                    return self.order_financials(order_id)
            self.connection.execute(
                """INSERT INTO order_payments(order_id, amount, method, note, paid_at, created_at, idempotency_key)
                   VALUES(?, ?, ?, ?, ?, ?, ?)""",
                (order_id, amount, method.strip(), note.strip(), now, now, key),
            )
            financials = self.order_financials(order_id)
            self.connection.execute(
                "UPDATE orders SET budget_total = ?, paid_amount = ?, payment_status = ?, updated_at = ? WHERE id = ?",
                (financials["budget_total"], financials["paid_amount"], financials["payment_status"], now, order_id),
            )
        self.add_order_event(order_id, "Cobro", f"Cobro registrado: ${amount:,.2f}" + (f" · {method.strip()}" if method.strip() else ""), {"amount": amount, "method": method, "note": note})
        try:
            self.event_repo.publish_event(
                event_type="payment.received",
                priority="high",
                title="Pago registrado",
                message=f"Pedido #{order_id} · ${amount:,.0f}" + (f" · {method.strip()}" if method.strip() else ""),
                entity_type="order",
                entity_id=order_id,
                payload={"amount": amount, "method": method},
            )
        except Exception:
            pass
        return self.order_financials(order_id)

    def order_payments(self, order_id: int) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM order_payments WHERE order_id = ? ORDER BY id DESC", (order_id,)
        )
        return [dict(row) for row in rows]

    def cancel_order_payment(self, order_id: int, payment_id: int, reason: str = "") -> dict:
        """Anula un cobro sin borrar su registro contable ni su trazabilidad."""
        from datetime import datetime

        payment = self.connection.execute(
            "SELECT * FROM order_payments WHERE id = ? AND order_id = ?", (payment_id, order_id)
        ).fetchone()
        if not payment:
            raise ValueError("El cobro ya no existe o no pertenece a este pedido.")
        if str(payment["cancelled_at"] or ""):
            raise ValueError("El cobro ya fue cancelado.")
        amount = float(payment["amount"] or 0)
        method = str(payment["method"] or "").strip()
        now = datetime.now().isoformat(timespec="seconds")
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE order_payments SET cancelled_at=?, cancellation_reason=?
                   WHERE id=? AND order_id=? AND COALESCE(cancelled_at,'')=''""",
                (now, str(reason or "").strip(), payment_id, order_id),
            )
            if not cursor.rowcount:
                raise ValueError("El cobro ya fue cancelado.")
            financials = self.order_financials(order_id)
            self.connection.execute(
                "UPDATE orders SET budget_total = ?, paid_amount = ?, payment_status = ?, updated_at = ? WHERE id = ?",
                (financials["budget_total"], financials["paid_amount"], financials["payment_status"], now, order_id),
            )
        self.add_order_event(
            order_id, "Cobro cancelado", f"Cobro cancelado: ${amount:,.2f}" + (f" · {method}" if method else ""),
            {"payment_id": payment_id, "amount": amount, "method": method, "reason": str(reason or "").strip()},
        )
        return self.order_financials(order_id)

    def save_order_preview(self, order_id: int, preview_path: str, plancha_id: int | None = None) -> dict:
        """Registra una vista previa inalterable para consultar dentro del pedido."""
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        cursor = self.connection.execute(
            "INSERT INTO order_previews(order_id, plancha_id, preview_path, created_at) VALUES(?, ?, ?, ?)",
            (order_id, plancha_id, preview_path, now),
        )
        self.connection.commit()
        self.add_order_event(order_id, "Vista previa", "Se guardó una vista previa del pedido.", {
            "preview": preview_path, "plancha_id": plancha_id,
        })
        return {"id": int(cursor.lastrowid), "order_id": order_id, "plancha_id": plancha_id, "preview_path": preview_path, "created_at": now}

    def order_previews(self, order_id: int) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM order_previews WHERE order_id = ? ORDER BY created_at DESC, id DESC", (order_id,)
        )
        return [dict(row) for row in rows]
    
    def delete_order_preview(self, preview_id: int):
        """Elimina un registro de vista previa de la base de datos."""
        self.connection.execute("DELETE FROM order_previews WHERE id = ?", (preview_id,))
        self.connection.commit()

    def order_summaries(self) -> list[dict]:
        """Resumen persistente de cada pedido, sus productos y sus cobros."""
        rows = self.connection.execute(
            """SELECT orders.id, COALESCE(clients.name, orders.client) AS client,
                      orders.whatsapp, orders.created_at, orders.order_date, orders.status,
                      orders.budget_total,
                      COALESCE((SELECT SUM(amount) FROM order_payments
                                WHERE order_id = orders.id
                                  AND COALESCE(cancelled_at, '') = ''), 0) AS paid_amount,
                      COALESCE((SELECT MAX(paid_at) FROM order_payments
                                WHERE order_id = orders.id
                                  AND COALESCE(cancelled_at, '') = ''), '') AS last_payment_at,
                      COALESCE((SELECT GROUP_CONCAT(
                          CASE WHEN TRIM(COALESCE(title, '')) <> '' THEN title ELSE 'Producto' END
                          || CASE WHEN TRIM(COALESCE(material, '')) <> '' THEN ' · ' || material ELSE '' END,
                          ' | ')
                          FROM order_jobs WHERE order_id = orders.id),
                          orders.material, 'Sin productos') AS products
               FROM orders
               LEFT JOIN clients ON clients.id = orders.client_id
               ORDER BY orders.created_at DESC, orders.id DESC"""
        )
        return [dict(row) for row in rows]

    def orders_for_month(self, month: str) -> list[dict]:
        """Retorna pedidos cuyo `order_date` o `created_at` cae en el mes `YYYY-MM`.

        Esto facilita mostrar listados y detalles comerciales por mes.
        """
        rows = self.connection.execute(
            """
            SELECT orders.* FROM orders
            WHERE COALESCE(is_archived, 0) = 0
                AND strftime('%Y-%m', CASE WHEN TRIM(COALESCE(order_date, '')) <> '' THEN order_date ELSE created_at END) = ?
            ORDER BY orders.order_date DESC, orders.id DESC
            """,
            (month,),
        ).fetchall()
        return [dict(row) for row in rows]

    def price_rules(self) -> list[dict]:
        rows = self.connection.execute(
            """SELECT pr.*
                 FROM price_rules AS pr
            LEFT JOIN products AS p ON p.id = pr.product_id
            LEFT JOIN price_lists AS pl ON pl.id = pr.price_list_id
                WHERE pr.active = 1
             ORDER BY COALESCE(p.name, pr.material) COLLATE NOCASE,
                      COALESCE(pl.name, '') COLLATE NOCASE,
                      pr.material COLLATE NOCASE,
                      CAST(REPLACE(LOWER(TRIM(pr.size)), 'cm', '') AS REAL),
                      pr.size COLLATE NOCASE,
                      pr.min_quantity, pr.id"""
        )
        return [dict(row) for row in rows]

    def active_catalog_products(self) -> list[dict]:
        """Productos disponibles al definir una regla comercial."""
        rows = self.connection.execute(
            "SELECT id, code, name FROM products WHERE active = 1 ORDER BY name COLLATE NOCASE"
        )
        return [dict(row) for row in rows]

    def active_price_lists(self) -> list[dict]:
        """Listas de precios que pueden usarse en nuevos pedidos."""
        rows = self.connection.execute(
            "SELECT id, code, name FROM price_lists WHERE active = 1 ORDER BY CASE code WHEN 'general' THEN 0 WHEN 'pedidos' THEN 1 ELSE 2 END, name COLLATE NOCASE"
        )
        return [dict(row) for row in rows]

    def catalog_product_prices(self, product_id: int) -> list[dict]:
        """Precios activos de una ficha, ordenados para lectura comercial."""
        rows = self.connection.execute(
            """SELECT pr.id, pr.material, pr.size, pr.min_quantity, pr.max_quantity,
                      pr.price, pr.price_mode, pr.pack_quantity, pl.name AS price_list_name
                 FROM price_rules AS pr
            LEFT JOIN price_lists AS pl ON pl.id = pr.price_list_id
                WHERE pr.product_id = ? AND pr.active = 1
             ORDER BY COALESCE(pl.name, '') COLLATE NOCASE,
                      CAST(REPLACE(LOWER(pr.size), 'cm', '') AS REAL),
                      pr.size COLLATE NOCASE, pr.min_quantity, pr.id""",
            (int(product_id),),
        ).fetchall()
        return [dict(row) for row in rows]

    def price_rule_presentations(self) -> list[dict]:
        """Devuelve filas ya calculadas para la UI de reglas de precio."""
        presentations: list[dict] = []
        for rule in self.price_rules():
            quantity = max(1, int(rule.get("min_quantity") or 1))
            sale_price = float(rule.get("price") or 0)
            resolved_rule, warning = self.resolve_price_rule_cost_model(rule)
            legacy_rule = not bool(rule.get("variable_cost_model_id"))
            if resolved_rule is None:
                analysis = None
                detail = warning or "Modelo no disponible"
                status = "Modelo no disponible"
                cost_total = 0.0
                margin = round(sale_price - cost_total, 2)
                margin_pct = 0.0
                model_name = "—"
            else:
                analysis = CostCalculator.calculate(
                    resolved_rule,
                    sale_price=sale_price,
                    quantity=quantity,
                    hours=0.0,
                    surface=0.0,
                    suggested_price=sale_price,
                )
                cost_total = float(analysis.cost_total or 0)
                margin = float(analysis.gross_profit or 0)
                margin_pct = float(analysis.margin_percentage or 0)
                model_name = str(resolved_rule.name or "Modelo")
                detail = self._format_cost_detail(analysis)
                if legacy_rule:
                    status = "Regla antigua"
                elif analysis.profitability_status == "profitable":
                    status = "Rentable"
                elif analysis.profitability_status == "margin_low":
                    status = "Margen bajo"
                elif analysis.profitability_status == "loss":
                    status = "Pérdida"
                elif analysis.profitability_status == "no_costs":
                    status = "Sin costos"
                else:
                    status = "Sin datos"

            if warning and resolved_rule is None:
                status = "Modelo no disponible"
            elif legacy_rule and resolved_rule is not None:
                status = "Regla antigua"

            product = self.connection.execute("SELECT name FROM products WHERE id = ?", (rule.get("product_id"),)).fetchone() if rule.get("product_id") else None
            price_list = self.connection.execute("SELECT name, code FROM price_lists WHERE id = ?", (rule.get("price_list_id"),)).fetchone() if rule.get("price_list_id") else None
            presentations.append({
                **rule,
                "id": int(rule.get("id") or 0),
                "model_name": model_name,
                "cost_total": round(cost_total, 2),
                "margin": round(margin, 2),
                "margin_pct": round(margin_pct, 1),
                "status": status,
                "detail": detail,
                "warning": warning if warning else ("Regla antigua" if legacy_rule else None),
                "product_name": product[0] if product else "",
                "price_list_name": price_list[0] if price_list else "Precios generales",
                "price_list_code": price_list[1] if price_list else "general",
            })
        return presentations

    @staticmethod
    def _format_cost_detail(analysis) -> str:
        if not analysis or not analysis.components:
            return "Sin componentes configurados"
        parts: list[str] = []
        for component in analysis.components:
            if component.value_type == "percentage":
                value_text = f"{component.value:g}%"
            elif component.value_type == "fixed":
                value_text = f"${component.value:g}"
            elif component.value_type == "per_unit":
                value_text = f"${component.value:g}/u"
            elif component.value_type == "per_hour":
                value_text = f"${component.value:g}/h"
            elif component.value_type == "per_square_meter":
                value_text = f"${component.value:g}/m²"
            else:
                value_text = str(component.value)
            parts.append(f"{component.name}: {value_text} → ${component.amount:,.2f}")
        return " | ".join(parts)

    def sales_time_series(self, month: str) -> list[dict]:
        """Devuelve una serie diaria para `month` (YYYY-MM).

        Cada entrada es un dict: {"date": "YYYY-MM-DD", "budget": float, "paid": float}
        """
        from datetime import datetime
        import calendar

        month = (month or datetime.now().strftime("%Y-%m")).strip()
        try:
            year, mon = (int(part) for part in month.split("-"))
        except Exception:
            return []

        # Sumar presupuestos por fecha de pedido
        orders_rows = self.connection.execute(
            """
            SELECT strftime('%Y-%m-%d', CASE WHEN TRIM(COALESCE(order_date, '')) <> '' THEN order_date ELSE created_at END) AS d,
                   COALESCE(SUM(budget_total), 0) AS budget
            FROM orders
            WHERE COALESCE(is_archived, 0) = 0
              AND strftime('%Y-%m', CASE WHEN TRIM(COALESCE(order_date, '')) <> '' THEN order_date ELSE created_at END) = ?
            GROUP BY d
            """,
            (month,),
        ).fetchall()
        budgets = {row["d"]: float(row["budget"] or 0) for row in orders_rows}

        # Sumar cobros por fecha de pago
        payments_rows = self.connection.execute(
            """
            SELECT strftime('%Y-%m-%d', paid_at) AS d,
                   COALESCE(SUM(amount), 0) AS paid
            FROM order_payments
            WHERE paid_at IS NOT NULL
              AND COALESCE(cancelled_at, '') = ''
              AND strftime('%Y-%m', paid_at) = ?
            GROUP BY d
            """,
            (month,),
        ).fetchall()
        paids = {row["d"]: float(row["paid"] or 0) for row in payments_rows}

        _, ndays = calendar.monthrange(year, mon)
        result: list[dict] = []
        for day in range(1, ndays + 1):
            d = datetime(year, mon, day).strftime("%Y-%m-%d")
            result.append({"date": d, "budget": budgets.get(d, 0.0), "paid": paids.get(d, 0.0)})
        return result

    def price_materials(self) -> list[str]:
        rows = self.connection.execute(
            "SELECT DISTINCT material FROM price_rules WHERE active = 1 AND material <> '' ORDER BY material COLLATE NOCASE"
        )
        return [str(row[0]) for row in rows]

    def cost_models(self) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM cost_rules ORDER BY name COLLATE NOCASE, id"
        )
        return [dict(row) for row in rows]

    def cost_model_names(self) -> list[str]:
        return [f"{row['id']} - {row['name']}" for row in self.cost_models()]

    def cost_model(self, rule_id: int) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM cost_rules WHERE id = ?", (int(rule_id),)
        ).fetchone()
        return dict(row) if row else None

    def _build_cost_rule_from_model(self, model: dict | None) -> CostRule | None:
        if not model:
            return None
        if not model.get("id"):
            return None
        rule = CostRule(
            id=int(model.get("id") or 0),
            name=str(model.get("name") or ""),
            product_type=str(model.get("material") or ""),
            minimum_margin=0.0,
            active=True,
        )
        for label, code, mode_key, value_key in (
            ("Materia Prima", "mp", "cost_mp_mode", "cost_mp_percent"),
            ("Mano de Obra", "mo", "cost_mo_mode", "cost_mo_percent"),
            ("Carga Fabril", "cf", "cost_cf_mode", "cost_cf_percent"),
        ):
            mode = self._normalize_cost_mode(model.get(mode_key))
            if mode == "percent":
                value_type = "percentage"
            elif mode == "fixed":
                value_type = "fixed"
            else:
                value_type = mode
            value = float(model.get(value_key) or 0)
            rule.add_component(CostComponent(name=label, code=code, value_type=value_type, value=value))

        components_payload = model.get("components_json") or model.get("components") or []
        if isinstance(components_payload, str):
            try:
                components_payload = json.loads(components_payload)
            except json.JSONDecodeError:
                components_payload = []
        if isinstance(components_payload, list):
            for component in components_payload:
                if not isinstance(component, dict):
                    continue
                rule.add_component(CostComponent(
                    name=str(component.get("name") or component.get("code") or "Componente"),
                    code=str(component.get("code") or component.get("name") or "component"),
                    value_type=str(component.get("value_type") or "percentage"),
                    value=float(component.get("value") or 0),
                    enabled=bool(component.get("enabled", True)),
                    order=int(component.get("order") or 0),
                ))
        return rule

    def _build_cost_rule_from_variable_cost_model(self, model: dict | None) -> CostRule | None:
        """Convierte un modelo de costo variable en una CostRule compatible con CostCalculator."""
        if not model:
            return None
        
        model_id = model.get("id")
        if not model_id:
            return None
        
        # Cargar componentes del modelo
        components_data = self.variable_cost_model_components(int(model_id))
        if not components_data:
            return None
        
        # Construir la regla de costo
        rule = CostRule(
            id=int(model_id),
            name=str(model.get("name") or "Modelo de costo variable"),
            product_type=str(model.get("product_name") or ""),
            minimum_margin=0.0,
            active=bool(model.get("active", True)),
        )
        
        # Convertir cada componente de VariableCostComponent a CostComponent
        for comp_data in components_data:
            if not comp_data.get("active"):
                continue
            
            # Mapear calc_mode a value_type de CostComponent
            calc_mode = comp_data.get("calc_mode", "per_unit")
            if calc_mode == "percentage":
                value_type = "percentage"
                value = float(comp_data.get("unit_value") or 0)
            elif calc_mode in ("fixed", "per_unit", "per_sheet", "per_job"):
                value_type = "fixed"
                # Para componentes directos, usar el amount calculado
                amount = comp_data.get("amount") or 0
                quantity = comp_data.get("quantity") or 1
                unit_value = comp_data.get("unit_value") or 0
                waste_pct = comp_data.get("waste_pct") or 0
                
                # Calcular el valor final: quantity * unit_value * (1 + waste_pct/100)
                if calc_mode in ("per_unit", "per_sheet", "per_job"):
                    value = float(quantity) * float(unit_value) * (1 + float(waste_pct) / 100)
                else:
                    value = float(amount)
            else:
                value_type = "fixed"
                value = float(comp_data.get("amount") or 0)
            
            component = CostComponent(
                name=str(comp_data.get("name") or "Componente"),
                code=str(comp_data.get("name") or "component").lower().replace(" ", "_"),
                value_type=value_type,
                value=value,
                enabled=True,
                order=int(comp_data.get("sort_order") or 0),
            )
            rule.add_component(component)
        
        return rule

    def _build_cost_rule_from_legacy_price_rule(self, price_rule: dict | None) -> CostRule | None:
        if not price_rule:
            return None
        rule = CostRule(
            id=int(price_rule.get("id") or 0),
            name=str(price_rule.get("material") or "Regla legacy"),
            product_type=str(price_rule.get("material") or ""),
            minimum_margin=0.0,
            active=bool(int(price_rule.get("active") or 1)),
        )
        legacy_components = [
            ("Materia Prima", "mp", "cost_mp_mode", "cost_mp_percent", "cost_mp_fixed", "cost_mp_unit"),
            ("Mano de Obra", "mo", "cost_mo_mode", "cost_mo_percent", "cost_mo_fixed", "cost_mo_unit"),
            ("Carga Fabril", "cf", "cost_cf_mode", "cost_cf_percent", "cost_cf_fixed", "cost_cf_unit"),
        ]
        for label, code, mode_key, percent_key, fixed_key, unit_key in legacy_components:
            mode = self._normalize_cost_mode(price_rule.get(mode_key))
            if mode == "percent":
                value_type = "percentage"
                value = float(price_rule.get(percent_key) or 0)
            elif mode == "fixed":
                value_type = "fixed"
                value = float(price_rule.get(fixed_key) or 0)
            else:
                value_type = mode
                value = float(price_rule.get(unit_key) or 0)
            rule.add_component(CostComponent(name=label, code=code, value_type=value_type, value=value))
        return rule

    def resolve_price_rule_cost_model(self, price_rule: dict | None) -> tuple[CostRule | None, str | None]:
        if not price_rule:
            return None, None

        model_id = price_rule.get("variable_cost_model_id")
        if model_id not in {None, "", 0}:
            try:
                model = self.variable_cost_model(int(model_id))
            except (TypeError, ValueError):
                return None, "La regla de precio referencia un modelo de costos variables inválido o inexistente."
            if not model:
                return None, "La regla de precio referencia un modelo de costos variables inexistente."
            if not bool(model.get("active", True)):
                return None, "La regla de precio referencia un modelo de costos variables desactivado."
            return self._build_cost_rule_from_variable_cost_model(model), None

        legacy_rule = self._build_cost_rule_from_legacy_price_rule(price_rule)
        if legacy_rule is None:
            return None, None
        if not any(component.value > 0 for component in legacy_rule.components):
            return None, "No hay costos configurados en la regla legacy."
        return legacy_rule, None

    def _resolve_price_rule_cost_model(self, price_rule: dict | None) -> CostRule | None:
        resolved, _ = self.resolve_price_rule_cost_model(price_rule)
        return resolved

    def resolve_cost_model_with_priority(
        self,
        *,
        variant_model_id: int | None = None,
        price_rule: dict | None = None,
        product_key: str = "",
    ) -> tuple[CostRule | None, str | None]:
        """Resuelve el modelo de costo según prioridad:
        
        1. Modelo asignado directamente a la variante
        2. Modelo vinculado a la price_rule
        3. Modelo activo encontrado por product_key
        4. Costo manual existente (legacy)
        5. Configuración incompleta
        
        Retorna (CostRule, warning) donde warning explica el estado.
        """
        # Prioridad 1: Modelo asignado directamente a la variante
        if variant_model_id and variant_model_id not in {None, "", 0}:
            try:
                model = self.variable_cost_model(int(variant_model_id))
                if model and bool(model.get("active", True)):
                    return self._build_cost_rule_from_variable_cost_model(model), None
                elif model:
                    return None, "El modelo asignado a la variante está desactivado"
                else:
                    return None, "El modelo asignado a la variante no existe"
            except (TypeError, ValueError):
                return None, "El ID de modelo de variante es inválido"
        
        # Prioridad 2: Modelo vinculado a la price_rule
        if price_rule:
            model_id = price_rule.get("variable_cost_model_id")
            if model_id and model_id not in {None, "", 0}:
                try:
                    model = self.variable_cost_model(int(model_id))
                    if model and bool(model.get("active", True)):
                        return self._build_cost_rule_from_variable_cost_model(model), None
                    elif model:
                        return None, "El modelo vinculado a la regla de precio está desactivado"
                    else:
                        return None, "El modelo vinculado a la regla de precio no existe"
                except (TypeError, ValueError):
                    return None, "El ID de modelo en la regla de precio es inválido"
        
        # Prioridad 3: Modelo activo encontrado por product_key
        if product_key:
            model = self.variable_cost_model_by_product_key(product_key)
            if model:
                return self._build_cost_rule_from_variable_cost_model(model), None
        
        # Prioridad 4: Costo manual existente (legacy en price_rule)
        if price_rule:
            legacy_rule = self._build_cost_rule_from_legacy_price_rule(price_rule)
            if legacy_rule and any(comp.value > 0 for comp in legacy_rule.components):
                return legacy_rule, None
        
        # Prioridad 5: Configuración incompleta
        return None, "No hay modelo de costo configurado para este producto"

    def price_sizes(self) -> list[str]:
        rows = self.connection.execute(
            "SELECT DISTINCT size FROM price_rules WHERE active = 1 AND size <> '' ORDER BY CASE WHEN size = 'A4' THEN 99 ELSE CAST(REPLACE(size, 'cm', '') AS REAL) END DESC"
        )
        return [str(row[0]) for row in rows]

    def job_titles(self) -> list[str]:
        """Retorna una lista única de títulos de productos usados en trabajos."""
        rows = self.connection.execute(
            "SELECT DISTINCT title FROM order_jobs WHERE title IS NOT NULL AND TRIM(title) <> '' ORDER BY title COLLATE NOCASE"
        )
        return [str(row[0]) for row in rows]

    def install_doccione_price_catalog(self, force: bool = False) -> int:
        """Carga la lista inicial una vez; las reglas quedan editables después."""
        if not force and self.app_setting(DOCCIONE_PRICE_CATALOG_KEY):
            return 0
        from datetime import datetime

        added = 0
        for index, (material, size, minimum, price, mode, pack_quantity, detail) in enumerate(DOCCIONE_PRICE_CATALOG, start=1):
            catalog_key = f"doccione_2026_07_15_{index}"
            exists = self.connection.execute(
                "SELECT 1 FROM price_rules WHERE catalog_key = ?", (catalog_key,)
            ).fetchone()
            if exists:
                continue
            self.connection.execute(
                """INSERT INTO price_rules(material, size, min_quantity, price, extra_service,
                   discount_percent, active, price_mode, pack_quantity, catalog_key)
                   VALUES(?, ?, ?, ?, ?, 0, 1, ?, ?, ?)""",
                (material, size, minimum, price, detail, mode, pack_quantity, catalog_key),
            )
            added += 1
        self.connection.execute(
            """INSERT INTO app_settings(setting_key, setting_value, updated_at) VALUES(?, ?, ?)
               ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value,
               updated_at = excluded.updated_at""",
            (DOCCIONE_PRICE_CATALOG_KEY, "instalado", datetime.now().isoformat(timespec="seconds")),
        )
        return added

    @staticmethod
    def _price_material(material: str) -> str:
        value = " ".join((material or "").strip().split())
        if not value:
            return ""
        aliases = {
            "full color": "Vinilo Full Color HD",
            "vinilo full color": "Vinilo Full Color HD",
            "full color hd": "Vinilo Full Color HD",
            "resina 3d": "Resina 3D Premium",
            "doming": "Resina 3D Premium",
            "ploteado": "Vinilo Ploteado",
            "vinilo ploteado": "Vinilo Ploteado",
            "premium": "Vinilo Premium",
            "vinilo premium": "Vinilo Premium",
            "plancha vinilo blanco full color": "Plancha A4 - Vinilo Blanco Full Color",
            "plancha a4 vinilo blanco full color": "Plancha A4 - Vinilo Blanco Full Color",
            "plancha personalizada": "Plancha A4 - Vinilo Blanco Full Color",
            "plancha a4 personalizada": "Plancha A4 - Vinilo Blanco Full Color",
            "plancha personalizada 5 cm": "Plancha A4 - Vinilo Blanco Full Color",
            "plancha personalizada mixta": "Plancha A4 - Vinilo Blanco Full Color",
            "plancha diseño único": "Plancha A4 - Diseño Único",
            "plancha diseño unico": "Plancha A4 - Diseño Único",
            "plancha a4 diseño único": "Plancha A4 - Diseño Único",
            "plancha a4 diseño unico": "Plancha A4 - Diseño Único",
            "plancha doccione": "Plancha A4 - Diseño Único",
            "plancha a4 doccione": "Plancha A4 - Diseño Único",
            "plancha vinilos especiales": "Plancha A4 - Vinilos Especiales",
            "plancha a4 vinilos especiales": "Plancha A4 - Vinilos Especiales",
        }
        return aliases.get(value.casefold(), value)

    @staticmethod
    def _price_size(size: str) -> str:
        value = "".join((size or "").strip().lower().replace(" ", "").split())
        if not value:
            return ""
        if value == "a4":
            return "A4"
        if value.endswith("cm"):
            value = value[:-2]
        try:
            number = float(value.replace(",", "."))
        except ValueError:
            return size.strip()
        return f"{number:g}cm"

    def save_price_rule(
        self, material: str, size: str, min_quantity: int, price: float,
        extra_service: str = "", discount_percent: float = 0,
        price_mode: str = "fijo", pack_quantity: int = 1,
        variable_cost_model_id: int | None = None, image_path: str = "",
        product_id: int | None = None, price_list_id: int | None = None,
    ) -> int:
        minimum = max(1, int(min_quantity or 1))
        amount  = max(0.0, float(price or 0))
        discount = min(100.0, max(0.0, float(discount_percent or 0)))
        mode = str(price_mode or "fijo").strip().casefold()
        if mode not in {"fijo", "unitario", "pack"}:
            mode = "fijo"
        pack = max(1, int(pack_quantity or 1))
        sql = """INSERT INTO price_rules(
                material, size, min_quantity, price, extra_service, discount_percent,
                active, price_mode, pack_quantity, variable_cost_model_id, image_path, product_id, price_list_id
               ) VALUES(?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)"""
        params = (
            self._price_material(material), self._price_size(size), minimum, amount,
            extra_service.strip(), discount, mode, pack, None if variable_cost_model_id in {None, ""} else int(variable_cost_model_id), image_path.strip(),
            None if product_id in {None, ""} else int(product_id), None if price_list_id in {None, ""} else int(price_list_id),
        )
        cursor = self.connection.execute(sql, params)
        try:
            self.connection.commit()
            commit_made = True
        except Exception:
            commit_made = False
        lastrowid = int(cursor.lastrowid) if getattr(cursor, 'lastrowid', None) is not None else None
        rowcount = getattr(cursor, 'rowcount', None)
        try:
            log_path = Path(__file__).resolve().parents[2] / 'persistence_actions.log'
            with open(log_path, 'a', encoding='utf-8') as fh:
                fh.write('\n=====================================\n')
                fh.write('SAVE PRICE RULE\n')
                fh.write('=====================================\n\n')
                fh.write('Parámetros:\n')
                fh.write(str(params) + '\n\n')
                fh.write('SQL:\n')
                fh.write(sql + '\n\n')
                fh.write('lastrowid:\n')
                fh.write(str(lastrowid) + '\n\n')
                fh.write('rowcount:\n')
                fh.write(str(rowcount) + '\n\n')
                fh.write('commit realizado:\n')
                fh.write(str(bool(commit_made)) + '\n\n')
                fh.write('=====================================\n')
        except Exception:
            pass
        return int(lastrowid) if lastrowid is not None else 0

    def price_rule(self, rule_id: int) -> dict | None:
        """Devuelve una regla activa para poder editarla desde la interfaz."""
        row = self.connection.execute(
            "SELECT * FROM price_rules WHERE id = ? AND active = 1", (int(rule_id),)
        ).fetchone()
        return dict(row) if row else None

    def update_price_rule(
        self, rule_id: int, material: str, size: str, min_quantity: int, price: float,
        extra_service: str = "", discount_percent: float = 0,
        price_mode: str = "fijo", pack_quantity: int = 1,
        variable_cost_model_id: int | None = None, image_path: str = "",
        product_id: int | None = None, price_list_id: int | None = None,
    ) -> bool:
        """Actualiza una regla sin alterar su origen ni la clave de catálogo."""
        minimum = max(1, int(min_quantity or 1))
        amount  = max(0.0, float(price or 0))
        discount = min(100.0, max(0.0, float(discount_percent or 0)))
        mode = str(price_mode or "fijo").strip().casefold()
        if mode not in {"fijo", "unitario", "pack"}:
            mode = "fijo"
        pack = max(1, int(pack_quantity or 1))
        sql = """UPDATE price_rules
               SET material = ?, size = ?, min_quantity = ?, price = ?, extra_service = ?,
                   discount_percent = ?, active = 1, price_mode = ?, pack_quantity = ?,
                   variable_cost_model_id = ?, image_path = ?, product_id = ?, price_list_id = ?
               WHERE id = ?"""
        params = (
            self._price_material(material), self._price_size(size), minimum, amount,
            extra_service.strip(), discount, mode, pack,
            None if variable_cost_model_id in {None, ""} else int(variable_cost_model_id), image_path.strip(),
            None if product_id in {None, ""} else int(product_id), None if price_list_id in {None, ""} else int(price_list_id),
            int(rule_id),
        )
        cursor = self.connection.execute(sql, params)
        try:
            self.connection.commit()
            commit_made = True
        except Exception:
            commit_made = False
        lastrowid = getattr(cursor, 'lastrowid', None)
        rowcount = getattr(cursor, 'rowcount', None)
        try:
            log_path = Path(__file__).resolve().parents[2] / 'persistence_actions.log'
            with open(log_path, 'a', encoding='utf-8') as fh:
                fh.write('\n=====================================\n')
                fh.write('UPDATE PRICE RULE\n')
                fh.write('=====================================\n\n')
                fh.write('Parámetros:\n')
                fh.write(str(params) + '\n\n')
                fh.write('SQL:\n')
                fh.write(sql + '\n\n')
                fh.write('lastrowid:\n')
                fh.write(str(lastrowid) + '\n\n')
                fh.write('rowcount:\n')
                fh.write(str(rowcount) + '\n\n')
                fh.write('commit realizado:\n')
                fh.write(str(bool(commit_made)) + '\n\n')
                fh.write('=====================================\n')
        except Exception:
            pass
        return bool(rowcount)

    def remove_price_rule(self, rule_id: int) -> None:
        self.connection.execute("DELETE FROM price_rules WHERE id = ?", (rule_id,))
        self.connection.commit()

    def remove_all_price_rules(self) -> None:
        self.connection.execute("DELETE FROM price_rules")
        self.connection.commit()

    # ═══════════════════════════════════════════════════════════════════════════
    # Reglas de costos — M.P, M.O, C.F con modos flexibles
    # ═══════════════════════════════════════════════════════════════════════════

    def all_cost_rules(self) -> list[dict]:
        """Devuelve todas las reglas de costos ordenadas por nombre."""
        rows = self.connection.execute(
            "SELECT * FROM cost_rules ORDER BY name COLLATE NOCASE, id"
        )
        return [dict(row) for row in rows]

    def cost_rule(self, rule_id: int) -> dict | None:
        """Devuelve una regla de costos por su ID."""
        row = self.connection.execute(
            "SELECT * FROM cost_rules WHERE id = ?", (rule_id,)
        ).fetchone()
        return dict(row) if row else None

    def cost_rule_domain(self, rule_id: int) -> CostRule | None:
        """Convierte una regla de costos de SQLite al modelo de dominio."""
        row = self.cost_rule(rule_id)
        if not row:
            return None

        rule = CostRule(
            id=int(row.get("id") or 0),
            name=str(row.get("name") or ""),
            product_type=str(row.get("material") or ""),
            minimum_margin=float(row.get("cost_mp_percent") or 0),
            active=True,
        )

        components = [
            CostComponent(name="Materia Prima", code="mp", value_type="percentage", value=float(row.get("cost_mp_percent") or 0), enabled=True, order=1),
            CostComponent(name="Mano de Obra", code="mo", value_type="percentage", value=float(row.get("cost_mo_percent") or 0), enabled=True, order=2),
            CostComponent(name="Carga Fabril", code="cf", value_type="percentage", value=float(row.get("cost_cf_percent") or 0), enabled=True, order=3),
        ]
        rule.components = [component for component in components if component.value > 0 or component.name]
        if row.get("condition"):
            rule.add_condition(CostCondition(field="condition", operator="contains", value=str(row.get("condition") or "")))
        return rule

    def save_cost_rule_domain(self, rule: CostRule) -> int:
        """Guarda una regla del modelo de dominio usando la persistencia actual."""
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        if rule.components:
            mp_component = next((component for component in rule.components if component.code == "mp"), None)
            mo_component = next((component for component in rule.components if component.code == "mo"), None)
            cf_component = next((component for component in rule.components if component.code == "cf"), None)
        else:
            mp_component = mo_component = cf_component = None

        cursor = self.connection.execute(
            """INSERT INTO cost_rules(name, condition, material, cost_mp_mode, cost_mp_percent, cost_mp_fixed, cost_mp_unit, cost_mo_mode, cost_mo_percent, cost_mo_fixed, cost_mo_unit, cost_cf_mode, cost_cf_percent, cost_cf_fixed, cost_cf_unit, created_at, updated_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rule.name.strip(),
                "",
                rule.product_type.strip(),
                "percent",
                float(mp_component.value if mp_component else 0),
                0.0,
                0.0,
                "percent",
                float(mo_component.value if mo_component else 0),
                0.0,
                0.0,
                "percent",
                float(cf_component.value if cf_component else 0),
                0.0,
                0.0,
                now,
                now,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def cost_rule_domain(self, rule_id: int) -> CostRule | None:
        """Convierte una regla de costos de SQLite al modelo de dominio."""
        row = self.cost_rule(rule_id)
        if not row:
            return None

        rule = CostRule(
            id=int(row.get("id") or 0),
            name=str(row.get("name") or ""),
            product_type=str(row.get("material") or ""),
            minimum_margin=float(row.get("cost_mp_percent") or 0),
            active=True,
        )

        # Mapeo simple desde las columnas históricas al nuevo modelo de componentes.
        components = [
            CostComponent(name="Materia Prima", code="mp", value_type="percentage", value=float(row.get("cost_mp_percent") or 0), enabled=True, order=1),
            CostComponent(name="Mano de Obra", code="mo", value_type="percentage", value=float(row.get("cost_mo_percent") or 0), enabled=True, order=2),
            CostComponent(name="Carga Fabril", code="cf", value_type="percentage", value=float(row.get("cost_cf_percent") or 0), enabled=True, order=3),
        ]
        rule.components = [component for component in components if component.value > 0 or component.name]
        if row.get("condition"):
            rule.add_condition(CostCondition(field="condition", operator="contains", value=str(row.get("condition") or "")))
        return rule

    def save_cost_rule_domain(self, rule: CostRule) -> int:
        """Guarda una regla del modelo de dominio usando la persistencia actual."""
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        if rule.components:
            mp_component = next((component for component in rule.components if component.code == "mp"), None)
            mo_component = next((component for component in rule.components if component.code == "mo"), None)
            cf_component = next((component for component in rule.components if component.code == "cf"), None)
        else:
            mp_component = mo_component = cf_component = None

        cursor = self.connection.execute(
            """INSERT INTO cost_rules(name, condition, material, cost_mp_mode, cost_mp_percent, cost_mp_fixed, cost_mp_unit, cost_mo_mode, cost_mo_percent, cost_mo_fixed, cost_mo_unit, cost_cf_mode, cost_cf_percent, cost_cf_fixed, cost_cf_unit, created_at, updated_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rule.name.strip(),
                "",
                rule.product_type.strip(),
                "percent",
                float(mp_component.value if mp_component else 0),
                0.0,
                0.0,
                "percent",
                float(mo_component.value if mo_component else 0),
                0.0,
                0.0,
                "percent",
                float(cf_component.value if cf_component else 0),
                0.0,
                0.0,
                now,
                now,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def save_cost_rule(
        self, name: str, condition: str = "",
        material: str = "",
        # Materia Prima
        cost_mp_mode: str = "percent",
        cost_mp_percent: float = 0,
        cost_mp_fixed: float = 0,
        cost_mp_unit: float = 0,
        # Mano de Obra
        cost_mo_mode: str = "percent",
        cost_mo_percent: float = 0,
        cost_mo_fixed: float = 0,
        cost_mo_unit: float = 0,
        # Carga Fabril
        cost_cf_mode: str = "percent",
        cost_cf_percent: float = 0,
        cost_cf_fixed: float = 0,
        cost_cf_unit: float = 0,
        components: list[dict] | None = None,
    ) -> int:
        """Crea una nueva regla de costos."""
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")

        component_payload = []
        for component in components or []:
            if isinstance(component, CostComponent):
                component_payload.append({
                    "name": component.name,
                    "code": component.code,
                    "value_type": component.value_type,
                    "value": component.value,
                    "enabled": component.enabled,
                    "order": component.order,
                })
            elif isinstance(component, dict):
                component_payload.append(component)

        sql = """INSERT INTO cost_rules(
                name, condition, material,
                cost_mp_mode, cost_mp_percent, cost_mp_fixed, cost_mp_unit,
                cost_mo_mode, cost_mo_percent, cost_mo_fixed, cost_mo_unit,
                cost_cf_mode, cost_cf_percent, cost_cf_fixed, cost_cf_unit,
                components_json, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        params = (
            name.strip(), condition.strip(), material.strip(),
            self._normalize_cost_mode(cost_mp_mode), cost_mp_percent, cost_mp_fixed, cost_mp_unit,
            self._normalize_cost_mode(cost_mo_mode), cost_mo_percent, cost_mo_fixed, cost_mo_unit,
            self._normalize_cost_mode(cost_cf_mode), cost_cf_percent, cost_cf_fixed, cost_cf_unit,
            json.dumps(component_payload, ensure_ascii=False), now, now,
        )
        cursor = self.connection.execute(sql, params)
        try:
            self.connection.commit()
            commit_made = True
        except Exception:
            commit_made = False
        lastrowid = int(cursor.lastrowid) if getattr(cursor, 'lastrowid', None) is not None else None
        rowcount = getattr(cursor, 'rowcount', None)
        try:
            log_path = Path(__file__).resolve().parents[2] / 'persistence_actions.log'
            with open(log_path, 'a', encoding='utf-8') as fh:
                fh.write('\n=====================================\n')
                fh.write('SAVE COST RULE\n')
                fh.write('=====================================\n\n')
                fh.write('Parámetros:\n')
                fh.write(str(params) + '\n\n')
                fh.write('SQL:\n')
                fh.write(sql + '\n\n')
                fh.write('lastrowid:\n')
                fh.write(str(lastrowid) + '\n\n')
                fh.write('rowcount:\n')
                fh.write(str(rowcount) + '\n\n')
                fh.write('commit realizado:\n')
                fh.write(str(bool(commit_made)) + '\n\n')
                fh.write('=====================================\n')
        except Exception:
            pass
        return int(lastrowid) if lastrowid is not None else 0

    def update_cost_rule(
        self, rule_id: int, name: str, condition: str = "",
        material: str = "",
        # Materia Prima
        cost_mp_mode: str = "percent",
        cost_mp_percent: float = 0,
        cost_mp_fixed: float = 0,
        cost_mp_unit: float = 0,
        # Mano de Obra
        cost_mo_mode: str = "percent",
        cost_mo_percent: float = 0,
        cost_mo_fixed: float = 0,
        cost_mo_unit: float = 0,
        # Carga Fabril
        cost_cf_mode: str = "percent",
        cost_cf_percent: float = 0,
        cost_cf_fixed: float = 0,
        cost_cf_unit: float = 0,
    ) -> bool:
        """Actualiza una regla de costos existente."""
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        
        sql = """UPDATE cost_rules SET
                name = ?, condition = ?, material = ?,
                cost_mp_mode = ?, cost_mp_percent = ?, cost_mp_fixed = ?, cost_mp_unit = ?,
                cost_mo_mode = ?, cost_mo_percent = ?, cost_mo_fixed = ?, cost_mo_unit = ?,
                cost_cf_mode = ?, cost_cf_percent = ?, cost_cf_fixed = ?, cost_cf_unit = ?,
                updated_at = ?
            WHERE id = ?"""
        params = (
            name.strip(), condition.strip(), material.strip(),
            self._normalize_cost_mode(cost_mp_mode), cost_mp_percent, cost_mp_fixed, cost_mp_unit,
            self._normalize_cost_mode(cost_mo_mode), cost_mo_percent, cost_mo_fixed, cost_mo_unit,
            self._normalize_cost_mode(cost_cf_mode), cost_cf_percent, cost_cf_fixed, cost_cf_unit,
            now, rule_id
        )
        cursor = self.connection.execute(sql, params)
        try:
            self.connection.commit()
            commit_made = True
        except Exception:
            commit_made = False
        lastrowid = getattr(cursor, 'lastrowid', None)
        rowcount = getattr(cursor, 'rowcount', None)
        try:
            log_path = Path(__file__).resolve().parents[2] / 'persistence_actions.log'
            with open(log_path, 'a', encoding='utf-8') as fh:
                fh.write('\n=====================================\n')
                fh.write('UPDATE COST RULE\n')
                fh.write('=====================================\n\n')
                fh.write('Parámetros:\n')
                fh.write(str(params) + '\n\n')
                fh.write('SQL:\n')
                fh.write(sql + '\n\n')
                fh.write('lastrowid:\n')
                fh.write(str(lastrowid) + '\n\n')
                fh.write('rowcount:\n')
                fh.write(str(rowcount) + '\n\n')
                fh.write('commit realizado:\n')
                fh.write(str(bool(commit_made)) + '\n\n')
                fh.write('=====================================\n')
        except Exception:
            pass
        return bool(rowcount)

    def remove_cost_rule(self, rule_id: int) -> None:
        """Elimina una regla de costos."""
        self.connection.execute("DELETE FROM cost_rules WHERE id = ?", (rule_id,))
        self.connection.commit()

    # ── Costos Variables ────────────────────────────────────────────────────

    def all_variable_cost_models(self) -> list[dict]:
        """Devuelve todos los modelos de costo variable."""
        rows = self.connection.execute(
            "SELECT * FROM variable_cost_models ORDER BY name COLLATE NOCASE, id"
        )
        return [dict(row) for row in rows]

    def active_variable_cost_models(self) -> list[dict]:
        """Devuelve solo los modelos activos de costo variable."""
        rows = self.connection.execute(
            "SELECT * FROM variable_cost_models WHERE active = 1 ORDER BY name COLLATE NOCASE, id"
        )
        return [dict(row) for row in rows]

    def active_variable_cost_keys(self) -> set[str]:
        """Devuelve el conjunto de product_key con un modelo activo."""
        rows = self.connection.execute(
            "SELECT product_key FROM variable_cost_models WHERE active = 1 AND product_key != ''"
        )
        return {row[0] for row in rows}

    def variable_cost_model(self, model_id: int) -> dict | None:
        """Devuelve un modelo de costo variable por ID."""
        row = self.connection.execute(
            "SELECT * FROM variable_cost_models WHERE id = ?", (model_id,)
        ).fetchone()
        return dict(row) if row else None

    def variable_cost_model_components(self, model_id: int) -> list[dict]:
        """Devuelve los componentes de un modelo de costo variable."""
        rows = self.connection.execute(
            "SELECT * FROM variable_cost_components WHERE model_id = ? ORDER BY sort_order, id",
            (model_id,),
        )
        return [dict(row) for row in rows]

    def save_variable_cost_model(
        self,
        name: str,
        product_id: int | None = None,
        product_name: str = "",
        product_key: str = "",
        category: str = "",
        active: bool = True,
        outdated: bool = False,
        components: list[dict] | None = None,
    ) -> int:
        """Crea un nuevo modelo de costo variable con sus componentes.

        La operación se ejecuta dentro de una transacción: si falla
        un componente, no queda guardado un modelo incompleto.
        """
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        cursor = self.connection.execute(
            """INSERT INTO variable_cost_models(
                name, product_id, product_name, product_key, category,
                active, outdated, created_at, updated_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name.strip(), product_id, product_name.strip(),
                product_key.strip(), category.strip(),
                int(active), int(outdated), now, now,
            ),
        )
        model_id = int(cursor.lastrowid or 0)
        self._insert_variable_cost_components(model_id, components, now)
        self.connection.commit()
        return model_id

    def update_variable_cost_model(
        self,
        model_id: int,
        name: str,
        product_id: int | None = None,
        product_name: str = "",
        product_key: str = "",
        category: str = "",
        active: bool = True,
        outdated: bool = False,
        components: list[dict] | None = None,
    ) -> bool:
        """Actualiza un modelo de costo variable y reemplaza sus componentes.

        Si ``components`` es None, los componentes no se modifican.
        """
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        cursor = self.connection.execute(
            """UPDATE variable_cost_models SET
                name = ?, product_id = ?, product_name = ?, product_key = ?,
                category = ?, active = ?, outdated = ?, updated_at = ?
               WHERE id = ?""",
            (
                name.strip(), product_id, product_name.strip(),
                product_key.strip(), category.strip(),
                int(active), int(outdated), now, model_id,
            ),
        )
        if components is not None:
            self.connection.execute(
                "DELETE FROM variable_cost_components WHERE model_id = ?", (model_id,)
            )
            self._insert_variable_cost_components(model_id, components, now)
        
        # Marcar price_rules vinculadas como desactualizadas
        self._mark_price_rules_outdated_for_model(model_id, now)
        
        self.connection.commit()
        return bool(cursor.rowcount)

    def _insert_variable_cost_components(
        self, model_id: int, components: list[dict] | None, now: str
    ) -> None:
        """Inserta componentes de costo variable dentro de una transacción existente."""
        for idx, comp in enumerate(components or []):
            self.connection.execute(
                """INSERT INTO variable_cost_components(
                    model_id, name, category, origin, source_id, calc_mode,
                    quantity, unit_value, waste_pct, unit, percentage_base,
                    amount, sort_order, active,
                    source_updated_at, last_synced_at, manually_overridden,
                    created_at, updated_at)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    model_id,
                    str(comp.get("name") or "").strip(),
                    str(comp.get("category") or "").strip(),
                    str(comp.get("origin") or "manual").strip(),
                    comp.get("source_id"),
                    str(comp.get("calc_mode") or comp.get("calculation_mode") or "per_unit").strip(),
                    str(comp.get("quantity") or "0"),
                    str(comp.get("unit_value") or "0"),
                    str(comp.get("waste_pct") or "0"),
                    str(comp.get("unit") or "").strip(),
                    str(comp.get("percentage_base") or "").strip(),
                    str(comp.get("amount") or comp.get("calculated_amount") or "0"),
                    int(comp.get("sort_order") or comp.get("order") or idx),
                    int(comp.get("active", 1)),
                    str(comp.get("source_updated_at") or "").strip(),
                    str(comp.get("last_synced_at") or "").strip(),
                    int(comp.get("manually_overridden", 0)),
                    now,
                    now,
                ),
            )

    def remove_variable_cost_model(self, model_id: int) -> None:
        """Elimina un modelo de costo variable y sus componentes."""
        self.connection.execute("DELETE FROM variable_cost_components WHERE model_id = ?", (model_id,))
        self.connection.execute("DELETE FROM variable_cost_models WHERE id = ?", (model_id,))
        self.connection.commit()

    def deactivate_variable_cost_model(self, model_id: int) -> bool:
        """Desactiva un modelo (baja lógica) en lugar de eliminarlo."""
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        cursor = self.connection.execute(
            "UPDATE variable_cost_models SET active = 0, updated_at = ? WHERE id = ?",
            (now, model_id),
        )
        self.connection.commit()
        return bool(cursor.rowcount)

    def duplicate_variable_cost_model(self, model_id: int) -> int | None:
        """Duplica un modelo de costo variable existente."""
        model = self.variable_cost_model(model_id)
        if not model:
            return None
        components = self.variable_cost_model_components(model_id)
        new_id = self.save_variable_cost_model(
            name=f"{model['name']} (copia)",
            product_id=model.get("product_id"),
            product_name=str(model.get("product_name") or ""),
            product_key=str(model.get("product_key") or ""),
            category=str(model.get("category") or ""),
            active=bool(model.get("active", 1)),
            components=components,
        )
        return new_id

    def variable_cost_models_by_product(self, product_key: str) -> list[dict]:
        """Devuelve todos los modelos de costo variable para una product_key."""
        rows = self.connection.execute(
            "SELECT * FROM variable_cost_models WHERE product_key = ? ORDER BY active DESC, id",
            (product_key,),
        )
        return [dict(row) for row in rows]

    def variable_cost_model_by_product_key(self, product_key: str) -> dict | None:
        """Devuelve el modelo activo para una product_key dada."""
        row = self.connection.execute(
            "SELECT * FROM variable_cost_models WHERE product_key = ? AND active = 1 LIMIT 1",
            (product_key,),
        ).fetchone()
        return dict(row) if row else None

    def _mark_price_rules_outdated_for_model(self, model_id: int, timestamp: str) -> None:
        """Marca las price_rules vinculadas a un modelo como desactualizadas.
        
        Solo marca las reglas que no tienen manually_overridden = 1.
        """
        self.connection.execute(
            """UPDATE price_rules 
               SET outdated = 1, source_updated_at = ?
               WHERE variable_cost_model_id = ? AND manually_overridden = 0""",
            (timestamp, model_id),
        )

    def sync_price_rule_with_model(self, rule_id: int) -> tuple[bool, str | None]:
        """Sincroniza explícitamente una price_rule con su modelo vinculado.
        
        Retorna (success, warning).
        """
        rule = self.price_rule(rule_id)
        if not rule:
            return False, "Regla no encontrada"
        
        model_id = rule.get("variable_cost_model_id")
        if not model_id or model_id in {None, "", 0}:
            return False, "La regla no tiene un modelo vinculado"
        
        model = self.variable_cost_model(int(model_id))
        if not model:
            return False, "El modelo vinculado no existe"
        
        if not bool(model.get("active", True)):
            return False, "El modelo vinculado está desactivado"
        
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        
        # Actualizar campos de sincronización
        self.connection.execute(
            """UPDATE price_rules 
               SET outdated = 0, last_synced_at = ?, manually_overridden = 0
               WHERE id = ?""",
            (now, rule_id),
        )
        self.connection.commit()
        
        return True, None

    def price_rule_products(self) -> list[dict]:
        """Devuelve productos únicos de price_rules para el selector."""
        rows = self.connection.execute(
            """SELECT DISTINCT material, size FROM price_rules WHERE material <> ''
               ORDER BY material COLLATE NOCASE"""
        )
        products = []
        seen = set()
        for row in rows:
            mat = str(row[0] or "")
            if " - " in mat:
                prod = mat.split(" - ", 1)[0].strip()
            else:
                prod = mat.strip()
            if prod and prod.lower() not in seen:
                seen.add(prod.lower())
                products.append({"name": prod, "material_full": mat, "size": str(row[1] or "")})
        return products

    def catalog_products(self, search: str = "", *, include_inactive: bool = False) -> list[dict]:
        """Devuelve fichas de catálogo con un precio visible y sus reglas asociadas."""
        filters = []
        params: list[object] = []
        if not include_inactive:
            filters.append("p.active = 1")
        term = str(search or "").strip()
        if term:
            filters.append(
                "(p.name LIKE ? COLLATE NOCASE OR p.code LIKE ? COLLATE NOCASE "
                "OR p.category LIKE ? COLLATE NOCASE OR p.description LIKE ? COLLATE NOCASE)"
            )
            wildcard = f"%{term}%"
            params.extend([wildcard, wildcard, wildcard, wildcard])
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        rows = self.connection.execute(
            f"""SELECT p.*,
                       COALESCE(p.base_price, MIN(CASE WHEN pr.active = 1 THEN pr.price END), 0) AS price,
                       COUNT(CASE WHEN pr.active = 1 THEN pr.id END) AS price_rule_count,
                       MIN(CASE WHEN pr.active = 1 THEN pr.price END) AS min_price,
                       MAX(CASE WHEN pr.active = 1 THEN pr.price END) AS max_price,
                       GROUP_CONCAT(DISTINCT NULLIF(pr.size, '')) AS available_sizes
                  FROM products AS p
             LEFT JOIN price_rules AS pr ON pr.product_id = p.id
                  {where}
              GROUP BY p.id
              ORDER BY p.active DESC, p.updated_at DESC, p.name COLLATE NOCASE""",
            params,
        )
        return [dict(row) for row in rows]

    def catalog_product(self, product_id: int) -> dict | None:
        """Devuelve una ficha de producto, incluso si está archivada."""
        row = self.connection.execute(
            """SELECT p.*,
                      COALESCE(p.base_price, MIN(CASE WHEN pr.active = 1 THEN pr.price END), 0) AS price,
                      COUNT(CASE WHEN pr.active = 1 THEN pr.id END) AS price_rule_count,
                      MIN(CASE WHEN pr.active = 1 THEN pr.price END) AS min_price,
                      MAX(CASE WHEN pr.active = 1 THEN pr.price END) AS max_price,
                      GROUP_CONCAT(DISTINCT NULLIF(pr.size, '')) AS available_sizes
                 FROM products AS p
            LEFT JOIN price_rules AS pr ON pr.product_id = p.id
                WHERE p.id = ?
             GROUP BY p.id""",
            (int(product_id),),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _catalog_product_code(name: str) -> str:
        """Construye una clave estable y legible para productos creados desde la UI."""
        normalized = unicodedata.normalize("NFKD", str(name or "producto"))
        ascii_name = normalized.encode("ascii", "ignore").decode("ascii").casefold()
        code = re.sub(r"[^a-z0-9]+", "_", ascii_name).strip("_")
        return code or "producto"

    def _available_catalog_product_code(self, name: str, product_id: int | None = None) -> str:
        base = self._catalog_product_code(name)
        candidate = base
        suffix = 2
        while True:
            row = self.connection.execute(
                "SELECT id FROM products WHERE code = ?",
                (candidate,),
            ).fetchone()
            if row is None or (product_id is not None and int(row[0]) == int(product_id)):
                return candidate
            candidate = f"{base}_{suffix}"
            suffix += 1

    def _save_catalog_base_price_rule(self, product_id: int, name: str, price: float) -> None:
        """Mantiene una regla base para que un producto nuevo también cotice en pedidos."""
        from datetime import datetime

        catalog_key = f"product_card_{int(product_id)}"
        now = datetime.now().isoformat(timespec="seconds")
        price_list = self.connection.execute(
            "SELECT id FROM price_lists WHERE code = 'general' AND active = 1"
        ).fetchone()
        price_list_id = int(price_list[0]) if price_list else None
        existing = self.connection.execute(
            "SELECT id FROM price_rules WHERE catalog_key = ?",
            (catalog_key,),
        ).fetchone()
        if existing:
            self.connection.execute(
                """UPDATE price_rules
                      SET product_id = ?, material = ?, price = ?, price_mode = 'unitario',
                          min_quantity = 1, pack_quantity = 1, price_list_id = ?,
                          rule_name = ?, active = 1, priority = 25
                    WHERE id = ?""",
                (
                    int(product_id),
                    name.strip(),
                    float(price),
                    price_list_id,
                    f"Precio base de {name.strip()}",
                    int(existing[0]),
                ),
            )
        else:
            self.connection.execute(
                """INSERT INTO price_rules(
                       product_id, material, size, min_quantity, price, active,
                       price_mode, pack_quantity, catalog_key, price_list_id,
                       priority, rule_name, source_updated_at
                   ) VALUES(?, ?, '', 1, ?, 1, 'unitario', 1, ?, ?, 25, ?, ?)""",
                (
                    int(product_id),
                    name.strip(),
                    float(price),
                    catalog_key,
                    price_list_id,
                    f"Precio base de {name.strip()}",
                    now,
                ),
            )

    def save_catalog_product(
        self,
        *,
        name: str,
        price: float,
        description: str = "",
        category: str = "",
        image_path: str = "",
    ) -> int:
        """Crea una ficha de producto y su regla de precio base."""
        from datetime import datetime

        cleaned_name = str(name or "").strip()
        if not cleaned_name:
            raise ValueError("El nombre del producto es obligatorio.")
        amount = float(price)
        if amount < 0:
            raise ValueError("El precio no puede ser negativo.")
        now = datetime.now().isoformat(timespec="seconds")
        code = self._available_catalog_product_code(cleaned_name)
        cursor = self.connection.execute(
            """INSERT INTO products(
                   code, name, description, category, image_path, base_price,
                   active, created_at, updated_at
               ) VALUES(?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (
                code,
                cleaned_name,
                str(description or "").strip(),
                str(category or "").strip(),
                str(image_path or "").strip(),
                amount,
                now,
                now,
            ),
        )
        product_id = int(cursor.lastrowid)
        self._save_catalog_base_price_rule(product_id, cleaned_name, amount)
        self.connection.commit()
        return product_id

    def update_catalog_product(
        self,
        product_id: int,
        *,
        name: str,
        price: float,
        description: str = "",
        category: str = "",
        image_path: str = "",
    ) -> bool:
        """Actualiza el contenido editable de una ficha y su precio base."""
        from datetime import datetime

        cleaned_name = str(name or "").strip()
        if not cleaned_name:
            raise ValueError("El nombre del producto es obligatorio.")
        amount = float(price)
        if amount < 0:
            raise ValueError("El precio no puede ser negativo.")
        product_id = int(product_id)
        existing_product = self.connection.execute(
            "SELECT name FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if not existing_product:
            return False
        previous_name = str(existing_product[0] or "").strip()
        now = datetime.now().isoformat(timespec="seconds")
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE products
                      SET name = ?, description = ?, category = ?, image_path = ?,
                          base_price = ?, updated_at = ?
                    WHERE id = ?""",
                (
                    cleaned_name,
                    str(description or "").strip(),
                    str(category or "").strip(),
                    str(image_path or "").strip(),
                    amount,
                    now,
                    product_id,
                ),
            )
            self._save_catalog_base_price_rule(product_id, cleaned_name, amount)

            # Las reglas se vinculan por ``product_id`` y por eso muestran el
            # nombre nuevo automáticamente. Los trabajos de pedidos, en cambio,
            # conservan el título para que puedan leerse sin hacer joins. Al
            # renombrar un producto vinculado mantenemos ese título alineado,
            # sin tocar los importes ni los snapshots comerciales del pedido.
            self.connection.execute(
                "UPDATE order_jobs SET title = ?, updated_at = ? WHERE product_id = ?",
                (cleaned_name, now, product_id),
            )
            # Compatibilidad con pedidos creados antes de que se guardara el
            # vínculo de catálogo: sólo se actualizan los que aún llevan el
            # nombre anterior exacto.
            if previous_name and previous_name != cleaned_name:
                self.connection.execute(
                    """UPDATE order_jobs
                          SET title = ?, updated_at = ?
                        WHERE product_id IS NULL AND title = ?""",
                    (cleaned_name, now, previous_name),
                )
            self.connection.execute(
                "UPDATE variable_cost_models SET product_name = ?, updated_at = ? WHERE product_id = ?",
                (cleaned_name, now, product_id),
            )
        return bool(cursor.rowcount)

    def set_catalog_product_active(self, product_id: int, active: bool) -> bool:
        """Archiva o restaura una ficha sin borrar precios ni pedidos históricos."""
        from datetime import datetime

        cursor = self.connection.execute(
            "UPDATE products SET active = ?, updated_at = ? WHERE id = ?",
            (
                int(bool(active)),
                datetime.now().isoformat(timespec="seconds"),
                int(product_id),
            ),
        )
        self.connection.commit()
        return bool(cursor.rowcount)

    def delete_catalog_product(self, product_id: int) -> bool:
        """Elimina permanentemente un producto y sus reglas de precio asociadas."""
        with self.connection:
            self.connection.execute("DELETE FROM price_rules WHERE product_id = ?", (int(product_id),))
            cursor = self.connection.execute("DELETE FROM products WHERE id = ?", (int(product_id),))
        return bool(cursor.rowcount)

    def resolve_commercial_price(self, *, product_id: int | None = None, product_code: str = "",
                                 material: str = "", size: str = "", quantity: int = 1,
                                 price_list_id: int | None = None, price_list_code: str = "",
                                 manual_price: float | None = None, manual_reason: str = "") -> dict:
        """Resuelve una regla comercial sin mutar el pedido.

        Los packs se informan como sugerencia: sólo se aplican al confirmar la regla.
        """
        quantity = max(1, int(quantity or 1))
        if manual_price is not None:
            if not str(manual_reason).strip():
                return {"matched": False, "warning": "El precio manual requiere un motivo.", "requires_confirmation": True}
            return {"matched": True, "manual_override": True, "unit_price": float(manual_price),
                    "fixed_total": None, "subtotal": round(float(manual_price) * quantity, 2),
                    "calculation_type": "manual", "requires_confirmation": True, "warning": None}
        if product_code and product_id is None:
            row = self.connection.execute("SELECT id FROM products WHERE code = ?", (product_code,)).fetchone()
            product_id = int(row[0]) if row else None
        if price_list_code and price_list_id is None:
            row = self.connection.execute("SELECT id FROM price_lists WHERE code = ? AND active = 1", (price_list_code,)).fetchone()
            price_list_id = int(row[0]) if row else None
        if price_list_id is None and not price_list_code:
            row = self.connection.execute("SELECT id FROM price_lists WHERE code = 'general' AND active = 1").fetchone()
            price_list_id = int(row[0]) if row else None
        normalized_size = self._price_size(size)
        normalized_material = self._price_material(material)
        where, params = ["active = 1"], []
        if product_id is not None:
            where.append("product_id = ?"); params.append(product_id)
        if price_list_id is not None:
            where.append("price_list_id = ?"); params.append(price_list_id)
        if normalized_material:
            where.append("(material = '' OR material = ? COLLATE NOCASE)"); params.append(normalized_material)
        if normalized_size:
            where.append("(size = '' OR size = ? COLLATE NOCASE)"); params.append(normalized_size)
        rows = [dict(row) for row in self.connection.execute(
            "SELECT * FROM price_rules WHERE " + " AND ".join(where) + " ORDER BY priority DESC, id DESC", params)]
        rows = [r for r in rows if int(r.get("min_quantity") or 1) <= quantity and (r.get("max_quantity") is None or quantity <= int(r["max_quantity"]))]
        packs = [r for r in rows if str(r.get("price_mode") or "").casefold() == "pack" and int(r.get("pack_quantity") or 1) == quantity]
        non_packs = [r for r in rows if str(r.get("price_mode") or "").casefold() != "pack"]
        if not non_packs and not packs:
            return {"matched": False, "warning": "No existe una regla de precio para esta selección.", "requires_confirmation": True}
        rule = max(non_packs or packs, key=lambda r: (int(r.get("priority") or 0), int(r.get("min_quantity") or 1), int(r["id"])))
        mode = str(rule.get("price_mode") or "fijo").casefold()
        fixed_total = float(rule["price"]) if mode == "fijo" else None
        unit_price = float(rule["price"]) if mode == "unitario" else None
        subtotal = fixed_total if fixed_total is not None else round((unit_price or 0) * quantity, 2)
        result = {"matched": True, "rule_id": int(rule["id"]), "rule_name": rule.get("rule_name") or rule.get("material") or "Regla de precio",
                  "price_list_id": rule.get("price_list_id"), "calculation_type": mode, "unit_price": unit_price,
                  "fixed_total": fixed_total, "subtotal": subtotal, "discount_amount": 0, "requires_confirmation": False,
                  "warning": None, "preparation_limit": rule.get("preparation_limit")}
        if packs and mode != "pack":
            pack = max(packs, key=lambda r: int(r["id"]))
            result["pack_suggestion"] = {"rule_id": int(pack["id"]), "quantity": quantity, "total": float(pack["price"]), "savings": round(subtotal - float(pack["price"]), 2)}
        return result

    def save_order_job_price_snapshot(self, order_job_id: int, calculation: dict, *, manual_reason: str = "") -> None:
        """Fija el cálculo confirmado; los cambios futuros de reglas no lo alteran."""
        from datetime import datetime
        if not calculation.get("matched"):
            raise ValueError("No se puede guardar un cálculo sin regla.")
        now = datetime.now().isoformat(timespec="seconds")
        self.connection.execute("""UPDATE order_jobs SET price_rule_id=?, unit_price_snapshot=?, fixed_price_snapshot=?,
            calculation_type=?, manual_override=?, manual_override_reason=?, calculated_at=? WHERE id=?""",
            (calculation.get("rule_id"), calculation.get("unit_price"), calculation.get("fixed_total"), calculation.get("calculation_type", ""),
             int(bool(calculation.get("manual_override"))), manual_reason, now, int(order_job_id)))
        self.connection.commit()

    def suggest_price(self, material: str, size: str, quantity: int) -> dict | None:
        """Propone el importe más conveniente sin cambiar el pedido."""
        quantity = max(1, int(quantity or 1))
        material = self._price_material(material)
        size = self._price_size(size)
        rows = self.connection.execute(
            """SELECT * FROM price_rules WHERE active = 1
               AND (material = '' OR material = ? COLLATE NOCASE)
               AND (size = '' OR size = ? COLLATE NOCASE)
               ORDER BY (material <> '') DESC, (size <> '') DESC, min_quantity DESC, id DESC""",
            (material, size),
        ).fetchall()
        rules = [dict(row) for row in rows]
        rules = [
            rule for rule in rules
            if int(rule.get("min_quantity") or 1) <= quantity
            and (rule.get("max_quantity") is None or quantity <= int(rule["max_quantity"]))
        ]
        if not rules:
            return None

        candidates: list[tuple[float, dict, str]] = []
        fixed = [rule for rule in rules if (rule.get("price_mode") or "fijo").casefold() == "fijo" and int(rule.get("min_quantity") or 1) <= quantity]
        if fixed:
            rule = fixed[0]
            candidates.append((float(rule["price"]), rule, "Precio fijo"))

        unit_rules = [rule for rule in rules if (rule.get("price_mode") or "fijo").casefold() == "unitario" and int(rule.get("min_quantity") or 1) <= quantity]
        if unit_rules:
            rule = max(unit_rules, key=lambda item: (int(item.get("min_quantity") or 1), int(item.get("id") or 0)))
            unit = float(rule["price"])
            candidates.append((round(unit * quantity, 2), rule, f"${unit:,.2f} c/u × {quantity}"))

        pack_rules = [rule for rule in rules if (rule.get("price_mode") or "").casefold() == "pack" and int(rule.get("pack_quantity") or 1) <= quantity]
        if pack_rules:
            highest_pack = max(int(rule.get("pack_quantity") or 1) for rule in pack_rules)
            limit = quantity + highest_pack
            amounts: list[tuple[float, list[dict]] | None] = [None] * (limit + 1)
            amounts[0] = (0.0, [])
            for current in range(limit + 1):
                state = amounts[current]
                if state is None:
                    continue
                for rule in pack_rules:
                    next_quantity = min(limit, current + int(rule.get("pack_quantity") or 1))
                    next_cost = state[0] + float(rule["price"])
                    if amounts[next_quantity] is None or next_cost < amounts[next_quantity][0]:
                        amounts[next_quantity] = (next_cost, [*state[1], rule])
            possible = [(total, state) for total, state in enumerate(amounts) if total >= quantity and state is not None]
            if possible:
                _total, state = min(possible, key=lambda entry: (entry[1][0], entry[0]))
                cost, packs = state
                rule = max(packs, key=lambda item: int(item.get("pack_quantity") or 1))
                description = " + ".join(f"{int(item.get('pack_quantity') or 1)} u." for item in packs)
                candidates.append((round(cost, 2), rule, f"Packs: {description}"))

        if not candidates:
            return None
        subtotal, rule, detail = min(candidates, key=lambda item: (item[0], -int(item[1].get("min_quantity") or 1)))

        # ── Calcular costos desglosados para la cantidad solicitada ───────────
        model_rule = self._resolve_price_rule_cost_model(rule)
        analysis = CostCalculator.calculate(
            model_rule or CostRule(name="Sin modelo", active=False),
            sale_price=subtotal,
            quantity=quantity,
            hours=0.0,
            surface=0.0,
            suggested_price=subtotal,
        )
        component_map = {component.code.lower(): component.amount for component in analysis.components}
        cost_mp = round(float(component_map.get("mp", 0.0)), 2)
        cost_mo = round(float(component_map.get("mo", 0.0)), 2)
        cost_cf = round(float(component_map.get("cf", 0.0)), 2)
        cost_total = round(analysis.cost_total, 2)
        margin = round(analysis.gross_profit, 2)
        margin_pct = round(analysis.margin_percentage, 1)

        return {
            **rule,
            "suggested_subtotal":  subtotal,
            "calculation_detail":  detail,
            "cost_mp":    cost_mp,
            "cost_mo":    cost_mo,
            "cost_cf":    cost_cf,
            "cost_total": cost_total,
            "margin":     margin,
            "margin_pct": margin_pct,
        }

    def quantity_discount_details(self, material: str, size: str, quantity: int) -> dict | None:
        """Devuelve el beneficio de la escala aplicada frente al precio de lista.

        Solo informa descuentos reales de reglas unitarias; los precios fijos y
        packs conservan su forma de cotización sin presentar un ahorro supuesto.
        """
        quantity = max(1, int(quantity or 1))
        applied = self.suggest_price(material, size, quantity)
        list_price = self.suggest_price(material, size, 1)
        if not applied or not list_price:
            return None
        if str(applied.get("price_mode") or "").casefold() != "unitario":
            return None
        if str(list_price.get("price_mode") or "").casefold() != "unitario":
            return None
        applied_unit = float(applied.get("price") or 0)
        list_unit = float(list_price.get("price") or 0)
        if list_unit <= 0 or applied_unit >= list_unit:
            return None
        savings = round((list_unit - applied_unit) * quantity, 2)
        return {
            "list_unit_price": list_unit,
            "tier_unit_price": applied_unit,
            "list_total": round(list_unit * quantity, 2),
            "tier_total": round(applied_unit * quantity, 2),
            "savings": savings,
            "discount_percent": round((list_unit - applied_unit) * 100 / list_unit, 2),
            "rule_id": applied.get("id"),
        }

    # Preparación con Photoshop -----------------------------------------
    def app_setting(self, key: str, default: str = "") -> str:
        row = self.connection.execute("SELECT setting_value FROM app_settings WHERE setting_key = ?", (key,)).fetchone()
        return str(row[0]) if row else default

    def save_app_setting(self, key: str, value: str) -> None:
        from datetime import datetime

        self.connection.execute(
            """INSERT INTO app_settings(setting_key, setting_value, updated_at) VALUES(?, ?, ?)
               ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value, updated_at = excluded.updated_at""",
            (key, value, datetime.now().isoformat(timespec="seconds")),
        )
        self.connection.commit()

    def productive_plancha_a4_settings(self) -> dict[str, float]:
        """Devuelve la configuración persistente para el cálculo A4."""
        prefix = "productive_plancha_a4."
        rows = self.connection.execute(
            "SELECT setting_key, setting_value FROM app_settings WHERE setting_key LIKE ?", (prefix + "%",)
        )
        values: dict[str, float] = {}
        for row in rows:
            try:
                values[str(row["setting_key"])[len(prefix):]] = float(row["setting_value"])
            except (TypeError, ValueError):
                continue
        return values

    def resolve_plancha_a4_base_price(self) -> dict:
        """Resuelve el precio A4 vigente desde una sola fuente comercial.

        ``price_rules`` es canónica. ``app_settings`` sólo conserva el valor
        legado para instalaciones donde aún no existe el catálogo comercial.
        Los pedidos deben guardar el resultado como snapshot, nunca releerlo.
        """
        row = self.connection.execute(
            """SELECT id, price, catalog_key, rule_name, last_synced_at, source_updated_at
               FROM price_rules WHERE active = 1 AND catalog_key = ? LIMIT 1""",
            ("commercial_plancha_a4_diseno_unico",),
        ).fetchone()
        if row:
            return {"price": float(row["price"] or 0), "source": "price_rules",
                    "rule_id": int(row["id"]), "rule_key": str(row["catalog_key"] or ""),
                    "version": str(row["last_synced_at"] or row["source_updated_at"] or "")}
        legacy = self.app_setting("productive_plancha_a4.base_price", "5000")
        try:
            price = max(0.0, float(legacy))
        except (TypeError, ValueError):
            price = 5000.0
        return {"price": price, "source": "legacy_app_settings", "rule_id": None,
                "rule_key": "productive_plancha_a4.base_price", "version": ""}

    def save_productive_plancha_a4_setting(self, key: str, value: float) -> None:
        """Actualiza una variable permitida sin introducir configuraciones ad hoc."""
        allowed = set(self.productive_plancha_a4_settings())
        if key not in allowed:
            raise ValueError("Configuración productiva no reconocida")
        self.save_app_setting(f"productive_plancha_a4.{key}", str(float(value)))

    def calculate_productive_plancha_a4(self, context: dict) -> dict:
        """Punto de entrada persistente del motor unificado para planchas A4."""
        resolved = self.resolve_plancha_a4_base_price()
        calculation_context = dict(context or {})
        calculation_context.setdefault("base_price", resolved["price"])
        calculation_context.setdefault("base_price_source", resolved["source"])
        calculation_context.setdefault("base_price_rule_id", resolved["rule_id"])
        calculation_context.setdefault("base_price_version", resolved["version"])
        return asdict(CostCalculator.calculate_plancha_a4(calculation_context, self.productive_plancha_a4_settings()))

    def register_private_design(self, file_path: str, order_id: int | None = None, client: str = "") -> None:
        """Indexa la copia de trabajo como privada, sin tocar ni renombrar el original."""
        path = Path(file_path)
        stat = path.stat()
        self.upsert({
            "path": str(path), "name": path.name, "extension": path.suffix.lower(),
            "size": stat.st_size, "modified": stat.st_mtime, "caption": "",
        })
        self.connection.execute(
            """UPDATE images SET design_client = ?, design_order_id = ?, is_private = 1,
               is_reusable = 0, import_status = 'Preparación' WHERE path = ?""",
            (client, order_id, str(path)),
        )
        self.connection.commit()

    def create_preparation(self, order_id: int, original_path: str, work_path: str, source_modified: float) -> int:
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        cursor = self.connection.execute(
            """INSERT INTO design_preparations(order_id, original_path, work_path, status, source_modified, work_modified, created_at, updated_at)
               VALUES(?, ?, ?, 'En edición', ?, ?, ?, ?)""",
            (order_id, original_path, work_path, source_modified, source_modified, now, now),
        )
        self.connection.commit()
        self.add_order_event(order_id, "Preparación", f"Se creó una copia de trabajo para Photoshop: {Path(original_path).name}.")
        return int(cursor.lastrowid)

    def preparation(self, preparation_id: int) -> dict | None:
        row = self.connection.execute("SELECT * FROM design_preparations WHERE id = ?", (preparation_id,)).fetchone()
        return dict(row) if row else None

    def latest_preparation(self, order_id: int, original_path: str) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM design_preparations WHERE order_id = ? AND original_path = ? AND status <> 'Descartado' ORDER BY id DESC LIMIT 1",
            (order_id, original_path),
        ).fetchone()
        return dict(row) if row else None

    def order_preparations(self, order_id: int) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM design_preparations WHERE order_id = ? ORDER BY id DESC", (order_id,)
        )
        return [dict(row) for row in rows]

    def set_preparation_status(self, preparation_id: int, status: str, note: str = "") -> None:
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        fields = "status = ?, updated_at = ?, note = ?"
        values: list[object] = [status, now, note.strip()]
        if status == "Confirmado":
            fields += ", confirmed_at = ?"
            values.append(now)
        elif status == "Descartado":
            fields += ", discarded_at = ?"
            values.append(now)
        values.append(preparation_id)
        self.connection.execute(f"UPDATE design_preparations SET {fields} WHERE id = ?", values)
        self.connection.commit()

    def refresh_preparation_file(self, preparation_id: int) -> dict | None:
        from datetime import datetime

        entry = self.preparation(preparation_id)
        if not entry:
            return None
        path = Path(entry["work_path"])
        if not path.exists():
            return entry
        modified = path.stat().st_mtime
        if modified > float(entry.get("work_modified") or 0) + 0.001 and entry["status"] == "En edición":
            now = datetime.now().isoformat(timespec="seconds")
            self.connection.execute(
                "UPDATE design_preparations SET status = 'Actualizado', work_modified = ?, updated_at = ? WHERE id = ?",
                (modified, now, preparation_id),
            )
            self.connection.commit()
            self.add_order_event(int(entry["order_id"]), "Preparación", f"Photoshop actualizó la copia de trabajo: {path.name}.")
            entry = self.preparation(preparation_id)
        return entry

    def confirm_preparation(self, preparation_id: int) -> dict:
        entry = self.refresh_preparation_file(preparation_id)
        if not entry:
            raise ValueError("No se encontró la copia de trabajo.")
        if entry["status"] not in {"Actualizado", "En edición"}:
            raise ValueError("Esta copia ya fue descartada o confirmada.")
        work_path = Path(entry["work_path"])
        if not work_path.exists():
            raise ValueError("No se encontró la copia de trabajo de Photoshop.")
        order = self.order(int(entry["order_id"])) or {}
        self.register_private_design(str(work_path), int(entry["order_id"]), str(order.get("client") or ""))
        with self.connection:
            original = self.connection.execute(
                "SELECT quantity, size_cm, rotation, status FROM order_designs WHERE order_id = ? AND image_path = ?",
                (entry["order_id"], entry["original_path"]),
            ).fetchone()
            if original:
                self.connection.execute("DELETE FROM order_designs WHERE order_id = ? AND image_path = ?", (entry["order_id"], entry["original_path"]))
                self.connection.execute(
                    """INSERT INTO order_designs(order_id, image_path, quantity, size_cm, rotation, status)
                       VALUES(?, ?, ?, ?, ?, ?) ON CONFLICT(order_id, image_path) DO UPDATE SET
                       quantity = excluded.quantity, size_cm = excluded.size_cm, rotation = excluded.rotation, status = excluded.status""",
                    (entry["order_id"], str(work_path), original["quantity"], original["size_cm"], original["rotation"], "Confirmado"),
                )
        self.set_preparation_status(preparation_id, "Confirmado")
        self.add_order_event(int(entry["order_id"]), "Preparación", f"Se confirmó la copia editada para producción: {work_path.name}.")
        return self.preparation(preparation_id) or entry

    def create_collection(self, name: str, description: str = "") -> int:
        from datetime import datetime

        self.connection.execute(
            "INSERT OR IGNORE INTO collections(name, description, created_at) VALUES(?, ?, ?)",
            (name.strip(), description.strip(), datetime.now().isoformat(timespec="seconds")),
        )
        row = self.connection.execute("SELECT id FROM collections WHERE name = ? COLLATE NOCASE", (name.strip(),)).fetchone()
        self.connection.commit()
        return int(row[0])

    def collection_names(self) -> list[str]:
        """Colecciones disponibles para filtros visuales y armado de planchas."""
        return [row[0] for row in self.connection.execute(
            "SELECT name FROM collections ORDER BY name COLLATE NOCASE"
        )]

    def set_design_library_state(self, image_path: str, reusable: bool, private: bool | None = None) -> None:
        private = (not reusable) if private is None else private
        status = "Biblioteca" if reusable else "En revisión"
        self.connection.execute(
            "UPDATE images SET is_reusable = ?, is_private = ?, import_status = ? WHERE path = ?",
            (int(reusable), int(private), status, image_path),
        )
        self.connection.commit()

    def upsert(self, image: dict) -> None:
        self.connection.execute(
            """INSERT INTO images(path, name, extension, size, modified, caption)
               VALUES(:path, :name, :extension, :size, :modified, :caption)
               ON CONFLICT(path) DO UPDATE SET
                 name=excluded.name, extension=excluded.extension, size=excluded.size,
                 modified=excluded.modified, caption=excluded.caption,
                 recognized_text=CASE
                    WHEN images.size != excluded.size OR images.modified != excluded.modified
                    THEN '' ELSE images.recognized_text END,
                 visual_score=CASE
                    WHEN images.size != excluded.size OR images.modified != excluded.modified
                    THEN -1 ELSE images.visual_score END""",
            image,
        )
        self.update_plancha_metrics(image["path"], image["modified"])
        self._refresh_sticker_search_entry(image["path"])
        self._search_cache.clear()

    def update_plancha_metrics(self, image_path: str, modified: float) -> None:
        """Registra la hitbox visible sin alterar el archivo original."""
        cached = self.connection.execute(
            "SELECT plancha_metric_modified FROM images WHERE path = ?", (image_path,)
        ).fetchone()
        if cached and float(cached[0] or -1) == float(modified):
            return
        try:
            from PIL import Image
            from app.planchas.model import visible_bbox

            with Image.open(image_path) as image:
                left, top, right, bottom = visible_bbox(image)
            width, height = max(1, right - left), max(1, bottom - top)
        except Exception:
            width = height = 1
        self.connection.execute(
            """UPDATE images SET visible_width = ?, visible_height = ?,
               visible_long_side = ?, visible_ratio = ?, plancha_metric_modified = ?
               WHERE path = ?""",
            (width, height, max(width, height), width / height, modified, image_path),
        )

    def plancha_dimensions(self, image_path: str, requested_size_cm: float) -> tuple[float, float]:
        """Calcula cm desde las métricas guardadas, sin volver a leer el PNG."""
        from app.planchas.model import size_from_visible_dimensions

        row = self.connection.execute(
            "SELECT visible_width, visible_height FROM images WHERE path = ?", (image_path,)
        ).fetchone()
        if row and row[0] and row[1]:
            return size_from_visible_dimensions(row[0], row[1], requested_size_cm)
        return 0.0, 0.0

    def remove_image(self, path: str) -> None:
        """Elimina un diseño de la biblioteca y todas sus relaciones.

        No mueve ni borra el archivo físico: esa responsabilidad queda en
        la capa de UI (que lo envía a la papelera de stickers).
        """
        with self.connection:
            if getattr(self, "_sticker_search_fts", False):
                self.connection.execute("DELETE FROM sticker_search WHERE image_path = ?", (path,))
            self.connection.execute("DELETE FROM image_tags WHERE image_path = ?", (path,))
            self.connection.execute("DELETE FROM visual_similarities WHERE query_path = ? OR candidate_path = ?", (path, path))
            self.connection.execute("DELETE FROM ai_results WHERE image_path = ?", (path,))
            self.connection.execute("DELETE FROM dismissed_ai_tags WHERE image_path = ?", (path,))
            self.connection.execute("DELETE FROM order_designs WHERE image_path = ?", (path,))
            self.connection.execute("DELETE FROM plancha_usage WHERE image_path = ?", (path,))
            self.connection.execute("DELETE FROM images WHERE path = ?", (path,))

    def commit(self) -> None:
        self.connection.commit()

    def _query_parts(self, query: str, extension: str | None = None, tags: list[str] | None = None, categories: list[str] | None = None, untagged_only: bool = False) -> tuple[str, list[str]]:
        terms = [f"%{term}%" for term in query.lower().split()]
        clauses = []
        params: list[str] = []
        if terms:
            for term in terms:
                # La búsqueda de la biblioteca se apoya en información de
                # trabajo (etiquetas, categoría, cliente y planchas), nunca
                # en el nombre técnico del archivo original.
                clauses.append(
                    "(LOWER(COALESCE(images.caption, '')) LIKE ? "
                    "OR LOWER(COALESCE(tags.name, '')) LIKE ? "
                    "OR LOWER(COALESCE(images.category, '')) LIKE ? "
                    "OR LOWER(COALESCE(images.design_client, '')) LIKE ? "
                    "OR LOWER(COALESCE(images.recognized_text, '')) LIKE ? "
                    "OR EXISTS (SELECT 1 FROM order_designs AS od "
                    "JOIN orders AS o ON o.id = od.order_id "
                    "WHERE od.image_path = images.path "
                    "AND (LOWER(COALESCE(o.client, '')) LIKE ? "
                    "OR LOWER(COALESCE(o.whatsapp, '')) LIKE ?)) "
                    "OR EXISTS (SELECT 1 FROM plancha_usage AS pu "
                    "WHERE pu.image_path = images.path "
                    "AND (LOWER(COALESCE(pu.client, '')) LIKE ? "
                    "OR LOWER(COALESCE(pu.order_number, '')) LIKE ?)))"
                )
                params.extend([term] * 9)
        if extension:
            clauses.append("images.extension = ?")
            params.append(extension)
        if tags:
            placeholders = ", ".join("?" for _ in tags)
            clauses.append(
                "images.path IN (SELECT image_tags.image_path FROM image_tags "
                "JOIN tags AS selected_tags ON selected_tags.id = image_tags.tag_id "
                f"WHERE selected_tags.name COLLATE NOCASE IN ({placeholders}) "
                "GROUP BY image_tags.image_path "
                "HAVING COUNT(DISTINCT selected_tags.id) = ?)"
            )
            params.extend(tags)
            params.append(len(tags))
        if categories:
            placeholders = ", ".join("?" for _ in categories)
            clauses.append(f"images.category IN ({placeholders})")
            params.extend(categories)
        if untagged_only:
            clauses.append("NOT EXISTS (SELECT 1 FROM image_tags WHERE image_tags.image_path = images.path)")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return where, params

    def _database_cache_version(self) -> int:
        """Versión bajo-coste del contenido de SQLite para invalidar cachés sin tocar la UI."""
        try:
            return int(self.connection.execute("PRAGMA data_version").fetchone()[0])
        except Exception:
            return 0

    def search(self, query: str = "", limit: int = 50, extension: str | None = None, tags: list[str] | None = None, categories: list[str] | None = None, random_order: bool = False, untagged_only: bool = False) -> list[dict]:
        cache_key = (
            "random" if random_order else "query",
            limit,
            extension,
            tuple(sorted((tags or []))),
            tuple(sorted((categories or []))),
            untagged_only,
            query.strip(),
            self._database_cache_version(),
        )
        cached = self._search_cache.get(cache_key)
        if cached is not None:
            return [row.copy() for row in cached]

        if query.strip() and getattr(self, "_sticker_search_fts", False) and not random_order:
            results = self._search_indexed(query, limit, extension, tags, categories, untagged_only)
            self._search_cache[cache_key] = results
            return results

        where, params = self._query_parts(query, extension, tags, categories, untagged_only)
        order = "RANDOM()" if random_order else "images.modified DESC"
        sql = "SELECT images.*, GROUP_CONCAT(tags.name, ' · ') AS tags FROM images LEFT JOIN image_tags ON image_tags.image_path = images.path LEFT JOIN tags ON tags.id = image_tags.tag_id" + where + " GROUP BY images.path ORDER BY " + order + " LIMIT ?"
        params.append(limit)
        results = [dict(row) for row in self.connection.execute(sql, params)]
        self._search_cache[cache_key] = results
        return results

    def _search_indexed(self, query: str, limit: int, extension: str | None, tags: list[str] | None, categories: list[str] | None, untagged_only: bool = False) -> list[dict]:
        """Búsqueda instantánea, con etiquetas por delante de texto secundario."""
        where, params = self._query_parts("", extension, tags, categories, untagged_only)
        sql = (
            "SELECT images.*, GROUP_CONCAT(tags.name, ' · ') AS tags, "
            "bm25(sticker_search, 1.5, 10.0, 4.0, 3.0, 2.0) AS relevance "
            "FROM sticker_search JOIN images ON images.path = sticker_search.image_path "
            "LEFT JOIN image_tags ON image_tags.image_path = images.path "
            "LEFT JOIN tags ON tags.id = image_tags.tag_id "
            "WHERE sticker_search MATCH ?" +
            (" AND " + where.removeprefix(" WHERE ") if where else "") +
            " GROUP BY images.path ORDER BY relevance ASC, images.modified DESC LIMIT ?"
        )
        try:
            results = [dict(row) for row in self.connection.execute(sql, [self._fts_query(query), *params, limit])]
            if results:
                return results
            # La corrección ortográfica solo se activa sin resultados exactos:
            # conserva la velocidad y evita que una coincidencia débil opaque
            # una etiqueta que el usuario escribió bien.
            corrected = self._fuzzy_fts_query(query)
            if not corrected:
                return []
            paths = [row[0] for row in self.connection.execute(
                "SELECT image_path FROM sticker_search WHERE sticker_search MATCH ? LIMIT ?",
                (corrected, limit),
            )]
            if not paths:
                return []
            # bm25 no es necesario en este fallback: todas las entradas ya
            # son correcciones cercanas. Reutilizamos la recuperación normal
            # para conservar tarjetas, etiquetas y orden de resultados.
            if not extension and not tags and not categories and not untagged_only:
                return self.images_by_paths(paths)
            placeholders = ", ".join("?" for _ in paths)
            filter_where, filter_params = self._query_parts("", extension, tags, categories, untagged_only)
            filtered = (
                "SELECT images.path FROM images WHERE images.path IN (" + placeholders + ")" +
                (" AND " + filter_where.removeprefix(" WHERE ") if filter_where else "")
            )
            allowed = {row[0] for row in self.connection.execute(filtered, [*paths, *filter_params])}
            return self.images_by_paths([path for path in paths if path in allowed])
        except sqlite3.OperationalError:
            where, params = self._query_parts(query, extension, tags, categories, untagged_only)
            sql = "SELECT images.*, GROUP_CONCAT(tags.name, ' · ') AS tags FROM images LEFT JOIN image_tags ON image_tags.image_path = images.path LEFT JOIN tags ON tags.id = image_tags.tag_id" + where + " GROUP BY images.path ORDER BY images.modified DESC LIMIT ?"
            return [dict(row) for row in self.connection.execute(sql, [*params, limit])]

    def _fuzzy_fts_query(self, query: str) -> str:
        """Propone palabras conocidas para una consulta sin coincidencias.

        La base se consulta únicamente en este fallback; no se carga un
        diccionario en memoria ni se agrega latencia a una búsqueda correcta.
        """
        asked = [self._normalise_search_token(token) for token in re.findall(r"[\wÀ-ÿ]+", query)]
        asked = [token for token in asked if len(token) >= 4]
        if not asked:
            return ""
        rows = self.connection.execute(
            """SELECT name FROM tags
               UNION SELECT caption FROM images WHERE caption <> ''
               UNION SELECT category FROM images WHERE category <> ''
               UNION SELECT design_client FROM images WHERE design_client <> ''
               UNION SELECT recognized_text FROM images WHERE recognized_text <> ''"""
        )
        vocabulary = {
            self._normalise_search_token(token)
            for (value,) in rows
            for token in re.findall(r"[\wÀ-ÿ]+", str(value))
            if len(token) >= 3
        }
        parts = []
        for token in asked:
            matches = difflib.get_close_matches(token, vocabulary, n=3, cutoff=0.78)
            if not matches:
                return ""
            alternatives = " OR ".join(f"{match}*" for match in matches)
            # Los paréntesis solo son necesarios cuando existen alternativas;
            # así se mantiene compatibilidad con todas las compilaciones FTS5.
            parts.append(f"({alternatives})" if len(matches) > 1 else alternatives)
        return " AND ".join(parts)

    @staticmethod
    def _normalise_search_token(value: str) -> str:
        return "".join(
            char for char in unicodedata.normalize("NFKD", value.casefold())
            if not unicodedata.combining(char)
        )

    def plancha_browser_images(
        self,
        query: str = "",
        mode: str = "Todo",
        category: str = "",
        collection: str = "",
        limit: int = 300,
        order_id: int | None = None,
    ) -> list[dict]:
        """Diseños para el selector de plancha sin mirar nombres de archivo.

        Personaje, color y etiqueta se modelan como palabras clave: así la
        búsqueda mejora con las etiquetas que el usuario va agregando y no
        obliga a crear nombres o carpetas nuevas.
        """
        term = query.strip().casefold()
        clauses: list[str] = []
        params: list[object] = []
        # El banco aporta diseños reutilizables. Desde un pedido se suman sólo
        # los diseños privados de ese pedido, nunca los de otro cliente.
        if order_id is None:
            clauses.append("images.is_reusable = 1")
        else:
            clauses.append(
                "(images.is_reusable = 1 OR EXISTS ("
                "SELECT 1 FROM order_designs AS own_design "
                "WHERE own_design.order_id = ? AND own_design.image_path = images.path))"
            )
            params.append(int(order_id))
        if category and category != "Todas las categorías":
            clauses.append("images.category = ? COLLATE NOCASE")
            params.append(category)
        if collection and collection != "Todas las colecciones":
            clauses.append(
                "EXISTS (SELECT 1 FROM image_collections AS ic "
                "JOIN collections AS c ON c.id = ic.collection_id "
                "WHERE ic.image_path = images.path AND c.name = ? COLLATE NOCASE)"
            )
            params.append(collection)
        if mode == "Favoritos comerciales":
            clauses.append("images.is_favorite = 1 AND images.is_reusable = 1")
        if term:
            if mode == "Categoría":
                clauses.append("LOWER(COALESCE(images.category, '')) LIKE ?")
                params.append(f"%{term}%")
            elif mode == "Colección":
                clauses.append(
                    "EXISTS (SELECT 1 FROM image_collections AS ic "
                    "JOIN collections AS c ON c.id = ic.collection_id "
                    "WHERE ic.image_path = images.path AND LOWER(c.name) LIKE ?)"
                )
                params.append(f"%{term}%")
            else:
                clauses.append(
                    "(LOWER(COALESCE(images.caption, '')) LIKE ? "
                    "OR LOWER(COALESCE(images.category, '')) LIKE ? "
                    "OR EXISTS (SELECT 1 FROM image_tags AS it "
                    "JOIN tags AS search_tags ON search_tags.id = it.tag_id "
                    "WHERE it.image_path = images.path AND LOWER(search_tags.name) LIKE ?))"
                )
                params.extend([f"%{term}%"] * 3)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        if mode == "Top 100":
            ordering = "COUNT(DISTINCT plancha_usage.id) DESC, images.visual_score DESC, images.modified DESC"
        elif mode == "Novedades":
            ordering = "images.modified DESC"
        else:
            ordering = "images.visual_score DESC, images.modified DESC"
        sql = (
            "SELECT images.*, GROUP_CONCAT(DISTINCT tags.name) AS tags, "
            "(SELECT GROUP_CONCAT(c.name, ' · ') FROM image_collections AS ic "
            "JOIN collections AS c ON c.id = ic.collection_id WHERE ic.image_path = images.path) AS collections "
            "FROM images "
            "LEFT JOIN image_tags ON image_tags.image_path = images.path "
            "LEFT JOIN tags ON tags.id = image_tags.tag_id "
            "LEFT JOIN plancha_usage ON plancha_usage.image_path = images.path"
            + where
            + " GROUP BY images.path ORDER BY " + ordering + " LIMIT ?"
        )
        params.append(max(1, min(int(limit), 500)))
        return [dict(row) for row in self.connection.execute(sql, params)]

    def count(self, query: str = "", extension: str | None = None, tags: list[str] | None = None, categories: list[str] | None = None, untagged_only: bool = False) -> int:
        cache_key = (
            "count",
            query.strip(),
            extension,
            tuple(sorted((tags or []))),
            tuple(sorted((categories or []))),
            untagged_only,
            self._database_cache_version(),
        )
        cached = self._count_cache.get(cache_key)
        if cached is not None:
            return cached

        if query.strip() and getattr(self, "_sticker_search_fts", False):
            where, params = self._query_parts("", extension, tags, categories, untagged_only)
            sql = "SELECT COUNT(DISTINCT images.path) FROM sticker_search JOIN images ON images.path = sticker_search.image_path WHERE sticker_search MATCH ?"
            if where:
                sql += " AND " + where.removeprefix(" WHERE ")
            try:
                value = int(self.connection.execute(sql, [self._fts_query(query), *params]).fetchone()[0])
                if value > 0:
                    self._count_cache[cache_key] = value
                    return value
            except sqlite3.OperationalError:
                pass
        where, params = self._query_parts(query, extension, tags, categories, untagged_only)
        sql = "SELECT COUNT(DISTINCT images.path) FROM images LEFT JOIN image_tags ON image_tags.image_path = images.path LEFT JOIN tags ON tags.id = image_tags.tag_id"
        value = int(self.connection.execute(sql + where, params).fetchone()[0])
        self._count_cache[cache_key] = value
        return value

    def extension_counts(self) -> list[tuple[str, int]]:
        return [tuple(row) for row in self.connection.execute(
            "SELECT extension, COUNT(*) FROM images GROUP BY extension ORDER BY COUNT(*) DESC"
        )]

    def add_tag(self, image_path: str, tag_name: str, commit: bool = True) -> None:
        name = tag_name.strip().title()
        if not name:
            raise ValueError("La etiqueta no puede estar vacía.")
        self.connection.execute("INSERT OR IGNORE INTO tags(name) VALUES(?)", (name,))
        tag_id = self.connection.execute("SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (name,)).fetchone()[0]
        self.connection.execute("INSERT OR IGNORE INTO image_tags(image_path, tag_id) VALUES(?, ?)", (image_path, tag_id))
        self._refresh_sticker_search_entry(image_path)
        if commit:
            self.connection.commit()

    def set_caption(self, image_path: str, caption: str) -> None:
        self.connection.execute("UPDATE images SET caption = ? WHERE path = ?", (caption.strip(), image_path))
        self._refresh_sticker_search_entry(image_path)
        self.connection.commit()

    def set_classification(self, image_path: str, caption: str, category: str) -> None:
        self.connection.execute(
            "UPDATE images SET caption = ?, category = ? WHERE path = ?",
            (caption.strip(), category.strip().title(), image_path),
        )
        self._refresh_sticker_search_entry(image_path)
        self.connection.commit()

    def set_image_category(self, image_path: str, category: str) -> None:
        """Actualiza solo la categoría, sin alterar el nombre interno ni etiquetas."""
        self.connection.execute(
            "UPDATE images SET category = ? WHERE path = ?",
            (category.strip().title(), image_path),
        )
        self._refresh_sticker_search_entry(image_path)
        self.connection.commit()

    @staticmethod
    def _update_native_publication_metadata(artifacts):
        """Mantiene reabribles los resultados nativos después de publicar."""
        if not artifacts.get("native_master") or not artifacts.get("metadata"):
            return
        path = Path(artifacts["metadata"])
        if not path.is_file():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        data["artifacts"] = artifacts
        data["status"] = "Confirmado"
        temporary = path.with_suffix(".publication.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def save_sticker_processing(self, result, category: str = "", tags: list[str] | None = None) -> None:
        """Persiste el proceso y sus archivos sin tocar el original."""
        import json
        from datetime import datetime

        if isinstance(result, dict):
            payload = result
        else:
            from dataclasses import asdict
            payload = asdict(result)
        now = datetime.now().isoformat(timespec="seconds")
        analysis = payload.get("analysis") or {}
        artifacts = payload.get("artifacts") or {}
        self.connection.execute(
            """INSERT INTO sticker_processing_jobs(
                   id, source_path, status, engine, analysis, quality_status, quality_notes,
                   profile, artifacts, category, tags, duplicate_path, duplicate_score,
                   created_at, updated_at
               ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   status=excluded.status, engine=excluded.engine,
                   analysis=excluded.analysis,
                   quality_status=excluded.quality_status, quality_notes=excluded.quality_notes,
                   profile=excluded.profile, artifacts=excluded.artifacts,
                   category=excluded.category, tags=excluded.tags,
                   duplicate_path=excluded.duplicate_path, duplicate_score=excluded.duplicate_score,
                   updated_at=excluded.updated_at""",
            (
                payload["job_id"], payload["source_path"], payload.get("status", "Procesado"),
                analysis.get("engine", ""), json.dumps(analysis, ensure_ascii=False),
                payload.get("quality_status", ""),
                json.dumps(payload.get("quality_notes") or [], ensure_ascii=False),
                json.dumps(payload.get("profile") or {}, ensure_ascii=False),
                json.dumps(artifacts, ensure_ascii=False), category.strip().title(),
                json.dumps(tags or [], ensure_ascii=False), payload.get("duplicate_path", ""),
                float(payload.get("duplicate_score", 0) or 0), now, now,
            ),
        )
        for kind, path in artifacts.items():
            self.connection.execute(
                "INSERT OR REPLACE INTO sticker_artifacts(job_id, kind, path) VALUES(?, ?, ?)",
                (payload["job_id"], kind, path),
            )
        self.connection.commit()

    def set_sticker_processing_status(self, job_id: str, status: str) -> None:
        from datetime import datetime

        self.connection.execute(
            "UPDATE sticker_processing_jobs SET status = ?, updated_at = ? WHERE id = ?",
            (status, datetime.now().isoformat(timespec="seconds"), job_id),
        )
        self.connection.commit()

    def discard_processed_sticker(self, job_id: str) -> bool:
        """Descarta un resultado y elimina el origen si provino del monitor automático."""
        import tempfile
        from datetime import datetime

        row = self.connection.execute(
            "SELECT source_path, analysis FROM sticker_processing_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if not row:
            return False
        try:
            analysis = json.loads(row["analysis"] or "{}")
        except (TypeError, json.JSONDecodeError):
            analysis = {}
        automatic = bool(analysis.get("auto_process"))
        artifact_paths = [
            Path(item[0]) for item in self.connection.execute(
                "SELECT path FROM sticker_artifacts WHERE job_id = ?", (job_id,)
            )
        ]

        source = Path(row["source_path"])

        # Los artefactos del monitor siempre viven bajo este directorio temporal.
        if automatic:
            auto_root = (Path(tempfile.gettempdir()) / "visionvault_auto").resolve()
            for artifact in artifact_paths:
                try:
                    relative = artifact.resolve().relative_to(auto_root)
                except (OSError, ValueError):
                    continue
                shutil.rmtree(auto_root / relative.parts[0], ignore_errors=True)

            try:
                if source.is_file():
                    source.unlink()
            except OSError:
                pass
            self.remove_image(str(source))

        # El resultado rechazado nunca debe quedar disponible como archivo
        # procesado. El original manual se conserva; solo se eliminan los
        # artefactos generados por el pipeline.
        for artifact in artifact_paths:
            try:
                if artifact != source and artifact.is_file():
                    artifact.unlink()
            except OSError:
                pass

        with self.connection:
            self.connection.execute(
                "UPDATE sticker_processing_jobs SET status = ?, artifacts = ?, updated_at = ? WHERE id = ?",
                ("Descartado", "{}", datetime.now().isoformat(timespec="seconds"), job_id),
            )
            self.connection.execute("DELETE FROM sticker_artifacts WHERE job_id = ?", (job_id,))
        return True

    def approve_processed_sticker(self, result, category: str = "", tags: list[str] | None = None) -> dict:
        """Publica el PNG aprobado en el banco y elimina sus archivos temporales."""
        from pathlib import Path

        if isinstance(result, dict):
            payload = result
        else:
            from dataclasses import asdict
            payload = asdict(result)
        artifacts = payload.get("artifacts") or {}
        master = Path(artifacts.get("master") or artifacts["print"])
        if not master.is_file():
            raise FileNotFoundError(f"No se encontró el PNG aprobado: {master}")

        # El proceso genera una carpeta temporal por sticker. El resultado
        # confirmado se publica en una carpeta común: la raíz de la biblioteca
        # elegida por el usuario o, si aún no existe, el banco del creador.
        library_root = self.get_library_root().strip()
        bank_dir = Path(library_root) if library_root else master.parent.parent / "banco"
        bank_dir.mkdir(parents=True, exist_ok=True)
        def build_candidate(sequence: int) -> Path:
            # La publicación ocurre sólo al confirmar y conserva una serie
            # numérica continua en el banco.
            return bank_dir / f"{sequence:05d}.png"

        existing_numbers = []
        for candidate in bank_dir.glob("*.png"):
            match = re.match(r"^(\d+)\.png$", candidate.name, flags=re.IGNORECASE)
            if match:
                existing_numbers.append(int(match.group(1)))

        sequence = max(existing_numbers, default=0) + 1
        approved_path = build_candidate(sequence)
        while approved_path.exists():
            sequence += 1
            approved_path = build_candidate(sequence)
        shutil.move(str(master), str(approved_path))
        approved_path = approved_path.resolve()

        # Sólo se borra una carpeta que coincida exactamente con el identificador
        # temporal generado por el pipeline; así no se puede borrar una biblioteca.
        temporary_dir = master.parent
        job_id = str(payload.get("job_id") or "")
        if master.name == "sticker_master.png" and job_id and temporary_dir.name == job_id and not artifacts.get("native_master"):
            shutil.rmtree(temporary_dir, ignore_errors=True)

        stat = approved_path.stat()
        image = {
            "path": str(approved_path),
            "name": approved_path.name,
            "extension": approved_path.suffix.lower(),
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "caption": "",
        }
        self.upsert(image)
        self.set_image_category(image["path"], category)
        for tag in tags or []:
            self.add_tag(image["path"], tag, commit=False)
        # Los resultados nativos conservan sus máscaras, geometría y trazabilidad.
        # Los trabajos legacy mantienen la publicación histórica de un solo PNG.
        published_artifacts = ({**artifacts, "master": str(approved_path)}
                               if artifacts.get("native_master") else {"master": str(approved_path)})
        self._update_native_publication_metadata(published_artifacts)
        self.connection.execute(
            "UPDATE sticker_processing_jobs SET artifacts = ? WHERE id = ?",
            (json.dumps(published_artifacts, ensure_ascii=False), payload["job_id"]),
        )
        self.connection.execute("DELETE FROM sticker_artifacts WHERE job_id = ?", (payload["job_id"],))
        self.connection.executemany(
            "INSERT INTO sticker_artifacts(job_id, kind, path) VALUES(?, ?, ?)",
            [(payload["job_id"], kind, path) for kind, path in published_artifacts.items()],
        )
        self.connection.execute(
            "UPDATE images SET is_private = 0, is_reusable = 1, import_status = 'Biblioteca' WHERE path = ?",
            (image["path"],),
        )
        self.connection.commit()
        self.set_sticker_processing_status(payload["job_id"], "Confirmado")
        return image

    def approve_processed_sticker_for_order(
        self, result, order_id: int, category: str = "", tags: list[str] | None = None,
    ) -> dict:
        """Publica un sticker sólo para un pedido, fuera de la biblioteca reutilizable."""
        from pathlib import Path

        payload = result if isinstance(result, dict) else asdict(result)
        artifacts = payload.get("artifacts") or {}
        master = Path(artifacts.get("master") or artifacts["print"])
        if not master.is_file():
            raise FileNotFoundError(f"No se encontró el PNG aprobado: {master}")
        order_id = int(order_id)
        if not self.order(order_id):
            raise ValueError(f"No existe el pedido #{order_id}.")

        # La plancha conserva una fuente privada, sin publicar el diseño en el banco.
        destination_dir = master.parent.parent.parent / "orders" / str(order_id) / "stickers"
        destination_dir.mkdir(parents=True, exist_ok=True)
        job_id = str(payload.get("job_id") or "sticker")
        destination = destination_dir / f"{job_id}.png"
        suffix = 2
        while destination.exists():
            destination = destination_dir / f"{job_id}-{suffix}.png"
            suffix += 1
        shutil.move(str(master), str(destination))
        destination = destination.resolve()

        temporary_dir = master.parent
        if master.name == "sticker_master.png" and job_id and temporary_dir.name == job_id and not artifacts.get("native_master"):
            shutil.rmtree(temporary_dir, ignore_errors=True)
        stat = destination.stat()
        image = {"path": str(destination), "name": destination.name,
                 "extension": destination.suffix.lower(), "size": stat.st_size,
                 "modified": stat.st_mtime, "caption": f"Diseño privado del pedido #{order_id}"}
        self.upsert(image)
        self.set_image_category(image["path"], category)
        for tag in tags or []:
            self.add_tag(image["path"], tag, commit=False)
        published_artifacts = ({**artifacts, "master": str(destination)}
                               if artifacts.get("native_master") else {"master": str(destination)})
        self._update_native_publication_metadata(published_artifacts)
        self.connection.execute("UPDATE sticker_processing_jobs SET artifacts = ? WHERE id = ?",
                                (json.dumps(published_artifacts, ensure_ascii=False), payload["job_id"]))
        self.connection.execute("DELETE FROM sticker_artifacts WHERE job_id = ?", (payload["job_id"],))
        self.connection.executemany("INSERT INTO sticker_artifacts(job_id, kind, path) VALUES(?, ?, ?)",
                                   [(payload["job_id"], kind, path) for kind, path in published_artifacts.items()])
        self.connection.execute("UPDATE images SET is_private = 1, is_reusable = 0, import_status = 'Pedido' WHERE path = ?",
                                (image["path"],))
        self.connection.commit()
        self.set_sticker_processing_status(payload["job_id"], "Confirmado")
        return image

    def sticker_processing_jobs(self, limit: int = 200) -> list[dict]:
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM sticker_processing_jobs ORDER BY updated_at DESC LIMIT ?", (limit,)
        )]

    def all_images(self) -> list[dict]:
        return [dict(row) for row in self.connection.execute("SELECT path, name FROM images")]

    def visual_search_images(self) -> list[dict]:
        """Datos mínimos para comparar localmente sin cargar toda la biblioteca.

        Se cachea por versión de base de datos para evitar repetir el mismo JOIN
        masivo en cada cambio de sección o cada recarga de UI.
        """
        cache_version = self._database_cache_version()
        cached = self._visual_search_cache
        if cached is not None and cached[0] == cache_version:
            return [row.copy() for row in cached[1]]

        rows = self.connection.execute(
            """SELECT images.path, images.name, images.modified, images.visual_signature,
                      images.visual_signature_modified, GROUP_CONCAT(tags.name, ' · ') AS tags
               FROM images
               LEFT JOIN image_tags ON image_tags.image_path = images.path
               LEFT JOIN tags ON tags.id = image_tags.tag_id
               GROUP BY images.path"""
        )
        results = [dict(row) for row in rows]
        self._visual_search_cache = (cache_version, results)
        return [row.copy() for row in results]

    def indexed_visual_search_images(self) -> list[dict]:
        """Devuelve firmas vigentes sin indexar durante una acción de UI.
        
        OPTIMIZACIÓN: Eliminado JOIN con tags para acelerar la consulta.
        Los tags no son necesarios para la búsqueda de duplicados rápida.
        """
        rows = self.connection.execute(
            """SELECT images.path, images.name, images.modified, images.visual_signature,
                      images.visual_signature_modified
               FROM images
               WHERE images.visual_signature IS NOT NULL AND images.visual_signature != ''
                 AND images.visual_signature_modified = images.modified
               ORDER BY images.modified DESC"""
        )
        return [dict(row) for row in rows]

    def images_missing_visual_signature(self) -> list[dict]:
        """Imágenes nuevas o modificadas que todavía no están en el índice visual."""
        rows = self.connection.execute(
            """SELECT images.path, images.modified, images.caption,
                      images.visual_signature, images.visual_signature_modified,
                      GROUP_CONCAT(tags.name, ' · ') AS tags,
                      (SELECT result FROM ai_results
                        WHERE ai_results.image_path = images.path
                          AND ai_results.modified = images.modified LIMIT 1) AS ai_result
                 FROM images
                 LEFT JOIN image_tags ON image_tags.image_path = images.path
                 LEFT JOIN tags ON tags.id = image_tags.tag_id
                WHERE images.visual_signature IS NULL OR images.visual_signature = ''
                   OR images.visual_signature_modified != images.modified
                GROUP BY images.path"""
        )
        return [self._visual_index_row(dict(row)) for row in rows]

    @staticmethod
    def _visual_index_row(row: dict) -> dict:
        values = [str(row.get("caption") or ""), str(row.get("tags") or "")]
        try:
            result = json.loads(row.get("ai_result") or "{}")
            values.extend((str(result.get("text") or ""), str(result.get("caption") or "")))
        except (TypeError, ValueError, json.JSONDecodeError, AttributeError):
            pass
        row["index_text"] = " ".join(value for value in values if value).strip()
        row["existing_embedding"] = None
        try:
            signature_is_current = (
                float(row.get("visual_signature_modified", -1))
                == float(row.get("modified", -2))
            )
            decoded_signature = json.loads(row.get("visual_signature") or "{}")
            embedding = decoded_signature.get("embedding") if signature_is_current else None
            if isinstance(embedding, list) and embedding:
                row["existing_embedding"] = embedding
        except (TypeError, ValueError, json.JSONDecodeError, AttributeError):
            pass
        return row

    def images_needing_index_migration(self, target_version: int) -> list[dict]:
        """Imágenes que necesitan migración por cambio de versión del índice visual."""
        try:
            rows = self.connection.execute(
                """SELECT images.path, images.modified, images.caption,
                          images.visual_signature, images.visual_signature_modified,
                          GROUP_CONCAT(tags.name, ' · ') AS tags,
                          (SELECT result FROM ai_results
                            WHERE ai_results.image_path = images.path
                              AND ai_results.modified = images.modified LIMIT 1) AS ai_result
                     FROM images
                     LEFT JOIN image_tags ON image_tags.image_path = images.path
                     LEFT JOIN tags ON tags.id = image_tags.tag_id
                    WHERE images.visual_signature IS NULL OR images.visual_signature = ''
                       OR images.visual_signature_modified != images.modified
                       OR json_extract(images.visual_signature, '$.index_version') IS NULL
                       OR json_extract(images.visual_signature, '$.index_version') != ?
                    GROUP BY images.path""",
                (target_version,)
            )
            return [self._visual_index_row(dict(row)) for row in rows]
        except Exception:
            # Si falla el json_extract, retornar todas las imágenes con signature
            rows = self.connection.execute(
                """SELECT path, modified, visual_signature, visual_signature_modified FROM images"""
            )
            return [self._visual_index_row(dict(row)) for row in rows]

    def set_visual_index_version(self, version: int) -> None:
        """Actualiza la versión del índice visual en la base de datos."""
        # Crear tabla de metadatos si no existe
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS visual_index_metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )"""
        )
        self.connection.execute(
            "INSERT OR REPLACE INTO visual_index_metadata (key, value) VALUES ('index_version', ?)",
            (str(version),)
        )
        self.connection.commit()

    def get_visual_index_version(self) -> int:
        """Obtiene la versión actual del índice visual."""
        try:
            row = self.connection.execute(
                "SELECT value FROM visual_index_metadata WHERE key = 'index_version'"
            ).fetchone()
            if row:
                return int(row[0])
        except Exception:
            pass
        return 1  # Default version

    def needs_visual_index_rebuild(self, target_version: int) -> bool:
        """Verifica si el índice visual necesita reconstrucción por cambio de versión."""
        current_version = self.get_visual_index_version()
        return current_version != target_version

    def mark_visual_index_rebuild_in_progress(self) -> None:
        """Marca que una reconstrucción del índice está en progreso."""
        self.connection.execute(
            "INSERT OR REPLACE INTO visual_index_metadata (key, value) VALUES ('rebuild_in_progress', '1')"
        )
        self.connection.commit()

    def clear_visual_index_rebuild_flag(self) -> None:
        """Limpia la marca de reconstrucción en progreso."""
        self.connection.execute(
            "DELETE FROM visual_index_metadata WHERE key = 'rebuild_in_progress'"
        )
        self.connection.commit()

    def is_visual_index_rebuild_in_progress(self) -> bool:
        """Verifica si hay una reconstrucción en progreso interrumpida."""
        try:
            row = self.connection.execute(
                "SELECT value FROM visual_index_metadata WHERE key = 'rebuild_in_progress'"
            ).fetchone()
            return row is not None and row[0] == '1'
        except Exception:
            return False

    def invalidate_all_visual_signatures(self) -> None:
        """Invalida todas las firmas visuales para forzar reconstrucción completa."""
        self.connection.execute(
            "UPDATE images SET visual_signature = NULL, visual_signature_modified = NULL"
        )
        self.connection.commit()

    def update_visual_signatures(self, signatures: list[tuple[str, float, str]]) -> None:
        """Persiste huellas visuales para no recalcular 5000 archivos en cada búsqueda."""
        if not signatures:
            return
        self.connection.executemany(
            "UPDATE images SET visual_signature = ?, visual_signature_modified = ? WHERE path = ?",
            signatures,
        )
        self.connection.commit()
        self._visual_search_cache = None

    def tags_for_image(self, image_path: str) -> str:
        row = self.connection.execute(
            """SELECT GROUP_CONCAT(tags.name, ' · ') FROM image_tags
               JOIN tags ON tags.id = image_tags.tag_id WHERE image_path = ?""",
            (image_path,),
        ).fetchone()
        return str(row[0] or "") if row else ""

    def cached_visual_matches(self, query_path: str, query_modified: float, limit: int = 50) -> list[tuple[str, float]]:
        rows = self.connection.execute(
            """SELECT visual_similarities.candidate_path, visual_similarities.score
               FROM visual_similarities JOIN images ON images.path = visual_similarities.candidate_path
               WHERE visual_similarities.query_path = ?
                 AND visual_similarities.query_modified = ?
                 AND visual_similarities.candidate_modified = images.modified
               ORDER BY visual_similarities.score DESC LIMIT ?""",
            (query_path, query_modified, limit),
        )
        return [(row[0], float(row[1])) for row in rows]

    def cached_visual_run(self, cache_key: str, query_path: str, query_modified: float, candidate_fingerprint: str) -> list[tuple[str, float]] | None:
        """Resultados completos reutilizables para cualquier combinación de opciones."""
        row = self.connection.execute(
            """SELECT matches_json FROM visual_search_runs
               WHERE cache_key = ? AND query_path = ? AND query_modified = ?
                 AND candidate_fingerprint = ?""",
            (cache_key, query_path, query_modified, candidate_fingerprint),
        ).fetchone()
        if not row:
            return None
        try:
            return [(str(path), float(score)) for path, score in json.loads(row[0])]
        except (TypeError, ValueError):
            return None

    def save_visual_run(self, cache_key: str, query_path: str, query_modified: float, candidate_fingerprint: str, options: dict, matches: list[tuple[str, float]]) -> None:
        from datetime import datetime

        self.connection.execute(
            """INSERT OR REPLACE INTO visual_search_runs(
                cache_key, query_path, query_modified, candidate_fingerprint,
                options_json, matches_json, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?)""",
            (cache_key, query_path, query_modified, candidate_fingerprint,
             json.dumps(options, sort_keys=True), json.dumps(matches),
             datetime.now().isoformat(timespec="seconds")),
        )
        self.connection.commit()

    def save_visual_matches(self, query_path: str, query_modified: float, matches: list[tuple[str, float]], candidate_modified: dict[str, float]) -> None:
        from datetime import datetime

        self.connection.execute("DELETE FROM visual_similarities WHERE query_path = ?", (query_path,))
        timestamp = datetime.now().isoformat(timespec="seconds")
        rows = [
            (query_path, path, score, query_modified, candidate_modified.get(path, -1), timestamp)
            for path, score in matches
        ]
        if rows:
            self.connection.executemany(
                """INSERT OR REPLACE INTO visual_similarities
                   (query_path, candidate_path, score, query_modified, candidate_modified, updated_at)
                   VALUES(?, ?, ?, ?, ?, ?)""",
                rows,
            )
        self.connection.commit()

    def images_by_paths(self, paths: list[str]) -> list[dict]:
        if not paths:
            return []
        normalized = list(dict.fromkeys(paths))
        cache_key = (self._database_cache_version(), tuple(normalized))
        cached = self._images_by_paths_cache.get(cache_key)
        if cached is not None:
            return [row.copy() for row in cached]

        placeholders = ", ".join("?" for _ in normalized)
        rows = self.connection.execute(
            "SELECT images.*, GROUP_CONCAT(tags.name, ' · ') AS tags "
            "FROM images LEFT JOIN image_tags ON image_tags.image_path = images.path "
            "LEFT JOIN tags ON tags.id = image_tags.tag_id "
            f"WHERE images.path IN ({placeholders}) GROUP BY images.path",
            normalized,
        )
        by_path = {row["path"]: dict(row) for row in rows}
        result = [by_path[path] for path in normalized if path in by_path]
        self._images_by_paths_cache[cache_key] = result
        return [row.copy() for row in result]

    def images_missing_visual_score(self) -> list[dict]:
        return [dict(row) for row in self.connection.execute("SELECT path FROM images WHERE visual_score < 0")]

    def update_visual_scores(self, scores: list[tuple[float, str]]) -> None:
        self.connection.executemany("UPDATE images SET visual_score = ? WHERE path = ?", scores)
        self.connection.commit()

    def ai_result(self, image_path: str, provider: str, model: str, modified: float) -> dict | None:
        import json

        row = self.connection.execute(
            "SELECT result FROM ai_results WHERE image_path = ? AND provider = ? AND model = ? AND modified = ?",
            (image_path, provider, model, modified),
        ).fetchone()
        try:
            return json.loads(row[0]) if row else None
        except (TypeError, json.JSONDecodeError):
            return None

    def images_needing_ai(self, provider: str, model: str) -> list[dict]:
        """Imágenes sin un análisis válido para el proveedor y modelo pedidos."""
        rows = self.connection.execute(
            """SELECT images.path, images.modified
               FROM images LEFT JOIN ai_results
                 ON ai_results.image_path = images.path
                AND ai_results.provider = ?
                AND ai_results.model = ?
               WHERE ai_results.image_path IS NULL OR ai_results.modified <> images.modified
               ORDER BY images.modified DESC""",
            (provider, model),
        )
        return [dict(row) for row in rows]

    def visual_products(self) -> list[dict]:
        """Agrupa reglas por producto para los selectores visuales."""
        grouped: dict[str, dict] = {}
        for rule in self.price_rules():
            material = str(rule.get("material") or "").strip()
            if not material:
                continue
            item = grouped.setdefault(material, {**rule, "sizes": []})
            size = str(rule.get("size") or "").strip()
            if size and size not in item["sizes"]:
                item["sizes"].append(size)
            if not item.get("image_path") and rule.get("image_path"):
                item["image_path"] = rule["image_path"]
            if float(rule.get("price") or 0) < float(item.get("price") or 0):
                item["price"] = rule["price"]
        def size_key(value: str) -> tuple[int, float, str]:
            match = re.search(r"\d+(?:[.,]\d+)?", str(value))
            if match:
                return (0, float(match.group(0).replace(",", ".")), str(value).casefold())
            return (1, 0.0, str(value).casefold())
        for item in grouped.values():
            item["sizes"].sort(key=size_key)
        return sorted(grouped.values(), key=lambda item: str(item["material"]).casefold())

    def ai_review_images(self, provider: str, model: str, limit: int = 100) -> list[dict]:
        """Analisis vigentes de disenos aun sin etiquetas, listos para revisar."""
        import json

        rows = self.connection.execute(
            """SELECT images.*, ai_results.result
               FROM images JOIN ai_results ON ai_results.image_path = images.path
               WHERE ai_results.provider = ? AND ai_results.model = ?
                 AND ai_results.modified = images.modified
                 AND NOT EXISTS (SELECT 1 FROM image_tags WHERE image_tags.image_path = images.path)
               ORDER BY images.modified DESC LIMIT ?""",
            (provider, model, limit),
        )
        items = []
        for row in rows:
            item = dict(row)
            try:
                item["ai_result"] = json.loads(item.pop("result") or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            items.append(item)
        return items

    def save_ai_result(self, image_path: str, provider: str, model: str, modified: float, result: dict) -> None:
        import json

        self.connection.execute(
            """INSERT INTO ai_results(image_path, provider, model, modified, result) VALUES(?, ?, ?, ?, ?)
               ON CONFLICT(image_path, provider, model) DO UPDATE SET modified=excluded.modified, result=excluded.result""",
            (image_path, provider, model, modified, json.dumps(result, ensure_ascii=False)),
        )
        # El OCR es información de búsqueda, no una etiqueta aprobada. Así el
        # usuario puede encontrar una palabra del diseño inmediatamente sin
        # llenar la biblioteca con etiquetas automáticas o poco confiables.
        recognized_text = " ".join(str(result.get("text") or "").split())
        self.connection.execute(
            "UPDATE images SET recognized_text = ? WHERE path = ? AND modified = ?",
            (recognized_text, image_path, modified),
        )
        self._refresh_sticker_search_entry(image_path)
        self._search_cache.clear()
        self.connection.commit()

    def dismissed_ai_tags(self, image_path: str) -> set[str]:
        rows = self.connection.execute(
            "SELECT tag FROM dismissed_ai_tags WHERE image_path = ?", (image_path,)
        )
        return {row[0].casefold() for row in rows}

    def dismiss_ai_tag(self, image_path: str, tag: str) -> None:
        cleaned = tag.strip()
        if not cleaned:
            return
        self.connection.execute(
            "INSERT OR IGNORE INTO dismissed_ai_tags(image_path, tag) VALUES(?, ?)",
            (image_path, cleaned),
        )
        self.connection.commit()

    def record_plancha_usage(self, items: list[dict]) -> None:
        from datetime import datetime

        timestamp = datetime.now().isoformat(timespec="seconds")
        rows = [
            (item["path"], item.get("client", ""), item.get("order_number", ""), max(item["width_cm"], item["height_cm"]), 1, timestamp, item.get("source", "Stock"))
            for item in items
        ]
        self.connection.executemany(
            "INSERT INTO plancha_usage(image_path, client, order_number, size_cm, quantity, used_at, source) VALUES(?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self.connection.commit()

    def plancha_stats(self, image_path: str) -> dict:
        row = self.connection.execute(
            """SELECT COUNT(*) AS times_used, COALESCE(SUM(quantity), 0) AS total_produced,
                      COUNT(DISTINCT NULLIF(client, '')) AS clients, MAX(used_at) AS last_used
               FROM plancha_usage WHERE image_path = ?""",
            (image_path,),
        ).fetchone()
        return dict(row)

    def featured_random(self, limit: int) -> list[dict]:
        pool = max(limit * 6, 300)
        sql = """SELECT images.*, GROUP_CONCAT(tags.name, ' · ') AS tags
                 FROM images LEFT JOIN image_tags ON image_tags.image_path = images.path
                 LEFT JOIN tags ON tags.id = image_tags.tag_id
                 WHERE images.path IN (
                    SELECT path FROM images ORDER BY visual_score DESC, size DESC LIMIT ?
                 )
                 GROUP BY images.path ORDER BY RANDOM() LIMIT ?"""
        return [dict(row) for row in self.connection.execute(sql, (pool, limit))]

    def fill_candidates(self, limit: int = 400) -> list[dict]:
        """Devuelve candidatos para completar planchas, con su origen visible."""
        candidates: list[dict] = []
        seen: set[str] = set()
        per_source = max(40, limit // 4)

        def append_rows(sql: str, params: tuple, origin: str, priority: int):
            rows = self.connection.execute(sql, params).fetchall()
            for row in rows:
                image = dict(row)
                if image["path"] in seen:
                    continue
                seen.add(image["path"])
                image["fill_origin"] = origin
                image["fill_priority"] = priority
                candidates.append(image)

        image_columns = "images.*, GROUP_CONCAT(tags.name, ' · ') AS tags"
        image_joins = " FROM images LEFT JOIN image_tags ON image_tags.image_path = images.path LEFT JOIN tags ON tags.id = image_tags.tag_id "
        pending_statuses = ("Nuevo", "En revisión", "Presupuesto enviado", "Esperando aprobación", "Aprobado", "En diseño", "Listo para plancha")
        placeholders = ", ".join("?" for _ in pending_statuses)
        append_rows(
            "SELECT " + image_columns + ", orders.client, orders.id AS fill_order_id" + image_joins +
            "JOIN order_designs ON order_designs.image_path = images.path "
            "JOIN orders ON orders.id = order_designs.order_id "
            f"WHERE orders.status IN ({placeholders}) GROUP BY images.path ORDER BY orders.order_date ASC LIMIT ?",
            (*pending_statuses, per_source), "Pedido pendiente", 0,
        )
        append_rows(
            "SELECT " + image_columns + image_joins +
            "JOIN image_collections ON image_collections.image_path = images.path "
            "JOIN collections ON collections.id = image_collections.collection_id "
            "WHERE collections.name = ? COLLATE NOCASE GROUP BY images.path ORDER BY images.modified DESC LIMIT ?",
            ("Completar planchas", per_source), "Colección Completar planchas", 1,
        )
        append_rows(
            "SELECT " + image_columns + image_joins +
            "LEFT JOIN plancha_usage ON plancha_usage.image_path = images.path "
            "GROUP BY images.path ORDER BY COUNT(plancha_usage.id) DESC, images.visual_score DESC LIMIT ?",
            (min(100, per_source),), "Top 100", 2,
        )
        append_rows(
            "SELECT " + image_columns + image_joins +
            "WHERE images.is_reusable = 1 GROUP BY images.path ORDER BY images.visual_score DESC, images.modified DESC LIMIT ?",
            (per_source,), "Biblioteca", 3,
        )
        # Intercala orígenes para que la evaluación de espacios compare de
        # verdad todas las fuentes, en vez de quedarse con la primera lista.
        buckets = [[item for item in candidates if item["fill_priority"] == priority] for priority in range(4)]
        mixed: list[dict] = []
        for index in range(max((len(bucket) for bucket in buckets), default=0)):
            for bucket in buckets:
                if index < len(bucket):
                    mixed.append(bucket[index])
        return mixed[:limit]

    def tag_counts(self, limit: int | None = None, query: str = "", category: str = "") -> list[tuple[str, int]]:
        clauses: list[str] = []
        params: list[str] = []
        if query.strip():
            clauses.append("LOWER(tags.name) LIKE ?")
            params.append(f"%{query.strip().lower()}%")
        if category.strip():
            clauses.append("images.category = ? COLLATE NOCASE")
            params.append(category.strip())
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = """SELECT tags.name, COUNT(DISTINCT image_tags.image_path)
                 FROM tags
                 JOIN image_tags ON image_tags.tag_id = tags.id
                 JOIN images ON images.path = image_tags.image_path""" + where + """
                 GROUP BY tags.id ORDER BY COUNT(DISTINCT image_tags.image_path) DESC, tags.name COLLATE NOCASE"""
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        return [tuple(row) for row in self.connection.execute(sql, params)]

    def tag_total(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM tags").fetchone()[0])

    def category_counts(self) -> list[tuple[str, int]]:
        return [tuple(row) for row in self.connection.execute(
            "SELECT category, COUNT(*) FROM images WHERE category <> '' GROUP BY category ORDER BY category COLLATE NOCASE"
        )]

    def clear_category(self, category: str) -> int:
        """Quita una categoría de los diseños, sin tocar sus archivos ni etiquetas."""
        cursor = self.connection.execute(
            "UPDATE images SET category = '' WHERE category = ? COLLATE NOCASE", (category.strip(),)
        )
        self.connection.commit()
        return int(cursor.rowcount)

    def rename_category(self, category: str, new_name: str) -> int:
        """Renombra o fusiona una categoria conservando todos sus disenos."""
        source = category.strip()
        target = new_name.strip().title()
        if not target:
            raise ValueError("La categoria no puede estar vacia.")
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE images SET category = ? WHERE category = ? COLLATE NOCASE",
                (target, source),
            )
        self.connection.commit()
        return int(cursor.rowcount)

    def clear_image_category(self, image_path: str) -> None:
        self.connection.execute("UPDATE images SET category = '' WHERE path = ?", (image_path,))
        self.connection.commit()

    def clear_tags(self) -> None:
        """Elimina las etiquetas y sus asociaciones, sin tocar los diseños."""
        self.connection.execute("DELETE FROM image_tags")
        self.connection.execute("DELETE FROM tags")
        self.connection.commit()

    def suggestions(self, query: str, limit: int = 6, typed: bool = False) -> list[str]:
        """Predicciones rápidas: prioriza etiquetas, incluso si son frases largas."""
        term = query.strip().lower()
        if len(term) < 2:
            return []
        like = f"%{term}%"
        rows = self.connection.execute(
            """SELECT name, MIN(priority) AS priority FROM (
                   SELECT tags.name AS name, 0 AS priority, COUNT(image_tags.image_path) AS usage
                   FROM tags JOIN image_tags ON image_tags.tag_id = tags.id
                   WHERE LOWER(tags.name) LIKE ?
                   GROUP BY tags.id
                   UNION ALL
                   SELECT images.category AS name, 1 AS priority, COUNT(*) AS usage
                   FROM images
                   WHERE images.category <> '' AND LOWER(images.category) LIKE ?
                   GROUP BY images.category COLLATE NOCASE
                   UNION ALL
                   SELECT images.caption AS name, 2 AS priority, COUNT(*) AS usage
                   FROM images
                   WHERE images.caption <> '' AND LOWER(images.caption) LIKE ?
                   GROUP BY images.caption COLLATE NOCASE
                   UNION ALL
                   SELECT images.design_client AS name, 3 AS priority, COUNT(*) AS usage
                   FROM images
                   WHERE images.design_client <> '' AND LOWER(images.design_client) LIKE ?
                   GROUP BY images.design_client COLLATE NOCASE
                   UNION ALL
                   SELECT orders.client AS name, 4 AS priority, COUNT(*) AS usage
                   FROM orders
                   WHERE orders.client <> '' AND LOWER(orders.client) LIKE ?
                   GROUP BY orders.client COLLATE NOCASE
               )
               GROUP BY name COLLATE NOCASE
               ORDER BY MIN(priority), CASE WHEN LOWER(name) LIKE ? THEN 0 ELSE 1 END,
                        MAX(usage) DESC, name COLLATE NOCASE
               LIMIT ?""",
            (like, like, like, like, like, f"{term}%", limit),
        )
        rows = list(rows)
        # SQLite LIKE no ignora tildes. El recorrido completo solo se usa
        # cuando la consulta rápida no devolvió resultados.
        if not rows:
            normalized_term = self._normalise_search_token(term)
            candidates = self.connection.execute(
                """SELECT name, priority FROM (
                       SELECT name, 0 AS priority FROM tags
                       UNION ALL SELECT category, 1 FROM images WHERE category <> ''
                       UNION ALL SELECT caption, 2 FROM images WHERE caption <> ''
                       UNION ALL SELECT design_client, 3 FROM images WHERE design_client <> ''
                       UNION ALL SELECT client, 4 FROM orders WHERE client <> ''
                   )"""
            )
            matches: dict[str, tuple[str, int]] = {}
            for name, priority in candidates:
                clean_name = str(name or "").strip()
                if not clean_name or normalized_term not in self._normalise_search_token(clean_name):
                    continue
                key = clean_name.casefold()
                existing = matches.get(key)
                if existing is None or priority < existing[1]:
                    matches[key] = (clean_name, int(priority))
            rows = sorted(matches.values(), key=lambda item: (item[1], item[0].casefold()))[:limit]
        if not typed:
            return [row[0] for row in rows]
        labels = {0: "Etiqueta", 1: "Categoría", 2: "Nombre", 3: "Cliente del diseño", 4: "Cliente"}
        return [f"{labels.get(row[1], 'Sticker')}: {row[0]}" for row in rows]

    def remove_tag(self, image_path: str, tag_name: str) -> None:
        self.connection.execute(
            "DELETE FROM image_tags WHERE image_path = ? AND tag_id = "
            "(SELECT id FROM tags WHERE name = ? COLLATE NOCASE)",
            (image_path, tag_name),
        )
        self.connection.execute("DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM image_tags)")
        self._refresh_sticker_search_entry(image_path)
        self.connection.commit()

    def remove_tag_from_images(self, image_paths: list[str], tag_name: str) -> int:
        """Quita una etiqueta de varias imagenes en una sola transaccion."""
        paths = [path for path in image_paths if path]
        if not paths:
            return 0
        tag_row = self.connection.execute(
            "SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (tag_name.strip(),)
        ).fetchone()
        if tag_row is None:
            return 0
        tag_id = tag_row[0]
        placeholders = ", ".join("?" for _ in paths)
        with self.connection:
            cursor = self.connection.execute(
                f"DELETE FROM image_tags WHERE tag_id = ? AND image_path IN ({placeholders})",
                (tag_id, *paths),
            )
            self.connection.execute("DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM image_tags)")
        for path in paths:
            self._refresh_sticker_search_entry(path)
        self.connection.commit()
        return int(cursor.rowcount)

    def record_sticker_similarity_check(
        self, job_id: str, match_path: str = "", score: float = 0.0,
        color_variant_applied: bool = False,
    ) -> None:
        """Registra la revisión diferida de similitud de un procesado."""
        from datetime import datetime

        row = self.connection.execute(
            "SELECT analysis FROM sticker_processing_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        try:
            analysis = json.loads(row[0] or "{}") if row else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            analysis = {}
        analysis["similarity_checked"] = True
        analysis["similar_design_path"] = match_path
        analysis["similar_design_score"] = round(float(score), 2)
        analysis["color_variant_applied"] = bool(color_variant_applied)
        self.connection.execute(
            """UPDATE sticker_processing_jobs
               SET analysis = ?, duplicate_path = ?, duplicate_score = ?, updated_at = ?
               WHERE id = ?""",
            (
                json.dumps(analysis, ensure_ascii=False), match_path, float(score),
                datetime.now().isoformat(timespec="seconds"), job_id,
            ),
        )
        self.connection.commit()

    def delete_tag(self, tag_name: str) -> None:
        """Elimina una etiqueta de todos los diseños, sin borrar archivos."""
        paths = [row[0] for row in self.connection.execute(
            "SELECT image_path FROM image_tags WHERE tag_id = (SELECT id FROM tags WHERE name = ? COLLATE NOCASE)",
            (tag_name,),
        )]
        self.connection.execute(
            "DELETE FROM image_tags WHERE tag_id = (SELECT id FROM tags WHERE name = ? COLLATE NOCASE)",
            (tag_name,),
        )
        self.connection.execute("DELETE FROM tags WHERE name = ? COLLATE NOCASE", (tag_name,))
        for path in paths:
            self._refresh_sticker_search_entry(path)
        self.connection.commit()

    def rename_tag(self, tag_name: str, new_name: str) -> str:
        """Renombra una etiqueta o fusiona las asociaciones con una existente."""
        source = tag_name.strip()
        target = new_name.strip().title()
        if not target:
            raise ValueError("La etiqueta no puede estar vacia.")
        source_row = self.connection.execute(
            "SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (source,)
        ).fetchone()
        if source_row is None:
            raise ValueError("La etiqueta original ya no existe.")
        source_id = source_row[0]
        target_row = self.connection.execute(
            "SELECT id, name FROM tags WHERE name = ? COLLATE NOCASE", (target,)
        ).fetchone()
        paths = [row[0] for row in self.connection.execute(
            "SELECT image_path FROM image_tags WHERE tag_id = ?", (source_id,)
        )]
        with self.connection:
            if target_row and target_row[0] != source_id:
                target_id, target = target_row
                self.connection.execute(
                    "INSERT OR IGNORE INTO image_tags(image_path, tag_id) "
                    "SELECT image_path, ? FROM image_tags WHERE tag_id = ?",
                    (target_id, source_id),
                )
                self.connection.execute("DELETE FROM image_tags WHERE tag_id = ?", (source_id,))
                self.connection.execute("DELETE FROM tags WHERE id = ?", (source_id,))
            else:
                self.connection.execute("UPDATE tags SET name = ? WHERE id = ?", (target, source_id))
        for path in paths:
            self._refresh_sticker_search_entry(path)
        self.connection.commit()
        return target

    def delete_image(self, image_path: str) -> None:
        """Elimina las referencias internas de un sticker ya borrado del disco."""
        self.connection.execute("DELETE FROM image_tags WHERE image_path = ?", (image_path,))
        self.connection.execute("DELETE FROM dismissed_ai_tags WHERE image_path = ?", (image_path,))
        self.connection.execute("DELETE FROM ai_results WHERE image_path = ?", (image_path,))
        self.connection.execute("DELETE FROM visual_similarities WHERE query_path = ? OR candidate_path = ?", (image_path, image_path))
        self.connection.execute("DELETE FROM plancha_usage WHERE image_path = ?", (image_path,))
        self.connection.execute("DELETE FROM order_designs WHERE image_path = ?", (image_path,))
        self.connection.execute("DELETE FROM image_collections WHERE image_path = ?", (image_path,))
        self.connection.execute("DELETE FROM design_preparations WHERE original_path = ?", (image_path,))
        self.connection.execute("DELETE FROM images WHERE path = ?", (image_path,))
        self.connection.execute("DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM image_tags)")
        self.connection.commit()

    def remove_missing(self) -> None:
        for row in self.connection.execute("SELECT path FROM images"):
            if not Path(row["path"]).exists():
                self.connection.execute("DELETE FROM images WHERE path = ?", (row["path"],))
        self.connection.commit()

    # Impresión directa --------------------------------------------------
    def printing_config(self) -> dict:
        import json

        default = {
            "printer_name": "", "paper": "A4", "orientation": "Vertical",
            "scale": 97.27, "quality": "Alta", "color": "Color", "copies": 1,
            "printer_profiles": {},
        }
        row = self.connection.execute(
            "SELECT setting_value FROM app_settings WHERE setting_key = 'printing_config'"
        ).fetchone()
        if not row:
            return default
        try:
            saved = json.loads(row[0])
        except (TypeError, ValueError):
            saved = {}
        config = {**default, **saved}
        profiles = config.get("printer_profiles")
        config["printer_profiles"] = profiles if isinstance(profiles, dict) else {}
        active_profile = config["printer_profiles"].get(config.get("printer_name") or "")
        if isinstance(active_profile, dict):
            config.update({key: value for key, value in active_profile.items() if key in {
                "copies", "devmode_b64", "devmode_summary",
            }})
        return config

    def save_printing_config(self, printer_name: str, preferences: dict | None = None) -> dict:
        """Guarda la impresora y el perfil fijo que usará toda la producción."""
        from datetime import datetime
        import json

        config = self.printing_config()
        selected_printer = printer_name.strip()
        preferences = preferences or {}
        # La aplicación imprime planchas A4 reales: estos valores quedan
        # protegidos aunque se restauren configuraciones antiguas o dañadas.
        config["paper"] = "A4"
        config["orientation"] = "Vertical"
        config["scale"] = 97.27
        config["quality"] = "Alta"
        config["color"] = "Color"
        # Preservar la configuración del driver (DEVMODE) y su resumen si están siendo guardadas
        # Cada impresora conserva su propio DEVMODE. Cambiar de impresora no
        # puede reemplazar ni aplicar la configuración de otra por accidente.
        profiles = dict(config.get("printer_profiles") or {})
        previous_printer = str(config.get("printer_name") or "")
        profile = dict(profiles.get(selected_printer) or {})
        if not profile and selected_printer and selected_printer == previous_printer:
            for key in ("copies", "devmode_b64", "devmode_summary"):
                if key in config:
                    profile[key] = config[key]
        for key in ("devmode_b64", "devmode_summary"):
            if key in preferences:
                profile[key] = preferences[key]
        try:
            profile["copies"] = min(99, max(1, int(preferences.get("copies", profile.get("copies", config.get("copies", 1))))))
        except (TypeError, ValueError):
            profile["copies"] = 1
        if selected_printer:
            profiles[selected_printer] = profile
        config["printer_name"] = selected_printer
        config["printer_profiles"] = profiles
        # Las claves superiores mantienen compatibilidad con los flujos
        # actuales, y siempre reflejan solo la impresora activa.
        for key in ("copies", "devmode_b64", "devmode_summary"):
            config.pop(key, None)
        config.update(profile)
        now = datetime.now().isoformat(timespec="seconds")
        self.connection.execute(
            """INSERT INTO app_settings(setting_key, setting_value, updated_at) VALUES('printing_config', ?, ?)
               ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value, updated_at = excluded.updated_at""",
            (json.dumps(config, ensure_ascii=False), now),
        )
        self.connection.commit()
        return config

    def save_plancha_project(self, order_id: int | None, name: str, material: str, project_json: str,
                             project_path: str, plancha_id: int | None = None,
                             person_name: str = "", person_phone: str = "", workspace_format: str = "a4") -> int:
        """Guarda proyecto y reservas trazables en una única transacción."""
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        if str(name).startswith("plancha_borrador"):
            name = "Plancha (Cliente)" if order_id else "Plancha Doccione"
        try:
            payload = json.loads(project_json or "{}")
            items = payload.get("items", []) if isinstance(payload, dict) else []
        except (TypeError, json.JSONDecodeError):
            items = []
        previous = None
        with self.connection:
            if plancha_id:
                previous = self.connection.execute(
                    "SELECT approval_status, order_id FROM plancha_projects WHERE id = ?", (plancha_id,)
                ).fetchone()
                self.connection.execute(
                    """UPDATE plancha_projects SET order_id = ?, name = ?, material = ?, project_json = ?,
                       project_path = ?, person_name = ?, person_phone = ?, workspace_format = ?,
                       approval_status = CASE WHEN approval_status = 'Aprobada' THEN 'Borrador' ELSE approval_status END,
                       updated_at = ? WHERE id = ?""",
                    (order_id, name, material, project_json, project_path, person_name, person_phone, workspace_format, now, plancha_id),
                )
                saved_id = int(plancha_id)
            else:
                cursor = self.connection.execute(
                    """INSERT INTO plancha_projects(order_id, name, material, project_json, project_path,
                       person_name, person_phone, workspace_format, created_at, updated_at)
                       VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (order_id, name, material, project_json, project_path, person_name, person_phone, workspace_format, now, now),
                )
                saved_id = int(cursor.lastrowid)
            self._sync_plancha_assignments(saved_id, items, now)
        if previous and previous["approval_status"] == "Aprobada" and (order_id or previous["order_id"]):
            self._sync_order_approval(int(order_id or previous["order_id"]))
        return saved_id

    def _sync_plancha_assignments(self, plancha_id: int, items: list[dict], now: str) -> None:
        """Sincroniza reservas; el llamador controla la transacción."""
        desired: dict[str, dict] = {}
        for raw in items or []:
            item = dict(raw) if isinstance(raw, dict) else {}
            item_id = str(item.get("item_id") or "").strip()
            unit_key = str(item.get("requested_unit_key") or "").strip()
            order_id = item.get("order_id")
            order_job_id = item.get("order_job_id")
            if not item_id or not unit_key or order_id is None or order_job_id is None:
                continue
            job = self.connection.execute(
                "SELECT order_id FROM order_jobs WHERE id = ?", (int(order_job_id),)
            ).fetchone()
            if not job or int(job[0]) != int(order_id):
                raise ValueError("La procedencia de un elemento no coincide con el trabajo del pedido.")
            raw_quantity = float(item.get("production_quantity", 1))
            if not math.isfinite(raw_quantity) or raw_quantity <= 0:
                raise ValueError("La cantidad productiva debe ser mayor que cero.")
            if item_id in desired:
                raise ValueError("La plancha contiene un elemento productivo repetido.")
            desired[item_id] = {
                "item_id": item_id, "requested_unit_key": unit_key,
                "order_id": int(order_id), "order_job_id": int(order_job_id),
                "order_design_line_id": str(item.get("order_design_line_id") or ""),
                "image_path": str(item.get("path") or ""),
                "copy_number": max(1, int(item.get("copy_number") or 1)),
                "unit_kind": str(item.get("production_unit_kind") or "item"),
                "quantity": raw_quantity,
            }
        existing = {
            str(row["item_id"]): dict(row)
            for row in self.connection.execute(
                "SELECT * FROM plancha_item_assignments WHERE plancha_id = ?", (int(plancha_id),)
            )
        }
        for item_id, row in existing.items():
            if item_id not in desired and row["state"] == "prepared":
                self.connection.execute(
                    "UPDATE plancha_item_assignments SET state='released',released_at=?,updated_at=? WHERE id=?",
                    (now, now, row["id"]),
                )
        for item_id, item in desired.items():
            previous = existing.get(item_id)
            if previous and previous["state"] in {"printed", "finished"}:
                if previous["requested_unit_key"] != item["requested_unit_key"]:
                    raise ValueError("Un elemento ya impreso no puede cambiar de unidad solicitada.")
                continue
            conflict = self.connection.execute(
                """SELECT plancha_id FROM plancha_item_assignments
                   WHERE requested_unit_key=? AND state<>'released' AND plancha_id<>? LIMIT 1""",
                (item["requested_unit_key"], int(plancha_id)),
            ).fetchone()
            if conflict:
                raise ValueError(
                    f"La unidad {item['copy_number']} ya está preparada en la plancha #{int(conflict[0])}."
                )
            if previous:
                self.connection.execute(
                    """UPDATE plancha_item_assignments SET requested_unit_key=?,order_id=?,order_job_id=?,order_design_line_id=?,
                       image_path=?,copy_number=?,unit_kind=?,quantity=?,state='prepared',released_at='',updated_at=?
                       WHERE id=?""",
                    (item["requested_unit_key"], item["order_id"], item["order_job_id"], item["order_design_line_id"], item["image_path"],
                     item["copy_number"], item["unit_kind"], item["quantity"], now, previous["id"]),
                )
            else:
                self.connection.execute(
                    """INSERT INTO plancha_item_assignments(
                       plancha_id,item_id,requested_unit_key,order_id,order_job_id,order_design_line_id,image_path,copy_number,
                       unit_kind,quantity,state,prepared_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,'prepared',?,?)""",
                    (int(plancha_id), item_id, item["requested_unit_key"], item["order_id"],
                     item["order_job_id"], item["order_design_line_id"], item["image_path"], item["copy_number"], item["unit_kind"],
                     item["quantity"], now, now),
                )

    def plancha_assignments(self, plancha_id: int, *, include_released: bool = False) -> list[dict]:
        sql = "SELECT * FROM plancha_item_assignments WHERE plancha_id=?"
        if not include_released:
            sql += " AND state<>'released'"
        sql += " ORDER BY id"
        return [dict(row) for row in self.connection.execute(sql, (int(plancha_id),))]

    def plancha_order_ids(self, plancha_id: int) -> list[int]:
        rows = self.connection.execute(
            """SELECT DISTINCT order_id FROM plancha_item_assignments
               WHERE plancha_id=? AND state<>'released' ORDER BY order_id""", (int(plancha_id),)
        )
        values = [int(row[0]) for row in rows]
        if values:
            return values
        legacy = self.plancha_project(plancha_id)
        return [int(legacy["order_id"])] if legacy and legacy.get("order_id") else []

    def confirm_plancha_printed_assignments(self, plancha_id: int) -> int:
        """Confirma salida física; enviar al driver no llama a este método."""
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE plancha_item_assignments SET state='printed',printed_at=?,updated_at=?
                   WHERE plancha_id=? AND state='prepared'""", (now, now, int(plancha_id)),
            )
        return int(cursor.rowcount)

    def confirm_plancha_finished_assignments(self, plancha_id: int, item_ids: list[str] | None = None) -> int:
        """Confirma terminación parcial e idempotente sólo sobre unidades impresas."""
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        params: list[object] = [now, now, int(plancha_id)]
        sql = """UPDATE plancha_item_assignments SET state='finished',finished_at=?,updated_at=?
                 WHERE plancha_id=? AND state='printed'"""
        if item_ids is not None:
            clean = sorted({str(value) for value in item_ids if str(value)})
            if not clean:
                return 0
            sql += " AND item_id IN (" + ",".join("?" for _ in clean) + ")"
            params.extend(clean)
        with self.connection:
            cursor = self.connection.execute(sql, params)
        return int(cursor.rowcount)

    def order_job_production_quantities(self, order_job_id: int) -> dict:
        job = self.connection.execute(
            "SELECT id,order_id,quantity,title,material,size FROM order_jobs WHERE id=?", (int(order_job_id),)
        ).fetchone()
        if not job:
            raise ValueError("Trabajo no encontrado.")
        requested = max(0.0, float(job["quantity"] or 0))
        rows = self.connection.execute(
            """SELECT state,COALESCE(SUM(quantity),0) AS total FROM plancha_item_assignments
               WHERE order_job_id=? AND state<>'released' GROUP BY state""", (int(order_job_id),)
        )
        totals = {str(row["state"]): float(row["total"] or 0) for row in rows}
        prepared = totals.get("prepared", 0.0)
        printed = totals.get("printed", 0.0)
        finished = totals.get("finished", 0.0)
        linked_designs = int(self.connection.execute(
            """SELECT
                 (SELECT COUNT(*) FROM order_designs WHERE order_job_id=?) +
                 (SELECT COUNT(*) FROM order_design_job_links WHERE order_job_id=?)""",
            (int(order_job_id), int(order_job_id)),
        ).fetchone()[0])
        traced = prepared + printed + finished
        return {
            "order_job_id": int(order_job_id), "requested": requested,
            "unprepared": max(0.0, requested - traced),
            "prepared_unprinted": prepared, "printed_unfinished": printed,
            "finished": finished, "pending_finish": max(0.0, requested - finished),
            "traceability": "configured" if linked_designs or traced else "untracked",
        }

    def available_requested_copy_numbers(
        self, *, order_id: int, order_job_id: int, image_path: str,
        nominal_size_cm: float, rotation: int, requested_quantity: int,
        design_line_id: str = "",
    ) -> list[int]:
        """Devuelve sólo unidades todavía no reservadas ni producidas."""
        from app.planchas.model import requested_unit_key
        active = {
            str(row[0]) for row in self.connection.execute(
                "SELECT requested_unit_key FROM plancha_item_assignments WHERE state<>'released'"
            )
        }
        legacy_copy_numbers: set[int] = set()
        if design_line_id:
            matching_lines = int(self.connection.execute(
                """SELECT COUNT(*) FROM order_design_demand_lines
                   WHERE order_job_id=? AND LOWER(REPLACE(image_path,'\\','/'))=LOWER(REPLACE(?,'\\','/'))""",
                (int(order_job_id), image_path),
            ).fetchone()[0] or 0)
            legacy_rows = self.connection.execute(
                """SELECT copy_number FROM plancha_item_assignments
                   WHERE order_job_id=? AND COALESCE(order_design_line_id,'')=''
                     AND LOWER(REPLACE(image_path,'\\','/'))=LOWER(REPLACE(?,'\\','/'))
                     AND state<>'released'""",
                (int(order_job_id), image_path),
            ).fetchall()
            if legacy_rows and matching_lines != 1:
                raise ValueError("Historial v1 ambiguo: resolvé la correspondencia antes de preparar una tanda.")
            legacy_copy_numbers = {max(1, int(row[0] or 1)) for row in legacy_rows}
        return [
            copy_number for copy_number in range(1, max(0, int(requested_quantity)) + 1)
            if copy_number not in legacy_copy_numbers and requested_unit_key(
                int(order_id), int(order_job_id), image_path,
                float(nominal_size_cm), int(rotation), copy_number,
                design_line_id=design_line_id,
            ) not in active
        ]

    def plancha_project(self, plancha_id: int) -> dict | None:
        row = self.connection.execute("SELECT * FROM plancha_projects WHERE id = ?", (plancha_id,)).fetchone()
        return dict(row) if row else None

    def link_plancha_to_order(self, plancha_id: int, order_id: int) -> bool:
        """Vincula una plancha guardada a un pedido existente."""
        from datetime import datetime

        plancha_id, order_id = int(plancha_id), int(order_id)
        if not self.plancha_project(plancha_id):
            raise ValueError("No se encontró la plancha guardada.")
        order = self.order(order_id)
        if not order:
            raise ValueError("No se encontró el pedido indicado.")
        now = datetime.now().isoformat(timespec="seconds")
        self.connection.execute(
            """UPDATE plancha_projects
               SET order_id = ?, material = CASE WHEN material = '' THEN ? ELSE material END,
                   updated_at = ?
               WHERE id = ?""",
            (order_id, order.get("material") or "", now, plancha_id),
        )
        self.connection.commit()
        return True

    def plancha_by_project_path(self, project_path: str) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM plancha_projects WHERE project_path = ? ORDER BY id DESC LIMIT 1", (project_path,)
        ).fetchone()
        return dict(row) if row else None

    def delete_plancha_project(self, plancha_id: int) -> bool:
        """Elimina una plancha y sus registros de producción asociados.

        No borra los archivos del proyecto ni los PNG del disco; así se evita
        eliminar material que pueda ser necesario recuperar manualmente.
        """
        plancha_id = int(plancha_id)
        if not self.plancha_project(plancha_id):
            return False

        try:
            with self.connection:
                produced = self.connection.execute(
                    """SELECT 1 FROM plancha_item_assignments
                       WHERE plancha_id=? AND state IN ('printed','finished') LIMIT 1""", (plancha_id,),
                ).fetchone()
                printed_history = self.connection.execute(
                    """SELECT 1 FROM print_history
                       WHERE plancha_id=? AND status='Impresa' LIMIT 1""", (plancha_id,),
                ).fetchone()
                if produced or printed_history:
                    raise RuntimeError("La plancha tiene producción registrada y debe conservarse como historial.")
                if self.connection.execute("SELECT 1 FROM production_batch_planchas WHERE plancha_id=?", (plancha_id,)).fetchone():
                    raise RuntimeError("La plancha pertenece a una tanda; cancelá la tanda para conservar su trazabilidad.")
                self.connection.execute("DELETE FROM plancha_item_assignments WHERE plancha_id = ?", (plancha_id,))
                self.connection.execute("DELETE FROM order_previews WHERE plancha_id = ?", (plancha_id,))
                self.connection.execute("DELETE FROM print_history WHERE plancha_id = ?", (plancha_id,))
                self.connection.execute("DELETE FROM print_jobs WHERE plancha_id = ?", (plancha_id,))
                self.connection.execute("DELETE FROM plancha_projects WHERE id = ?", (plancha_id,))
        except sqlite3.Error as error:
            raise RuntimeError(f"No se pudo eliminar la plancha: {error}") from error
        return True

    def set_plancha_final_png(self, plancha_id: int, final_png_path: str) -> None:
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        self.connection.execute(
            """UPDATE plancha_projects SET final_png_path = ?, print_status = 'Lista para imprimir',
               print_error = '', print_updated_at = ?,
               production_status = CASE WHEN production_status = 'borrador' THEN 'guardada' ELSE production_status END,
               updated_at = ? WHERE id = ?""",
            (final_png_path, now, now, plancha_id),
        )
        self.connection.commit()
        self._sync_order_printing(plancha_id)

    # Aprobación de planchas --------------------------------------------
    def request_plancha_approval(self, plancha_id: int, preview_path: str, note: str = "") -> None:
        """Deja la aprobación a decisión explícita del usuario/cliente."""
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        self.connection.execute(
            """UPDATE plancha_projects SET approval_status = 'Enviada', approval_preview_path = ?,
               approval_requested_at = ?, approval_decision_at = '', approval_note = ?, updated_at = ? WHERE id = ?""",
            (preview_path, now, note.strip(), now, plancha_id),
        )
        self.connection.commit()
        plancha = self.plancha_project(plancha_id) or {}
        if plancha.get("order_id"):
            order_id = int(plancha["order_id"])
            self.update_order_status(order_id, "Esperando aprobación")
            self.add_order_event(order_id, "Aprobación", f"Se solicitó aprobación para la plancha «{plancha.get('name', plancha_id)}».", {"plancha_id": plancha_id, "preview": preview_path})

    def decide_plancha_approval(self, plancha_id: int, approved: bool, note: str = "") -> None:
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        status = "Aprobada" if approved else "Cambios solicitados"
        self.connection.execute(
            """UPDATE plancha_projects SET approval_status = ?, approval_decision_at = ?,
               approval_note = ?, updated_at = ? WHERE id = ?""",
            (status, now, note.strip(), now, plancha_id),
        )
        self.connection.commit()
        plancha = self.plancha_project(plancha_id) or {}
        if plancha.get("order_id"):
            order_id = int(plancha["order_id"])
            self.add_order_event(order_id, "Aprobación", f"Plancha «{plancha.get('name', plancha_id)}»: {status.lower()}." + (f" {note.strip()}" if note.strip() else ""), {"plancha_id": plancha_id, "approved": approved})
            self._sync_order_approval(order_id)

    def order_planchas(self, order_id: int) -> list[dict]:
        rows = self.connection.execute(
            """SELECT DISTINCT pp.* FROM plancha_projects pp
               LEFT JOIN plancha_item_assignments pia
                 ON pia.plancha_id=pp.id AND pia.state<>'released'
               WHERE pp.order_id=? OR pia.order_id=?
               ORDER BY pp.updated_at DESC, pp.id DESC""", (order_id, order_id)
        )
        return [dict(row) for row in rows]

    # Producción: consulta de planchas para el módulo Producción --------
    def production_planchas(self) -> list[dict]:
        """Todas las planchas guardadas con datos del pedido, para la tabla de Producción."""
        rows = self.connection.execute(
            """SELECT pp.*,
                      COALESCE(NULLIF(pp.person_name, ''), clients.name, o.client, '') AS order_client,
                      COALESCE(o.delivery_date, '') AS delivery_date,
                      COALESCE(o.print_priority, 0) AS print_priority,
                      COALESCE(o.whatsapp, '') AS order_whatsapp,
                      (SELECT COUNT(*) FROM print_jobs pj WHERE pj.plancha_id = pp.id) AS total_jobs,
                      (SELECT COUNT(*) FROM print_jobs pj WHERE pj.plancha_id = pp.id
                       AND pj.status = 'Impresa') AS printed_jobs,
                      (SELECT GROUP_CONCAT(DISTINCT pia.order_id)
                         FROM plancha_item_assignments pia
                        WHERE pia.plancha_id=pp.id AND pia.state<>'released') AS represented_order_ids,
                      (SELECT GROUP_CONCAT(DISTINCT COALESCE(c2.name,o2.client,'') )
                         FROM plancha_item_assignments pia2
                         JOIN orders o2 ON o2.id=pia2.order_id
                         LEFT JOIN clients c2 ON c2.id=o2.client_id
                        WHERE pia2.plancha_id=pp.id AND pia2.state<>'released') AS represented_clients
               FROM plancha_projects pp
               LEFT JOIN orders o ON o.id = pp.order_id
               LEFT JOIN clients ON clients.id = o.client_id
               ORDER BY pp.updated_at DESC, pp.id DESC"""
        )
        return [dict(row) for row in rows]

    def production_planchas_by_status(self, status: str) -> list[dict]:
        """Planchas filtradas por production_status."""
        rows = self.connection.execute(
            """SELECT pp.*,
                      COALESCE(NULLIF(pp.person_name, ''), clients.name, o.client, '') AS order_client,
                      COALESCE(o.delivery_date, '') AS delivery_date,
                      COALESCE(o.print_priority, 0) AS print_priority,
                      COALESCE(o.whatsapp, '') AS order_whatsapp,
                      (SELECT COUNT(*) FROM print_jobs pj WHERE pj.plancha_id = pp.id) AS total_jobs,
                      (SELECT COUNT(*) FROM print_jobs pj WHERE pj.plancha_id = pp.id
                       AND pj.status = 'Impresa') AS printed_jobs,
                      (SELECT GROUP_CONCAT(DISTINCT pia.order_id)
                         FROM plancha_item_assignments pia
                        WHERE pia.plancha_id=pp.id AND pia.state<>'released') AS represented_order_ids,
                      (SELECT GROUP_CONCAT(DISTINCT COALESCE(c2.name,o2.client,''))
                         FROM plancha_item_assignments pia2
                         JOIN orders o2 ON o2.id=pia2.order_id
                         LEFT JOIN clients c2 ON c2.id=o2.client_id
                        WHERE pia2.plancha_id=pp.id AND pia2.state<>'released') AS represented_clients
               FROM plancha_projects pp
               LEFT JOIN orders o ON o.id = pp.order_id
               LEFT JOIN clients ON clients.id = o.client_id
               WHERE pp.production_status = ?
               ORDER BY pp.updated_at DESC, pp.id DESC""",
            (status,),
        )
        return [dict(row) for row in rows]

    def update_plancha_production_status(self, plancha_id: int, status: str) -> None:
        """Actualiza el estado de producción de una plancha."""
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        self.connection.execute(
            "UPDATE plancha_projects SET production_status = ?, updated_at = ? WHERE id = ?",
            (status, now, plancha_id),
        )
        self.connection.commit()
        try:
            project = self.plancha_project(plancha_id)
            order_id = project.get("order_id") if project else None
            if status == "impresa":
                self.event_repo.publish_event(
                    event_type="production.completed",
                    priority="normal",
                    title="Producción terminada",
                    message=f"Plancha #{plancha_id} lista para entregar" + (f" · Pedido #{order_id}" if order_id else ""),
                    entity_type="plancha",
                    entity_id=plancha_id,
                    payload={"order_id": order_id},
                )
            elif status == "error":
                self.event_repo.publish_event(
                    event_type="production.error",
                    priority="high",
                    title="Error de producción",
                    message=f"Plancha #{plancha_id}" + (f" · Pedido #{order_id}" if order_id else ""),
                    entity_type="plancha",
                    entity_id=plancha_id,
                    payload={"order_id": order_id},
                )
        except Exception:
            pass

    def save_plancha_status_before_continuous(self, plancha_id: int) -> None:
        """Guarda el production_status actual en previous_production_status antes de marcar usada_en_continua."""
        from datetime import datetime

        project = self.plancha_project(plancha_id)
        if not project:
            return
        current = project.get("production_status") or ""
        self.connection.execute(
            "UPDATE plancha_projects SET previous_production_status = ?, updated_at = ? WHERE id = ?",
            (current, datetime.now().isoformat(timespec="seconds"), plancha_id),
        )
        self.connection.commit()

    def restore_plancha_status_after_continuous(self, plancha_id: int) -> str:
        """Restaura el production_status desde previous_production_status al quitar de tira continua. Devuelve el estado restaurado."""
        from datetime import datetime
        project = self.plancha_project(plancha_id)
        if not project:
            return "lista"
        prev = (project.get("previous_production_status") or "").strip()
        has_png = bool((project.get("final_png_path") or "").strip())
        # Si no había estado previo guardado, derivar uno lógico
        if not prev:
            prev = "lista" if has_png else "guardada"
        now = datetime.now().isoformat(timespec="seconds")
        self.connection.execute(
            """UPDATE plancha_projects
               SET production_status = ?, continuous_confirmed = 0,
                   previous_production_status = '', updated_at = ?
               WHERE id = ?""",
            (prev, now, plancha_id),
        )
        self.connection.commit()
        return prev

    # Vista previa para cliente ------------------------------------------

    def save_client_preview(self, plancha_id: int, path: str, bg_type: str, bg_value: str = "") -> None:
        """Guarda la ruta y configuración de la vista previa para cliente."""
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        self.connection.execute(
            """UPDATE plancha_projects
               SET client_preview_path = ?, client_preview_bg_type = ?,
                   client_preview_bg_value = ?, client_preview_updated_at = ?, updated_at = ?
               WHERE id = ?""",
            (path.strip(), bg_type, bg_value, now, now, plancha_id),
        )
        self.connection.commit()

    def client_preview_config(self, plancha_id: int) -> dict:
        """Devuelve la configuración actual de la vista cliente para una plancha."""
        project = self.plancha_project(plancha_id)
        if not project:
            return {}
        return {
            "path": project.get("client_preview_path") or "",
            "bg_type": project.get("client_preview_bg_type") or "",
            "bg_value": project.get("client_preview_bg_value") or "",
            "updated_at": project.get("client_preview_updated_at") or "",
        }

    def set_plancha_usuario(self, plancha_id: int, usuario: str) -> None:
        """Registra quién creó/modificó la plancha."""
        self.connection.execute(
            "UPDATE plancha_projects SET usuario = ? WHERE id = ?",
            (usuario.strip(), plancha_id),
        )
        self.connection.commit()

    def increment_plancha_print_count(self, plancha_id: int, success: bool) -> None:
        """Incrementa print_count o error_count según resultado de impresión."""
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        if success:
            self.connection.execute(
                """UPDATE plancha_projects SET print_count = print_count + 1,
                   last_printed_at = ?, updated_at = ? WHERE id = ?""",
                (now, now, plancha_id),
            )
        else:
            self.connection.execute(
                "UPDATE plancha_projects SET error_count = error_count + 1, updated_at = ? WHERE id = ?",
                (now, plancha_id),
            )
        self.connection.commit()

    # Produccion continua ------------------------------------------------
    def available_planchas_for_continuous(self) -> list[dict]:
        """Planchas confirmadas con PNG final que pueden combinarse en una tira."""
        rows = self.connection.execute(
            """SELECT plancha_projects.*, orders.client AS order_client,
                      orders.material AS order_material, orders.status AS order_status
               FROM plancha_projects
               LEFT JOIN orders ON orders.id = plancha_projects.order_id
               WHERE COALESCE(plancha_projects.final_png_path, '') <> ''
                 AND COALESCE(plancha_projects.production_status, '') = 'lista'
                 AND COALESCE(plancha_projects.continuous_confirmed, 0) = 1
                 AND COALESCE(plancha_projects.production_status, 'lista') <> 'usada_en_continua'
               ORDER BY plancha_projects.updated_at DESC, plancha_projects.id DESC"""
        )
        return [dict(row) for row in rows]

    def confirm_plancha_for_continuous(self, plancha_id: int) -> None:
        """Marca una A4 verificada para que pueda entrar a impresión continua."""
        self.connection.execute(
            "UPDATE plancha_projects SET continuous_confirmed = 1, production_status = 'lista' WHERE id = ?", (plancha_id,),
        )
        self.connection.commit()
        self._sync_order_printing(plancha_id)

    def release_plancha_from_continuous(self, plancha_id: int) -> bool:
        """Quita una plancha de tiras pendientes y libera su reserva.

        Sirve para recuperar una plancha marcada como usada cuando la tira no
        está abierta en pantalla. No afecta trabajos ya enviados a imprimir.
        """
        from datetime import datetime
        import json

        plancha_id = int(plancha_id)
        changed = False
        now = datetime.now().isoformat(timespec="seconds")
        with self.connection:
            records = self.connection.execute(
                "SELECT id, production_json FROM continuous_productions WHERE status = 'Pendiente'"
            ).fetchall()
            for record in records:
                try:
                    data = json.loads(record["production_json"] or "{}")
                    sections = list(data.get("sections") or [])
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                remaining = [section for section in sections if int(section.get("plancha_id") or 0) != plancha_id]
                if len(remaining) == len(sections):
                    continue
                changed = True
                if remaining:
                    data["sections"] = remaining
                    self.connection.execute(
                        "UPDATE continuous_productions SET production_json = ?, updated_at = ? WHERE id = ?",
                        (json.dumps(data, ensure_ascii=False), now, int(record["id"])),
                    )
                else:
                    self.connection.execute("DELETE FROM continuous_productions WHERE id = ?", (int(record["id"]),))
            if changed:
                self.connection.execute(
                    """UPDATE plancha_projects
                       SET production_status = CASE
                               WHEN COALESCE(previous_production_status, '') <> '' THEN previous_production_status
                               WHEN COALESCE(final_png_path, '') <> '' THEN 'lista'
                               ELSE 'guardada' END,
                           continuous_confirmed = 0, previous_production_status = '', updated_at = ?
                       WHERE id = ?""",
                    (now, plancha_id),
                )
        return changed

    def delete_continuous_production(self, production_id: int) -> None:
        """Elimina una tira pendiente que quedó sin secciones."""
        self.connection.execute("DELETE FROM continuous_productions WHERE id = ?", (int(production_id),))
        self.connection.commit()

    def save_continuous_production(
        self, name: str, mode: str, width_cm: float, length_cm: float,
        material: str, production_json: str, production_id: int | None = None,
    ) -> int:
        """Guarda una tira pendiente como referencias ordenadas a planchas A4."""
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        if production_id:
            self.connection.execute(
                """UPDATE continuous_productions SET name = ?, mode = ?, width_cm = ?, length_cm = ?,
                   material = ?, production_json = ?, status = 'Pendiente', updated_at = ? WHERE id = ?""",
                (name.strip() or "Producción continua", mode, float(width_cm), float(length_cm), material.strip(), production_json, now, production_id),
            )
            self.connection.commit()
            return int(production_id)
        cursor = self.connection.execute(
            """INSERT INTO continuous_productions(name, mode, width_cm, length_cm, material,
               status, production_json, created_at, updated_at)
               VALUES(?, ?, ?, ?, ?, 'Pendiente', ?, ?, ?)""",
            (name.strip() or "Producción continua", mode, float(width_cm), float(length_cm), material.strip(), production_json, now, now),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def continuous_production(self, production_id: int) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM continuous_productions WHERE id = ?", (production_id,)
        ).fetchone()
        return dict(row) if row else None

    def continuous_productions(self) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM continuous_productions ORDER BY updated_at DESC, id DESC"
        )
        return [dict(row) for row in rows]

    def mark_continuous_production_print_submitted(self, production_id: int) -> None:
        """Registra que la tira fue entregada a la cola, sin marcarla como impresa."""
        from datetime import datetime

        self.connection.execute(
            "UPDATE continuous_productions SET status = 'Enviada a impresión', updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(timespec="seconds"), production_id),
        )
        self.connection.commit()

    def _sync_order_approval(self, order_id: int) -> None:
        """Un pedido solo pasa a Aprobado cuando todas sus planchas lo están."""
        from datetime import datetime

        counts = self.connection.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN approval_status = 'Aprobada' THEN 1 ELSE 0 END) AS approved,
                      SUM(CASE WHEN approval_status = 'Cambios solicitados' THEN 1 ELSE 0 END) AS changes
               FROM plancha_projects WHERE order_id = ?""",
            (order_id,),
        ).fetchone()
        total, approved, changes = int(counts["total"] or 0), int(counts["approved"] or 0), int(counts["changes"] or 0)
        if total and approved == total:
            status = "Aprobado"
        elif changes:
            status = "En diseño"
        else:
            status = "Esperando aprobación"
        self.connection.execute(
            "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
            (status, datetime.now().isoformat(timespec="seconds"), order_id),
        )
        self.connection.commit()

    def set_plancha_print_status(self, plancha_id: int, status: str, error: str = "") -> None:
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        self.connection.execute(
            "UPDATE plancha_projects SET print_status = ?, print_error = ?, print_updated_at = ?, updated_at = ? WHERE id = ?",
            (status, error, now, now, plancha_id),
        )
        self.connection.commit()
        self._sync_order_printing(plancha_id)

    def _sync_order_printing(self, plancha_id: int) -> None:
        from datetime import datetime

        row = self.connection.execute("SELECT order_id FROM plancha_projects WHERE id = ?", (plancha_id,)).fetchone()
        if not row or not row[0]:
            return
        order_id = int(row[0])
        counts = self.connection.execute(
            """SELECT COUNT(*) AS total, SUM(CASE WHEN print_status = 'Impresa' THEN 1 ELSE 0 END) AS printed,
                      SUM(CASE WHEN print_status IN ('Enviando a impresora', 'En cola') THEN 1 ELSE 0 END) AS queued
               FROM plancha_projects WHERE order_id = ?""",
            (order_id,),
        ).fetchone()
        total, printed, queued = int(counts["total"] or 0), int(counts["printed"] or 0), int(counts["queued"] or 0)
        state = "Impresa" if total and printed == total else ("En cola" if queued else "No lista")
        self.connection.execute(
            "UPDATE orders SET print_status = ?, printed_planchas = ?, total_planchas = ?, updated_at = ? WHERE id = ?",
            (state, printed, total, datetime.now().isoformat(timespec="seconds"), order_id),
        )
        self.connection.commit()

    def create_print_job(self, plancha_id: int, user_name: str, printer_name: str, configuration: dict,
                         copies: int, final_png_path: str, parent_job_id: int | None = None) -> int:
        from datetime import datetime
        import json

        project = self.plancha_project(plancha_id)
        if not project:
            raise ValueError("La plancha no está guardada.")
        if project.get("production_status") == "Cancelada":
            raise ValueError("La plancha fue retirada de una tanda cancelada y no puede imprimirse.")
        order = self.order(int(project["order_id"])) if project.get("order_id") else None
        priority = max(0, int((order or {}).get("print_priority", 0) or 0))
        delivery_date = (order or {}).get("delivery_date", "") or ""
        now = datetime.now().isoformat(timespec="seconds")
        cursor = self.connection.execute(
            """INSERT INTO print_jobs(plancha_id, order_id, parent_job_id, user_name, printer_name,
               configuration_json, copies, priority, delivery_date, final_png_path, status, created_at, updated_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pendiente', ?, ?)""",
            (plancha_id, project.get("order_id"), parent_job_id, user_name, printer_name,
             json.dumps(configuration, ensure_ascii=False), max(1, int(copies)), priority, delivery_date, final_png_path, now, now),
        )
        job_id = int(cursor.lastrowid)
        self.connection.execute(
            """INSERT INTO print_history(print_job_id, plancha_id, order_id, user_name, printer_name,
               configuration_json, copies, status, message, final_png_path, created_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, 'Pendiente', '', ?, ?)""",
            (job_id, plancha_id, project.get("order_id"), user_name, printer_name,
             json.dumps(configuration, ensure_ascii=False), max(1, int(copies)), final_png_path, now),
        )
        self.connection.commit()
        self.set_plancha_print_status(plancha_id, "Lista para imprimir")
        # Actualizar estado de producción y usuario si falta
        self.connection.execute(
            """UPDATE plancha_projects SET production_status = 'en_cola',
               usuario = CASE WHEN TRIM(COALESCE(usuario, '')) = '' THEN ? ELSE usuario END,
               updated_at = ? WHERE id = ?""",
            (user_name, now, plancha_id),
        )
        self.connection.commit()
        return job_id

    def print_job(self, job_id: int) -> dict | None:
        row = self.connection.execute("SELECT * FROM print_jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def next_print_job(self) -> dict | None:
        row = self.connection.execute(
            """SELECT * FROM print_jobs WHERE status = 'Pendiente'
               ORDER BY priority DESC,
                        CASE WHEN NULLIF(delivery_date, '') IS NULL THEN '9999-12-31' ELSE delivery_date END,
                        created_at, id LIMIT 1"""
        ).fetchone()
        return dict(row) if row else None

    def print_queue(self) -> list[dict]:
        rows = self.connection.execute(
            """SELECT print_jobs.*, plancha_projects.name AS plancha_name, orders.client AS client, orders.material
               FROM print_jobs LEFT JOIN plancha_projects ON plancha_projects.id = print_jobs.plancha_id
               LEFT JOIN orders ON orders.id = print_jobs.order_id
               WHERE print_jobs.status IN ('Pendiente', 'Enviando a impresora', 'En cola', 'Error de impresión')
               ORDER BY print_jobs.priority DESC, print_jobs.created_at, print_jobs.id"""
        )
        return [dict(row) for row in rows]

    def latest_print_job(self, plancha_id: int, statuses: tuple[str, ...] | None = None) -> dict | None:
        sql = "SELECT * FROM print_jobs WHERE plancha_id = ?"
        params: list[object] = [plancha_id]
        if statuses:
            sql += " AND status IN (" + ", ".join("?" for _ in statuses) + ")"
            params.extend(statuses)
        sql += " ORDER BY id DESC LIMIT 1"
        row = self.connection.execute(sql, params).fetchone()
        return dict(row) if row else None

    def print_queue_counts(self) -> dict:
        rows = self.connection.execute(
            "SELECT status, COUNT(*) AS total FROM print_jobs WHERE status IN ('Pendiente', 'Enviando a impresora', 'En cola', 'Impresa', 'Error de impresión') GROUP BY status"
        )
        counts = {"Pendiente": 0, "Enviando a impresora": 0, "En cola": 0, "Impresa": 0, "Error de impresión": 0}
        counts.update({row["status"]: int(row["total"]) for row in rows})
        return counts

    def update_print_job(self, job_id: int, status: str, message: str = "", spool_job_id: int | None = None) -> None:
        from datetime import datetime
        import json

        job = self.print_job(job_id)
        if not job:
            return
        prev_status = job.get("status", "")
        now = datetime.now().isoformat(timespec="seconds")
        printed_at = now if status == "Impresa" else job.get("printed_at", "")
        self.connection.execute(
            """UPDATE print_jobs SET status = ?, error_message = ?, spool_job_id = COALESCE(?, spool_job_id),
               updated_at = ?, printed_at = ? WHERE id = ?""",
            (status, message, spool_job_id, now, printed_at, job_id),
        )
        self.connection.execute(
            """INSERT INTO print_history(print_job_id, plancha_id, order_id, user_name, printer_name,
               configuration_json, copies, status, message, final_png_path, created_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, job["plancha_id"], job.get("order_id"), job.get("user_name", ""), job["printer_name"],
             job["configuration_json"], job["copies"], status, message, job["final_png_path"], now),
        )
        self.connection.commit()
        self.set_plancha_print_status(job["plancha_id"], status, message)
        # Sincronizar production_status y contadores SOLO si el estado realmente cambió
        if status == "Impresa" and prev_status != "Impresa":
            # Sólo la confirmación física existente mueve las unidades. El
            # envío al spool queda en "En cola" y no acredita producción.
            self.confirm_plancha_printed_assignments(job["plancha_id"])
            self.increment_plancha_print_count(job["plancha_id"], success=True)
            current = self.plancha_project(job["plancha_id"]) or {}
            if current.get("production_status") not in {"usada_en_continua"}:
                self.update_plancha_production_status(job["plancha_id"], "impresa")
        elif status == "Error de impresión" and prev_status != "Error de impresión":
            self.increment_plancha_print_count(job["plancha_id"], success=False)

    def cancel_print_job(self, job_id: int, message: str = "Cancelada por el usuario.") -> dict | None:
        job = self.print_job(job_id)
        if not job:
            return None
        self.update_print_job(job_id, "Cancelada", message)
        return self.print_job(job_id)

    def print_history(self, plancha_id: int) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM print_history WHERE plancha_id = ? ORDER BY created_at DESC, id DESC", (plancha_id,)
        )
        return [dict(row) for row in rows]

    @property
    def connection(self) -> sqlite3.Connection:
        if not hasattr(self._thread_connections, 'conn'):
            self._thread_connections.conn = self._create_connection()
        return self._thread_connections.conn

    def close(self) -> None:
        self.connection.close()

    # Biblioteca activa ----------------------------------------------------
    def get_library_root(self) -> str:
        """Obtiene la carpeta raíz de la biblioteca activa."""
        return self.app_setting("library_root", "")

    def save_library_root(self, folder: str) -> None:
        """Guarda la carpeta raíz de la biblioteca activa."""
        self.save_app_setting("library_root", folder)

    def import_and_number_external_library_images(self) -> list[dict]:
        """Number and index images added directly to the active library folder."""
        from app.indexer.scanner import IMAGE_EXTENSIONS

        root_value = self.get_library_root().strip()
        if not root_value:
            return []
        library_root = Path(root_value)
        if not library_root.is_dir():
            return []

        images = [
            path for path in library_root.iterdir()
            if path.is_file()
            and path.suffix.lower() in IMAGE_EXTENSIONS
            and not path.name.startswith((".", "~"))
        ]
        numbered = [path for path in images if re.fullmatch(r"\d+", path.stem)]
        unnumbered = sorted(
            (path for path in images if not re.fullmatch(r"\d+", path.stem)),
            key=lambda path: (path.stat().st_mtime, path.name.casefold()),
        )
        if not unnumbered:
            return []

        occupied = {int(path.stem) for path in numbered}
        occupied_stems = {path.stem for path in images}
        width = max(5, *(len(path.stem) for path in numbered)) if numbered else 5
        next_number = max(occupied, default=0) + 1
        imported = []

        for source in unnumbered:
            while next_number in occupied:
                next_number += 1
            destination = library_root / f"{next_number:0{width}d}{source.suffix.lower()}"
            # A sequence number is unique even if another image has a different extension.
            while destination.stem in occupied_stems:
                next_number += 1
                destination = library_root / f"{next_number:0{width}d}{source.suffix.lower()}"

            old_path = str(source.resolve())
            try:
                source.rename(destination)
            except OSError:
                # Another app may still be writing this file; retry next startup.
                continue

            destination = destination.resolve()
            new_path = str(destination)
            stat = destination.stat()
            with self.connection:
                # Preserve metadata if the file was indexed by the watcher first.
                for table in (
                    "image_tags", "ai_results", "dismissed_ai_tags",
                    "plancha_usage", "order_designs", "image_collections",
                    "sticker_search",
                ):
                    self.connection.execute(
                        f"UPDATE {table} SET image_path = ? WHERE image_path = ?",
                        (new_path, old_path),
                    )
                self.connection.execute(
                    "UPDATE visual_similarities SET query_path = ? WHERE query_path = ?",
                    (new_path, old_path),
                )
                self.connection.execute(
                    "UPDATE visual_similarities SET candidate_path = ? WHERE candidate_path = ?",
                    (new_path, old_path),
                )
                self.connection.execute(
                    "UPDATE images SET path = ?, name = ?, extension = ?, size = ?, modified = ? WHERE path = ?",
                    (new_path, destination.name, destination.suffix.lower(), stat.st_size, stat.st_mtime, old_path),
                )
                self.upsert({
                    "path": new_path,
                    "name": destination.name,
                    "extension": destination.suffix.lower(),
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                    "caption": "Agregado desde otra aplicacion",
                })
                self.connection.execute(
                    "UPDATE images SET is_private = 0, is_reusable = 1, import_status = 'Biblioteca' WHERE path = ?",
                    (new_path,),
                )
            self._refresh_sticker_search_entry(new_path)
            imported.append({"path": new_path, "name": destination.name})
            occupied.add(next_number)
            occupied_stems.discard(source.stem)
            occupied_stems.add(destination.stem)
            next_number += 1

        return imported

    def backup_database(self) -> str:
        """Crea una copia consistente, incluyendo cambios que aún estén en WAL."""
        return str(self.maintenance.create_backup("manual"))

    def remove_images_outside_folder(self, folder: str) -> dict:
        """Elimina todos los registros de imágenes fuera de la carpeta especificada.
        
        No borra archivos físicos, solo registros de la base de datos.
        Retorna un diccionario con estadísticas de eliminación.
        """
        folder_path = Path(folder).resolve()
        stats = {
            "images_removed": 0,
            "tags_removed": 0,
            "similarities_removed": 0,
            "ai_results_removed": 0,
            "dismissed_tags_removed": 0,
            "order_designs_removed": 0,
            "plancha_usage_removed": 0,
        }
        
        # Obtener todas las rutas de imágenes fuera de la carpeta
        rows = self.connection.execute("SELECT path FROM images").fetchall()
        paths_to_remove = []
        
        for row in rows:
            img_path = Path(row["path"])
            try:
                if not img_path.resolve().is_relative_to(folder_path):
                    paths_to_remove.append(row["path"])
            except (ValueError, OSError):
                # Si no se puede resolver la ruta, asumir que está fuera
                paths_to_remove.append(row["path"])
        
        # Eliminar registros para cada imagen fuera de la carpeta
        for path in paths_to_remove:
            with self.connection:
                # Contar antes de eliminar
                stats["tags_removed"] += self.connection.execute(
                    "SELECT COUNT(*) FROM image_tags WHERE image_path = ?", (path,)
                ).fetchone()[0]
                stats["similarities_removed"] += self.connection.execute(
                    "SELECT COUNT(*) FROM visual_similarities WHERE query_path = ? OR candidate_path = ?", (path, path)
                ).fetchone()[0]
                stats["ai_results_removed"] += self.connection.execute(
                    "SELECT COUNT(*) FROM ai_results WHERE image_path = ?", (path,)
                ).fetchone()[0]
                stats["dismissed_tags_removed"] += self.connection.execute(
                    "SELECT COUNT(*) FROM dismissed_ai_tags WHERE image_path = ?", (path,)
                ).fetchone()[0]
                stats["order_designs_removed"] += self.connection.execute(
                    "SELECT COUNT(*) FROM order_designs WHERE image_path = ?", (path,)
                ).fetchone()[0]
                stats["plancha_usage_removed"] += self.connection.execute(
                    "SELECT COUNT(*) FROM plancha_usage WHERE image_path = ?", (path,)
                ).fetchone()[0]
                
                # Eliminar registros
                self.connection.execute("DELETE FROM image_tags WHERE image_path = ?", (path,))
                self.connection.execute("DELETE FROM visual_similarities WHERE query_path = ? OR candidate_path = ?", (path, path))
                self.connection.execute("DELETE FROM ai_results WHERE image_path = ?", (path,))
                self.connection.execute("DELETE FROM dismissed_ai_tags WHERE image_path = ?", (path,))
                self.connection.execute("DELETE FROM order_designs WHERE image_path = ?", (path,))
                self.connection.execute("DELETE FROM plancha_usage WHERE image_path = ?", (path,))
                self.connection.execute("DELETE FROM images WHERE path = ?", (path,))
                
                stats["images_removed"] += 1
        
        # Limpiar etiquetas huérfanas
        self.connection.execute("DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM image_tags)")
        
        self.commit()
        return stats
