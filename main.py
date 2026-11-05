from pathlib import Path
import argparse
import logging
import traceback

from app.diagnostics import configure_logging

LOG_PATH: Path | None = None
logger = logging.getLogger("doccione.startup")

_WEBHOOK_SERVER = None
_WHATSAPP_OUTBOX_WORKER = None


def resolve_database_path(value: str | Path | None = None) -> tuple[Path, bool]:
    """Resuelve la base elegida sin degradar silenciosamente a producción."""
    default = Path(__file__).resolve().parent / "visionvault.db"
    if value is None:
        return default, False
    raw = str(value).strip()
    if not raw:
        raise ValueError("La ruta alternativa de base de datos está vacía.")
    candidate = Path(raw).expanduser()
    candidate = (Path.cwd() / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if candidate.exists() and not candidate.is_file():
        raise ValueError(f"La ruta alternativa no es un archivo: {candidate}")
    if not candidate.parent.exists():
        raise ValueError(f"La carpeta de la base alternativa no existe: {candidate.parent}")
    try:
        probe = candidate.parent / ".doccione-write-test"
        with probe.open("a", encoding="utf-8"):
            pass
        probe.unlink()
    except OSError as error:
        raise ValueError(f"No se puede escribir en la carpeta de la base alternativa: {candidate.parent}") from error
    return candidate, candidate != default.resolve()


def parse_startup_args(argv=None):
    parser = argparse.ArgumentParser(description="Doccione Studio")
    parser.add_argument("--database", help="Ruta explícita a una base SQLite alternativa")
    return parser.parse_args(argv)


def _start_whatsapp_webhook(db_path: Path):
    """Inicia el servidor webhook de WhatsApp si la configuración lo habilita."""
    global _WEBHOOK_SERVER, _WHATSAPP_OUTBOX_WORKER
    try:
        from app.whatsapp.config import load_config, _load_dotenv
        _load_dotenv()
        cfg = load_config(reload=True)
        if not cfg.enabled:
            return
        if not cfg.verify_token:
            return
        import sqlite3
        from app.whatsapp.repository import create_whatsapp_tables, WhatsAppRepository
        from app.whatsapp.service import WhatsAppService
        from app.whatsapp.webhook_server import WhatsAppWebhookServer
        from app.whatsapp.client import WhatsAppCloudClient
        from app.whatsapp.outbox_worker import WhatsAppOutboxWorker

        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        create_whatsapp_tables(conn)
        repo = WhatsAppRepository(conn)
        svc = WhatsAppService(repo)
        server = WhatsAppWebhookServer(
            service=svc,
            host="127.0.0.1",
            port=8767,
            config=cfg,
        )
        if server.start():
            _WEBHOOK_SERVER = server
        _WHATSAPP_OUTBOX_WORKER = WhatsAppOutboxWorker(repo, WhatsAppCloudClient(cfg), cfg)
        _WHATSAPP_OUTBOX_WORKER.start()
    except Exception:
        logger.exception("No se pudo iniciar la integración de WhatsApp")


def _stop_whatsapp_webhook():
    global _WEBHOOK_SERVER, _WHATSAPP_OUTBOX_WORKER
    if _WHATSAPP_OUTBOX_WORKER is not None:
        try:
            _WHATSAPP_OUTBOX_WORKER.stop()
        except Exception:
            pass
        _WHATSAPP_OUTBOX_WORKER = None
    if _WEBHOOK_SERVER is not None:
        try:
            _WEBHOOK_SERVER.stop()
        except Exception:
            pass
        _WEBHOOK_SERVER = None


def run(argv=None):
    global LOG_PATH
    args = parse_startup_args(argv)
    db_path, isolated = resolve_database_path(args.database)
    LOG_PATH = configure_logging(db_path.parent if isolated else Path(__file__).resolve().parent)
    logger.info("Inicio de Doccione Studio", extra={"component": "startup", "event": "start"})
    _start_whatsapp_webhook(db_path)
    try:
        from app.ui.main_window import VisionVaultApp
        VisionVaultApp(database_path=db_path, isolated_database=isolated).mainloop()
    finally:
        _stop_whatsapp_webhook()


if __name__ == "__main__":
    try:
        run()
    except Exception as error:
        logger.exception("Doccione Studio no pudo abrirse")
        details = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        log_path = (LOG_PATH.parent / "error_inicio_doccione.log") if LOG_PATH else None
        if log_path is not None:
            try:
                log_path.write_text(details, encoding="utf-8")
            except OSError:
                log_path = None
        message = str(error)
        if log_path is not None:
            message += f"\n\nSe guardó el detalle en:\n{log_path}"
        if LOG_PATH is not None:
            message += f"\n\nRegistro general:\n{LOG_PATH}"
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Doccione no pudo abrirse", message)
            root.destroy()
        except Exception:
            # Si la instalación de Tcl/Tk está dañada, mostrar el error sin
            # depender de Tk para que el acceso directo no falle en silencio.
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, message, "Doccione no pudo abrirse", 0x10)
            except Exception:
                pass
