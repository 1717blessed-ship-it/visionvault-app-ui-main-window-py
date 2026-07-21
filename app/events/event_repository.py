"""Almacén de eventos en SQLite con soporte para outbox de notificaciones."""

from __future__ import annotations

import hashlib
import json
import logging
import random
import secrets
import sqlite3
import string
import uuid
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class EventRepository:
    """Gestiona las tablas app_events, notification_outbox, mobile_devices y pairing_codes."""

    def __init__(self, connection: sqlite3.Connection):
        self.conn = connection

    def create_tables(self) -> None:
        """Crea las tablas necesarias si no existen."""
        self.conn.execute(
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
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_app_events_type ON app_events(event_type, created_at DESC)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_app_events_processed ON app_events(processed, created_at DESC)"
        )
        self.conn.execute(
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
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_outbox_status ON notification_outbox(status, next_attempt_at)"
        )
        # Idempotencia: evitar mensajes duplicados al mismo dispositivo
        self.conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_outbox_event_device
               ON notification_outbox(event_uuid, recipient_id, channel)"""
        )
        self.conn.execute(
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
        self.conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_mobile_devices_token ON mobile_devices(push_token)"
        )
        # Preferencias de notificación por dispositivo
        self.conn.execute(
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
        self.conn.execute(
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
        self.conn.execute(
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
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_production_history_job ON production_stage_history(job_id, changed_at DESC)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_production_history_order ON production_stage_history(order_id, changed_at DESC)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_production_history_device ON production_stage_history(device_id, changed_at DESC)"
        )
        self.conn.commit()

    # ── Publicación de eventos ──────────────────────────────────────────────

    def publish_event(
        self,
        event_type: str,
        priority: str,
        title: str,
        message: str,
        entity_type: str | None = None,
        entity_id: int | None = None,
        payload: dict | None = None,
    ) -> str:
        """Publica un evento y crea entradas en el outbox para cada dispositivo activo."""
        event_uuid = str(uuid.uuid4())
        now = datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            """INSERT INTO app_events(event_uuid, event_type, priority, title, message,
               entity_type, entity_id, payload_json, created_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_uuid, event_type, priority, title, message,
                entity_type, entity_id,
                json.dumps(payload or {}, ensure_ascii=False),
                now,
            ),
        )
        # Crear entradas en outbox para dispositivos activos
        devices = self.conn.execute(
            "SELECT id, push_token FROM mobile_devices WHERE active = 1"
        ).fetchall()
        for device in devices:
            # Verificar preferencias del dispositivo
            pref = self.conn.execute(
                "SELECT enabled FROM device_notification_prefs WHERE device_id = ? AND event_type = ?",
                (device["id"], event_type),
            ).fetchone()
            if pref and not pref["enabled"]:
                continue
            # INSERT OR IGNORE respeta el índice de idempotencia
            self.conn.execute(
                """INSERT OR IGNORE INTO notification_outbox(event_uuid, channel, recipient_id, status, created_at)
                   VALUES(?, 'push', ?, 'pending', ?)""",
                (event_uuid, device["push_token"], now),
            )
        self.conn.commit()
        return event_uuid

    # ── Outbox ──────────────────────────────────────────────────────────────

    def pending_outbox(self, limit: int = 50) -> list[dict]:
        """Obtiene mensajes pendientes de envío."""
        rows = self.conn.execute(
            """SELECT o.*, e.event_type, e.priority, e.title, e.message, e.payload_json,
                      e.entity_type, e.entity_id
               FROM notification_outbox o
               JOIN app_events e ON e.event_uuid = o.event_uuid
               WHERE o.status = 'pending'
                 AND (o.next_attempt_at IS NULL OR o.next_attempt_at <= ?)
               ORDER BY e.created_at ASC
               LIMIT ?""",
            (datetime.now().isoformat(timespec="seconds"), limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def mark_outbox_processing(self, outbox_id: int) -> None:
        """Marca un mensaje como 'en proceso' para evitar procesamiento concurrente."""
        self.conn.execute(
            "UPDATE notification_outbox SET status = 'processing' WHERE id = ? AND status = 'pending'",
            (outbox_id,),
        )
        self.conn.commit()

    def mark_outbox_sent(self, outbox_id: int) -> None:
        """Marca un mensaje como enviado exitosamente."""
        now = datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            "UPDATE notification_outbox SET status = 'sent', sent_at = ? WHERE id = ?",
            (now, outbox_id),
        )
        self.conn.commit()

    def mark_outbox_failed(self, outbox_id: int, error: str, retry_after_seconds: int = 60) -> None:
        """Marca un mensaje como fallido y programa reintento."""
        now = datetime.now().isoformat(timespec="seconds")
        next_attempt = (datetime.now() + timedelta(seconds=retry_after_seconds)).isoformat(timespec="seconds")
        self.conn.execute(
            """UPDATE notification_outbox
               SET status = 'pending', attempts = attempts + 1,
                   last_error = ?, next_attempt_at = ?
               WHERE id = ?""",
            (error, next_attempt, outbox_id),
        )
        self.conn.commit()

    def mark_outbox_dead_letter(self, outbox_id: int, error: str) -> None:
        """Marca un mensaje como permanentemente fallido."""
        self.conn.execute(
            "UPDATE notification_outbox SET status = 'dead_letter', last_error = ? WHERE id = ?",
            (error, outbox_id),
        )
        self.conn.commit()

    # ── Eventos recientes ──────────────────────────────────────────────────

    def recent_events(self, limit: int = 20) -> list[dict]:
        """Devuelve los eventos más recientes."""
        rows = self.conn.execute(
            "SELECT * FROM app_events ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    # ── Dispositivos ───────────────────────────────────────────────────────

    def register_device(
        self,
        push_token: str,
        platform: str,
        device_name: str = "",
        user_id: int | None = None,
    ) -> tuple[int, str]:
        """Registra o actualiza un dispositivo móvil y genera session token.
        
        Retorna (device_id, session_token) donde session_token es el token real (solo una vez).
        """
        now = datetime.now().isoformat(timespec="seconds")
        session_token = secrets.token_urlsafe(32)
        session_token_hash = self._hash_session_token(session_token)
        session_expires_at = (datetime.now() + timedelta(days=30)).isoformat(timespec="seconds")
        
        existing = self.conn.execute(
            "SELECT id FROM mobile_devices WHERE push_token = ?", (push_token,)
        ).fetchone()
        if existing:
            device_id = existing["id"]
            self.conn.execute(
                """UPDATE mobile_devices SET device_name = ?, last_seen_at = ?, active = 1,
                   session_token_hash = ?, session_expires_at = ?, session_last_used_at = ?
                   WHERE id = ?""",
                (device_name, now, session_token_hash, session_expires_at, now, device_id),
            )
            self.conn.commit()
            logger.info("Dispositivo actualizado con nuevo session token: id=%d", device_id)
            return device_id, session_token
        
        cursor = self.conn.execute(
            """INSERT INTO mobile_devices(user_id, device_name, platform, push_token, active, last_seen_at, created_at,
               session_token_hash, session_expires_at, session_last_used_at)
               VALUES(?, ?, ?, ?, 1, ?, ?, ?, ?, ?)""",
            (user_id, device_name, platform, push_token, now, now, session_token_hash, session_expires_at, now),
        )
        self.conn.commit()
        device_id = cursor.lastrowid
        logger.info("Nuevo dispositivo registrado con session token: id=%d", device_id)
        return device_id, session_token

    def active_devices(self) -> list[dict]:
        """Lista dispositivos activos."""
        rows = self.conn.execute(
            "SELECT * FROM mobile_devices WHERE active = 1 ORDER BY last_seen_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    def deactivate_device(self, device_id: int) -> None:
        """Desactiva un dispositivo."""
        self.conn.execute("UPDATE mobile_devices SET active = 0 WHERE id = ?", (device_id,))
        self.conn.commit()

    def deactivate_device_by_token(self, token: str, reason: str = "") -> None:
        """Desactiva un dispositivo por su token FCM (usado cuando FCM reporta token inválido)."""
        now = datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            "UPDATE mobile_devices SET active = 0, last_seen_at = ? WHERE push_token = ?",
            (now, token),
        )
        self.conn.commit()
        logger.info("Dispositivo desactivado por token inválido: %s... reason=%s", token[:12], reason)

    def update_device_token(self, device_id: int, new_token: str) -> None:
        """Actualiza el token FCM de un dispositivo (renovación de token)."""
        now = datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            "UPDATE mobile_devices SET push_token = ?, last_seen_at = ?, active = 1 WHERE id = ?",
            (new_token, now, device_id),
        )
        self.conn.commit()

    def _hash_session_token(self, token: str) -> str:
        """Genera hash SHA-256 del session token para almacenamiento seguro."""
        return hashlib.sha256(token.encode()).hexdigest()

    def validate_session_token(self, session_token: str) -> dict | None:
        """Valida un session token y retorna el dispositivo si es válido.
        
        También actualiza session_last_used_at.
        """
        session_token_hash = self._hash_session_token(session_token)
        now = datetime.now().isoformat(timespec="seconds")
        
        device = self.conn.execute(
            """SELECT id, device_name, platform, push_token, active, session_expires_at,
                      created_at, app_version
               FROM mobile_devices
               WHERE session_token_hash = ? AND active = 1""",
            (session_token_hash,),
        ).fetchone()
        
        if not device:
            logger.warning("Session token inválido o dispositivo inactivo")
            return None
        
        # Verificar expiración
        if device["session_expires_at"] and device["session_expires_at"] < now:
            logger.warning("Session token expirado para dispositivo id=%d", device["id"])
            return None
        
        # Actualizar last_used_at
        self.conn.execute(
            "UPDATE mobile_devices SET session_last_used_at = ? WHERE id = ?",
            (now, device["id"]),
        )
        self.conn.commit()
        
        # Convertir a dict con nombres de campos estables
        device_dict = dict(device)
        # Mapear created_at a registered_at para compatibilidad
        device_dict["registered_at"] = device_dict["created_at"]
        # is_paused se deriva de active (0 = pausado, 1 = activo)
        device_dict["is_paused"] = 0 if device_dict["active"] == 1 else 1
        
        return device_dict

    # ── Preferencias ───────────────────────────────────────────────────────

    def get_device_prefs(self, device_id: int) -> dict[str, bool]:
        """Obtiene las preferencias de notificación de un dispositivo."""
        rows = self.conn.execute(
            "SELECT event_type, enabled FROM device_notification_prefs WHERE device_id = ?",
            (device_id,),
        ).fetchall()
        return {row["event_type"]: bool(row["enabled"]) for row in rows}

    def set_device_pref(self, device_id: int, event_type: str, enabled: bool) -> None:
        """Establece una preferencia de notificación para un dispositivo."""
        self.conn.execute(
            """INSERT INTO device_notification_prefs(device_id, event_type, enabled)
               VALUES(?, ?, ?)
               ON CONFLICT(device_id, event_type) DO UPDATE SET enabled = excluded.enabled""",
            (device_id, event_type, int(enabled)),
        )
        self.conn.commit()

    # ── Códigos de emparejamiento ──────────────────────────────────────────

    def _hash_code(self, code: str) -> str:
        """Genera hash SHA-256 del código para almacenamiento seguro."""
        return hashlib.sha256(code.encode()).hexdigest()

    def create_pairing_code(self, installation_id: str = "studio-principal") -> str:
        """Genera un código temporal de 6 dígitos, válido 5 minutos, uso único.
        
        Retorna el código en texto plano (para mostrar al usuario) pero almacena el hash.
        """
        code = "".join(random.choices(string.digits, k=6))
        code_hash = self._hash_code(code)
        now = datetime.now()
        expires = (now + timedelta(minutes=5)).isoformat(timespec="seconds")
        self.conn.execute(
            "INSERT INTO pairing_codes(code_hash, installation_id, created_at, expires_at) VALUES(?, ?, ?, ?)",
            (code_hash, installation_id, now.isoformat(timespec="seconds"), expires),
        )
        self.conn.commit()
        return code

    def validate_pairing_code(self, code: str) -> dict | None:
        """Valida un código de emparejamiento. Devuelve info o None si inválido/expirado."""
        code_hash = self._hash_code(code)
        row = self.conn.execute(
            "SELECT * FROM pairing_codes WHERE code_hash = ? AND used = 0", (code_hash,)
        ).fetchone()
        if not row:
            return None
        record = dict(row)
        if datetime.fromisoformat(record["expires_at"]) < datetime.now():
            return None
        return record

    def consume_pairing_code(self, code: str) -> bool:
        """Marca un código como usado. Devuelve True si era válido."""
        code_hash = self._hash_code(code)
        now = datetime.now().isoformat(timespec="seconds")
        cursor = self.conn.execute(
            "UPDATE pairing_codes SET used = 1 WHERE code_hash = ? AND used = 0", (code_hash,)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def register_device_with_pairing(
        self,
        pairing_code: str,
        push_token: str,
        platform: str,
        device_name: str = "",
        app_version: str = "",
    ) -> tuple[bool, str, int | None, str]:
        """Registra un dispositivo usando código de emparejamiento.
        
        Returns:
            (success, message, device_id, session_token)
        """
        # Validar código
        pairing_record = self.validate_pairing_code(pairing_code)
        if not pairing_record:
            return False, "Código inválido o expirado", None, ""
        
        # Consumir código (uso único)
        if not self.consume_pairing_code(pairing_code):
            return False, "Código ya utilizado", None, ""
        
        # Registrar dispositivo y obtener session token
        device_id, session_token = self.register_device(
            push_token=push_token,
            platform=platform,
            device_name=device_name,
        )
        
        return True, "Dispositivo registrado exitosamente", device_id, session_token

    def update_device_token_safe(self, old_token: str, new_token: str) -> bool:
        """Actualiza token FCM de forma segura, desactivando el anterior si existe."""
        now = datetime.now().isoformat(timespec="seconds")
        
        # Verificar si el nuevo token ya existe
        existing = self.conn.execute(
            "SELECT id FROM mobile_devices WHERE push_token = ?", (new_token,)
        ).fetchone()
        if existing:
            # El nuevo token ya está registrado, actualizar last_seen
            self.conn.execute(
                "UPDATE mobile_devices SET last_seen_at = ? WHERE push_token = ?",
                (now, new_token),
            )
            self.conn.commit()
            return True
        
        # Desactivar dispositivo con token anterior
        self.conn.execute(
            "UPDATE mobile_devices SET active = 0, last_seen_at = ? WHERE push_token = ?",
            (now, old_token),
        )
        
        # Crear nuevo registro con el mismo device_name si existe
        old_device = self.conn.execute(
            "SELECT device_name FROM mobile_devices WHERE push_token = ?", (old_token,)
        ).fetchone()
        
        device_name = old_device["device_name"] if old_device else ""
        
        # Insertar nuevo dispositivo
        cursor = self.conn.execute(
            """INSERT INTO mobile_devices(device_name, platform, push_token, active, last_seen_at, created_at)
               VALUES(?, ?, ?, 1, ?, ?)""",
            (device_name, "android", new_token, now, now),
        )
        self.conn.commit()
        return True

    def pause_device(self, device_id: int) -> None:
        """Pausa temporalmente un dispositivo (no recibe notificaciones)."""
        now = datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            "UPDATE mobile_devices SET active = 0, last_seen_at = ? WHERE id = ?",
            (now, device_id),
        )
        self.conn.commit()

    def resume_device(self, device_id: int) -> None:
        """Reactiva un dispositivo pausado."""
        now = datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            "UPDATE mobile_devices SET active = 1, last_seen_at = ? WHERE id = ?",
            (now, device_id),
        )
        self.conn.commit()

    def rename_device(self, device_id: int, new_name: str) -> None:
        """Cambia el nombre de un dispositivo."""
        self.conn.execute(
            "UPDATE mobile_devices SET device_name = ? WHERE id = ?",
            (new_name, device_id),
        )
        self.conn.commit()

    def unlink_device(self, device_id: int) -> None:
        """Desvincula completamente un dispositivo."""
        self.deactivate_device(device_id)

    def cleanup_expired_pairing_codes(self) -> None:
        """Elimina códigos expirados o ya usados (más de 1 hora)."""
        cutoff = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
        self.conn.execute(
            "DELETE FROM pairing_codes WHERE used = 1 OR expires_at < ?", (cutoff,)
        )
        self.conn.commit()

    # ── Estadísticas ───────────────────────────────────────────────────────

    def outbox_stats(self) -> dict:
        """Estadísticas del outbox."""
        row = self.conn.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) as processing,
                SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END) as sent,
                SUM(CASE WHEN status = 'dead_letter' THEN 1 ELSE 0 END) as dead
               FROM notification_outbox"""
        ).fetchone()
        return dict(row) if row else {"total": 0, "pending": 0, "processing": 0, "sent": 0, "dead": 0}
