"""Interfaz de escritorio para administrar el acceso a la API móvil."""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from app.security.mobile_access import MobileAccessRepository, MobileIPRule
from app.security.mobile_users import (
    MobileUser,
    MobileUserRepository,
)
from app.ui.theme import COLORS, IDENTITY_FONT, UI_FONT


EVENT_LABELS = {
    "authentication_failed": "Autenticación fallida",
    "invalid_client_ip": "IP inválida",
    "rate_limit_blocked": "Rate limit excedido",
    "rule_added": "Regla agregada",
    "rule_deleted": "Regla eliminada",
    "rule_updated": "Regla modificada",
    "whitelist_blocked": "Acceso bloqueado",
    "whitelist_disabled": "Whitelist deshabilitada",
    "whitelist_enabled": "Whitelist habilitada",
    "pairing_failed": "Enlace fallido",
    "seller_device_linked": "Dispositivo enlazado",
    "seller_logout": "Sesión cerrada",
    "seller_login_failed": "Login fallido",
    "seller_login_success": "Login correcto",
    "seller_password_reset": "Contraseña cambiada",
    "seller_account_unlocked": "Cuenta desbloqueada",
    "seller_status_changed": "Estado de vendedor",
    "seller_user_created": "Vendedor creado",
    "insecure_credentials_blocked": "HTTP público bloqueado",
}


def _display_date(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "—"
    return raw[:16].replace("T", " ")


class MobileSecurityPanel(tk.Frame):
    """Panel embebible que gestiona reglas IP y aplica los cambios al instante."""

    def __init__(
        self,
        parent: tk.Widget,
        repository: MobileAccessRepository,
        users_repository: MobileUserRepository | None = None,
        status_callback: Callable[[str], None] | None = None,
    ):
        super().__init__(parent, background=COLORS.panel)
        self.repository = repository
        self.users_repository = users_repository
        self.status_callback = status_callback or (lambda _message: None)
        self.enabled_var = tk.BooleanVar(value=self.repository.enabled)
        self.summary_var = tk.StringVar()
        self.state_var = tk.StringVar()
        self._build()
        self.refresh()

    def _build(self) -> None:
        self.pack(fill="both", expand=True)

        heading = tk.Frame(self, background=COLORS.panel)
        heading.pack(fill="x", padx=16, pady=(14, 8))
        title_column = tk.Frame(heading, background=COLORS.panel)
        title_column.pack(side="left", fill="x", expand=True)
        tk.Label(
            title_column,
            text="ACCESO A LA APP MÓVIL",
            background=COLORS.panel,
            foreground=COLORS.wine_active,
            font=(IDENTITY_FONT, 12, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title_column,
            text=(
                "Permití IPs individuales o redes CIDR. Los cambios se aplican "
                "sin reiniciar Studio."
            ),
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 9),
            justify="left",
        ).pack(anchor="w", pady=(3, 0))
        if self.users_repository is not None:
            ttk.Button(
                heading,
                text="Vendedores y contraseñas",
                command=self.open_users,
                style="Primary.TButton",
            ).pack(side="right", padx=(12, 0))

        status_card = tk.Frame(
            self,
            background=COLORS.panel_elevated,
            highlightthickness=1,
            highlightbackground=COLORS.border,
        )
        status_card.pack(fill="x", padx=16, pady=(0, 10))
        status_inner = tk.Frame(status_card, background=COLORS.panel_elevated)
        status_inner.pack(fill="x", padx=12, pady=9)
        self.enable_check = ttk.Checkbutton(
            status_inner,
            text="Habilitar whitelist de IPs",
            variable=self.enabled_var,
            command=self._toggle_whitelist,
        )
        self.enable_check.pack(side="left")
        tk.Label(
            status_inner,
            textvariable=self.state_var,
            background=COLORS.panel_elevated,
            foreground=COLORS.muted,
            font=(UI_FONT, 9, "bold"),
        ).pack(side="right")
        tk.Label(
            status_card,
            text=(
                "Para que los vendedores trabajen desde cualquier red o datos "
                "móviles, mantené la whitelist deshabilitada."
            ),
            background=COLORS.panel_elevated,
            foreground=COLORS.warning,
            font=(UI_FONT, 8),
            justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 9))

        table_shell = tk.Frame(self, background=COLORS.panel)
        table_shell.pack(fill="both", expand=True, padx=16)
        columns = ("active", "address", "description", "created", "last_access")
        self.tree = ttk.Treeview(
            table_shell,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=8,
        )
        headings = {
            "active": ("Estado", 72, "center"),
            "address": ("IP o red CIDR", 155, "w"),
            "description": ("Descripción", 205, "w"),
            "created": ("Creada", 115, "center"),
            "last_access": ("Último acceso", 115, "center"),
        }
        for column, (label, width, anchor) in headings.items():
            self.tree.heading(column, text=label)
            self.tree.column(
                column,
                width=width,
                minwidth=60,
                anchor=anchor,
                stretch=column == "description",
            )
        scrollbar = ttk.Scrollbar(
            table_shell, orient="vertical", command=self.tree.yview
        )
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _event: self.edit_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._update_actions())

        lower = tk.Frame(self, background=COLORS.panel)
        lower.pack(fill="x", padx=16, pady=(10, 14))
        tk.Label(
            lower,
            textvariable=self.summary_var,
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 8),
        ).pack(side="left")

        actions = tk.Frame(lower, background=COLORS.panel)
        actions.pack(side="right")
        ttk.Button(
            actions,
            text="Registro",
            command=self.open_audit_log,
            style="Secondary.TButton",
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            actions,
            text="Agregar",
            command=self.add_rule,
            style="Primary.TButton",
        ).pack(side="left", padx=(0, 6))
        self.edit_button = ttk.Button(
            actions,
            text="Editar",
            command=self.edit_selected,
            style="Secondary.TButton",
        )
        self.edit_button.pack(side="left", padx=(0, 6))
        self.active_button = ttk.Button(
            actions,
            text="Activar",
            command=self.toggle_selected_rule,
            style="Secondary.TButton",
        )
        self.active_button.pack(side="left", padx=(0, 6))
        self.delete_button = ttk.Button(
            actions,
            text="Eliminar",
            command=self.delete_selected,
            style="Danger.TButton",
        )
        self.delete_button.pack(side="left")

    def refresh(self, selected_id: int | None = None) -> None:
        rules = self.repository.list_rules()
        selected_id = selected_id or self._selected_rule_id()
        self.tree.delete(*self.tree.get_children())
        for rule in rules:
            self.tree.insert(
                "",
                "end",
                iid=str(rule.id),
                values=(
                    "Activa" if rule.active else "Inactiva",
                    rule.ip_address,
                    rule.description or "—",
                    _display_date(rule.created_at),
                    _display_date(rule.last_matched_at),
                ),
                tags=("active",) if rule.active else ("inactive",),
            )
        self.tree.tag_configure("inactive", foreground=COLORS.disabled)
        active_count = sum(1 for rule in rules if rule.active)
        self.summary_var.set(
            f"{active_count} regla(s) activa(s) · {len(rules)} en total"
        )
        self.enabled_var.set(self.repository.enabled)
        self.state_var.set(
            "PROTECCIÓN ACTIVA" if self.repository.enabled else "ACCESO SIN FILTRO IP"
        )
        if selected_id is not None and self.tree.exists(str(selected_id)):
            self.tree.selection_set(str(selected_id))
            self.tree.focus(str(selected_id))
        self._update_actions()

    def _selected_rule_id(self) -> int | None:
        selection = self.tree.selection() if hasattr(self, "tree") else ()
        return int(selection[0]) if selection else None

    def _selected_rule(self) -> MobileIPRule | None:
        rule_id = self._selected_rule_id()
        return self.repository.get_rule(rule_id) if rule_id is not None else None

    def _update_actions(self) -> None:
        rule = self._selected_rule()
        state = "normal" if rule else "disabled"
        self.edit_button.configure(state=state)
        self.delete_button.configure(state=state)
        self.active_button.configure(
            state=state, text="Desactivar" if rule and rule.active else "Activar"
        )

    def _toggle_whitelist(self) -> None:
        requested = bool(self.enabled_var.get())
        if requested:
            confirmed = messagebox.askyesno(
                "Habilitar whitelist",
                (
                    "Solo podrán acceder los dispositivos cuya IP coincida con "
                    "una regla activa.\n\n¿Querés habilitarla ahora?"
                ),
                parent=self.winfo_toplevel(),
            )
            if not confirmed:
                self.enabled_var.set(False)
                return
        try:
            self.repository.set_enabled(requested)
        except ValueError as error:
            self.enabled_var.set(self.repository.enabled)
            messagebox.showerror(
                "No se pudo cambiar la whitelist",
                str(error),
                parent=self.winfo_toplevel(),
            )
            return
        action = "habilitada" if requested else "deshabilitada"
        self.status_callback(f"Whitelist de acceso móvil {action}.")
        self.refresh()

    def add_rule(self) -> None:
        RuleEditorDialog(
            self.winfo_toplevel(),
            title="Agregar IP permitida",
            on_save=self._save_new_rule,
        )

    def _save_new_rule(
        self, address: str, description: str, active: bool
    ) -> MobileIPRule:
        rule = self.repository.add_rule(address, description, active)
        self.refresh(rule.id)
        self.status_callback(f"Se agregó {rule.ip_address} a la whitelist.")
        return rule

    def edit_selected(self) -> None:
        rule = self._selected_rule()
        if rule is None:
            return
        RuleEditorDialog(
            self.winfo_toplevel(),
            title="Editar IP permitida",
            rule=rule,
            on_save=lambda address, description, active: self._save_rule(
                rule.id, address, description, active
            ),
        )

    def _save_rule(
        self, rule_id: int, address: str, description: str, active: bool
    ) -> MobileIPRule:
        rule = self.repository.update_rule(
            rule_id, address, description, active=active
        )
        self.refresh(rule.id)
        self.status_callback(f"Se actualizó la regla {rule.ip_address}.")
        return rule

    def toggle_selected_rule(self) -> None:
        rule = self._selected_rule()
        if rule is None:
            return
        try:
            updated = self.repository.set_rule_active(rule.id, not rule.active)
        except ValueError as error:
            messagebox.showerror(
                "No se pudo cambiar la regla",
                str(error),
                parent=self.winfo_toplevel(),
            )
            return
        self.refresh(updated.id)
        state = "activó" if updated.active else "desactivó"
        self.status_callback(f"Se {state} la regla {updated.ip_address}.")

    def delete_selected(self) -> None:
        rule = self._selected_rule()
        if rule is None:
            return
        if not messagebox.askyesno(
            "Eliminar regla",
            f"¿Eliminar {rule.ip_address} de la whitelist?",
            parent=self.winfo_toplevel(),
        ):
            return
        try:
            self.repository.delete_rule(rule.id)
        except ValueError as error:
            messagebox.showerror(
                "No se pudo eliminar",
                str(error),
                parent=self.winfo_toplevel(),
            )
            return
        self.refresh()
        self.status_callback(f"Se eliminó {rule.ip_address} de la whitelist.")

    def open_users(self) -> None:
        if self.users_repository is None:
            return
        MobileUsersDialog(
            self.winfo_toplevel(),
            repository=self.users_repository,
            access_audit=self.repository,
            status_callback=self.status_callback,
        )

    def open_audit_log(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Registro de seguridad móvil")
        dialog.configure(background=COLORS.background)
        dialog.transient(self.winfo_toplevel())
        dialog.geometry("820x460")
        dialog.minsize(680, 360)

        header = tk.Frame(dialog, background=COLORS.panel)
        header.pack(fill="x", padx=12, pady=(12, 0))
        tk.Label(
            header,
            text="REGISTRO DE SEGURIDAD MÓVIL",
            background=COLORS.panel,
            foreground=COLORS.wine_active,
            font=(IDENTITY_FONT, 13, "bold"),
        ).pack(anchor="w", padx=14, pady=(10, 2))
        tk.Label(
            header,
            text="Cambios de configuración, bloqueos y autenticaciones fallidas.",
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 9),
        ).pack(anchor="w", padx=14, pady=(0, 10))

        shell = tk.Frame(dialog, background=COLORS.background)
        shell.pack(fill="both", expand=True, padx=12, pady=12)
        columns = ("date", "event", "ip", "endpoint", "details")
        tree = ttk.Treeview(shell, columns=columns, show="headings")
        config = {
            "date": ("Fecha", 125),
            "event": ("Evento", 145),
            "ip": ("IP / regla", 125),
            "endpoint": ("Endpoint", 185),
            "details": ("Detalle", 190),
        }
        for column, (label, width) in config.items():
            tree.heading(column, text=label)
            tree.column(
                column,
                width=width,
                minwidth=70,
                stretch=column in {"endpoint", "details"},
            )
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for event in self.repository.recent_audit_events(limit=200):
            details = str(event.get("details") or "")
            if details.startswith("{"):
                try:
                    parsed = json.loads(details)
                    details = " · ".join(
                        f"{key}: {value}" for key, value in parsed.items()
                    )
                except (json.JSONDecodeError, TypeError):
                    pass
            event_type = str(event.get("event_type") or "")
            tree.insert(
                "",
                "end",
                values=(
                    _display_date(str(event.get("created_at") or "")),
                    EVENT_LABELS.get(event_type, event_type),
                    str(event.get("ip_address") or "—"),
                    str(event.get("endpoint") or "—"),
                    details or "—",
                ),
            )

        footer = tk.Frame(dialog, background=COLORS.background)
        footer.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(
            footer,
            text="Cerrar",
            command=dialog.destroy,
            style="Secondary.TButton",
        ).pack(side="right")


class MobileUsersDialog(tk.Toplevel):
    """Administración de credenciales y revocación de vendedores."""

    def __init__(
        self,
        parent: tk.Widget,
        *,
        repository: MobileUserRepository,
        access_audit: MobileAccessRepository,
        status_callback: Callable[[str], None],
    ):
        super().__init__(parent)
        self.repository = repository
        self.access_audit = access_audit
        self.status_callback = status_callback
        self.title("Vendedores de la app móvil")
        self.configure(background=COLORS.background)
        self.transient(parent)
        self.geometry("860x520")
        self.minsize(720, 420)
        self._build()
        self.refresh()

    def _build(self) -> None:
        header = tk.Frame(
            self,
            background=COLORS.panel,
            highlightthickness=1,
            highlightbackground=COLORS.border,
        )
        header.pack(fill="x", padx=12, pady=(12, 0))
        tk.Label(
            header,
            text="VENDEDORES Y CONTRASEÑAS",
            background=COLORS.panel,
            foreground=COLORS.wine_active,
            font=(IDENTITY_FONT, 13, "bold"),
        ).pack(anchor="w", padx=14, pady=(10, 2))
        tk.Label(
            header,
            text=(
                "El vendedor inicia sesión una vez, ingresa el código de Studio "
                "y luego accede automáticamente desde su dispositivo."
            ),
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 9),
        ).pack(anchor="w", padx=14, pady=(0, 10))

        shell = tk.Frame(self, background=COLORS.background)
        shell.pack(fill="both", expand=True, padx=12, pady=12)
        columns = ("status", "username", "name", "devices", "last_login", "locked")
        self.tree = ttk.Treeview(
            shell, columns=columns, show="headings", selectmode="browse"
        )
        config = {
            "status": ("Estado", 85, "center"),
            "username": ("Usuario", 130, "w"),
            "name": ("Vendedor", 185, "w"),
            "devices": ("Dispositivos", 85, "center"),
            "last_login": ("Último login", 125, "center"),
            "locked": ("Bloqueo", 125, "center"),
        }
        for column, (label, width, anchor) in config.items():
            self.tree.heading(column, text=label)
            self.tree.column(
                column,
                width=width,
                minwidth=70,
                anchor=anchor,
                stretch=column == "name",
            )
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._update_actions())

        footer = tk.Frame(self, background=COLORS.background)
        footer.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(
            footer,
            text="Cerrar",
            command=self.destroy,
            style="Secondary.TButton",
        ).pack(side="right")
        ttk.Button(
            footer,
            text="Agregar vendedor",
            command=self.add_user,
            style="Primary.TButton",
        ).pack(side="left")
        self.password_button = ttk.Button(
            footer,
            text="Cambiar contraseña",
            command=self.reset_password,
            style="Secondary.TButton",
        )
        self.password_button.pack(side="left", padx=(8, 0))
        self.active_button = ttk.Button(
            footer,
            text="Desactivar",
            command=self.toggle_active,
            style="Danger.TButton",
        )
        self.active_button.pack(side="left", padx=(8, 0))
        self.unlock_button = ttk.Button(
            footer,
            text="Desbloquear",
            command=self.unlock,
            style="Secondary.TButton",
        )
        self.unlock_button.pack(side="left", padx=(8, 0))

    def refresh(self, selected_id: int | None = None) -> None:
        selected_id = selected_id or self._selected_id()
        self.tree.delete(*self.tree.get_children())
        for user in self.repository.list_users():
            self.tree.insert(
                "",
                "end",
                iid=str(user.id),
                values=(
                    "Activo" if user.active else "Inactivo",
                    user.username,
                    user.display_name,
                    user.device_count,
                    _display_date(user.last_login_at),
                    _display_date(user.locked_until),
                ),
                tags=("active",) if user.active else ("inactive",),
            )
        self.tree.tag_configure("inactive", foreground=COLORS.disabled)
        if selected_id is not None and self.tree.exists(str(selected_id)):
            self.tree.selection_set(str(selected_id))
        elif self.tree.get_children():
            self.tree.selection_set(self.tree.get_children()[0])
        self._update_actions()

    def _selected_id(self) -> int | None:
        selection = self.tree.selection() if hasattr(self, "tree") else ()
        return int(selection[0]) if selection else None

    def _selected_user(self) -> MobileUser | None:
        user_id = self._selected_id()
        return self.repository.get_user(user_id) if user_id is not None else None

    def _update_actions(self) -> None:
        user = self._selected_user()
        state = "normal" if user else "disabled"
        self.password_button.configure(state=state)
        self.active_button.configure(
            state=state,
            text="Desactivar" if user and user.active else "Reactivar",
            style="Danger.TButton" if user and user.active else "Primary.TButton",
        )
        self.unlock_button.configure(
            state="normal" if user and user.locked_until else "disabled"
        )

    def add_user(self) -> None:
        MobileUserEditorDialog(
            self,
            title="Agregar vendedor",
            username_enabled=True,
            on_save=self._create_user,
        )

    def _create_user(
        self, username: str, display_name: str, password: str
    ) -> MobileUser:
        user = self.repository.create_user(username, display_name, password)
        self.access_audit.audit_event(
            "seller_user_created",
            details={"user_id": user.id, "username": user.username},
            throttle_seconds=0,
        )
        self.refresh(user.id)
        self.status_callback(f"Vendedor {user.username} creado.")
        return user

    def reset_password(self) -> None:
        user = self._selected_user()
        if user is None:
            return
        if not messagebox.askyesno(
            "Cambiar contraseña",
            (
                "Cambiar la contraseña revocará los dispositivos enlazados. "
                "El vendedor deberá iniciar sesión y vincularse nuevamente.\n\n"
                "¿Continuar?"
            ),
            parent=self,
        ):
            return
        MobileUserEditorDialog(
            self,
            title=f"Nueva contraseña · {user.username}",
            username=user.username,
            display_name=user.display_name,
            username_enabled=False,
            on_save=lambda _username, _name, password: self._save_password(
                user, password
            ),
        )

    def _save_password(self, user: MobileUser, password: str) -> MobileUser:
        self.repository.reset_password(user.id, password)
        self.access_audit.audit_event(
            "seller_password_reset",
            details={"user_id": user.id, "username": user.username},
            throttle_seconds=0,
        )
        self.refresh(user.id)
        self.status_callback(f"Contraseña de {user.username} actualizada.")
        updated = self.repository.get_user(user.id)
        if updated is None:
            raise RuntimeError("No se pudo recuperar el vendedor.")
        return updated

    def toggle_active(self) -> None:
        user = self._selected_user()
        if user is None:
            return
        target = not user.active
        if not target and not messagebox.askyesno(
            "Desactivar vendedor",
            (
                f"¿Desactivar a {user.display_name or user.username}?\n\n"
                "Sus sesiones y dispositivos quedarán revocados inmediatamente."
            ),
            parent=self,
        ):
            return
        updated = self.repository.set_active(user.id, target)
        self.access_audit.audit_event(
            "seller_status_changed",
            details={
                "user_id": updated.id,
                "username": updated.username,
                "active": updated.active,
            },
            throttle_seconds=0,
        )
        self.refresh(updated.id)
        state = "reactivado" if target else "desactivado"
        self.status_callback(f"Vendedor {updated.username} {state}.")

    def unlock(self) -> None:
        user = self._selected_user()
        if user is None:
            return
        self.repository.unlock(user.id)
        self.access_audit.audit_event(
            "seller_account_unlocked",
            details={"user_id": user.id, "username": user.username},
            throttle_seconds=0,
        )
        self.refresh(user.id)
        self.status_callback(f"Cuenta {user.username} desbloqueada.")


class MobileUserEditorDialog(tk.Toplevel):
    """Formulario de alta o cambio de contraseña."""

    def __init__(
        self,
        parent: tk.Widget,
        *,
        title: str,
        on_save: Callable[[str, str, str], MobileUser],
        username: str = "",
        display_name: str = "",
        username_enabled: bool = True,
    ):
        super().__init__(parent)
        self.on_save = on_save
        self.title(title)
        self.configure(background=COLORS.background)
        self.transient(parent)
        self.grab_set()
        self.geometry("470x365")
        self.resizable(False, False)

        body = tk.Frame(
            self,
            background=COLORS.panel,
            highlightthickness=1,
            highlightbackground=COLORS.border,
        )
        body.pack(fill="both", expand=True, padx=14, pady=14)
        tk.Label(
            body,
            text=title.upper(),
            background=COLORS.panel,
            foreground=COLORS.wine_active,
            font=(IDENTITY_FONT, 12, "bold"),
        ).pack(anchor="w", padx=14, pady=(14, 10))
        form = tk.Frame(body, background=COLORS.panel)
        form.pack(fill="x", padx=14)

        self.username_var = tk.StringVar(value=username)
        self.name_var = tk.StringVar(value=display_name)
        self.password_var = tk.StringVar()
        self.confirm_var = tk.StringVar()

        self._field(form, "Usuario", self.username_var, enabled=username_enabled)
        self._field(
            form,
            "Nombre del vendedor",
            self.name_var,
            enabled=username_enabled,
        )
        self._field(form, "Contraseña", self.password_var, secret=True)
        self._field(form, "Repetir contraseña", self.confirm_var, secret=True)
        tk.Label(
            form,
            text="Mínimo 10 caracteres, con letras y números.",
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 8),
        ).pack(anchor="w", pady=(0, 8))

        actions = tk.Frame(body, background=COLORS.panel)
        actions.pack(fill="x", padx=14, pady=10)
        ttk.Button(
            actions,
            text="Cancelar",
            command=self.destroy,
            style="Secondary.TButton",
        ).pack(side="right")
        ttk.Button(
            actions,
            text="Guardar",
            command=self._save,
            style="Primary.TButton",
        ).pack(side="right", padx=(0, 8))
        self.bind("<Return>", lambda _event: self._save())
        self.bind("<Escape>", lambda _event: self.destroy())

    @staticmethod
    def _field(
        parent: tk.Widget,
        label: str,
        variable: tk.StringVar,
        *,
        secret: bool = False,
        enabled: bool = True,
    ) -> None:
        tk.Label(
            parent,
            text=label,
            background=COLORS.panel,
            foreground=COLORS.text,
            font=(UI_FONT, 9, "bold"),
        ).pack(anchor="w")
        ttk.Entry(
            parent,
            textvariable=variable,
            show="•" if secret else "",
            state="normal" if enabled else "disabled",
        ).pack(fill="x", pady=(3, 8))

    def _save(self) -> None:
        if self.password_var.get() != self.confirm_var.get():
            messagebox.showerror(
                "Contraseñas diferentes",
                "Las contraseñas no coinciden.",
                parent=self,
            )
            return
        try:
            self.on_save(
                self.username_var.get(),
                self.name_var.get(),
                self.password_var.get(),
            )
        except (ValueError, RuntimeError) as error:
            messagebox.showerror("No se pudo guardar", str(error), parent=self)
            return
        self.destroy()


class RuleEditorDialog(tk.Toplevel):
    """Diálogo pequeño y validado para crear o modificar una regla."""

    def __init__(
        self,
        parent: tk.Widget,
        *,
        title: str,
        on_save: Callable[[str, str, bool], MobileIPRule],
        rule: MobileIPRule | None = None,
    ):
        super().__init__(parent)
        self.on_save = on_save
        self.title(title)
        self.configure(background=COLORS.background)
        self.transient(parent)
        self.grab_set()
        self.geometry("470x285")
        self.resizable(False, False)

        body = tk.Frame(
            self,
            background=COLORS.panel,
            highlightthickness=1,
            highlightbackground=COLORS.border,
        )
        body.pack(fill="both", expand=True, padx=14, pady=14)
        tk.Label(
            body,
            text=title.upper(),
            background=COLORS.panel,
            foreground=COLORS.wine_active,
            font=(IDENTITY_FONT, 12, "bold"),
        ).pack(anchor="w", padx=14, pady=(14, 10))

        form = tk.Frame(body, background=COLORS.panel)
        form.pack(fill="x", padx=14)
        tk.Label(
            form,
            text="Dirección IP o red CIDR",
            background=COLORS.panel,
            foreground=COLORS.text,
            font=(UI_FONT, 9, "bold"),
        ).pack(anchor="w")
        self.address_var = tk.StringVar(value=rule.ip_address if rule else "")
        address_entry = ttk.Entry(form, textvariable=self.address_var)
        address_entry.pack(fill="x", pady=(4, 3))
        tk.Label(
            form,
            text="Ejemplos: 203.0.113.8 · 192.168.1.0/24 · 2001:db8::/48",
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 8),
        ).pack(anchor="w")

        tk.Label(
            form,
            text="Descripción",
            background=COLORS.panel,
            foreground=COLORS.text,
            font=(UI_FONT, 9, "bold"),
        ).pack(anchor="w", pady=(10, 0))
        self.description_var = tk.StringVar(value=rule.description if rule else "")
        ttk.Entry(form, textvariable=self.description_var).pack(
            fill="x", pady=(4, 7)
        )
        self.active_var = tk.BooleanVar(value=rule.active if rule else True)
        ttk.Checkbutton(
            form, text="Regla activa", variable=self.active_var
        ).pack(anchor="w")

        actions = tk.Frame(body, background=COLORS.panel)
        actions.pack(fill="x", padx=14, pady=13)
        ttk.Button(
            actions,
            text="Cancelar",
            command=self.destroy,
            style="Secondary.TButton",
        ).pack(side="right")
        ttk.Button(
            actions,
            text="Guardar",
            command=self._save,
            style="Primary.TButton",
        ).pack(side="right", padx=(0, 8))

        address_entry.focus_set()
        self.bind("<Return>", lambda _event: self._save())
        self.bind("<Escape>", lambda _event: self.destroy())

    def _save(self) -> None:
        try:
            self.on_save(
                self.address_var.get(),
                self.description_var.get(),
                bool(self.active_var.get()),
            )
        except (ValueError, RuntimeError) as error:
            messagebox.showerror("No se pudo guardar", str(error), parent=self)
            return
        self.destroy()
