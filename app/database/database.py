import json
import sqlite3
from pathlib import Path
from decimal import Decimal

from costos.models.cost_component import CostComponent
from costos.models.cost_condition import CostCondition
from costos.models.cost_rule import CostRule
from costos.models.variable_cost_component import VariableCostComponent
from costos.models.variable_cost_model import VariableCostModel, build_product_key
from costos.services.cost_calculator import CostCalculator
from costos.services.variable_cost_calculator import VariableCostCalculator


DOCCIONE_PRICE_CATALOG_KEY = "precio_catalogo_doccione_2026_07_15"
MANUAL_PRIORITY_VALUES = {"Sin prisa": 0, "Baja": 1, "Media": 2, "Alta": 3, "Urgente": 4}


def _manual_priority_value(value) -> int:
    if isinstance(value, str) and value.strip() in MANUAL_PRIORITY_VALUES:
        return MANUAL_PRIORITY_VALUES[value.strip()]
    try:
        return min(4, max(0, int(value or 0)))
    except (TypeError, ValueError):
        return 0

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
    ("Plancha A4 - Diseño Único", "A4", 1, 5000, "fijo", 1, "Plancha personalizada"),
    ("Plancha A4 - Vinilos Especiales", "A4", 1, 7000, "fijo", 1, "Plancha personalizada"),
)


class ImageDatabase:
    def __init__(self, db_path: str | Path = "visionvault.db"):
        # Diagnóstico desactivado - la información se guarda en diagnostic_db_path.log si es necesaria
        # TEMP LOG: print effective DB path and metadata for diagnostics
        # try:
        #     from datetime import datetime
        #
        #     eff = Path(db_path).resolve()
        #     exists = eff.exists()
        #     size = eff.stat().st_size if exists else 0
        #     mtime = datetime.fromtimestamp(eff.stat().st_mtime).isoformat(timespec="seconds") if exists else ""
        # except Exception:
        #     eff = Path(db_path)
        #     exists = False
        #     size = 0
        #     mtime = ""
        # print("=====================================")
        # print("DATABASE PATH")
        # print("=====================================")
        # print("Ruta absoluta:")
        # print(str(eff))
        # print()
        # print("Existe:")
        # print(str(bool(exists)))
        # print()
        # print("Tamaño:")
        # print(str(size))
        # print()
        # print("Última modificación:")
        # print(str(mtime))
        # print()
        # print("=====================================")
        #
        # # Also write the same block to a deterministic log file for retrieval
        # try:
        #     log_path = Path(__file__).resolve().parents[2] / 'diagnostic_db_path.log'
        #     with open(log_path, 'w', encoding='utf-8') as fh:
        #         fh.write('=====================================\n')
        #         fh.write('DATABASE PATH\n')
        #         fh.write('=====================================\n')
        #         fh.write('Ruta absoluta:\n')
        #         fh.write(str(eff) + '\n\n')
        #         fh.write('Existe:\n')
        #         fh.write(str(bool(exists)) + '\n\n')
        #         fh.write('Tamaño:\n')
        #         fh.write(str(size) + '\n\n')
        #         fh.write('Última modificación:\n')
        #         fh.write(str(mtime) + '\n\n')
        #         fh.write('=====================================\n')
        # except Exception:
        #     pass

        self.connection = sqlite3.connect(db_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS images (
                path TEXT PRIMARY KEY, name TEXT NOT NULL, extension TEXT NOT NULL,
                size INTEGER NOT NULL, modified REAL NOT NULL, caption TEXT DEFAULT ''
            )"""
        )
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(images)")}
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
            # Presupuesto: se guardan valores simples y trazables. La regla de
            # precio, si se usa, solo propone un importe; nunca reemplaza uno
            # confirmado por el usuario.
            ("discount_percent", "REAL DEFAULT 0"),
            ("extra_services", "TEXT DEFAULT ''"),
            ("budget_total", "REAL DEFAULT 0"),
            ("paid_amount", "REAL DEFAULT 0"),
            ("payment_status", "TEXT DEFAULT 'Pendiente'"),
            ("assigned_to", "TEXT DEFAULT ''"),
            # Costos desglosados — sincronizados desde order_jobs
            ("cost_mp",    "REAL DEFAULT 0"),   # Materia Prima
            ("cost_mo",    "REAL DEFAULT 0"),   # Mano de Obra
            ("cost_cf",    "REAL DEFAULT 0"),   # Carga Fabril
            ("cost_total", "REAL DEFAULT 0"),   # M.P + M.O + C.F
            ("margin",     "REAL DEFAULT 0"),   # budget_total − cost_total
        ):
            if column not in order_columns:
                self.connection.execute(f"ALTER TABLE orders ADD COLUMN {column} {definition}")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(order_date DESC)")
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
        ):
            if column not in order_job_columns:
                self.connection.execute(f"ALTER TABLE order_jobs ADD COLUMN {column} {definition}")
        
        # Tabla de reglas de costos — permite calcular M.P, M.O y C.F de forma independiente
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS cost_rules (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
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
                size_cm REAL DEFAULT 5.9, rotation INTEGER DEFAULT 0,
                PRIMARY KEY(order_id, image_path),
                FOREIGN KEY(order_id) REFERENCES orders(id)
            )"""
        )
        design_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(order_designs)")}
        if "status" not in design_columns:
            self.connection.execute("ALTER TABLE order_designs ADD COLUMN status TEXT DEFAULT 'Pendiente'")
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
                pack_quantity INTEGER DEFAULT 1, catalog_key TEXT DEFAULT ''
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
        ):
            if column not in plancha_columns:
                self.connection.execute(f"ALTER TABLE plancha_projects ADD COLUMN {column} {definition}")
        # Migración: asignar production_status basado en el estado actual
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

        # --- Sistema de eventos y notificaciones push ---
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS app_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_uuid TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'normal',
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                entity_type TEXT,
                entity_id INTEGER,
                payload_json TEXT,
                created_at TEXT NOT NULL,
                processed INTEGER NOT NULL DEFAULT 0
            )"""
        )
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_app_events_type ON app_events(event_type, created_at DESC)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_app_events_processed ON app_events(processed, created_at DESC)")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS notification_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_uuid TEXT NOT NULL,
                channel TEXT NOT NULL DEFAULT 'push',
                recipient_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                next_attempt_at TEXT,
                sent_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(event_uuid) REFERENCES app_events(event_uuid)
            )"""
        )
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_outbox_status ON notification_outbox(status, next_attempt_at)")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS mobile_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                device_name TEXT,
                platform TEXT NOT NULL,
                push_token TEXT NOT NULL UNIQUE,
                active INTEGER NOT NULL DEFAULT 1,
                last_seen_at TEXT,
                created_at TEXT NOT NULL
            )"""
        )
        self.connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_mobile_devices_token ON mobile_devices(push_token)")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS device_notification_prefs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(device_id) REFERENCES mobile_devices(id),
                UNIQUE(device_id, event_type)
            )"""
        )
        # Códigos de emparejamiento temporales (uso único, expiran en 5 min, almacenados como hash)
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS pairing_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code_hash TEXT NOT NULL UNIQUE,
                installation_id TEXT NOT NULL DEFAULT 'studio-principal',
                used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )"""
        )
        # Historial de etapas de producción para auditoría
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS production_stage_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                order_id INTEGER NOT NULL,
                old_stage TEXT,
                new_stage TEXT NOT NULL,
                device_id INTEGER,
                device_name TEXT,
                operator_name TEXT,
                source TEXT NOT NULL DEFAULT 'mobile',
                notes TEXT DEFAULT '',
                changed_at TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES order_jobs(id),
                FOREIGN KEY(order_id) REFERENCES orders(id),
                FOREIGN KEY(device_id) REFERENCES mobile_devices(id)
            )"""
        )
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_production_history_job ON production_stage_history(job_id, changed_at DESC)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_production_history_order ON production_stage_history(order_id, changed_at DESC)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_production_history_device ON production_stage_history(device_id, changed_at DESC)")
        # Idempotencia del outbox: evitar mensajes duplicados al mismo dispositivo
        self.connection.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_outbox_event_device
               ON notification_outbox(event_uuid, recipient_id, channel)"""
        )
        
        # ── Migraciones de esquema (ejecutar antes de crear EventRepository) ──
        self._migrate_order_clients()
        self._migrate_order_jobs()
        self._migrate_mobile_devices()
        self._migrate_pairing_codes()
        self._migrate_sync_indexes()
        self.install_doccione_price_catalog()
        self.connection.commit()

        # ── Crear EventRepository después de todas las migraciones ──
        from app.events.event_repository import EventRepository
        self.event_repo = EventRepository(self.connection)

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

        title = str(job.get("title", "") or "").strip() or f"Producto {position + 1}"
        return {
            "id": job.get("id"), "title": title,
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
        }

    def _write_order_jobs(self, order_id: int, jobs: list[dict], now: str) -> list[dict]:
        """Reemplaza el detalle dentro de la transacción que guarda el pedido."""
        clean_jobs = [self._clean_order_job(job, position) for position, job in enumerate(jobs)]
        if not clean_jobs:
            clean_jobs = [self._clean_order_job({}, 0)]
        self.connection.execute("DELETE FROM order_jobs WHERE order_id = ?", (order_id,))
        for job in clean_jobs:
            self.connection.execute(
                """INSERT INTO order_jobs(order_id, title, material, size, quantity, subtotal,
                   discount_percent, extra_services, status, notes, sort_order,
                   cost_mp, cost_mo, cost_cf, cost_total,
                   created_at, updated_at)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    order_id, job["title"], job["material"], job["size"], job["quantity"],
                    job["subtotal"], job["discount_percent"], job["extra_services"],
                    job["status"], job["notes"], job["sort_order"],
                    job["cost_mp"], job["cost_mo"], job["cost_cf"], job["cost_total"],
                    now, now,
                ),
            )
        return clean_jobs

    def _sync_order_from_jobs(self, order_id: int, now: str) -> None:
        """Actualiza el resumen compatible del pedido desde sus trabajos."""
        rows = [dict(row) for row in self.connection.execute(
            "SELECT * FROM order_jobs WHERE order_id = ? ORDER BY sort_order, id", (order_id,)
        )]
        if not rows:
            return
        subtotal     = round(sum(float(job.get("subtotal") or 0) for job in rows), 2)
        total        = round(sum(float(job.get("subtotal") or 0) * (1 - float(job.get("discount_percent") or 0) / 100) for job in rows), 2)
        total_quantity = sum(max(1, int(job.get("quantity") or 1)) for job in rows)
        # Costos desglosados — suma de todos los trabajos
        cost_mp    = round(sum(float(job.get("cost_mp")    or 0) for job in rows), 2)
        cost_mo    = round(sum(float(job.get("cost_mo")    or 0) for job in rows), 2)
        cost_cf    = round(sum(float(job.get("cost_cf")    or 0) for job in rows), 2)
        cost_total = round(cost_mp + cost_mo + cost_cf, 2)
        margin     = round(total - cost_total, 2)
        one_job    = len(rows) == 1
        material   = rows[0].get("material", "") if one_job else f"{len(rows)} trabajos"
        size       = rows[0].get("size", "")     if one_job else "Varios"
        services   = rows[0].get("extra_services", "") if one_job else ""
        self.connection.execute(
            """UPDATE orders SET material = ?, size = ?, quantity = ?, price = ?,
               discount_percent = 0, extra_services = ?, budget_total = ?,
               cost_mp = ?, cost_mo = ?, cost_cf = ?, cost_total = ?, margin = ?,
               updated_at = ?
               WHERE id = ?""",
            (material, size, total_quantity, subtotal, services, total,
             cost_mp, cost_mo, cost_cf, cost_total, margin,
             now, order_id),
        )

    def _migrate_order_jobs(self) -> None:
        """Los pedidos creados antes del detalle se conservan como un único trabajo."""
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        rows = self.connection.execute(
            """SELECT orders.* FROM orders
               LEFT JOIN order_jobs ON order_jobs.order_id = orders.id
               WHERE order_jobs.id IS NULL"""
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
                   quantity, price, discount_percent, extra_services, budget_total, assigned_to,
                   observations, pending_reason, delivery_date, print_priority, order_concept,
                   order_description, created_at, updated_at, last_autosave_at)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    client, whatsapp, client_id, final_order_date, values.get("status", "Nuevo"),
                    first["material"], first["size"], first["quantity"], first["subtotal"],
                    first["discount_percent"], first["extra_services"], 0, values.get("assigned_to", ""),
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
        self.add_order_event(order_id, "Pedido", f"Pedido creado con {len(jobs)} trabajo(s).")
        try:
            total = sum(float(j.get("subtotal", 0) or 0) * (1 - float(j.get("discount_percent", 0) or 0) / 100) for j in jobs)
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
        # Verificar columnas existentes
        existing_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(mobile_devices)")}
        
        # Agregar columnas faltantes de forma idempotente
        # SQLite no permite agregar columnas UNIQUE con ALTER TABLE, así que agregamos sin UNIQUE
        for column, definition in (
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

    def _migrate_pairing_codes(self) -> None:
        """Migra pairing_codes de código en texto plano a hash SHA-256."""
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

    def orders(self, status: str | None = None, query: str = "", pending_only: bool = False) -> list[dict]:
        """Devuelve la lista operativa sin tocar precios ni otros módulos."""
        sql = """
            SELECT orders.*, COALESCE(clients.name, orders.client) AS client_name,
                   COALESCE(clients.client_type, 'Particular') AS client_type,
                   COALESCE(metrics.design_count, 0) AS design_count,
                   COALESCE(metrics.assigned_quantity, 0) AS assigned_quantity,
                   COALESCE(metrics.confirmed_count, 0) AS confirmed_count,
                   COALESCE(plancha_counts.total, 0) AS plancha_count
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
        """
        clauses: list[str] = ["COALESCE(orders.is_archived, 0) = 0"]
        params: list[str] = []
        if status:
            clauses.append("orders.status = ?")
            params.append(status)
        if pending_only:
            clauses.append("(TRIM(COALESCE(orders.pending_reason, '')) <> '' OR orders.status = 'Pendiente')")
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

    def update_order_status(self, order_id: int, status: str) -> None:
        from datetime import datetime

        self.connection.execute(
            "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
            (status, datetime.now().isoformat(timespec="seconds"), order_id),
        )
        self.connection.commit()
        self.add_order_event(order_id, "Estado", f"Estado actualizado a: {status}.")

    def archive_order(self, order_id: int) -> None:
        """Marca el pedido como Archivado sin eliminar ningún dato."""
        self.update_order_status(order_id, "Archivado")

    def delete_order(self, order_id: int) -> None:
        """Elimina permanentemente el pedido y todos sus registros relacionados."""
        from datetime import datetime
        with self.connection:
            for table in (
                "order_events", "order_payments", "order_designs",
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
        """Guarda una recuperaciÃ³n inmediata antes del autoguardado definitivo."""
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
        """Actualiza ficha y diseÃ±os en una sola operaciÃ³n reversible desde la UI."""
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        client = str(values.get("client", "")).strip()
        if not client:
            raise ValueError("IndicÃ¡ el cliente del pedido.")
        whatsapp = str(values.get("whatsapp", "")).strip()
        client_id = self._ensure_client(client, whatsapp, now)
        quantity = max(0, int(values.get("quantity", 0) or 0))
        try:
            print_priority = _manual_priority_value(values.get("print_priority", 0))
        except (TypeError, ValueError):
            print_priority = 0
        status = str(values.get("status", "Nuevo") or "Nuevo")
        try:
            price = max(0.0, float(str(values.get("price", 0) or 0).replace(",", ".")))
        except (TypeError, ValueError):
            price = 0.0
        try:
            discount_percent = min(100.0, max(0.0, float(str(values.get("discount_percent", 0) or 0).replace(",", "."))))
        except (TypeError, ValueError):
            discount_percent = 0.0
        budget_total = round(price * (1 - discount_percent / 100), 2)
        with self.connection:
            self.connection.execute(
                """UPDATE orders SET client = ?, whatsapp = ?, client_id = ?,
                   status = ?, material = ?, size = ?, quantity = ?, price = ?, discount_percent = ?,
                   extra_services = ?, budget_total = ?, assigned_to = ?, observations = ?,
                   pending_reason = ?, delivery_date = ?, print_priority = ?, order_date = ?,
                   order_concept = ?, order_description = ?, last_autosave_at = ?, updated_at = ? WHERE id = ?""",
                (
                    client, whatsapp, client_id,
                    status, str(values.get("material", "")).strip(), str(values.get("size", "")).strip(),
                    quantity, price, discount_percent, str(values.get("extra_services", "")).strip(),
                    budget_total, str(values.get("assigned_to", "")).strip(), str(values.get("observations", "")).strip(),
                    str(values.get("pending_reason", "")).strip(), str(values.get("delivery_date", "")).strip(),
                    print_priority, str(values.get("order_date", "") or "").strip(),
                    str(values.get("order_concept", "") or "").strip(),
                    str(values.get("order_description", "") or "").strip(),
                    now, now, order_id,
                ),
            )
            self.connection.execute("DELETE FROM order_designs WHERE order_id = ?", (order_id,))
            for design in designs:
                path = str(design.get("image_path", "")).strip()
                if not path:
                    continue
                self.connection.execute(
                    """INSERT INTO order_designs(order_id, image_path, quantity, size_cm, rotation, status)
                       VALUES(?, ?, ?, ?, ?, ?)""",
                    (
                        order_id, path, max(1, int(design.get("quantity", 1) or 1)),
                        float(design.get("size_cm", 5.9) or 5.9), int(design.get("rotation", 0) or 0),
                        str(design.get("status", "Pendiente") or "Pendiente"),
                    ),
                )
                self.connection.execute("UPDATE images SET design_order_id = ? WHERE path = ?", (order_id, path))
            if jobs is not None:
                self._write_order_jobs(order_id, jobs, now)
                self._sync_order_from_jobs(order_id, now)
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

    def link_design_to_order(self, order_id: int, image_path: str, quantity: int = 1, size_cm: float = 5.9, rotation: int = 0, status: str = "Pendiente") -> None:
        self.connection.execute(
            """INSERT INTO order_designs(order_id, image_path, quantity, size_cm, rotation, status)
               VALUES(?, ?, ?, ?, ?, ?) ON CONFLICT(order_id, image_path) DO UPDATE SET
               quantity=excluded.quantity, size_cm=excluded.size_cm, rotation=excluded.rotation, status=excluded.status""",
            (order_id, image_path, quantity, size_cm, rotation, status),
        )
        self.connection.execute("UPDATE images SET design_order_id = ? WHERE path = ?", (order_id, image_path))
        self.connection.commit()

    def order_designs(self, order_id: int) -> list[dict]:
        rows = self.connection.execute(
            """SELECT order_designs.*, images.name, images.tags, images.category
               FROM order_designs JOIN (
                    SELECT images.path, images.name, images.category,
                           GROUP_CONCAT(tags.name, ' · ') AS tags
                    FROM images LEFT JOIN image_tags ON image_tags.image_path = images.path
                    LEFT JOIN tags ON tags.id = image_tags.tag_id
                    GROUP BY images.path
               ) AS images ON images.path = order_designs.image_path
               WHERE order_designs.order_id = ? ORDER BY images.name COLLATE NOCASE""",
            (order_id,),
        )
        return [dict(row) for row in rows]

    def order_jobs(self, order_id: int) -> list[dict]:
        """Detalle de trabajos de un pedido, ordenado como lo ve el usuario."""
        rows = self.connection.execute(
            "SELECT * FROM order_jobs WHERE order_id = ? ORDER BY sort_order, id", (order_id,)
        )
        return [dict(row) for row in rows]

    def replace_order_jobs(self, order_id: int, jobs: list[dict]) -> list[dict]:
        """Guarda el listado completo de trabajos y actualiza el resumen del pedido."""
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        with self.connection:
            saved = self._write_order_jobs(order_id, jobs, now)
            self._sync_order_from_jobs(order_id, now)
        self.add_order_event(order_id, "Trabajos", f"Se actualizaron {len(saved)} trabajo(s) del pedido.")
        return self.order_jobs(order_id)

    def order_jobs_summary(self, order_id: int) -> dict:
        """Resumen de ítems para listas y pantallas de pedido."""
        rows = self.order_jobs(order_id)
        subtotal = round(sum(float(job.get("subtotal") or 0) for job in rows), 2)
        total = round(sum(float(job.get("subtotal") or 0) * (1 - float(job.get("discount_percent") or 0) / 100) for job in rows), 2)
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
            "SELECT price, discount_percent, budget_total, paid_amount, payment_status, cost_mp, cost_mo, cost_cf, cost_total, margin FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        if not row:
            return {"subtotal": 0.0, "discount_percent": 0.0, "budget_total": 0.0, "paid_amount": 0.0, "pending_amount": 0.0, "payment_status": "Pendiente", "cost_mp": 0.0, "cost_mo": 0.0, "cost_cf": 0.0, "cost_total": 0.0, "margin": 0.0}
        paid = self.connection.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM order_payments WHERE order_id = ?", (order_id,)
        ).fetchone()[0]
        jobs = self.order_jobs(order_id)
        if jobs:
            subtotal = round(sum(float(job.get("subtotal") or 0) for job in jobs), 2)
            total = round(sum(float(job.get("subtotal") or 0) * (1 - float(job.get("discount_percent") or 0) / 100) for job in jobs), 2)
            discount = 0.0
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
            # Calcular budget_total y cantidad de trabajos
            budget_total = round(sum(float(job.get("subtotal") or 0) * (1 - float(job.get("discount_percent") or 0) / 100) for job in jobs), 2)
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

        cost_total = round(total_mp + total_mo + total_cf, 2)
        margin = round(budget_total - cost_total, 2)

        self.connection.execute(
            """UPDATE orders 
               SET cost_mp = ?, cost_mo = ?, cost_cf = ?, cost_total = ?, margin = ?, budget_total = ?
               WHERE id = ?""",
            (round(total_mp, 2), round(total_mo, 2), round(total_cf, 2), cost_total, margin, budget_total, order_id)
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

    def register_order_payment(self, order_id: int, amount: float, method: str = "", note: str = "") -> dict:
        from datetime import datetime

        amount = round(float(amount), 2)
        if amount <= 0:
            raise ValueError("El cobro debe ser mayor que cero.")
        now = datetime.now().isoformat(timespec="seconds")
        with self.connection:
            self.connection.execute(
                "INSERT INTO order_payments(order_id, amount, method, note, paid_at, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (order_id, amount, method.strip(), note.strip(), now, now),
            )
        financials = self.order_financials(order_id)
        self.connection.execute(
            "UPDATE orders SET budget_total = ?, paid_amount = ?, payment_status = ?, updated_at = ? WHERE id = ?",
            (financials["budget_total"], financials["paid_amount"], financials["payment_status"], now, order_id),
        )
        self.connection.commit()
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
                                WHERE order_id = orders.id), 0) AS paid_amount,
                      COALESCE((SELECT MAX(paid_at) FROM order_payments
                                WHERE order_id = orders.id), '') AS last_payment_at,
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
            "SELECT * FROM price_rules WHERE active = 1 ORDER BY material COLLATE NOCASE, size COLLATE NOCASE, min_quantity DESC, id DESC"
        )
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
            "plancha diseño único": "Plancha A4 - Diseño Único",
            "plancha a4 diseño único": "Plancha A4 - Diseño Único",
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
        variable_cost_model_id: int | None = None,
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
                active, price_mode, pack_quantity, variable_cost_model_id
               ) VALUES(?, ?, ?, ?, ?, ?, 1, ?, ?, ?)"""
        params = (
            self._price_material(material), self._price_size(size), minimum, amount,
            extra_service.strip(), discount, mode, pack, None if variable_cost_model_id in {None, ""} else int(variable_cost_model_id),
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
        variable_cost_model_id: int | None = None,
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
                   variable_cost_model_id = ?
               WHERE id = ?"""
        params = (
            self._price_material(material), self._price_size(size), minimum, amount,
            extra_service.strip(), discount, mode, pack,
            None if variable_cost_model_id in {None, ""} else int(variable_cost_model_id),
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
                 modified=excluded.modified, caption=excluded.caption, visual_score=-1""",
            image,
        )
        self.update_plancha_metrics(image["path"], image["modified"])

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
            self.connection.execute("DELETE FROM image_tags WHERE image_path = ?", (path,))
            self.connection.execute("DELETE FROM visual_similarities WHERE query_path = ? OR candidate_path = ?", (path, path))
            self.connection.execute("DELETE FROM ai_results WHERE image_path = ?", (path,))
            self.connection.execute("DELETE FROM dismissed_ai_tags WHERE image_path = ?", (path,))
            self.connection.execute("DELETE FROM order_designs WHERE image_path = ?", (path,))
            self.connection.execute("DELETE FROM plancha_usage WHERE image_path = ?", (path,))
            self.connection.execute("DELETE FROM images WHERE path = ?", (path,))

    def commit(self) -> None:
        self.connection.commit()

    def _query_parts(self, query: str, extension: str | None = None, tags: list[str] | None = None, categories: list[str] | None = None) -> tuple[str, list[str]]:
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
                params.extend([term] * 8)
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
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return where, params

    def search(self, query: str = "", limit: int = 50, extension: str | None = None, tags: list[str] | None = None, categories: list[str] | None = None, random_order: bool = False) -> list[dict]:
        where, params = self._query_parts(query, extension, tags, categories)
        order = "RANDOM()" if random_order else "images.modified DESC"
        sql = "SELECT images.*, GROUP_CONCAT(tags.name, ' · ') AS tags FROM images LEFT JOIN image_tags ON image_tags.image_path = images.path LEFT JOIN tags ON tags.id = image_tags.tag_id" + where + " GROUP BY images.path ORDER BY " + order + " LIMIT ?"
        params.append(limit)
        return [dict(row) for row in self.connection.execute(sql, params)]

    def plancha_browser_images(
        self,
        query: str = "",
        mode: str = "Todo",
        category: str = "",
        collection: str = "",
        limit: int = 300,
    ) -> list[dict]:
        """Diseños para el selector de plancha sin mirar nombres de archivo.

        Personaje, color y etiqueta se modelan como palabras clave: así la
        búsqueda mejora con las etiquetas que el usuario va agregando y no
        obliga a crear nombres o carpetas nuevas.
        """
        term = query.strip().casefold()
        clauses: list[str] = []
        params: list[object] = []
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

    def count(self, query: str = "", extension: str | None = None, tags: list[str] | None = None, categories: list[str] | None = None) -> int:
        where, params = self._query_parts(query, extension, tags, categories)
        sql = "SELECT COUNT(DISTINCT images.path) FROM images LEFT JOIN image_tags ON image_tags.image_path = images.path LEFT JOIN tags ON tags.id = image_tags.tag_id"
        return self.connection.execute(sql + where, params).fetchone()[0]

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
        if commit:
            self.connection.commit()

    def set_caption(self, image_path: str, caption: str) -> None:
        self.connection.execute("UPDATE images SET caption = ? WHERE path = ?", (caption.strip(), image_path))
        self.connection.commit()

    def set_classification(self, image_path: str, caption: str, category: str) -> None:
        self.connection.execute(
            "UPDATE images SET caption = ?, category = ? WHERE path = ?",
            (caption.strip(), category.strip().title(), image_path),
        )
        self.connection.commit()

    def set_image_category(self, image_path: str, category: str) -> None:
        """Actualiza solo la categoría, sin alterar el nombre interno ni etiquetas."""
        self.connection.execute(
            "UPDATE images SET category = ? WHERE path = ?",
            (category.strip().title(), image_path),
        )
        self.connection.commit()

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

    def approve_processed_sticker(self, result, category: str = "", tags: list[str] | None = None) -> dict:
        """Agrega el PNG de impresión aprobado al banco con categoría y etiquetas."""
        from pathlib import Path

        if isinstance(result, dict):
            payload = result
        else:
            from dataclasses import asdict
            payload = asdict(result)
        artifacts = payload.get("artifacts") or {}
        master = Path(artifacts.get("master") or artifacts["print"])
        stat = master.stat()
        image = {
            "path": str(master.resolve()),
            "name": master.name,
            "extension": master.suffix.lower(),
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "caption": "",
        }
        self.upsert(image)
        self.set_image_category(image["path"], category)
        for tag in tags or []:
            self.add_tag(image["path"], tag, commit=False)
        self.connection.execute(
            "UPDATE images SET is_private = 0, is_reusable = 1, import_status = 'Biblioteca' WHERE path = ?",
            (image["path"],),
        )
        self.connection.commit()
        self.set_sticker_processing_status(payload["job_id"], "Aprobado")
        return image

    def sticker_processing_jobs(self, limit: int = 200) -> list[dict]:
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM sticker_processing_jobs ORDER BY updated_at DESC LIMIT ?", (limit,)
        )]

    def all_images(self) -> list[dict]:
        return [dict(row) for row in self.connection.execute("SELECT path, name FROM images")]

    def visual_search_images(self) -> list[dict]:
        """Datos mínimos para comparar localmente sin cargar toda la biblioteca."""
        rows = self.connection.execute(
            """SELECT images.path, images.name, images.modified, images.visual_signature,
                      images.visual_signature_modified, GROUP_CONCAT(tags.name, ' · ') AS tags
               FROM images
               LEFT JOIN image_tags ON image_tags.image_path = images.path
               LEFT JOIN tags ON tags.id = image_tags.tag_id
               GROUP BY images.path"""
        )
        return [dict(row) for row in rows]

    def update_visual_signatures(self, signatures: list[tuple[str, float, str]]) -> None:
        """Persiste huellas visuales para no recalcular 5000 archivos en cada búsqueda."""
        if not signatures:
            return
        self.connection.executemany(
            "UPDATE images SET visual_signature = ?, visual_signature_modified = ? WHERE path = ?",
            signatures,
        )
        self.connection.commit()

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
        placeholders = ", ".join("?" for _ in paths)
        rows = self.connection.execute(
            "SELECT images.*, GROUP_CONCAT(tags.name, ' · ') AS tags "
            "FROM images LEFT JOIN image_tags ON image_tags.image_path = images.path "
            "LEFT JOIN tags ON tags.id = image_tags.tag_id "
            f"WHERE images.path IN ({placeholders}) GROUP BY images.path",
            paths,
        )
        by_path = {row["path"]: dict(row) for row in rows}
        return [by_path[path] for path in paths if path in by_path]

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

    def save_ai_result(self, image_path: str, provider: str, model: str, modified: float, result: dict) -> None:
        import json

        self.connection.execute(
            """INSERT INTO ai_results(image_path, provider, model, modified, result) VALUES(?, ?, ?, ?, ?)
               ON CONFLICT(image_path, provider, model) DO UPDATE SET modified=excluded.modified, result=excluded.result""",
            (image_path, provider, model, modified, json.dumps(result, ensure_ascii=False)),
        )
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

    def clear_image_category(self, image_path: str) -> None:
        self.connection.execute("UPDATE images SET category = '' WHERE path = ?", (image_path,))
        self.connection.commit()

    def clear_tags(self) -> None:
        """Elimina las etiquetas y sus asociaciones, sin tocar los diseños."""
        self.connection.execute("DELETE FROM image_tags")
        self.connection.execute("DELETE FROM tags")
        self.connection.commit()

    def suggestions(self, query: str, limit: int = 6) -> list[str]:
        """Predicciones rápidas: prioriza etiquetas, incluso si son frases largas."""
        term = query.strip().lower()
        if len(term) < 2:
            return []
        like = f"%{term}%"
        rows = self.connection.execute(
            """SELECT name FROM (
                   SELECT tags.name AS name, 0 AS priority, COUNT(image_tags.image_path) AS usage
                   FROM tags JOIN image_tags ON image_tags.tag_id = tags.id
                   WHERE LOWER(tags.name) LIKE ?
                   GROUP BY tags.id
               )
               GROUP BY name COLLATE NOCASE
               ORDER BY MIN(priority), CASE WHEN LOWER(name) LIKE ? THEN 0 ELSE 1 END,
                        MAX(usage) DESC, name COLLATE NOCASE
               LIMIT ?""",
            (like, f"{term}%", limit),
        )
        return [row[0] for row in rows]

    def remove_tag(self, image_path: str, tag_name: str) -> None:
        self.connection.execute(
            "DELETE FROM image_tags WHERE image_path = ? AND tag_id = "
            "(SELECT id FROM tags WHERE name = ? COLLATE NOCASE)",
            (image_path, tag_name),
        )
        self.connection.execute("DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM image_tags)")
        self.connection.commit()

    def delete_tag(self, tag_name: str) -> None:
        """Elimina una etiqueta de todos los diseños, sin borrar archivos."""
        self.connection.execute(
            "DELETE FROM image_tags WHERE tag_id = (SELECT id FROM tags WHERE name = ? COLLATE NOCASE)",
            (tag_name,),
        )
        self.connection.execute("DELETE FROM tags WHERE name = ? COLLATE NOCASE", (tag_name,))
        self.connection.commit()

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
        return {**default, **saved}

    def save_printing_config(self, printer_name: str, preferences: dict | None = None) -> dict:
        """Guarda la impresora y el perfil fijo que usará toda la producción."""
        from datetime import datetime
        import json

        config = self.printing_config()
        config["printer_name"] = printer_name.strip()
        preferences = preferences or {}
        # La aplicación imprime planchas A4 reales: estos valores quedan
        # protegidos aunque se restauren configuraciones antiguas o dañadas.
        config["paper"] = "A4"
        config["orientation"] = "Vertical"
        config["scale"] = 97.27
        config["quality"] = "Alta"
        config["color"] = "Color"
        # Preservar la configuración del driver (DEVMODE) y su resumen si están siendo guardadas
        if "devmode_b64" in preferences:
            config["devmode_b64"] = preferences["devmode_b64"]
        if "devmode_summary" in preferences:
            config["devmode_summary"] = preferences["devmode_summary"]
        try:
            config["copies"] = min(99, max(1, int(preferences.get("copies", config.get("copies", 1)))))
        except (TypeError, ValueError):
            config["copies"] = 1
        now = datetime.now().isoformat(timespec="seconds")
        self.connection.execute(
            """INSERT INTO app_settings(setting_key, setting_value, updated_at) VALUES('printing_config', ?, ?)
               ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value, updated_at = excluded.updated_at""",
            (json.dumps(config, ensure_ascii=False), now),
        )
        self.connection.commit()
        return config

    def save_plancha_project(self, order_id: int | None, name: str, material: str, project_json: str,
                             project_path: str, plancha_id: int | None = None) -> int:
        """Registra el proyecto editable sin alterar los PNG originales de cada diseño."""
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        if plancha_id:
            previous = self.connection.execute(
                "SELECT approval_status, order_id FROM plancha_projects WHERE id = ?", (plancha_id,)
            ).fetchone()
            self.connection.execute(
                """UPDATE plancha_projects SET order_id = ?, name = ?, material = ?, project_json = ?,
                   project_path = ?,
                   approval_status = CASE WHEN approval_status = 'Aprobada' THEN 'Borrador' ELSE approval_status END,
                   updated_at = ? WHERE id = ?""",
                (order_id, name, material, project_json, project_path, now, plancha_id),
            )
            self.connection.commit()
            if previous and previous["approval_status"] == "Aprobada" and (order_id or previous["order_id"]):
                self._sync_order_approval(int(order_id or previous["order_id"]))
            return int(plancha_id)
        cursor = self.connection.execute(
            """INSERT INTO plancha_projects(order_id, name, material, project_json, project_path, created_at, updated_at)
               VALUES(?, ?, ?, ?, ?, ?, ?)""",
            (order_id, name, material, project_json, project_path, now, now),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def plancha_project(self, plancha_id: int) -> dict | None:
        row = self.connection.execute("SELECT * FROM plancha_projects WHERE id = ?", (plancha_id,)).fetchone()
        return dict(row) if row else None

    def plancha_by_project_path(self, project_path: str) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM plancha_projects WHERE project_path = ? ORDER BY id DESC LIMIT 1", (project_path,)
        ).fetchone()
        return dict(row) if row else None

    def set_plancha_final_png(self, plancha_id: int, final_png_path: str) -> None:
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        self.connection.execute(
            """UPDATE plancha_projects SET final_png_path = ?, print_status = 'Lista para imprimir',
               print_error = '', print_updated_at = ?,
               production_status = CASE WHEN production_status IN ('borrador', 'guardada') THEN 'lista' ELSE production_status END,
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
            "SELECT * FROM plancha_projects WHERE order_id = ? ORDER BY updated_at DESC, id DESC", (order_id,)
        )
        return [dict(row) for row in rows]

    # Producción: consulta de planchas para el módulo Producción --------
    def production_planchas(self) -> list[dict]:
        """Todas las planchas guardadas con datos del pedido, para la tabla de Producción."""
        rows = self.connection.execute(
            """SELECT pp.*,
                      COALESCE(clients.name, o.client, '') AS order_client,
                      COALESCE(o.delivery_date, '') AS delivery_date,
                      COALESCE(o.print_priority, 0) AS print_priority,
                      COALESCE(o.whatsapp, '') AS order_whatsapp,
                      (SELECT COUNT(*) FROM print_jobs pj WHERE pj.plancha_id = pp.id) AS total_jobs,
                      (SELECT COUNT(*) FROM print_jobs pj WHERE pj.plancha_id = pp.id
                       AND pj.status = 'Impresa') AS printed_jobs
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
                      COALESCE(clients.name, o.client, '') AS order_client,
                      COALESCE(o.delivery_date, '') AS delivery_date,
                      COALESCE(o.print_priority, 0) AS print_priority,
                      COALESCE(o.whatsapp, '') AS order_whatsapp,
                      (SELECT COUNT(*) FROM print_jobs pj WHERE pj.plancha_id = pp.id) AS total_jobs,
                      (SELECT COUNT(*) FROM print_jobs pj WHERE pj.plancha_id = pp.id
                       AND pj.status = 'Impresa') AS printed_jobs
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
            "UPDATE plancha_projects SET production_status = ?, previous_production_status = '', updated_at = ? WHERE id = ?",
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
        """Planchas guardadas y exportadas que pueden combinarse en una tira."""
        rows = self.connection.execute(
            """SELECT plancha_projects.*, orders.client AS order_client,
                      orders.material AS order_material, orders.status AS order_status
               FROM plancha_projects
               LEFT JOIN orders ON orders.id = plancha_projects.order_id
               WHERE COALESCE(plancha_projects.project_path, '') <> ''
                 AND COALESCE(plancha_projects.final_png_path, '') <> ''
               ORDER BY plancha_projects.updated_at DESC, plancha_projects.id DESC"""
        )
        return [dict(row) for row in rows]

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

    def close(self) -> None:
        self.connection.close()
