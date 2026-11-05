from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from http.client import HTTPConnection
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.whatsapp.config import WhatsAppConfig, _load_dotenv, load_config
from app.whatsapp.repository import WhatsAppRepository, create_whatsapp_tables
from app.whatsapp.service import WhatsAppService
from app.whatsapp.webhook_server import WhatsAppWebhookServer


def _sanitize(val: str, keep_last: int = 4) -> str:
    if not val:
        return ""
    visible = val[-keep_last:]
    hidden = "*" * max(0, len(val) - keep_last)
    return hidden + visible


def cmd_check_local(cfg: WhatsAppConfig) -> None:
    import sqlite3

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    create_whatsapp_tables(conn)
    repo = WhatsAppRepository(conn)
    svc = WhatsAppService(repo)

    test_cfg = WhatsAppConfig(
        enabled=True,
        verify_token="test_token_webhook",
        app_secret="test_secret_webhook",
        verify_signature=False,
    )
    server = WhatsAppWebhookServer(
        service=svc,
        host="127.0.0.1",
        port=0,
        config=test_cfg,
    )
    server.start()
    port = server.port

    print("=== WEBHOOK LOCAL CHECK ===")
    print(f"Servidor iniciado en 127.0.0.1:{port}")
    errors = 0

    # GET verification
    conn_http = HTTPConnection("127.0.0.1", port, timeout=5)
    conn_http.request(
        "GET",
        "/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=test_token_webhook&hub.challenge=CHALLENGE_42",
    )
    resp = conn_http.getresponse()
    data = resp.read()
    if resp.status == 200 and data.decode() == "CHALLENGE_42":
        print("GET /api/whatsapp/webhook: OK (challenge verificado)")
    else:
        print(f"GET /api/whatsapp/webhook: FALLÓ (HTTP {resp.status})")
        errors += 1
    conn_http.close()

    # POST with sample payload
    test_payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "biz_check",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": "pn_check", "display_phone_number": "+15550001111"},
                    "contacts": [{"wa_id": "wa_check", "profile": {"name": "Check User"}}],
                    "messages": [{
                        "id": "msg_check_1", "from": "wa_check", "timestamp": str(int(time.time())),
                        "type": "text", "text": {"body": "Webhook check"},
                    }],
                }
            }],
        }],
    }
    body = json.dumps(test_payload).encode("utf-8")
    conn_http = HTTPConnection("127.0.0.1", port, timeout=5)
    conn_http.request("POST", "/api/whatsapp/webhook", body=body, headers={"Content-Type": "application/json"})
    resp = conn_http.getresponse()
    resp_data = resp.read()
    if resp.status == 200:
        print("POST /api/whatsapp/webhook: OK (payload aceptado)")
    else:
        print(f"POST /api/whatsapp/webhook: FALLÓ (HTTP {resp.status})")
        errors += 1
    conn_http.close()

    # Verify persistence
    contact = repo.get_contact_by_wa_id("wa_check")
    if contact and contact.display_name == "Check User":
        print("Persistencia contacto: OK")
    else:
        print("Persistencia contacto: FALLÓ")
        errors += 1

    msgs = repo.get_messages_for_conversation(1) if contact else []
    if msgs:
        print("Persistencia mensaje: OK")
    else:
        print("Persistencia mensaje: FALLÓ (puede ser esperado si no hay conversación)")
        errors += 1

    server.stop()
    conn.close()

    print()
    if errors == 0:
        print("Webhook local: FUNCIONANDO CORRECTAMENTE")
    else:
        print(f"Webhook local: {errors} error(es) detectado(s)")
        sys.exit(1)


def cmd_status(cfg: WhatsAppConfig) -> None:
    import sqlite3

    db_path = Path(__file__).resolve().parents[1] / "visionvault.db"
    if not db_path.exists():
        print("Base de datos no encontrada:", db_path)
        print("Estadísticas no disponibles.")
        return

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    create_whatsapp_tables(conn)

    counts = {}
    for status in ("pending", "processing", "processed", "failed", "ignored"):
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM whatsapp_webhook_events WHERE processing_status = ?",
            (status,),
        ).fetchone()
        counts[status] = row["cnt"] if row else 0

    inbound = conn.execute(
        "SELECT COUNT(*) as cnt FROM whatsapp_messages WHERE direction = 'inbound'"
    ).fetchone()
    outbound = conn.execute(
        "SELECT COUNT(*) as cnt FROM whatsapp_messages WHERE direction = 'outbound'"
    ).fetchone()

    outbox_counts = {}
    for status in ("pending", "processing", "sent", "failed"):
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM whatsapp_outbox WHERE status = ?",
            (status,),
        ).fetchone()
        outbox_counts[status] = row["cnt"] if row else 0

    conn.close()

    print("=== WHATSAPP WEBHOOK STATUS ===")
    print()
    print("Eventos de webhook:")
    print(f"  Pendientes:  {counts['pending']}")
    print(f"  Procesando:  {counts['processing']}")
    print(f"  Procesados:  {counts['processed']}")
    print(f"  Fallidos:    {counts['failed']}")
    print(f"  Ignorados:   {counts['ignored']}")
    print()
    print("Mensajes:")
    print(f"  Inbound:     {inbound['cnt'] if inbound else 0}")
    print(f"  Outbound:    {outbound['cnt'] if outbound else 0}")
    print()
    print("Outbox:")
    print(f"  Pendientes:  {outbox_counts['pending']}")
    print(f"  Procesando:  {outbox_counts['processing']}")
    print(f"  Enviados:    {outbox_counts['sent']}")
    print(f"  Fallidos:    {outbox_counts['failed']}")


def main():
    _load_dotenv()
    cfg = load_config(reload=True)

    parser = argparse.ArgumentParser(description="Verificación del webhook de WhatsApp")
    parser.add_argument("--check-local", action="store_true", help="Probar servidor webhook local")
    parser.add_argument("--status", action="store_true", help="Mostrar estadísticas de la base")
    args = parser.parse_args()

    if args.check_local:
        cmd_check_local(cfg)
    elif args.status:
        cmd_status(cfg)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
