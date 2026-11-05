from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.whatsapp.client import WhatsAppCloudClient
from app.whatsapp.config import WhatsAppConfig, _load_dotenv, load_config
from app.whatsapp.outbox_worker import WhatsAppOutboxWorker
from app.whatsapp.repository import WhatsAppRepository, create_whatsapp_tables
from app.whatsapp.service import WhatsAppService


def _sanitize(val: str, keep_last: int = 4) -> str:
    if not val:
        return ""
    visible = val[-keep_last:]
    hidden = "*" * max(0, len(val) - keep_last)
    return hidden + visible


def _mask_token(val: str) -> str:
    if not val:
        return "no configurado"
    if len(val) <= 8:
        return val[:2] + "****"
    return val[:4] + "****" + val[-4:]


def cmd_check(cfg: WhatsAppConfig) -> None:
    print("WhatsApp habilitado:", "sí" if cfg.enabled else "no")
    print("Access token:", "configurado" if cfg.access_token else "no configurado")
    print("Phone number ID:", "configurado" if cfg.phone_number_id else "no configurado")
    print("Business account ID:", "configurado" if cfg.business_account_id else "no configurado")
    print("API version:", cfg.api_version)
    print("Webhook port:", cfg.webhook_port)
    print("Firma webhook:", "habilitada" if cfg.verify_signature else "deshabilitada")

    timeout_ok = 0 < cfg.http_timeout_seconds <= 120
    batch_ok = 0 < cfg.outbox_batch_size <= 500
    attempts_ok = 0 < cfg.outbox_max_attempts <= 50
    backoff_ok = cfg.outbox_retry_base_seconds > 0
    processing_ok = cfg.outbox_processing_timeout_seconds > 0
    print("Timeout HTTP:", f"{cfg.http_timeout_seconds}s {'OK' if timeout_ok else 'FUERA DE RANGO'}")
    print("Outbox batch:", cfg.outbox_batch_size, "OK" if batch_ok else "FUERA DE RANGO")
    print("Outbox max attempts:", cfg.outbox_max_attempts, "OK" if attempts_ok else "FUERA DE RANGO")
    print("Outbox retry base:", f"{cfg.outbox_retry_base_seconds}s {'OK' if backoff_ok else 'INVÁLIDO'}")
    print("Outbox processing timeout:", f"{cfg.outbox_processing_timeout_seconds}s {'OK' if processing_ok else 'INVÁLIDO'}")

    can_build_url = bool(cfg.api_version and cfg.phone_number_id)
    print("Cliente HTTP:", "listo" if (cfg.enabled and cfg.access_token and cfg.phone_number_id and can_build_url) else "incompleto")

    print()
    if cfg.enabled and cfg.access_token and cfg.phone_number_id:
        print("El cliente puede enviar mensajes.")
    else:
        print("Corregí la configuración antes de enviar.")
    print("Envío real: no ejecutado")


def cmd_dry_run(cfg: WhatsAppConfig, args: argparse.Namespace) -> None:
    to_raw = args.to.strip()
    if not to_raw:
        print("ERROR: --to es requerido")
        sys.exit(1)
    text = args.text
    if not text:
        print("ERROR: --text es requerido")
        sys.exit(1)

    preview_url = args.preview_url
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_raw,
        "type": "text",
        "text": {"preview_url": preview_url, "body": text},
    }
    url = f"https://graph.facebook.com/{cfg.api_version}/{cfg.phone_number_id or '<PHONE_NUMBER_ID>'}/messages"

    print("=== WHATSAPP SEND - DRY RUN ===")
    print("Modo: simulación — no se realizaron conexiones.")
    print()
    print(f"API version:          {cfg.api_version}")
    print(f"URL:                  {url}")
    print(f"Destinatario:         {_sanitize(to_raw)}")
    print(f"Preview URL:          {'sí' if preview_url else 'no'}")
    print(f"Payload (sanitizado): {json.dumps({k: v for k, v in payload.items() if k != 'text'}, ensure_ascii=False)}")
    print(f"  text.body:          {repr(text[:100])}{'...' if len(text) > 100 else ''}")
    if cfg.phone_number_id:
        print(f"Phone number ID:      {_sanitize(cfg.phone_number_id)}")
    print()
    print("DRY RUN: no se realizó ningún envío.")


def cmd_send_real(cfg: WhatsAppConfig, args: argparse.Namespace, transport=None) -> dict:
    if args.confirm != "SEND":
        print("ERROR: --confirm SEND es requerido para --send-real")
        print()
        print("Uso correcto:")
        print(f"  python {Path(__file__).name} --send-real --confirm SEND --to \"NUMERO\" --text \"Mensaje\"")
        sys.exit(1)

    to_raw = args.to.strip()
    if not to_raw:
        print("ERROR: --to es requerido")
        sys.exit(1)
    text = args.text
    if not text:
        print("ERROR: --text es requerido")
        sys.exit(1)

    if not cfg.enabled:
        print("ERROR: WhatsApp no está habilitado (WHATSAPP_ENABLED=true)")
        sys.exit(1)
    if not cfg.access_token:
        print("ERROR: WHATSAPP_ACCESS_TOKEN no está configurado")
        sys.exit(1)
    if not cfg.phone_number_id:
        print("ERROR: WHATSAPP_PHONE_NUMBER_ID no está configurado")
        sys.exit(1)

    print("=== WHATSAPP SEND - ENVÍO REAL ===")
    print("ADVERTENCIA: se enviará un mensaje real por WhatsApp.")
    print()
    print(f"Destinatario: {_sanitize(to_raw)}")
    print(f"API version:  {cfg.api_version}")

    client = WhatsAppCloudClient(config=cfg, transport=transport)
    preview_url = args.preview_url
    result = client.send_text_message(
        recipient_wa_id=to_raw,
        text=text,
        preview_url=preview_url,
    )

    print()
    print("=== RESULTADO ===")
    if result.success:
        print("Envío completado")
        print(f"HTTP:             {result.http_status}")
        print(f"Message ID:       {result.whatsapp_message_id}")
        print(f"Reintentable:     {'sí' if result.retryable else 'no'}")
    else:
        print("Envío rechazado")
        print(f"HTTP:             {result.http_status}")
        if result.error_code:
            print(f"Código:           {result.error_code}")
        print(f"Error:            {result.error_message or 'desconocido'}")
        print(f"Reintentable:     {'sí' if result.retryable else 'no'}")
        if result.retry_after_seconds:
            print(f"Reintentar en:    {result.retry_after_seconds}s")

    return {
        "timestamp": datetime.now().isoformat(),
        "mode": "send-real",
        "api_version": cfg.api_version,
        "url_sanitized": f"https://graph.facebook.com/{cfg.api_version}/<PN_ID>/messages",
        "recipient_last4": to_raw[-4:] if len(to_raw) >= 4 else to_raw,
        "success": result.success,
        "http_status": result.http_status,
        "whatsapp_message_id": result.whatsapp_message_id,
        "error_code": result.error_code,
        "error_message_sanitized": result.error_message[:200] if result.error_message else None,
        "retryable": result.retryable,
    }


def cmd_send_via_outbox(cfg: WhatsAppConfig, args: argparse.Namespace, transport=None) -> dict:
    if args.confirm != "SEND":
        print("ERROR: --confirm SEND es requerido para --send-via-outbox")
        print()
        print("Uso correcto:")
        print(f"  python {Path(__file__).name} --send-via-outbox --confirm SEND --to \"NUMERO\" --text \"Mensaje\"")
        sys.exit(1)

    to_raw = args.to.strip()
    if not to_raw:
        print("ERROR: --to es requerido")
        sys.exit(1)
    text = args.text
    if not text:
        print("ERROR: --text es requerido")
        sys.exit(1)

    if not cfg.enabled:
        print("ERROR: WhatsApp no está habilitado")
        sys.exit(1)
    if not cfg.access_token:
        print("ERROR: WHATSAPP_ACCESS_TOKEN no está configurado")
        sys.exit(1)
    if not cfg.phone_number_id:
        print("ERROR: WHATSAPP_PHONE_NUMBER_ID no está configurado")
        sys.exit(1)

    import sqlite3
    db_path = Path(__file__).resolve().parents[1] / "visionvault.db"
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    create_whatsapp_tables(conn)
    repo = WhatsAppRepository(conn)
    svc = WhatsAppService(repo)
    client = WhatsAppCloudClient(config=cfg, transport=transport)
    worker = WhatsAppOutboxWorker(repo=repo, client=client, config=cfg)

    idem_key = f"manual-test-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    contact = repo.create_or_update_contact(wa_id=to_raw, display_name="Prueba manual")
    conv = repo.create_or_get_open_conversation(contact.id, phone_number_id=cfg.phone_number_id)

    item = svc.queue_text_message(
        recipient_wa_id=to_raw,
        text_body=text,
        conversation_id=conv.id,
        phone_number_id=cfg.phone_number_id,
        idempotency_key=idem_key,
    )

    print("=== WHATSAPP SEND - VÍA OUTBOX ===")
    print(f"Outbox ID:        {item.id}")
    print(f"Estado inicial:   {item.status}")
    print(f"Idempotency key:  {idem_key}")
    print(f"Destinatario:     {_sanitize(to_raw)}")
    print()

    count = worker.process_once(limit=10)
    print(f"Elementos procesados: {count}")
    print()

    import sqlite3 as _sqlite3
    conn2 = _sqlite3.connect(str(db_path), check_same_thread=False)
    conn2.row_factory = _sqlite3.Row
    row = conn2.execute("SELECT * FROM whatsapp_outbox WHERE id = ?", (item.id,)).fetchone()
    conn2.close()

    if row:
        print("=== RESULTADO OUTBOX ===")
        print(f"Outbox ID:        {row['id']}")
        print(f"Estado:           {row['status']}")
        print(f"Attempts:         {row['attempts']}")
        print(f"Message ID:       {row['whatsapp_message_id'] or 'N/A'}")
        err = row["last_error"]
        print(f"Last error:       {err[:200] if err else 'N/A'}")
    else:
        print("No se encontró el elemento en outbox")

    conn.close()
    return {
        "timestamp": datetime.now().isoformat(),
        "mode": "send-via-outbox",
        "outbox_id": item.id,
        "idempotency_key": idem_key,
        "recipient_last4": to_raw[-4:] if len(to_raw) >= 4 else to_raw,
        "status": row["status"] if row else "unknown",
        "attempts": row["attempts"] if row else 0,
        "whatsapp_message_id": row["whatsapp_message_id"] if row else None,
        "last_error_sanitized": (row["last_error"] or "")[:200] if row else None,
    }


def main():
    _load_dotenv()
    cfg = load_config(reload=True)

    parser = argparse.ArgumentParser(description="Prueba manual de envío WhatsApp")
    parser.add_argument("--check", action="store_true", help="Validar configuración")
    parser.add_argument("--dry-run", action="store_true", help="Simular envío sin conexiones")
    parser.add_argument("--send-real", action="store_true", help="Enviar mensaje real")
    parser.add_argument("--send-via-outbox", action="store_true", help="Enviar mediante outbox worker")
    parser.add_argument("--to", type=str, default="", help="Número de destinatario")
    parser.add_argument("--text", type=str, default="", help="Texto del mensaje")
    parser.add_argument("--preview-url", action="store_true", help="Habilitar preview de enlaces")
    parser.add_argument("--confirm", type=str, default="", help='Confirmar con "SEND"')
    parser.add_argument("--output-report", type=str, default="", help="Ruta para guardar reporte JSON")

    args = parser.parse_args()

    report = None

    if args.check:
        cmd_check(cfg)
    elif args.dry_run:
        cmd_dry_run(cfg, args)
    elif args.send_real:
        report = cmd_send_real(cfg, args)
    elif args.send_via_outbox:
        report = cmd_send_via_outbox(cfg, args)
    else:
        parser.print_help()

    if report and args.output_report:
        out_path = Path(args.output_report)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nReporte guardado en: {out_path}")


if __name__ == "__main__":
    main()
