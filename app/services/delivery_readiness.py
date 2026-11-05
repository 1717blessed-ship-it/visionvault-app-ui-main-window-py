"""Contrato único de entrega total, utilizado también por guardas SQLite."""
import json
from datetime import datetime


DELIVERY_STATES = {"entregado", "terminado", "completado"}


def readiness(connection, order_id):
    exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name='order_delivery_readiness'").fetchone()
    if not exists:
        raise ValueError("No se puede verificar la entrega: el esquema requiere la migración de cumplimiento.")
    return [dict(row) for row in connection.execute(
        "SELECT * FROM order_delivery_readiness WHERE order_id=?", (int(order_id),))]


def assert_deliverable(connection, order_id):
    rows = readiness(connection, order_id)
    if not rows:
        raise ValueError("No se puede entregar un pedido sin trabajos verificables.")
    blocked = [r for r in rows if not r["deliverable"]]
    if blocked:
        detail = "; ".join(f"Trabajo #{r['job_id']} {r['title']}: solicita {r['requested']:g}, "
                           f"terminadas {r['finished']:g}, pendientes {r['pending']:g}" for r in blocked)
        raise ValueError("No se puede registrar entrega total. " + detail + ". Confirmá producción u origen entregable verificable.")


def confirm_direct_source(connection, job_id, *, source, quantity, reference, actor):
    """Constancia explícita del operador sobre stock o servicio ya cumplido.

    No consume materias primas ni permite ignorar fabricación vinculada.
    """
    if source not in {"stock", "service"} or not str(reference).strip() or not str(actor).strip():
        raise ValueError("Indicá origen stock/service, referencia verificable y responsable.")
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        job = connection.execute("SELECT * FROM order_jobs WHERE id=?", (job_id,)).fetchone()
        if not job or quantity != job["quantity"] or quantity <= 0:
            raise ValueError("La constancia debe cubrir la cantidad exacta del trabajo actual.")
        traced = connection.execute("SELECT 1 FROM order_design_demand_lines WHERE order_job_id=? UNION ALL SELECT 1 FROM plancha_item_assignments WHERE order_job_id=? LIMIT 1", (job_id, job_id)).fetchone()
        if traced:
            raise ValueError("El trabajo tiene demanda o historial productivo; debe cumplir su producción.")
        connection.execute(
            "INSERT INTO order_events(order_id,event_type,message,data_json,created_at) VALUES(?,?,?,?,?)",
            (job["order_id"], "delivery.source.confirmed", f"Origen entregable confirmado por {actor}: {reference}",
             json.dumps({"job_id": job_id, "quantity": quantity, "source": source, "reference": reference,
                         "actor": actor, "material": job["material"], "size": job["size"], "title": job["title"]}),
             datetime.now().isoformat(timespec="seconds")),
        )


def install_delivery_guards(connection):
    connection.execute("""CREATE VIEW IF NOT EXISTS order_delivery_readiness AS
        SELECT j.id AS job_id,j.order_id,j.title,j.quantity AS requested,
          COALESCE((SELECT SUM(a.quantity) FROM plancha_item_assignments a
                    WHERE a.order_job_id=j.id AND a.state='finished'),0) AS finished,
          MAX(0,j.quantity-COALESCE((SELECT SUM(a.quantity) FROM plancha_item_assignments a
                    WHERE a.order_job_id=j.id AND a.state='finished'),0)) AS pending,
          CASE WHEN j.quantity>0 AND (
            (COALESCE((SELECT SUM(a.quantity) FROM plancha_item_assignments a
                       WHERE a.order_job_id=j.id AND a.state='finished'),0)>=j.quantity
             AND NOT EXISTS(SELECT 1 FROM plancha_item_assignments a WHERE a.order_job_id=j.id AND a.state NOT IN ('finished','released')))
            OR (NOT EXISTS(SELECT 1 FROM order_design_demand_lines d WHERE d.order_job_id=j.id)
                AND NOT EXISTS(SELECT 1 FROM plancha_item_assignments a WHERE a.order_job_id=j.id)
                AND EXISTS(SELECT 1 FROM order_events e WHERE e.order_id=j.order_id
                  AND e.event_type='delivery.source.confirmed' AND json_valid(e.data_json)
                  AND json_extract(e.data_json,'$.job_id')=j.id
                  AND json_extract(e.data_json,'$.quantity')=j.quantity
                  AND json_extract(e.data_json,'$.title')=j.title
                  AND json_extract(e.data_json,'$.material')=j.material
                  AND json_extract(e.data_json,'$.size')=j.size
                  AND json_extract(e.data_json,'$.source') IN ('stock','service')
                  AND LENGTH(TRIM(json_extract(e.data_json,'$.reference')))>0
                  AND LENGTH(TRIM(json_extract(e.data_json,'$.actor')))>0))
          ) THEN 1 ELSE 0 END AS deliverable
        FROM order_jobs j""")
    for table, scope in (("orders", "order_id=NEW.id"), ("order_jobs", "job_id=NEW.id")):
        missing_jobs = "OR NOT EXISTS(SELECT 1 FROM order_jobs WHERE order_id=NEW.id)" if table == "orders" else ""
        connection.execute(f"""CREATE TRIGGER IF NOT EXISTS guard_{table}_total_delivery
            BEFORE UPDATE OF status ON {table}
            WHEN LOWER(TRIM(NEW.status)) IN ('entregado','terminado','completado')
              AND LOWER(TRIM(OLD.status)) <> LOWER(TRIM(NEW.status))
              AND (EXISTS(SELECT 1 FROM order_delivery_readiness WHERE {scope} AND deliverable=0) {missing_jobs})
            BEGIN SELECT RAISE(ABORT,'Entrega total bloqueada: hay cantidades sin terminar u origen entregable no verificado.'); END""")
    connection.execute("""CREATE TRIGGER IF NOT EXISTS guard_delivered_job_edit
        AFTER UPDATE OF quantity,title,material,size,order_id ON order_jobs
        WHEN EXISTS(SELECT 1 FROM orders o WHERE o.id=NEW.order_id
                     AND LOWER(TRIM(o.status)) IN ('entregado','terminado','completado'))
          AND EXISTS(SELECT 1 FROM order_delivery_readiness WHERE job_id=NEW.id AND deliverable=0)
        BEGIN SELECT RAISE(ABORT,'No se puede invalidar una entrega total confirmada.'); END""")
    connection.execute("""CREATE TRIGGER IF NOT EXISTS guard_closed_order_new_job
        BEFORE INSERT ON order_jobs
        WHEN EXISTS(SELECT 1 FROM orders WHERE id=NEW.order_id AND LOWER(TRIM(status)) IN ('entregado','terminado','completado'))
        BEGIN SELECT RAISE(ABORT,'No se puede agregar un trabajo sin cumplir a un pedido entregado.'); END""")
    for operation in ("UPDATE", "DELETE"):
        connection.execute(f"""CREATE TRIGGER IF NOT EXISTS guard_delivered_assignments_{operation.lower()}
            AFTER {operation} ON plancha_item_assignments
            WHEN EXISTS(SELECT 1 FROM order_delivery_readiness r JOIN orders o ON o.id=r.order_id
                        WHERE r.job_id=OLD.order_job_id AND r.deliverable=0
                        AND LOWER(TRIM(o.status)) IN ('entregado','terminado','completado'))
            BEGIN SELECT RAISE(ABORT,'No se puede invalidar producción que respalda una entrega.'); END""")
        connection.execute(f"""CREATE TRIGGER IF NOT EXISTS guard_delivered_source_{operation.lower()}
            AFTER {operation} ON order_events
            WHEN OLD.event_type='delivery.source.confirmed'
              AND EXISTS(SELECT 1 FROM order_delivery_readiness r JOIN orders o ON o.id=r.order_id
                         WHERE r.order_id=OLD.order_id AND r.deliverable=0
                         AND LOWER(TRIM(o.status)) IN ('entregado','terminado','completado'))
            BEGIN SELECT RAISE(ABORT,'No se puede quitar el respaldo de una entrega confirmada.'); END""")
    connection.execute("""CREATE TRIGGER IF NOT EXISTS guard_delivered_job_delete
        BEFORE DELETE ON order_jobs
        WHEN EXISTS(SELECT 1 FROM orders WHERE id=OLD.order_id
                    AND LOWER(TRIM(status)) IN ('entregado','terminado','completado'))
        BEGIN SELECT RAISE(ABORT,'No se puede quitar un trabajo de un pedido entregado.'); END""")
