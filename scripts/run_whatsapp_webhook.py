"""Script de desarrollo para iniciar el webhook de WhatsApp.

Uso:
    python scripts/run_whatsapp_webhook.py

Carga la configuración desde variables de entorno y .env,
abre la base de datos real de Doccione Studio,
inicia el webhook y espera Ctrl+C.
"""

from __future__ import annotations

import logging
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.whatsapp.config import load_config, _load_dotenv
from app.whatsapp.repository import create_whatsapp_tables, WhatsAppRepository
from app.whatsapp.service import WhatsAppService
from app.whatsapp.webhook_server import WhatsAppWebhookServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_whatsapp_webhook")


def main():
    _load_dotenv()
    cfg = load_config(reload=True)

    print(f"WHATSAPP_ENABLED:          {cfg.enabled}")
    print(f"WHATSAPP_WEBHOOK_HOST:     0.0.0.0")
    print(f"WHATSAPP_WEBHOOK_PORT:     {cfg.webhook_port}")
    print(f"WHATSAPP_VERIFY_SIGNATURE: {cfg.verify_signature}")

    db_path = Path(__file__).resolve().parents[1] / "visionvault.db"
    import sqlite3

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    create_whatsapp_tables(conn)

    repo = WhatsAppRepository(conn)
    service = WhatsAppService(repo)

    server = WhatsAppWebhookServer(
        service=service,
        host="0.0.0.0",
        port=cfg.webhook_port,
        config=cfg,
    )

    if not server.start():
        logger.error("No se pudo iniciar el servidor webhook")
        sys.exit(1)

    print(f"\nWebhook escuchando en http://0.0.0.0:{server.port}/api/whatsapp/webhook")
    print("Presioná Ctrl+C para detener.\n")

    def shutdown(signum, frame):
        print("\nDeteniendo servidor...")
        server.stop()
        conn.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        server._thread.join()
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == "__main__":
    main()
