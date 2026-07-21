import re
import tkinter as tk
import calendar
import sys
import os
import threading
import subprocess
import json
import webbrowser
import time
import csv
import zipfile
import tempfile
import traceback
from pathlib import Path
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from app.database.database import ImageDatabase
from app.indexer.scanner import scan_folder
from app.ui.gallery import Gallery
from app.ui.search import SearchBar
from app.ui.theme import (
    COLORS,
    IDENTITY_FONT,
    UI_FONT,
    ORDER_STATUS_STYLES,
    PRIORITY_STYLES,
    apply_ttk_theme,
    configure_menu,
    format_currency,
    normalize_order_style_key,
)
from app.ui.components import (
    Toast,
    build_order_notification_payload,
    navigation_button,
    section_heading,
    set_navigation_active,
    status_strip,
)
from app.events.event_bus import EventBus
from app.events.event_repository import EventRepository
from app.events.event_types import (
    EVENT_TYPE_LABELS,
    EVENT_ICONS,
    PRIORITY_HIGH,
    PRIORITY_NORMAL,
    ORDER_CREATED,
    ORDER_COMPLETED,
    PAYMENT_RECEIVED,
    PRODUCTION_STARTED,
    PRODUCTION_COMPLETED,
    PRODUCTION_ERROR,
    STOCK_LOW,
)
from app.notifications.notification_service import NotificationService
from app.notifications.firebase_sender import initialize_firebase
from app.api.pairing_server import PairingServer
from app.api.mobile_jobs import MobileJobsServer
from app.stickers.editor import StickerStudio
from app.performance import record_performance
from app.workflow.priority import calculate_priority, get_priority_color, get_priority_emoji
from app.workflow.timeline import get_current_stage, format_timeline, get_stage_progress, order_statuses
from app.workflow.estimator import estimate_remaining_work, format_time_remaining, format_work_time
from app.workflow.dashboard import show_attention_dashboard
from costos.models.cost_component import CostComponent
from costos.models.cost_rule import CostRule
from costos.services.cost_calculator import CostCalculator
from costos.validators.cost_rule_validator import CostRuleValidator
try:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    HAS_MATPLOTLIB = True
except Exception:
    HAS_MATPLOTLIB = False

PRIORITY_LABELS = ("Sin prisa", "Baja", "Media", "Alta", "Urgente")
PRIORITY_VALUES = {label: value for value, label in enumerate(PRIORITY_LABELS)}


def priority_label(value) -> str:
    """Convierte el valor histórico de prioridad en una etiqueta legible."""
    if str(value) in PRIORITY_VALUES:
        return str(value)
    try:
        return PRIORITY_LABELS[min(len(PRIORITY_LABELS) - 1, max(0, int(value or 0)))]
    except (TypeError, ValueError):
        return "Sin prisa"


class CalendarDialog(tk.Toplevel):
    """Calendario liviano para elegir una fecha ISO sin dependencias externas."""

    def __init__(self, parent, target: tk.StringVar):
        super().__init__(parent)
        self.target = target
        self.configure(background=COLORS.panel)
        self.resizable(False, False)
        self.transient(parent)
        self.title("Elegir fecha")
        
        # Hacer que el calendario sea modal y se cierre con Escape o clic fuera
        self.grab_set()
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<FocusOut>", self._on_focus_out)
        
        try:
            selected = datetime.fromisoformat(target.get().strip()[:10])
        except ValueError:
            selected = datetime.now()
        self.year, self.month = selected.year, selected.month
        self.header = tk.StringVar()
        self.days = tk.Frame(self, background=COLORS.panel)

        controls = tk.Frame(self, background=COLORS.panel)
        controls.pack(fill="x", padx=10, pady=(10, 5))
        tk.Button(controls, text="‹", command=lambda: self.change_month(-1), width=3).pack(side="left")
        tk.Label(controls, textvariable=self.header, background=COLORS.panel, foreground=COLORS.text,
                 font=(UI_FONT, 10, "bold")).pack(side="left", expand=True)
        tk.Button(controls, text="›", command=lambda: self.change_month(1), width=3).pack(side="right")
        weekdays = tk.Frame(self, background=COLORS.panel)
        weekdays.pack(fill="x", padx=10)
        for column, name in enumerate(("Lu", "Ma", "Mi", "Ju", "Vi", "Sa", "Do")):
            tk.Label(weekdays, text=name, width=4, background=COLORS.panel, foreground=COLORS.muted,
                     font=(UI_FONT, 9, "bold")).grid(row=0, column=column, padx=1, pady=(0, 3))
        self.days.pack(padx=10, pady=(0, 10))
        self.render_days()
        
        # Centrar el calendario sobre la ventana padre
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (self.winfo_width() // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{x}+{y}")
    
    def _on_focus_out(self, event):
        """Cerrar el calendario cuando pierde el foco, pero solo si el nuevo foco está fuera del calendario."""
        # Verificar que el nuevo widget con foco no sea parte del calendario
        try:
            focus_widget = self.focus_get()
            if focus_widget is None or focus_widget.winfo_toplevel() != self:
                self.destroy()
        except (tk.TclError, AttributeError):
            # Si hay error al obtener el foco, cerrar el calendario
            self.destroy()

    def change_month(self, offset: int):
        self.month += offset
        if self.month == 13:
            self.month, self.year = 1, self.year + 1
        elif self.month == 0:
            self.month, self.year = 12, self.year - 1
        self.render_days()

    def render_days(self):
        for widget in self.days.winfo_children():
            widget.destroy()
        self.header.set(f"{calendar.month_name[self.month]} {self.year}")
        for row, week in enumerate(calendar.monthcalendar(self.year, self.month)):
            for column, day in enumerate(week):
                if not day:
                    tk.Label(self.days, text="", width=4, background=COLORS.panel).grid(row=row, column=column, padx=1, pady=1)
                    continue
                tk.Button(
                    self.days, text=str(day), width=4,
                    command=lambda current=day: self.select_day(current),
                ).grid(row=row, column=column, padx=1, pady=1)

    def select_day(self, day: int):
        self.target.set(f"{self.year:04d}-{self.month:02d}-{day:02d}")
        self.destroy()

# La dependencia se instala una vez dentro del proyecto para que el acceso directo
# también pueda usar el arrastre aunque Python no tenga permisos sobre el perfil.
_runtime_dir = Path(__file__).parents[2] / "runtime_deps"
if _runtime_dir.exists() and str(_runtime_dir) not in sys.path:
    sys.path.append(str(_runtime_dir))


# Al abrirse con pyw.exe, Windows puede omitir las librerías instaladas en el
# perfil del usuario. Se añade explícitamente ese directorio para la IA local.
_user_site = Path(os.environ.get("APPDATA", "")) / "Python" / f"Python{sys.version_info.major}{sys.version_info.minor}" / "site-packages"
if str(_user_site) not in sys.path:
    sys.path.insert(0, str(_user_site))

try:
    from tkinterdnd2 import TkinterDnD
    DndRoot = TkinterDnD.Tk
except (ImportError, OSError, PermissionError):
    DndRoot = tk.Tk


class VisionVaultApp(DndRoot):
    # Flujo inicial; cada pedido ajusta estas opciones según su material.
    ORDER_STATUSES = order_statuses()

    def __init__(self):
        startup_started = time.perf_counter()
        super().__init__()
        self._startup_started = startup_started
        self.withdraw()
        self.title("Doccione Studio · Sistema Inteligente de Producción de Stickers")
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        width = min(1040, round(screen_w * 0.95))
        height = min(700, round(screen_h * 0.85))
        self.geometry(f"{width}x{height}")
        self.minsize(max(780, round(screen_w * 0.6)), max(540, round(screen_h * 0.55)))
        self.state("zoomed")
        self.configure(background=COLORS.background)
        self.set_app_icon()
        self.add_pattern_background()
        self.splash = self.create_splash()
        self._configure_theme()
        self.database = ImageDatabase(Path(__file__).parents[2] / "visionvault.db")
        # --- Sistema de eventos y notificaciones ---
        self._event_repo = EventRepository(self.database.connection)
        self._event_repo.create_tables()
        self._event_bus = EventBus(self._event_repo)
        self._notification_service = NotificationService(self._event_repo)
        # --- Servidor de emparejamiento de dispositivos ---
        self._pairing_server = PairingServer(
            port=8765,
            repo_callback=lambda: self._event_repo,
        )
        self._pairing_server.start()
        # --- Servidor de API de jobs móviles ---
        self._mobile_jobs_server = MobileJobsServer(
            event_repo=self._event_repo,
            event_bus=self._event_bus,
            port=8766,
        )
        self._mobile_jobs_server.start()
        # Intentar inicializar Firebase (no bloqueante si no está configurado)
        try:
            firebase_ok = initialize_firebase()
            if firebase_ok:
                self._notification_service.start_worker(interval_seconds=15)
        except Exception:
            pass
        self.initial_render_complete = False
        self.startup_window_mapped = False
        self._startup_metric_saved = False
        self._orders_refresh_after = None
        self._tab_transition_after = None
        self._tab_transition_step = 0
        self._selected_order_id: int | None = None
        self.current_extension = None
        self.collection_extensions = [None]
        self.selected_tags: dict[str, tk.BooleanVar] = {}
        self.selected_categories: dict[str, tk.BooleanVar] = {}
        self.selected_images: dict[str, dict] = {}
        self.sticker_studio_window = None
        self.batch_scan_cancel = threading.Event()
        self._visual_search_started: dict[int, float] = {}
        self.settings_path = Path(os.environ.get("APPDATA", Path.home())) / "Doccione" / "settings.json"
        settings = self.load_settings()
        self.ai_provider = tk.StringVar(value=settings.get("ai_provider", "Local"))
        self.gemini_api_key = settings.get("gemini_api_key", os.environ.get("GEMINI_API_KEY", ""))
        saved_model = settings.get("gemini_model", "gemini-3.5-flash")
        self.gemini_model = "gemini-3.5-flash" if saved_model == "gemini-2.5-flash" else saved_model
        self._build()
        # Etiquetas y categorías pueden ser miles. Se cargan cuando la ventana
        # ya está visible para no bloquear la pantalla de inicio.
        # La biblioteca puede contener miles de imágenes. Se carga después de
        # mostrar la ventana para evitar que la aplicación quede viva pero
        # invisible durante la preparación de tarjetas y miniaturas.
        # El cálculo de impacto visual es pesado y no debe competir con la
        # primera carga de la biblioteca. Usar guardas para evitar que Tk
        # resuelva nombres en Tcl si el método falta temporalmente.
        self.after(2500, lambda: getattr(self, "prepare_visual_scores", lambda: None)())
        self.after(450, lambda: getattr(self, "connect_gemini_on_startup", lambda: None)())
        self.initial_render_complete = True
        self.after_idle(lambda: getattr(self, "finish_startup", lambda: None)())
        self.after(180, lambda: getattr(self, "refresh", lambda q=None: None)())
        self.after(350, lambda: getattr(self, "refresh_collections", lambda: None)())
        self.protocol("WM_DELETE_WINDOW", lambda: getattr(self, "close", lambda: None)())

    def _configure_theme(self):
        apply_ttk_theme(self)

    def set_app_icon(self):
        """Aplica el mismo icono a la ventana y a la barra de tareas de Windows.

        Soporta directamente un `.ico` en `app/assets/` o convierte un PNG/JPG
        encontrado allí a un `.ico` temporal usando Pillow y lo aplica.
        """
        try:
            assets_dir = Path(__file__).parents[1] / "assets"
            ico_path = assets_dir / "doccione_studio.ico"

            if not ico_path.exists():
                return

            # Establecer App User Model ID para Windows (necesario para icono de barra de tareas)
            try:
                import ctypes
                myappid = 'doccione.studio.visionvault.1.0'
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            except Exception as e:
                print(f"No se pudo establecer AppUserModelID: {e}")

            # Aplicar el icono de múltiples formas para asegurar compatibilidad
            try:
                # Método 1: iconbitmap con ruta absoluta (el más confiable para Windows)
                self.iconbitmap(str(ico_path.absolute()))
            except Exception as e:
                print(f"iconbitmap falló: {e}")
            
            try:
                # Método 2: wm_iconbitmap como fallback
                self.wm_iconbitmap(str(ico_path.absolute()))
            except Exception as e:
                print(f"wm_iconbitmap falló: {e}")
            
            # Método 3: Cargar icono directamente en la ventana usando Win32 API
            try:
                import ctypes
                from ctypes import wintypes
                
                # Obtener el handle de la ventana
                hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
                if hwnd == 0:
                    # Si GetParent falla, usar directamente winfo_id
                    hwnd = self.winfo_id()
                
                # Cargar el icono desde el archivo
                ICON_SMALL = 0
                ICON_BIG = 1
                LR_LOADFROMFILE = 0x00000010
                IMAGE_ICON = 1
                
                hicon = ctypes.windll.user32.LoadImageW(
                    0,
                    str(ico_path.absolute()),
                    IMAGE_ICON,
                    0, 0,
                    LR_LOADFROMFILE
                )
                
                if hicon:
                    WM_SETICON = 0x0080
                    ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
                    ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
                    
            except Exception as e:
                print(f"Win32 API falló: {e}")
            
            # Reintentar después de que la ventana esté inicializada
            self.after(100, lambda: self._apply_icon_delayed(ico_path))
            self.after(500, lambda: self._apply_icon_delayed(ico_path))

        except Exception as e:
            print(f"Error general en set_app_icon: {e}")

    def _apply_icon_delayed(self, ico_path: Path):
        """Reintenta aplicar el icono después de que la ventana esté completamente inicializada."""
        try:
            self.iconbitmap(str(ico_path.absolute()))
        except Exception:
            pass
        try:
            self.wm_iconbitmap(str(ico_path.absolute()))
        except Exception:
            pass
        try:
            import ctypes
            hwnd = self.winfo_id()
            if hwnd:
                ICON_SMALL = 0
                ICON_BIG = 1
                LR_LOADFROMFILE = 0x00000010
                IMAGE_ICON = 1
                
                hicon = ctypes.windll.user32.LoadImageW(
                    0,
                    str(ico_path.absolute()),
                    IMAGE_ICON,
                    0, 0,
                    LR_LOADFROMFILE
                )
                
                if hicon:
                    WM_SETICON = 0x0080
                    ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
                    ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
        except Exception:
            pass

    def add_pattern_background(self):
        """Añade el patrón de Doccione a baja intensidad, sin afectar la lectura."""
        try:
            from PIL import Image, ImageOps, ImageTk

            asset = Path(__file__).parents[1] / "assets" / "fondo_doccione_bw.png"
            with Image.open(asset) as source:
                size = (self.winfo_screenwidth(), self.winfo_screenheight())
                image = ImageOps.fit(source.convert("RGBA"), size, method=Image.Resampling.LANCZOS)
                image.putalpha(26)
                self.pattern_photo = ImageTk.PhotoImage(image)
            self.pattern = tk.Label(self, image=self.pattern_photo, background=COLORS.background, borderwidth=0)
            self.pattern.place(x=0, y=0, relwidth=1, relheight=1)
            self.pattern.lower()
        except Exception:
            self.pattern = None

    def configure_gemini(self):
        key = simpledialog.askstring("Configurar Gemini", "Clave de API de Gemini:", initialvalue=self.gemini_api_key, show="•", parent=self)
        if key is not None:
            self.gemini_api_key = key.strip()
            if self.gemini_api_key:
                self.ai_provider.set("Gemini")
            self.save_settings()
            self.status.set("Clave de Gemini configurada para esta sesión." if self.gemini_api_key else "Se usará el análisis local.")
            self.connect_gemini_on_startup()

    def set_gemini_indicator(self, state: str):
        """Muestra de un vistazo si Gemini está listo para analizar."""
        colors = {"ready": "#39d353", "checking": "#a7a7a7", "error": "#ff4d5a", "offline": "#777777"}
        texts = {
            "ready": "Gemini conectado",
            "checking": "Comprobando conexión con Gemini",
            "error": "No se pudo conectar con Gemini",
            "offline": "Gemini sin configurar",
        }
        if hasattr(self, "gemini_indicator"):
            self.gemini_indicator.configure(foreground=colors.get(state, colors["offline"]))
            self.gemini_indicator.tooltip = texts.get(state, texts["offline"])

    def load_settings(self) -> dict:
        try:
            return json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def save_settings(self):
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(json.dumps({
                "ai_provider": self.ai_provider.get(),
                "gemini_api_key": self.gemini_api_key,
                "gemini_model": self.gemini_model,
            }), encoding="utf-8")
        except OSError:
            pass

    def connect_gemini_on_startup(self):
        """Comprueba la conexión de Gemini sin analizar ni subir stickers."""
        if self.ai_provider.get() != "Gemini" or not self.gemini_api_key:
            self.set_gemini_indicator("offline")
            return
        self.set_gemini_indicator("checking")

        def verify():
            from urllib.request import Request, urlopen

            try:
                request = Request(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}",
                    headers={"x-goog-api-key": self.gemini_api_key},
                )
                with urlopen(request, timeout=15):
                    pass
                state = "ready"
            except Exception as error:
                state = "error"
            self.after(0, lambda: self.set_gemini_indicator(state))

        threading.Thread(target=verify, daemon=True).start()

    def start_full_gemini_scan(self):
        """Analiza toda la biblioteca, sin aplicar cambios automáticos."""
        if self.ai_provider.get() != "Gemini" or not self.gemini_api_key:
            messagebox.showwarning("Gemini", "Primero configurá una clave de Gemini y seleccioná Gemini como proveedor.", parent=self)
            return
        cache_model = f"{self.gemini_model}:structured-v3"
        images = self.database.images_needing_ai("Gemini", cache_model)
        if not images:
            messagebox.showinfo("Escaneo completo", "Todos los diseños ya tienen un análisis actualizado para revisar.", parent=self)
            return
        if not messagebox.askyesno(
            "Escanear biblioteca",
            f"Se analizarán {len(images)} diseños uno por uno con Gemini.\n\n"
            "Los resultados se guardarán para revisarlos después: no se modificarán nombres, categorías ni etiquetas. "
            "Podés detenerlo y retomarlo cuando quieras.",
            parent=self,
        ):
            return

        self.batch_scan_cancel.clear()
        dialog = tk.Toplevel(self)
        dialog.title("Escaneando biblioteca")
        dialog.configure(background="#080909")
        dialog.geometry("430x160")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.protocol("WM_DELETE_WINDOW", self.batch_scan_cancel.set)
        ttk.Label(dialog, text="Escaneo completo con Gemini", style="Title.TLabel", padding=(18, 14, 18, 4)).pack(anchor="w")
        status = tk.StringVar(value=f"Preparando 0 de {len(images)}…")
        ttk.Label(dialog, textvariable=status, style="Muted.TLabel", padding=(18, 0, 18, 8), wraplength=390).pack(anchor="w")
        progress = ttk.Progressbar(dialog, mode="determinate", maximum=len(images), length=390)
        progress.pack(padx=18, fill="x")
        ttk.Button(dialog, text="Detener y continuar después", command=lambda: self.batch_scan_cancel.set()).pack(anchor="e", padx=18, pady=14)

        def show_progress(index: int, successful: int, failed: int):
            if not dialog.winfo_exists():
                return
            progress["value"] = index
            status.set(f"Analizando {index} de {len(images)} · Guardados: {successful} · Reintentos/fallos: {failed}")

        def save_result(image: dict, result: dict):
            if not result.get("missing") and not result.get("errors"):
                self.database.save_ai_result(image["path"], "Gemini", cache_model, image["modified"], result)

        def finish(completed: int, successful: int, failed: int, stopped: bool):
            if dialog.winfo_exists():
                dialog.grab_release()
                dialog.destroy()
            message = (
                f"Escaneo {'pausado' if stopped else 'terminado'}: {successful} análisis guardados"
                f" de {completed} procesados"
                + (f" · {failed} sin completar." if failed else ".")
            )
            self.status.set(message)
            if not stopped:
                messagebox.showinfo("Escaneo completo", message, parent=self)

        def worker():
            from app.ai.gemini import analyze_image

            successful = failed = completed = 0
            for index, image in enumerate(images, start=1):
                if self.batch_scan_cancel.is_set():
                    break
                result = {"errors": ["Sin respuesta"], "missing": []}
                for attempt in range(3):
                    result = analyze_image(image["path"], self.gemini_api_key, self.gemini_model)
                    if not result.get("missing") and not result.get("errors"):
                        break
                    if self.batch_scan_cancel.wait(2 * (attempt + 1)):
                        break
                completed = index
                if not result.get("missing") and not result.get("errors"):
                    successful += 1
                    self.after(0, lambda item=image, data=result: save_result(item, data))
                else:
                    failed += 1
                self.after(0, lambda current=index, ok=successful, bad=failed: show_progress(current, ok, bad))
                if self.batch_scan_cancel.wait(0.45):
                    break
            self.after(0, lambda: finish(completed, successful, failed, self.batch_scan_cancel.is_set()))

        threading.Thread(target=worker, daemon=True).start()

    def bring_to_front(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def create_splash(self):
        splash = tk.Toplevel(self)
        splash.overrideredirect(True)
        splash.configure(background=COLORS.panel, highlightbackground=COLORS.wine, highlightthickness=1)
        splash.geometry("420x210")
        tk.Label(splash, text="2CCI", background=COLORS.panel, foreground=COLORS.text, font=(IDENTITY_FONT, 34, "bold")).pack(pady=(42, 2))
        tk.Label(splash, text="DOCCIONE STUDIO", background=COLORS.panel, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 11, "bold")).pack()
        tk.Label(splash, text="CARGANDO…", background=COLORS.panel, foreground=COLORS.muted, font=(IDENTITY_FONT, 10)).pack(pady=(4, 0))
        splash.update_idletasks()
        x = (splash.winfo_screenwidth() - splash.winfo_width()) // 2
        y = (splash.winfo_screenheight() - splash.winfo_height()) // 2
        splash.geometry(f"+{x}+{y}")
        splash.update()
        return splash

    def finish_startup(self):
        # Se mapea invisible para que Tk pueda calcular la cuadrícula sin
        # mostrar una interfaz a medio cargar detrás de la pantalla inicial.
        if not self.startup_window_mapped:
            self.attributes("-alpha", 0.0)
            self.deiconify()
            self.startup_window_mapped = True
            self.after(40, self.finish_startup)
            return
        self.update_idletasks()
        # No se espera el tamaño del canvas: en algunas pantallas de Windows
        # permanece en cero mientras la ventana está transparente y dejaba la
        # pantalla de inicio bloqueada indefinidamente.
        ready = self.initial_render_complete
        if not ready:
            self.after(40, self.finish_startup)
            return
        if self.splash.winfo_exists():
            self.splash.destroy()
        self.attributes("-alpha", 1.0)
        self.lift()
        self.focus_force()
        if not self._startup_metric_saved:
            self._startup_metric_saved = True
            record_performance(
                "application_startup",
                (time.perf_counter() - self._startup_started) * 1000,
                images=self.database.count(),
            )

    def _build(self):
        # Barra superior: identidad a la izquierda y acciones operativas a la
        # derecha. Las tareas no cambian; solo pasan a una jerarquía estable.
        toolbar = tk.Frame(self, background=COLORS.background_secondary, height=88)
        toolbar.pack(fill="x")
        toolbar.pack_propagate(False)
        brand = tk.Frame(toolbar, background=COLORS.background_secondary)
        brand.pack(side="left")
        tk.Label(brand, text="DOCCIONE STUDIO", background=COLORS.background_secondary, foreground=COLORS.text,
                 font=(IDENTITY_FONT, 27, "bold")).pack(anchor="w", padx=22, pady=(13, 0))
        tk.Label(brand, text="SISTEMA INTELIGENTE DE PRODUCCIÓN DE STICKERS", background=COLORS.background_secondary,
                 foreground=COLORS.wine_active, font=(IDENTITY_FONT, 9, "bold")).pack(anchor="w", padx=23, pady=(0, 12))
        # Acciones agrupadas por tarea, para evitar una fila de botones sin
        # jerarquía y dejar claro qué pertenece a biblioteca e IA.
        actions = tk.Frame(toolbar, background=COLORS.background_secondary)
        actions.pack(side="right", anchor="ne", padx=18, pady=14)
        library_actions = tk.Frame(actions, background=COLORS.background_secondary)
        library_actions.pack(anchor="e", pady=(0, 6))
        ttk.Button(library_actions, text="Indexar carpeta", command=lambda: self.index_folder(), style="Secondary.TButton").pack(side="right")
        ttk.Button(library_actions, text="Escanear biblioteca", command=lambda: self.start_full_gemini_scan(), style="Secondary.TButton").pack(side="right", padx=(0, 8))
        ai_actions = tk.Frame(actions, background=COLORS.background_secondary)
        ai_actions.pack(anchor="e")
        tk.Label(ai_actions, text="ANÁLISIS", background=COLORS.background_secondary, foreground=COLORS.muted,
                 font=(IDENTITY_FONT, 9, "bold")).pack(side="left", padx=(0, 6))
        provider = ttk.Combobox(ai_actions, textvariable=self.ai_provider, values=("Local", "Gemini"), state="readonly", width=10)
        provider.pack(side="left")
        ttk.Button(ai_actions, text="Configurar Gemini", command=lambda: self.configure_gemini(), style="Primary.TButton").pack(side="left", padx=(4, 0))
        provider.bind("<<ComboboxSelected>>", lambda _event: (self.save_settings(), self.connect_gemini_on_startup()))
        tk.Frame(self, height=1, background=COLORS.border).pack(fill="x")

        body = tk.Frame(self, background=COLORS.background)
        body.pack(fill="both", expand=True, padx=16, pady=(14, 16))

        navigation = tk.Frame(body, width=178, background=COLORS.background_secondary,
                              highlightthickness=1, highlightbackground=COLORS.border)
        navigation.pack(side="left", fill="y", padx=(0, 12))
        navigation.pack_propagate(False)
        tk.Label(navigation, text="NAVEGACIÓN", background=COLORS.background_secondary, foreground=COLORS.muted,
                 font=(IDENTITY_FONT, 9, "bold")).pack(anchor="w", padx=16, pady=(16, 8))
        self.navigation_items = tk.Frame(navigation, background=COLORS.background_secondary)
        self.navigation_items.pack(fill="x", pady=(0, 10))
        tk.Frame(navigation, height=1, background=COLORS.border).pack(fill="x", padx=14, pady=(6, 12))
        
        # Panel de notificaciones de pedidos
        tk.Label(navigation, text="NOTIFICACIONES", background=COLORS.background_secondary, foreground=COLORS.muted,
                 font=(IDENTITY_FONT, 9, "bold")).pack(anchor="w", padx=16, pady=(0, 8))
        self.notifications_frame = tk.Frame(navigation, background=COLORS.background_secondary)
        self.notifications_frame.pack(fill="x", padx=10, pady=(0, 12))
        try:
            self.refresh_notifications()
        except Exception as e:
            # Evitar que un fallo en el panel de notificaciones impida el arranque
            try:
                self.status.set(f"Aviso: no se pudieron cargar notificaciones: {e}")
            except Exception:
                pass
        
        # Botón para abrir el Centro de Notificaciones
        _notif_center_btn = tk.Button(
            navigation, text="📱 Centro de notificaciones", command=self.open_notification_center,
            background=COLORS.wine_dark, foreground=COLORS.text,
            activebackground=COLORS.wine, activeforeground=COLORS.text,
            borderwidth=0, relief="flat", highlightthickness=0,
            padx=10, pady=7, font=(UI_FONT, 9, "bold"), cursor="hand2",
        )
        _notif_center_btn.pack(fill="x", padx=10, pady=(0, 10))
        
        tk.Frame(navigation, height=1, background=COLORS.border).pack(fill="x", padx=14, pady=(6, 12))
        tk.Label(navigation, text="BIBLIOTECA ACTIVA", background=COLORS.background_secondary, foreground=COLORS.muted,
                 font=(IDENTITY_FONT, 8, "bold")).pack(anchor="w", padx=16)
        tk.Label(navigation, text="Las etiquetas y categorías se muestran en el panel contextual.",
                 background=COLORS.background_secondary, foreground=COLORS.disabled, font=(UI_FONT, 9),
                 justify="left", wraplength=140).pack(anchor="w", padx=16, pady=(5, 0))

        content_shell = tk.Frame(body, background=COLORS.background)
        content_shell.pack(side="left", fill="both", expand=True)
        sidebar = tk.Frame(content_shell, width=238, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        sidebar.pack(side="right", fill="y", padx=(14, 0))
        sidebar.pack_propagate(False)
        section_heading(sidebar, "FILTROS", detail="Combiná etiquetas para mostrar solo los diseños en común.")
        ttk.Button(sidebar, text="Desmarcar filtros", command=lambda: self.clear_all_tags(), style="Secondary.TButton").pack(fill="x", padx=14, pady=(0, 12))
        tk.Label(sidebar, text="BUSCAR ETIQUETAS", background=COLORS.panel, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 10, "bold")).pack(anchor="w", padx=14, pady=(0, 5))
        self.tag_filter_query = tk.StringVar()
        tag_filter_entry = ttk.Entry(sidebar, textvariable=self.tag_filter_query)
        tag_filter_entry.pack(fill="x", padx=14, pady=(0, 7))
        tag_filter_entry.bind("<KeyRelease>", lambda _event: self.refresh_tags())
        self.tag_category_filter = tk.StringVar(value="Todas las categorías")
        self.tag_category_picker = ttk.Combobox(sidebar, textvariable=self.tag_category_filter, state="readonly")
        self.tag_category_picker.pack(fill="x", padx=14, pady=(0, 12))
        self.tag_category_picker.bind("<<ComboboxSelected>>", lambda _event: self.refresh_tags())
        tk.Label(sidebar, text="CATEGORÍAS", background=COLORS.panel, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 10, "bold")).pack(anchor="w", padx=14, pady=(0, 6))
        self.categories_frame = tk.Frame(sidebar, background=COLORS.panel)
        self.categories_frame.pack(fill="x", padx=8, pady=(0, 8))
        tk.Label(sidebar, text="PALABRAS CLAVE", background=COLORS.panel, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 10, "bold")).pack(anchor="w", padx=14, pady=(4, 6))
        tags_area = tk.Frame(sidebar, background=COLORS.panel)
        tags_area.pack(fill="both", expand=True, padx=8, pady=(0, 10))
        self.tags_canvas = tk.Canvas(tags_area, background=COLORS.panel, highlightthickness=0)
        tags_scroll = ttk.Scrollbar(tags_area, orient="vertical", command=lambda *a: self.tags_canvas.yview(*a))
        self.tags_canvas.configure(yscrollcommand=tags_scroll.set)
        self.tags_frame = tk.Frame(self.tags_canvas, background=COLORS.panel)
        self.tags_canvas.create_window((0, 0), window=self.tags_frame, anchor="nw")
        self.tags_frame.bind("<Configure>", lambda _: self.tags_canvas.configure(scrollregion=self.tags_canvas.bbox("all")))
        self.tags_canvas.bind("<MouseWheel>", lambda e: self.scroll_tags_with_wheel(e))
        self.tags_frame.bind("<MouseWheel>", lambda e: self.scroll_tags_with_wheel(e))
        self.tags_canvas.pack(side="left", fill="both", expand=True)
        tags_scroll.pack(side="right", fill="y")

        workspace = ttk.Frame(content_shell)
        workspace.pack(side="left", fill="both", expand=True)
        self.status = tk.StringVar(value="")
        self.status_panel = status_strip(workspace, self.status)
        self.status_panel.pack(fill="x", pady=(0, 8))
        # Un barrido muy breve da continuidad al cambiar de vista sin bloquear
        # las miniaturas ni forzar una recarga completa de la aplicación.
        self.tab_transition = tk.Canvas(workspace, height=3, background=COLORS.background, highlightthickness=0)
        self.tab_transition.pack(fill="x")
        self.tabs = ttk.Notebook(workspace, style="Main.TNotebook")
        self.tabs.pack(fill="both", expand=True)
        orders_tab = ttk.Frame(self.tabs)
        designs_tab = ttk.Frame(self.tabs)
        selected_tab = ttk.Frame(self.tabs)
        production_tab = ttk.Frame(self.tabs)
        self.tabs.add(designs_tab, text="Diseños")
        self.tabs.add(selected_tab, text="Seleccionados (0)")
        self.tabs.add(orders_tab, text="Pedidos")
        self.tabs.add(production_tab, text="Producción")
        # La biblioteca es el punto de entrada operativo de Doccione Studio.
        self.tabs.select(designs_tab)
        self.designs_tab = designs_tab
        self.selected_tab = selected_tab
        self.orders_tab = orders_tab
        self.production_tab = production_tab
        self.order_tabs: dict[int, ttk.Frame] = {}
        orders_builder = getattr(type(self), "build_orders_module", None)
        if callable(orders_builder):
            orders_builder(self, orders_tab)
        production_builder = getattr(type(self), "build_production_module", None)
        if callable(production_builder):
            production_builder(self, production_tab)
        library_header = tk.Frame(designs_tab, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        library_header.pack(fill="x", padx=10, pady=(10, 0))
        tk.Label(library_header, text="BIBLIOTECA", background=COLORS.panel, foreground=COLORS.text,
                 font=(IDENTITY_FONT, 15, "bold")).pack(side="left", padx=14, pady=10)
        tk.Label(library_header, text="Diseños reutilizables · Doble clic para ver · Ctrl para seleccionar",
                 background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 9)).pack(side="left", padx=(0, 14), pady=10)
        search_panel = tk.Frame(designs_tab, background=COLORS.panel)
        search_panel.pack(fill="x", pady=(0, 8), padx=10)
        self.design_limit = tk.StringVar(value="100")
        limit_panel = tk.Frame(search_panel, background=COLORS.panel)
        limit_panel.pack(side="right", padx=(0, 12), pady=3)
        tk.Label(limit_panel, text="Mostrar", background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 9)).pack(side="left", padx=(0, 6))
        self.design_limit_picker = ttk.Combobox(limit_panel, textvariable=self.design_limit, values=("50", "100", "200", "500"), state="readonly", width=5)
        self.design_limit_picker.pack(side="left")
        self.design_limit_picker.bind("<<ComboboxSelected>>", self.change_design_limit)
        self.search = SearchBar(
            search_panel,
            lambda q=None: self.refresh(q),
            lambda q=None: self.database.suggestions(q),
            lambda: self.show_random_grid(),
            lambda q=None: self.predict_search(q),
            lambda: self.show_visual_search_dialog(),
            lambda: self.open_sticker_studio(),
        )
        self.search.pack(fill="x", padx=12, pady=3)
        self.gallery = Gallery(
            designs_tab,
            lambda img: self.preview_image(img),
            lambda img: self.add_tag(img),
            lambda img, name: self.remove_tag(img, name),
            lambda: None,
            lambda img: self.toggle_selection(img),
            lambda img: self.is_selected(img),
            lambda image: self.dragged_paths(image),
            on_trash=lambda img: self.trash_sticker(img),
        )
        self.gallery.pack(fill="both", expand=True)
        selected_actions = tk.Frame(selected_tab, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        selected_actions.pack(fill="x", padx=10, pady=(10, 0))
        selected_copy = tk.Frame(selected_actions, background=COLORS.panel)
        selected_copy.pack(side="left", padx=14, pady=10)
        tk.Label(selected_copy, text="SELECCIONADOS", background=COLORS.panel, foreground=COLORS.text,
                 font=(IDENTITY_FONT, 13, "bold")).pack(anchor="w")
        tk.Label(selected_copy, text="Arrastralos a Photoshop u otra aplicación.", background=COLORS.panel,
                 foreground=COLORS.muted, font=(UI_FONT, 9)).pack(anchor="w")
        selected_controls = tk.Frame(selected_actions, background=COLORS.panel)
        selected_controls.pack(side="right", padx=10, pady=13)
        ttk.Button(selected_controls, text="Deseleccionar todo", command=lambda: self.clear_selected(), style="Secondary.TButton").pack(side="right")
        ttk.Button(selected_controls, text="Seleccionar todos", command=lambda: self.select_all_visible(), style="Secondary.TButton").pack(side="right", padx=(0, 7))
        ttk.Button(selected_controls, text="Armado de planchas", command=lambda: self.open_plancha_constructor(), style="Primary.TButton").pack(side="right", padx=(0, 7))
        ttk.Button(selected_controls, text="Agregar etiqueta", command=lambda: self.add_tag_to_selected(), style="Secondary.TButton").pack(side="right", padx=(0, 7))
        self.selected_gallery = Gallery(
            selected_tab,
            lambda img: self.preview_image(img),
            lambda img: self.add_tag(img),
            lambda img, name: self.remove_tag(img, name),
            lambda: None,
            lambda img: self.toggle_selection(img),
            lambda img: self.is_selected(img),
            lambda image: self.dragged_paths(image),
            on_trash=lambda img: self.trash_sticker(img),
        )
        self.selected_gallery.pack(fill="both", expand=True)
        self._build_navigation_buttons({
            "Biblioteca": designs_tab,
            "Seleccionados": selected_tab,
            "Pedidos": orders_tab,
            "Producción": production_tab,
        })
        self.tabs.bind("<<NotebookTabChanged>>", self.on_tab_changed)
        self._update_navigation(designs_tab)

    def _build_navigation_buttons(self, destinations: dict[str, ttk.Frame]):
        """Crea un acceso persistente para las mismas pestañas existentes."""
        self.navigation_buttons: dict[object, tk.Button] = {}
        for label, tab in destinations.items():
            button = navigation_button(self.navigation_items, label, lambda current=tab: self.tabs.select(current))
            self.navigation_buttons[tab] = button
            if label == "Seleccionados":
                self.selected_navigation_button = button

    def _update_navigation(self, active_tab) -> None:
        for tab, button in getattr(self, "navigation_buttons", {}).items():
            set_navigation_active(button, tab is active_tab)

    def build_orders_module(self, parent: tk.Widget):
        """Construye un módulo de Pedidos básico (placeholder ligero).

        Este método proporciona las variables y widgets mínimos que otras
        partes del código esperan durante el arranque. Es intencionalmente
        simple: la UI completa se mantiene en otras funciones más detalladas.
        """
        container = tk.Frame(parent, background=COLORS.panel)
        container.pack(fill="both", expand=True)

        # Fila 1: título + botones de acción
        header = ttk.Frame(container, padding=(10, 10, 10, 4))
        header.pack(fill="x")
        ttk.Label(header, text="Pedidos", style="Title.TLabel").pack(side="left")
        ttk.Button(header, text="+ Nuevo pedido", command=self.new_order_dialog,
                   style="Primary.TButton").pack(side="right", padx=(8, 0))
        ttk.Button(header, text="Resumen", command=self.show_order_summary,
                   style="Secondary.TButton").pack(side="right", padx=(0, 8))
        ttk.Button(header, text="Abrir pedido",
                   command=self.open_selected_order,
                   style="Secondary.TButton").pack(side="right", padx=(0, 8))
        ttk.Button(header, text="Precios",
                   command=self.configure_price_rules,
                   style="Secondary.TButton").pack(side="right", padx=(0, 8))
        ttk.Button(header, text="Costos",
                   command=self.configure_cost_rules,
                   style="Secondary.TButton").pack(side="right", padx=(0, 8))
        # Botón urgentes: se inicializa antes de usarse como textvariable
        self.urgent_orders_button_var = tk.StringVar(value="🚨 Pedidos urgentes (0)")
        ttk.Button(header, textvariable=self.urgent_orders_button_var,
                   command=self.show_attention_dashboard,
                   style="Secondary.TButton").pack(side="right", padx=(0, 8))

        # Fila 2: filtros y búsqueda en su propia barra
        filter_bar = ttk.Frame(container, padding=(10, 0, 10, 8))
        filter_bar.pack(fill="x")
        self.orders_query = tk.StringVar(value="")
        self.orders_filter = tk.StringVar(value="Todos")
        ttk.Label(filter_bar, text="Buscar:").pack(side="left", padx=(0, 4))
        search_entry = ttk.Entry(filter_bar, textvariable=self.orders_query, width=30)
        search_entry.pack(side="left", fill="x", expand=True, padx=(0, 12))
        search_entry.bind("<KeyRelease>", lambda _event: self.queue_orders_refresh())
        ttk.Label(filter_bar, text="Vista:").pack(side="left", padx=(0, 4))
        filter_picker = ttk.Combobox(
            filter_bar, textvariable=self.orders_filter, state="readonly", width=18,
            values=("Todos", "Pendientes", "Recibidos", "Esperando archivos",
                    "Diseños confirmados", "En producción", "Listos para imprimir", "Finalizados"),
        )
        filter_picker.pack(side="left")
        filter_picker.bind("<<ComboboxSelected>>", lambda _event: self.refresh_orders())
        ttk.Button(filter_bar, text="Ver pendientes",
                   command=lambda: (self.orders_filter.set("Pendientes"), self.refresh_orders()),
                   style="Secondary.TButton").pack(side="left", padx=(12, 0))

        # ── Panel de estadísticas de ventas ───────────────────────────────────
        self.sales_month        = tk.StringVar(value=datetime.now().strftime("%Y-%m"))
        self.sales_granularity  = tk.StringVar(value="Diario")
        self.sales_summary_var  = tk.StringVar(value="Cargando…")
        self.sales_status_var   = tk.StringVar(value="")
        self.sales_stats_vars   = {
            "budget":  tk.StringVar(value="$0.00"),
            "paid":    tk.StringVar(value="$0.00"),
            "pending": tk.StringVar(value="$0.00"),
            "rate":    tk.StringVar(value="0.0%"),
        }
        self.sales_delta_vars   = {
            "budget": tk.StringVar(value=""),
            "paid":   tk.StringVar(value=""),
        }
        self.sales_delta_labels  = {}
        self.sales_metric_frames = {}   # refs a los frames de cada caja para colorear borde
        self.sales_status_chips  = {}   # refs a los chips de conteo (closed/partial/pending)

        _BG  = COLORS.panel_elevated
        _BG2 = COLORS.panel

        sales_panel = tk.Frame(container, background=_BG,
                               highlightthickness=1, highlightbackground=COLORS.border)
        sales_panel.pack(fill="x", padx=10, pady=(0, 6))

        # ── Fila 1: título · navegación · botón detalle ───────────────────────
        sales_head = tk.Frame(sales_panel, background=_BG)
        sales_head.pack(fill="x", padx=12, pady=(10, 4))

        tk.Label(sales_head, text="PANEL DE ESTADÍSTICAS Y VENTAS",
                 background=_BG, foreground=COLORS.wine_active,
                 font=(IDENTITY_FONT, 10, "bold")).pack(side="left")

        nav_frame = tk.Frame(sales_head, background=_BG)
        nav_frame.pack(side="left", padx=(14, 0))
        ttk.Button(nav_frame, text="◀", width=2,
                   command=lambda: self._change_sales_month(-1),
                   style="Secondary.TButton").pack(side="left")
        ttk.Entry(nav_frame, textvariable=self.sales_month, width=8,
                  font=(UI_FONT, 9)).pack(side="left", padx=(4, 4))
        ttk.Button(nav_frame, text="▶", width=2,
                   command=lambda: self._change_sales_month(1),
                   style="Secondary.TButton").pack(side="left")

        ttk.Button(sales_head, text="Detalle →", command=self.show_sales_details,
                   style="Secondary.TButton").pack(side="right")

        # ── Fila 2: resumen textual ───────────────────────────────────────────
        tk.Label(sales_panel, textvariable=self.sales_summary_var,
                 background=_BG, foreground=COLORS.text,
                 font=(UI_FONT, 8), anchor="w").pack(fill="x", padx=14, pady=(0, 1))

        # ── Fila 3: chips de conteo (cerrados / con seña / sin cobrar) ────────
        chips_row = tk.Frame(sales_panel, background=_BG)
        chips_row.pack(fill="x", padx=14, pady=(0, 4))

        _CHIP_DEFS = [
            ("closed",   "● Cerrados",    "#2D9B66", "#1E2E1E"),
            ("partial",  "◐ Con seña",    "#C98A27", "#2A1E0E"),
            ("pending",  "○ Sin cobrar",  "#C94B27", "#2A1010"),
        ]
        for chip_key, chip_text, fg, bg in _CHIP_DEFS:
            chip_var = tk.StringVar(value=chip_text)
            self.sales_status_chips[chip_key] = chip_var
            lbl = tk.Label(chips_row, textvariable=chip_var,
                           background=bg, foreground=fg,
                           font=(UI_FONT, 8, "bold"),
                           padx=6, pady=2, relief="flat",
                           highlightthickness=1, highlightbackground=fg)
            lbl.pack(side="left", padx=(0, 4))

        # ── Fila 4: cuatro cajas de métricas ocupando todo el ancho ──────────
        _METRIC_DEFS = [
            # key        label            acento
            ("budget",  "Presupuestado",  "#4E8AC7"),
            ("paid",    "Cobrado",        "#2D9B66"),
            ("pending", "Pendiente",      "#C98A27"),
            ("rate",    "Cobranza %",     None),      # color dinámico
        ]
        metrics_row = tk.Frame(sales_panel, background=_BG)
        metrics_row.pack(fill="x", padx=12, pady=(0, 6))
        metrics_row.columnconfigure(tuple(range(len(_METRIC_DEFS))), weight=1, uniform="metric")

        for col, (key, label, accent) in enumerate(_METRIC_DEFS):
            box = tk.Frame(metrics_row, background=_BG2,
                           highlightthickness=2,
                           highlightbackground=accent or COLORS.border)
            box.grid(row=0, column=col, padx=(0 if col == 0 else 4, 0), pady=2, sticky="nsew")
            self.sales_metric_frames[key] = box

            tk.Label(box, text=label, background=_BG2,
                     foreground=COLORS.muted,
                     font=(UI_FONT, 8)).pack(anchor="w", padx=8, pady=(6, 0))

            val_row = tk.Frame(box, background=_BG2)
            val_row.pack(fill="x", padx=8, pady=(1, 1))

            val_color = accent if accent else COLORS.text
            tk.Label(val_row, textvariable=self.sales_stats_vars[key],
                     background=_BG2, foreground=val_color,
                     font=(IDENTITY_FONT, 12, "bold")).pack(side="left")

            # chip de delta inline (solo budget y paid)
            if key in self.sales_delta_vars:
                delta_lbl = tk.Label(val_row, textvariable=self.sales_delta_vars[key],
                                     background=_BG2, foreground=COLORS.muted,
                                     font=(UI_FONT, 8), padx=5, pady=1)
                delta_lbl.pack(side="left", padx=(6, 0))
                self.sales_delta_labels[key] = delta_lbl

            # línea de acento inferior
            if accent:
                tk.Frame(box, height=2, background=accent).pack(fill="x", side="bottom")

        # ── Fila 5: barra de progreso de cobranza con etiqueta ────────────────
        prog_frame = tk.Frame(sales_panel, background=_BG)
        prog_frame.pack(fill="x", padx=12, pady=(0, 4))
        self.sales_progress_label = tk.Label(prog_frame, textvariable=self.sales_status_var,
                                             background=_BG, foreground=COLORS.muted,
                                             font=(UI_FONT, 8), anchor="w")
        self.sales_progress_label.pack(fill="x", pady=(0, 2))
        self.sales_progress = ttk.Progressbar(prog_frame, orient="horizontal",
                                              mode="determinate", maximum=100)
        self.sales_progress.pack(fill="x", pady=(0, 4))

        # Contenedor del gráfico (se llena solo si matplotlib está disponible)
        self._plot_container = tk.Frame(container, background=_BG2)
        self._plot_container.pack_forget()

        # Área de fichas (scrollable)
        cards_area = tk.Frame(container, background=COLORS.panel)
        cards_area.pack(fill="both", expand=True, padx=8, pady=8)
        canvas = tk.Canvas(cards_area, background=COLORS.panel, highlightthickness=0)
        vscroll = ttk.Scrollbar(cards_area, orient="vertical", command=lambda *a: canvas.yview(*a))
        canvas.configure(yscrollcommand=vscroll.set)
        inner = tk.Frame(canvas, background=COLORS.panel)
        self._orders_canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        def _sync_orders_frame_width(event):
            if not hasattr(self, "_orders_canvas_window"):
                return
            canvas.itemconfigure(self._orders_canvas_window, width=max(220, event.width))

        canvas.bind("<Configure>", _sync_orders_frame_width)
        canvas.pack(side="left", fill="both", expand=True)
        vscroll.pack(side="right", fill="y")
        self._orders_cards_frame = inner
        self._orders_cards_frame.columnconfigure(0, weight=1)

        # Otros valores referenciados
        self.orders_summary = tk.StringVar(value="Cargando pedidos…")

        # Cargar contenido inicial sin bloquear
        try:
            self.refresh_orders()
        except Exception:
            pass

    def build_production_module(self, parent: tk.Widget):
        """Construye un módulo de Producción mínimo para evitar errores en el arranque."""
        container = tk.Frame(parent, background=COLORS.panel)
        container.pack(fill="both", expand=True)

        header = ttk.Frame(container, padding=10)
        header.pack(fill="x")
        ttk.Label(header, text="Producción", style="Title.TLabel").pack(side="left")

        info = tk.Label(container, text="Panel de producción (temporal)", background=COLORS.panel, foreground=COLORS.muted)
        info.pack(padx=12, pady=12)

        # Guardar referencia mínima para llamadas posteriores
        self.production_summary = tk.StringVar(value="Sin métricas")
        ttk.Label(container, textvariable=self.production_summary, style="Muted.TLabel").pack(anchor="w", padx=12)

        try:
            # No bloquear el arranque con operaciones pesadas
            pass
        except Exception:
            pass

    def on_tab_changed(self, _event=None):
        """Transición ligera y actualizaciones bajo demanda al cambiar de pestaña."""
        self.animate_tab_transition()
        try:
            selected = self.tabs.nametowidget(self.tabs.select())
        except (tk.TclError, KeyError):
            return
        self._update_navigation(selected)
        if selected is self.production_tab:
            self.after_idle(lambda: getattr(self, "refresh_production", lambda: None)())
        elif selected is self.orders_tab:
            self.queue_orders_refresh(delay=30)

    def change_design_limit(self, _event=None):
        """Muestra 50, 100, 200 o 500 diseños sin cambiar los filtros activos."""
        if not hasattr(self, "gallery"):
            return
        self.gallery.set_display_limit(self.design_limit.get())
        self.refresh(self.search.query.get())

    def animate_tab_transition(self):
        if not hasattr(self, "tab_transition"):
            return
        if self._tab_transition_after is not None:
            try:
                self.after_cancel(self._tab_transition_after)
            except tk.TclError:
                pass
        self._tab_transition_step = 0

        def paint():
            if not self.tab_transition.winfo_exists():
                return
            width = max(1, self.tab_transition.winfo_width())
            progress = min(1.0, self._tab_transition_step / 7)
            self.tab_transition.delete("all")
            if progress < 1:
                end = max(2, round(width * progress))
                self.tab_transition.create_rectangle(0, 0, end, 3, fill=COLORS.wine, outline="")
                fade_start = max(0, end - 80)
                self.tab_transition.create_rectangle(fade_start, 0, end, 3, fill=COLORS.wine_active, outline="")
                self._tab_transition_step += 1
                self._tab_transition_after = self.after(16, paint)
            else:
                self._tab_transition_after = self.after(55, self.tab_transition.delete, "all")

        paint()

    def _format_datetime_display(self, datetime_str: str) -> str:
        """Formatea una fecha ISO en un formato legible con fecha y hora."""
        if not datetime_str:
            return ""
        try:
            from datetime import datetime
            # Intentar parsear como datetime completo
            if "T" in datetime_str or " " in datetime_str:
                dt = datetime.fromisoformat(datetime_str.replace(" ", "T"))
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                # Si es solo fecha, devolverla tal cual
                return datetime_str
        except (ValueError, AttributeError):
            return datetime_str

    def date_field(self, parent, variable: tk.StringVar, width: int = 20):
        """Campo de fecha ISO con calendario, reutilizado por altas y fichas."""
        field = tk.Frame(parent, background=COLORS.background)
        entry = ttk.Entry(field, textvariable=variable, width=width)
        entry.pack(side="left", fill="x", expand=True)
        ttk.Button(
            field,
            text="Calendario",
            command=lambda: CalendarDialog(self, variable),
            style="Secondary.TButton",
        ).pack(side="left", padx=(6, 0))
        return field



    def show_order_summary(self):
        """Abre el resumen histórico con quién, cuándo, qué y cuánto se cobró."""
        dialog = tk.Toplevel(self)
        dialog.title("Resumen de pedidos y cobros")
        dialog.configure(background=COLORS.background)
        dialog.geometry("1200x620")
        dialog.minsize(880, 430)
        dialog.transient(self)

        content = ttk.Frame(dialog, padding=18)
        content.pack(fill="both", expand=True)
        ttk.Label(content, text="RESUMEN DE PEDIDOS Y COBROS", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            content,
            text="Historial guardado al crear cada pedido. Incluye cliente, fecha, productos, presupuesto y cobros.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(3, 14))

        table_frame = ttk.Frame(content)
        table_frame.pack(fill="both", expand=True)
        columns = ("id", "client", "created", "products", "total", "paid", "last_payment", "status")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        for key, label, width in (
            ("id", "N.º", 55), ("client", "Cliente", 170), ("created", "Creado", 145),
            ("products", "Productos", 325), ("total", "Total", 105), ("paid", "Cobrado", 105),
            ("last_payment", "Último cobro", 145), ("status", "Estado", 120),
        ):
            tree.heading(key, text=label)
            tree.column(key, width=width, anchor="center" if key not in {"client", "products"} else "w")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        for summary in self.database.order_summaries():
            created = str(summary.get("created_at", "")).replace("T", " ")
            last_payment = str(summary.get("last_payment_at", "")).replace("T", " ") or "Sin cobros"
            tree.insert("", "end", iid=str(summary["id"]), values=(
                summary["id"], summary.get("client") or "Sin cliente", created,
                summary.get("products") or "Sin productos",
                f"${float(summary.get('budget_total') or 0):,.2f}",
                f"${float(summary.get('paid_amount') or 0):,.2f}", last_payment,
                summary.get("status") or "Nuevo",
            ))

        def open_summary_order(_event=None):
            selected = tree.selection()
            if selected:
                dialog.destroy()
                self.open_order_workspace(int(selected[0]))

        tree.bind("<Double-1>", open_summary_order)
        actions = ttk.Frame(content)
        actions.pack(fill="x", pady=(14, 0))
        ttk.Label(actions, text="Doble clic en un pedido para abrirlo.", style="Muted.TLabel").pack(side="left")
        ttk.Button(actions, text="Cerrar", command=dialog.destroy).pack(side="right")
        self.center_window(dialog)

    def queue_orders_refresh(self, delay: int = 160):
        """Evita consultar y redibujar la tabla por cada tecla escrita."""
        if self._orders_refresh_after is not None:
            try:
                self.after_cancel(self._orders_refresh_after)
            except tk.TclError:
                pass
        self._orders_refresh_after = self.after(delay, self._flush_orders_refresh)

    def _flush_orders_refresh(self):
        self._orders_refresh_after = None
        self.refresh_orders()

    def open_order_workspace(self, order_id: int):
        # Versión legacy — reemplazada por la definición activa más abajo.
        # Se conserva el método vacío para no romper referencias internas
        # durante la transición; la definición activa sobreescribe en runtime.
        pass

    def refresh_order_workspace(self, order_id: int):
        tab = self.order_tabs.get(order_id)
        if not tab:
            return
        order = next((item for item in self.database.orders() if item["id"] == order_id), None)
        if not order:
            return
        tab.order_title.set(f"Pedido #{order_id} · {order['client']}")
        tab.order_details.set(f"{order['status']} · {order['material'] or 'Sin material'} · {order['quantity']} unidades · {order['size'] or 'Sin tamaño'} · ${order['price']:,.0f}\n{order['observations']}")
        
        # Actualizar tree si existe (vista antigua)
        if hasattr(tab, "order_tree") and tab.order_tree.winfo_exists():
            tree = tab.order_tree
            tree.delete(*tree.get_children())
            for design in self.database.order_designs(order_id):
                tree.insert("", "end", values=(design["name"], design["quantity"], f"{design['size_cm']:g} cm", design.get("tags") or "Sin etiquetas"))

    def link_selection_to_order(self, order_id: int):
        if not self.selected_images:
            messagebox.showinfo("Pedido", "Seleccioná diseños en la pestaña Diseños antes de vincularlos.", parent=self)
            return
        for image in self.selected_images.values():
            self.database.link_design_to_order(order_id, image["path"])
        self.refresh_order_workspace(order_id)
        self.status.set(f"Se vincularon {len(self.selected_images)} diseños al pedido #{order_id}.")

    # Etapa 1 de Pedidos -------------------------------------------------
    # Estas definiciones sustituyen el panel inicial anterior y mantienen
    # las planchas, precios y demás módulos exactamente como estaban.


    # ── Avatar de tipo de cliente ─────────────────────────────────────────────
    # Colores y símbolos para cada tipo de cliente
    _CLIENT_TYPE_STYLE: dict[str, tuple[str, str, str]] = {
        # tipo        : (bg,          border,        símbolo)
        "Particular":  ("#1E2A38",    "#4E8AC7",     "👤"),
        "Empresa":     ("#1E2E1E",    "#2D9B66",     "🏢"),
        "Revendedor":  ("#2A1E2E",    "#8A4EC7",     "🔄"),
        "VIP":         ("#2E1E1A",    "#C98A27",     "⭐"),
    }

    def _render_client_avatar(self, parent: tk.Widget, client_type: str,
                              size: int = 56) -> tk.Canvas:
        """Dibuja un cuadrado con el ícono simbólico del tipo de cliente."""
        style = self._CLIENT_TYPE_STYLE.get(
            client_type, self._CLIENT_TYPE_STYLE["Particular"])
        bg, border_color, symbol = style
        cv = tk.Canvas(parent, width=size, height=size,
                       background=bg, highlightthickness=2,
                       highlightbackground=border_color, bd=0)
        # Emoji centrado — ocupa ~60 % del alto
        emoji_size = max(10, size // 2)
        emoji_y = size // 2 - 4          # ligeramente arriba para dejar espacio al label
        cv.create_text(size // 2, emoji_y, text=symbol,
                       fill=border_color, font=("Segoe UI Emoji", emoji_size))
        # Etiqueta con el nombre del tipo debajo del símbolo
        label_y = size - 9
        cv.create_text(size // 2, label_y, text=client_type.upper(),
                       fill=border_color,
                       font=(IDENTITY_FONT, max(6, size // 9), "bold"))
        return cv

    def _prepare_order_card_payload(self, order: dict) -> dict:
        """Prepara los datos visuales de una ficha sin tocar fuentes oficiales."""
        order_id = order["id"]
        estimated_minutes = estimate_remaining_work(order)
        priority_level, _, _ = calculate_priority(order, estimated_minutes)
        priority_color = get_priority_color(priority_level)
        priority_emoji = get_priority_emoji(priority_level)
        stage = get_current_stage(order)
        progress = get_stage_progress(order)
        time_str = format_time_remaining(order)
        financials = self.database.order_financials(order_id)
        client_type = order.get("client_type") or "Particular"
        client_name = order.get("client_name") or order.get("client") or "Sin cliente"
        delivery = order.get("delivery_date") or "—"
        ingreso = (order.get("order_date") or "")[:10] or "—"
        pending = (order.get("pending_reason") or "").strip()
        material = order.get("material") or "—"
        qty = order.get("quantity") or "—"
        budget_total = financials.get("budget_total", 0)
        paid_amount = financials.get("paid_amount", 0)
        pending_amount = financials.get("pending_amount")
        payment_status = financials.get("payment_status") or "Pendiente"
        status_key = normalize_order_style_key(order.get("status"))
        priority_key = normalize_order_style_key(priority_level)
        status_style = ORDER_STATUS_STYLES.get(status_key, ORDER_STATUS_STYLES["default"])
        priority_style = PRIORITY_STYLES.get(priority_key, PRIORITY_STYLES["default"])

        return {
            "order_id": order_id,
            "status_text": order.get("status", "—"),
            "client_type": client_type,
            "client_name": client_name,
            "delivery": delivery,
            "ingreso": ingreso,
            "pending": pending,
            "material": material,
            "qty": qty,
            "budget_total": budget_total,
            "paid_amount": paid_amount,
            "pending_amount": pending_amount,
            "payment_status": payment_status,
            "priority_level": priority_level,
            "priority_color": priority_color,
            "priority_emoji": priority_emoji,
            "priority_style": priority_style,
            "status_style": status_style,
            "stage": stage,
            "progress": progress,
            "time_str": time_str,
            "is_selected": self._selected_order_id == order_id,
            "delivery_date": order.get("delivery_date", ""),
        }

    def refresh_orders(self):
        """Borra y vuelve a dibujar todas las fichas de pedidos."""
        if not hasattr(self, "_orders_cards_frame"):
            return

        if not hasattr(self, "_orders_cards_frame"):
            return

        view = self.orders_filter.get() if hasattr(self, "orders_filter") else "Todos"
        status_map = {
            "Recibidos": "Recibido",
            "Esperando archivos": "Esperando archivos",
            "Diseños confirmados": "Diseños confirmados",
            "En producción": "En Armado de Planchas",
            "Listos para imprimir": "Listo para imprimir",
            "Finalizados": "Finalizado",
        }
        pending_only = view == "Pendientes"
        query = self.orders_query.get() if hasattr(self, "orders_query") else ""
        orders = self.database.orders(
            status=status_map.get(view), query=query, pending_only=pending_only)

        # Limpiar fichas anteriores y registros de cuenta regresiva
        for w in self._orders_cards_frame.winfo_children():
            w.destroy()
        self._countdown_vars = []
        self._orders_cards_frame.columnconfigure(0, weight=1)

        if not orders:
            tk.Label(
                self._orders_cards_frame,
                text="No hay pedidos para mostrar.",
                background=COLORS.panel, foreground=COLORS.muted,
                font=(UI_FONT, 11),
            ).pack(pady=40)
        else:
            for i, order in enumerate(orders):
                payload = self._prepare_order_card_payload(order)
                self._render_order_card(self._orders_cards_frame, payload, i)

        # Resumen
        if hasattr(self, "orders_summary"):
            urgent = sum(
                1 for o in orders
                if calculate_priority(o, estimate_remaining_work(o))[0] in ("Urgente", "Alta"))
            self.orders_summary.set(
                f"{len(orders)} pedidos · {urgent} urgentes · "
                f"{len(self.database.pending_orders())} pendientes")
            if hasattr(self, "urgent_orders_button_var"):
                self.urgent_orders_button_var.set(f"🚨 Pedidos urgentes ({urgent})")

        if hasattr(self, "notifications_frame"):
            try:
                self.refresh_notifications()
            except Exception:
                pass

        self._refresh_sales_stats()

        # Arrancar o reiniciar el ticker de cuenta regresiva (cada 60 s)
        self._start_countdown_ticker()

    def _refresh_sales_stats(self):
        """Actualiza el panel de ventas con datos reales y semántica de color."""
        if not hasattr(self, "sales_stats_vars"):
            return

        month = (self.sales_month.get().strip() if hasattr(self, "sales_month")
                 else datetime.now().strftime("%Y-%m"))
        stats = self.database.sales_statistics(month)

        budget_total    = stats["budget_total"]
        paid_amount     = stats["paid_amount"]
        pending_amount  = stats["pending_amount"]
        collection_rate = stats["collection_rate"]
        prev_label      = stats.get("prev_month") or "-"
        budget_delta     = stats.get("budget_delta", 0.0)
        budget_delta_pct = stats.get("budget_delta_pct", 0.0)
        paid_delta       = stats.get("paid_delta", 0.0)
        paid_delta_pct   = stats.get("paid_delta_pct", 0.0)
        total_orders     = stats["total_orders"]
        paid_orders      = stats["paid_orders"]
        partial_orders   = stats["partial_orders"]
        pending_orders   = stats["pending_orders"]

        # ── Valores de las cajas ──────────────────────────────────────────────
        self.sales_stats_vars["budget"].set(f"${budget_total:,.2f}")
        self.sales_stats_vars["paid"].set(f"${paid_amount:,.2f}")
        self.sales_stats_vars["pending"].set(f"${pending_amount:,.2f}")
        self.sales_stats_vars["rate"].set(f"{collection_rate:.1f}%")

        # ── Barra de progreso (0-100) con color semántico ─────────────────────
        if hasattr(self, "sales_progress"):
            self.sales_progress["maximum"] = 100
            self.sales_progress["value"]   = min(100.0, collection_rate)
        if hasattr(self, "sales_progress_label") and hasattr(self, "sales_status_var"):
            self.sales_status_var.set(
                f"Cobranza {collection_rate:.1f}%  ·  "
                f"${paid_amount:,.0f} cobrado de ${budget_total:,.0f}  ·  "
                f"vs {prev_label}"
            )

        # ── Resumen textual (fila 2) ──────────────────────────────────────────
        if hasattr(self, "sales_summary_var"):
            self.sales_summary_var.set(
                f"{total_orders} pedidos  ·  {paid_orders} cerrados  ·  "
                f"{partial_orders} con seña  ·  {pending_orders} sin cobrar"
            )

        # ── Chips de conteo con texto actualizado ─────────────────────────────
        if hasattr(self, "sales_status_chips"):
            chip_data = {
                "closed":  (paid_orders,    "● Cerrados"),
                "partial": (partial_orders, "◐ Con seña"),
                "pending": (pending_orders, "○ Sin cobrar"),
            }
            for key, (count, label) in chip_data.items():
                if key in self.sales_status_chips:
                    self.sales_status_chips[key].set(f"{label}: {count}")

        # ── Color semántico de la caja "Cobranza %" ───────────────────────────
        if hasattr(self, "sales_metric_frames") and "rate" in self.sales_metric_frames:
            if collection_rate >= 80:
                rate_accent = "#2D9B66"   # verde — bien cobrado
            elif collection_rate >= 40:
                rate_accent = "#C98A27"   # amarillo — parcial
            else:
                rate_accent = "#C94B27"   # rojo — poco cobrado
            try:
                box = self.sales_metric_frames["rate"]
                box.configure(highlightbackground=rate_accent)
                # actualizar la línea de acento inferior
                children = box.winfo_children()
                for child in children:
                    if isinstance(child, tk.Frame) and child.cget("height") == 3:
                        child.configure(background=rate_accent)
                # actualizar el color del valor
                for child in box.winfo_children():
                    if isinstance(child, tk.Frame):
                        for grandchild in child.winfo_children():
                            try:
                                if grandchild.cget("font") and "bold" in str(grandchild.cget("font")):
                                    grandchild.configure(foreground=rate_accent)
                            except Exception:
                                pass
            except Exception:
                pass

        # ── Chips de delta inline (▲/▼ junto a Presupuestado y Cobrado) ───────
        try:
            _delta_map = {
                "budget": (budget_delta, budget_delta_pct),
                "paid":   (paid_delta,   paid_delta_pct),
            }
            for key, (val, pct) in _delta_map.items():
                if not hasattr(self, "sales_delta_vars") or key not in self.sales_delta_vars:
                    continue
                arrow  = "▲" if val > 0 else ("▼" if val < 0 else "→")
                sign   = "+" if val >= 0 else ""
                text   = f"{arrow} {sign}${val:,.0f} ({sign}{pct:.1f}%)"
                self.sales_delta_vars[key].set(text)

                if not hasattr(self, "sales_delta_labels") or key not in self.sales_delta_labels:
                    continue
                lbl = self.sales_delta_labels[key]
                if val > 0:
                    lbl.configure(foreground="#2D9B66", background=COLORS.panel)
                elif val < 0:
                    lbl.configure(foreground="#C94B27", background=COLORS.panel)
                else:
                    lbl.configure(foreground=COLORS.muted, background=COLORS.panel)
        except Exception:
            pass

        # ── Gráfico matplotlib (si disponible) ────────────────────────────────
        if HAS_MATPLOTLIB and hasattr(self, "_plot_container"):
            try:
                self._draw_sales_chart()
            except Exception:
                pass

    def _draw_sales_chart(self):
        """Dibuja la serie diaria o semanal en el contenedor de la UI."""
        if not HAS_MATPLOTLIB:
            return
        month = (self.sales_month.get().strip() if hasattr(self, "sales_month") else datetime.now().strftime("%Y-%m"))
        series = self.database.sales_time_series(month)
        dates = [item["date"] for item in series]
        budgets = [item["budget"] for item in series]
        paids = [item["paid"] for item in series]

        # Limpiar contenedor
        for child in self._plot_container.winfo_children():
            child.destroy()

        fig = Figure(figsize=(8, 2.2), dpi=96)
        ax = fig.add_subplot(111)
        gran = (self.sales_granularity.get() if hasattr(self, "sales_granularity") else "Diario")
        if gran == "Diario":
            x = list(range(len(dates)))
            ax.plot(x, paids, label="Cobrado", color="#39d353")
            ax.bar(x, budgets, alpha=0.25, label="Presupuestado", color="#4E8AC7")
            ax.set_xticks(x[:: max(1, len(x)//10)])
            ax.set_xticklabels(dates[:: max(1, len(x)//10)], rotation=45, fontsize=8)
        else:
            # Agrupar por semana (semana ISO) simple: sumar cada 7 días
            import math
            n = len(dates)
            weeks = math.ceil(n / 7)
            x = list(range(weeks))
            budgets_w = [sum(budgets[i*7:(i+1)*7]) for i in x]
            paids_w = [sum(paids[i*7:(i+1)*7]) for i in x]
            ax.bar([i - 0.15 for i in x], budgets_w, width=0.3, label="Presupuestado", color="#4E8AC7")
            ax.bar([i + 0.15 for i in x], paids_w, width=0.3, label="Cobrado", color="#39d353")
            ax.set_xticks(x)
            ax.set_xticklabels([f"Semana {i+1}" for i in x], rotation=0, fontsize=8)

        ax.set_ylabel("ARS")
        ax.set_title(f"Ventas ({month})")
        ax.legend(fontsize=8)
        fig.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=self._plot_container)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        canvas.draw()

    def _change_sales_month(self, offset: int = 0):
        """Mueve el selector de mes `offset` meses (±1)."""
        try:
            cur = datetime.strptime(self.sales_month.get().strip(), "%Y-%m")
        except Exception:
            cur = datetime.now()
        # Calcular mes objetivo
        year = cur.year + ((cur.month - 1 + offset) // 12)
        month = ((cur.month - 1 + offset) % 12) + 1
        new = datetime(year, month, 1)
        self.sales_month.set(new.strftime("%Y-%m"))
        self._refresh_sales_stats()

    def show_order_line_details(self, order_id: int, parent_dialog=None):
        """Muestra las líneas (productos) de un pedido y permite exportarlas."""
        try:
            designs = self.database.order_designs(order_id) or []
        except Exception:
            designs = []
        dialog = tk.Toplevel(self)
        dialog.title(f"Detalle pedido #{order_id}")
        dialog.configure(background=COLORS.background)
        dialog.geometry("640x360")
        dialog.transient(self)

        content = ttk.Frame(dialog, padding=12)
        content.pack(fill="both", expand=True)
        ttk.Label(content, text=f"Líneas del pedido #{order_id}", style="Title.TLabel").pack(anchor="w")

        cols = ("name", "quantity", "size", "price")
        tree = ttk.Treeview(content, columns=cols, show="headings")
        for key, label, width in (("name", "Producto", 300), ("quantity", "Cantidad", 80), ("size", "Tamaño", 80), ("price", "Precio", 120)):
            tree.heading(key, text=label)
            tree.column(key, width=width, anchor="w")
        scrollbar = ttk.Scrollbar(content, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        lines = []
        for d in designs:
            name = d.get("name") or d.get("design_name") or "Item"
            qty = d.get("quantity") or d.get("qty") or 1
            size = d.get("size") or d.get("size_cm") or ""
            price = d.get("price") or ""
            lines.append({"name": name, "quantity": qty, "size": size, "price": price})
            tree.insert("", "end", values=(name, qty, size, price))

        actions = ttk.Frame(content)
        actions.pack(fill="x", pady=(8, 0))

        def export_lines():
            if not lines:
                messagebox.showinfo("Exportar", "No hay líneas para exportar.", parent=dialog)
                return
            path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile=f"pedido_{order_id}_lines.csv", filetypes=[("CSV files", "*.csv")], title="Exportar líneas a CSV", parent=dialog)
            if path:
                try:
                    write_order_lines_csv(lines, path)
                    messagebox.showinfo("Exportado", f"Se exportaron {len(lines)} líneas a:\n{path}", parent=dialog)
                except Exception as e:
                    messagebox.showerror("Error", f"No se pudo exportar: {e}", parent=dialog)

        ttk.Button(actions, text="Exportar líneas", command=export_lines, style="Secondary.TButton").pack(side="right", padx=(8, 0))
        ttk.Button(actions, text="Abrir pedido", command=lambda: (dialog.destroy(), parent_dialog and parent_dialog.destroy() or None, self.open_order_workspace(order_id))).pack(side="right")
        ttk.Button(actions, text="Cerrar", command=dialog.destroy).pack(side="right")

    def show_sales_details(self):
        """Muestra un diálogo con la lista de pedidos del mes seleccionado."""
        month = self.sales_month.get().strip() if hasattr(self, "sales_month") else datetime.now().strftime("%Y-%m")
        dialog = tk.Toplevel(self)
        dialog.title(f"Pedidos · {month}")
        dialog.configure(background=COLORS.background)
        dialog.geometry("1000x540")
        dialog.transient(self)

        content = ttk.Frame(dialog, padding=12)
        content.pack(fill="both", expand=True)
        ttk.Label(content, text=f"Pedidos de {month}", style="Title.TLabel").pack(anchor="w")

        cols = ("id", "client", "created", "total", "paid", "pending", "status")
        tree = ttk.Treeview(content, columns=cols, show="headings")
        for key, label, width in (("id", "N.º", 60), ("client", "Cliente", 220), ("created", "Creado", 160), ("total", "Total", 100), ("paid", "Cobrado", 100), ("pending", "Pendiente", 100), ("status", "Estado", 100)):
            tree.heading(key, text=label)
            tree.column(key, width=width, anchor="center" if key not in {"client"} else "w")
        scrollbar = ttk.Scrollbar(content, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # cargar pedidos y preparar filtros
        orders_list = list(self.database.orders_for_month(month))

        def format_row(order: dict) -> dict:
            fin = self.database.order_financials(order["id"])
            created = str(order.get("created_at") or order.get("order_date") or "").replace("T", " ")
            # Resumen de productos (nombre x cantidad)
            try:
                designs = self.database.order_designs(order["id"]) or []
                products = ", ".join(f"{d.get('name', 'Item')} x{d.get('quantity', 1)}" for d in designs)
            except Exception:
                products = ""
            return {
                "id": order["id"],
                "client": order.get("client") or "Sin cliente",
                "created": created,
                "total": f"${fin['budget_total']:,.2f}",
                "paid": f"${fin['paid_amount']:,.2f}",
                "pending": f"${fin['pending_amount']:,.2f}",
                "status": fin.get("payment_status") or "",
                "products": products,
            }

        for order in orders_list:
            row = format_row(order)
            tree.insert("", "end", iid=str(row["id"]), values=(row["id"], row["client"], row["created"], row["total"], row["paid"], row["pending"], row["status"]))

        # filtros: cliente y estado
        clients = [o.get("client") or "Sin cliente" for o in orders_list]
        clients = ["Todos"] + sorted(set(clients))
        statuses = [self.ORDER_STATUSES] if not hasattr(self, "ORDER_STATUSES") else []
        statuses = ["Todos"] + sorted(set(format_row(o)["status"] for o in orders_list if format_row(o)["status"]))

        filter_frame = ttk.Frame(content)
        filter_frame.pack(fill="x", pady=(8, 6))
        tk.Label(filter_frame, text="Cliente:", background=COLORS.background, foreground=COLORS.muted).pack(side="left", padx=(0, 6))
        client_var = tk.StringVar(value="Todos")
        client_picker = ttk.Combobox(filter_frame, textvariable=client_var, values=clients, state="readonly", width=30)
        client_picker.pack(side="left")
        tk.Label(filter_frame, text="Estado:", background=COLORS.background, foreground=COLORS.muted).pack(side="left", padx=(12, 6))
        status_var = tk.StringVar(value="Todos")
        status_picker = ttk.Combobox(filter_frame, textvariable=status_var, values=statuses, state="readonly", width=20)
        status_picker.pack(side="left")

        def refresh_filter(_event=None):
            sel_client = client_var.get()
            sel_status = status_var.get()
            tree.delete(*tree.get_children())
            for order in orders_list:
                row = format_row(order)
                if sel_client != "Todos" and row["client"] != sel_client:
                    continue
                if sel_status != "Todos" and row["status"] != sel_status:
                    continue
                tree.insert("", "end", iid=str(row["id"]), values=(row["id"], row["client"], row["created"], row["total"], row["paid"], row["pending"], row["status"]))

        client_picker.bind("<<ComboboxSelected>>", refresh_filter)
        status_picker.bind("<<ComboboxSelected>>", refresh_filter)

        def open_line_details(_event=None):
            sel = tree.selection()
            if not sel:
                return
            order_id = int(sel[0])
            # abrir diálogo de líneas sin cerrar el diálogo principal
            self.show_order_line_details(order_id, parent_dialog=dialog)

        tree.bind("<Double-1>", open_line_details)
        actions = ttk.Frame(content)
        actions.pack(fill="x", pady=(8, 0))

        def export_visible():
            sel_client = client_var.get()
            sel_status = status_var.get()
            visible = []
            for order in orders_list:
                row = format_row(order)
                if sel_client != "Todos" and row["client"] != sel_client:
                    continue
                if sel_status != "Todos" and row["status"] != sel_status:
                    continue
                visible.append(row)
            path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")], title="Exportar pedidos a CSV", parent=dialog)
            if path:
                try:
                    write_orders_csv(visible, path)
                    messagebox.showinfo("Exportado", f"Se exportaron {len(visible)} pedidos a:\n{path}", parent=dialog)
                except Exception as e:
                    messagebox.showerror("Error", f"No se pudo exportar: {e}", parent=dialog)

        def export_batch_zip():
            sel_client = client_var.get()
            sel_status = status_var.get()
            visible = []
            order_lines_map = {}
            for order in orders_list:
                row = format_row(order)
                if sel_client != "Todos" and row["client"] != sel_client:
                    continue
                if sel_status != "Todos" and row["status"] != sel_status:
                    continue
                visible.append(row)
                try:
                    lines = []
                    for d in self.database.order_designs(order["id"]) or []:
                        lines.append({"name": d.get("name") or d.get("design_name") or "Item", "quantity": d.get("quantity") or 1, "size": d.get("size") or d.get("size_cm") or "", "price": d.get("price") or ""})
                    if lines:
                        order_lines_map[order["id"]] = lines
                except Exception:
                    pass
            if not visible:
                messagebox.showinfo("Exportar lote", "No hay pedidos visibles para exportar.", parent=dialog)
                return
            path = filedialog.asksaveasfilename(defaultextension=".zip", filetypes=[("ZIP files", "*.zip")], title="Exportar pedidos como ZIP", parent=dialog)
            if not path:
                return
            try:
                write_orders_zip(visible, path, order_lines_map=order_lines_map)
                messagebox.showinfo("Exportado", f"Se exportaron {len(visible)} pedidos en \n{path}", parent=dialog)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo exportar: {e}", parent=dialog)

        ttk.Button(actions, text="Exportar lote (ZIP)", command=export_batch_zip, style="Secondary.TButton").pack(side="right", padx=(8, 0))

        def export_for_client(client_name: str):
            if not client_name or client_name == "Todos":
                messagebox.showinfo("Exportar cliente", "Seleccioná un cliente distinto de 'Todos' para exportar.", parent=dialog)
                return
            visible = []
            for order in orders_list:
                row = format_row(order)
                if row["client"] == client_name:
                    visible.append(row)
            if not visible:
                messagebox.showinfo("Exportar cliente", f"No se encontraron pedidos para {client_name}.", parent=dialog)
                return
            path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile=f"pedidos_{client_name}.csv", filetypes=[("CSV files", "*.csv")], title="Exportar pedidos de cliente a CSV", parent=dialog)
            if path:
                try:
                    write_orders_csv(visible, path)
                    messagebox.showinfo("Exportado", f"Se exportaron {len(visible)} pedidos de {client_name} a:\n{path}", parent=dialog)
                except Exception as e:
                    messagebox.showerror("Error", f"No se pudo exportar: {e}", parent=dialog)

        ttk.Button(actions, text="Exportar cliente", command=lambda: export_for_client(client_var.get()), style="Secondary.TButton").pack(side="right", padx=(8, 0))

        ttk.Button(actions, text="Exportar CSV", command=export_visible, style="Secondary.TButton").pack(side="right", padx=(8, 0))
        ttk.Button(actions, text="Cerrar", command=dialog.destroy).pack(side="right")

    def _start_countdown_ticker(self):
        """Cancela cualquier ticker previo y arranca uno nuevo cada 60 segundos."""
        # Cancelar tick anterior si existe
        if hasattr(self, "_countdown_after") and self._countdown_after is not None:
            try:
                self.after_cancel(self._countdown_after)
            except tk.TclError:
                pass
        self._countdown_after = None
        self._tick_countdowns()

    def _tick_countdowns(self):
        """Actualiza el texto de cada chip de cuenta regresiva activo."""
        if not hasattr(self, "_countdown_vars"):
            return
        for var, delivery_date, _ in self._countdown_vars:
            try:
                # Verificar que el StringVar sigue vivo
                var.get()
            except tk.TclError:
                continue
            from app.workflow.estimator import format_time_remaining
            text = format_time_remaining({"delivery_date": delivery_date})
            var.set(f"⏱ {text}")
        # Reprogramar para dentro de 60 s
        self._countdown_after = self.after(60_000, self._tick_countdowns)

    def _render_order_card(self, parent: tk.Widget, payload: dict, index: int):
        """Construye una ficha individual para un pedido con un layout más compacto."""
        card_bg = getattr(COLORS, "panel_elevated", COLORS.panel)
        panel_bg = getattr(COLORS, "background_secondary", COLORS.field)
        card = tk.Frame(
            parent, background=card_bg,
            highlightthickness=1, highlightbackground=COLORS.border,
            cursor="hand2",
        )
        card.pack(fill="x", expand=True, padx=10, pady=(5, 0))
        card.columnconfigure(1, weight=1)

        try:
            order_id = payload["order_id"]
            priority_level = payload["priority_level"]
            priority_color = payload["priority_color"]
            priority_emoji = payload["priority_emoji"]
            stage = payload["stage"]
            progress = payload["progress"]
            time_str = payload["time_str"]
            client_type = payload["client_type"]
            client_name = payload["client_name"]
            delivery = payload["delivery"]
            ingreso = payload["ingreso"]
            pending = payload["pending"]
            material = payload["material"]
            qty = payload["qty"]
            budget_total = payload["budget_total"]
            paid_amount = payload["paid_amount"]
            payment_status = payload["payment_status"]
            pending_amount = payload["pending_amount"]
            status_style = payload.get("status_style") or ORDER_STATUS_STYLES.get("default", ORDER_STATUS_STYLES["default"])
            priority_style = payload.get("priority_style") or PRIORITY_STYLES.get("default", PRIORITY_STYLES["default"])
            is_selected = payload["is_selected"]
            status_text = payload.get("status_text", "—")
            try:
                progress_value = max(0.0, min(1.0, float(progress or 0.0)))
                progress_pct = int(max(0, min(100, progress_value * 100)))
            except (TypeError, ValueError):
                progress_value = 0.0
                progress_pct = 0

            # Avatar reduced 20% for a more compact card
            avatar = self._render_client_avatar(card, client_type, size=42)
            avatar.grid(row=0, column=0, rowspan=3, padx=(8, 8), pady=(6, 6), sticky="n")

            header = tk.Frame(card, background=card_bg)
            header.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=(8, 3))
            header.columnconfigure(0, weight=1)

            client_frame = tk.Frame(header, background=card_bg)
            client_frame.grid(row=0, column=0, sticky="w")
            # Increase client name hierarchy for quick scanning
            tk.Label(
                client_frame, text=client_name, background=card_bg,
                foreground=COLORS.text, font=(IDENTITY_FONT, 15, "bold"), anchor="w"
            ).pack(anchor="w")
            tk.Label(
                client_frame, text=f"Pedido #{order_id}", background=card_bg,
                foreground=COLORS.muted, font=(UI_FONT, 9), anchor="w"
            ).pack(anchor="w")

            # Badges: status more prominent than priority
            badges = tk.Frame(header, background=card_bg)
            badges.grid(row=0, column=1, sticky="e")

            # Status badge (primary)
            status_badge = tk.Frame(badges, background=status_style.get("bg", COLORS.border), padx=0, pady=0)
            status_badge.pack(side="left", padx=(0, 6))
            tk.Label(
                status_badge,
                text=status_text,
                background=status_style.get("bg", COLORS.border),
                foreground=status_style.get("fg", COLORS.text),
                font=(UI_FONT, 8, "bold"), padx=6, pady=2,
            ).pack()

            # Priority chip (subtle)
            if priority_level in ("Urgente", "Alta", "Media", "Baja"):
                pri_lbl = tk.Label(
                    badges,
                    text=f"{priority_emoji} {priority_level}",
                    background=card_bg,
                    foreground=priority_style.get("accent", COLORS.muted),
                    font=(UI_FONT, 8), padx=6, pady=2,
                )
                pri_lbl.pack(side="left")

            meta = tk.Frame(card, background=card_bg)
            meta.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=(0, 4))
            meta.columnconfigure(1, weight=1)

            tk.Label(meta, text=f"📍 {stage}", background=card_bg, foreground=COLORS.muted, font=(UI_FONT, 8)).grid(row=0, column=0, sticky="w")

            # De-emphasize progress: smaller, muted and compact
            progress_frame = tk.Frame(meta, background=card_bg)
            progress_frame.grid(row=0, column=1, sticky="e", padx=(6, 0))
            try:
                style = ttk.Style()
                style.configure("Card.Small.Horizontal.TProgressbar", troughcolor=card_bg, background=COLORS.border_strong)
                progress_bar = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate", maximum=1.0, value=progress_value, length=120, style="Card.Small.Horizontal.TProgressbar")
            except Exception:
                progress_bar = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate", maximum=1.0, value=progress_value, length=120)
            progress_bar.pack(side="left", padx=(0, 4))
            tk.Label(progress_frame, text=f"{progress_pct}%", background=card_bg, foreground=COLORS.muted, font=(UI_FONT, 8)).pack(side="left")

            # Condensed secondary info: single-line chips with reduced borders
            metrics = tk.Frame(card, background=card_bg)
            metrics.grid(row=2, column=1, sticky="ew", padx=(0, 10), pady=(0, 6))
            metrics.columnconfigure(0, weight=1)

            chips = tk.Frame(metrics, background=panel_bg)
            chips.pack(fill="x")

            def chip(text, fg=COLORS.text, bg=panel_bg):
                lbl = tk.Label(chips, text=text, background=bg, foreground=fg, font=(UI_FONT, 8), padx=6, pady=4, relief="flat")
                lbl.pack(side="left", padx=(0, 6))
                return lbl

            chip(f"Ingreso: {ingreso}")
            if delivery == "—":
                chip("Entrega: Sin fecha", fg=COLORS.warning)
            else:
                chip(f"Entrega: {delivery}")
                countdown_var = tk.StringVar(value=f"⏱ {time_str}")
                if str(time_str).startswith("Atrasado"):
                    countdown_bg = COLORS.warning
                    countdown_fg = COLORS.text
                elif "h" in str(time_str) and any(token in str(time_str) for token in ("72", "48", "24")):
                    countdown_bg = COLORS.warning
                    countdown_fg = COLORS.text
                else:
                    countdown_bg = COLORS.success
                    countdown_fg = COLORS.text
                countdown_lbl = tk.Label(chips, textvariable=countdown_var, background=countdown_bg, foreground=countdown_fg, font=(UI_FONT, 8, "bold"), padx=6, pady=4, relief="flat")
                countdown_lbl.pack(side="left", padx=(0, 6))
                if not hasattr(self, "_countdown_vars"):
                    self._countdown_vars = []
                self._countdown_vars.append((countdown_var, payload["delivery_date"], priority_color))

            chip(f"{material} · {qty} u.")
            chip(f"Total: {format_currency(budget_total)}", fg=COLORS.success if payment_status == "Pagado" else COLORS.text)
            chip(f"Saldo: {format_currency(pending_amount) if pending_amount is not None else '—'}", fg=COLORS.warning if (pending_amount or 0) > 0 else COLORS.text)

            if pending:
                pending_lbl = tk.Label(chips, text=f"⚠ {pending[:40] + ('…' if len(pending) > 40 else '')}", background=COLORS.wine_soft, foreground=COLORS.warning, font=(UI_FONT, 8), padx=6, pady=4, relief="flat")
                pending_lbl.pack(side="left", padx=(0, 6))

            tk.Frame(card, background=COLORS.border, height=1).grid(row=3, column=0, columnspan=2, sticky="ew", padx=10)

            def on_click(_e, oid=order_id, c=card):
                self._selected_order_id = oid
                self.refresh_orders()

            def on_double(_e, oid=order_id):
                self.open_order_workspace(oid)

            def on_right_click(e, oid=order_id):
                self._orders_context_menu_for_card(e, oid)

            for widget in card.winfo_children():
                widget.bind("<Button-1>", on_click)
                widget.bind("<Double-1>", on_double)
                widget.bind("<Button-3>", on_right_click)
            card.bind("<Button-1>", on_click)
            card.bind("<Double-1>", on_double)
            card.bind("<Button-3>", on_right_click)
            avatar.bind("<Button-1>", on_click)
            avatar.bind("<Double-1>", on_double)
            avatar.bind("<Button-3>", on_right_click)

            if is_selected:
                card.configure(highlightbackground=COLORS.wine_active, highlightthickness=2)
        except Exception:
            traceback.print_exc()
            for child in card.winfo_children():
                child.destroy()
            card.configure(highlightbackground=COLORS.error, highlightthickness=2)
            tk.Label(card, text="Error al renderizar pedido", background=card_bg, foreground=COLORS.text, font=(UI_FONT, 10, "bold"), padx=10, pady=12).pack(fill="both", expand=True)

    def _orders_context_menu_for_card(self, event, order_id: int):
        """Menú contextual desde una ficha (equivalente al anterior de Treeview)."""
        self._selected_order_id = order_id
        menu = tk.Menu(self, tearoff=0)
        configure_menu(menu)
        menu.add_command(label="Abrir pedido",
                         command=lambda: self.open_order_workspace(order_id))
        menu.add_separator()
        menu.add_command(label="Archivar orden",
                         command=lambda: self._archive_order(order_id))
        menu.add_separator()
        menu.add_command(label="Eliminar orden",
                         command=lambda: self._delete_order(order_id))
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()

    def open_selected_order(self, _event=None):
        if self._selected_order_id is not None:
            self.open_order_workspace(self._selected_order_id)

    def _archive_order(self, order_id: int):
        """Archiva un pedido sin eliminarlo de la base de datos."""
        order = next((o for o in self.database.orders() if o["id"] == order_id), None)
        if not order:
            return
        
        if not messagebox.askyesno(
            "Archivar pedido",
            f"¿Archivar el pedido #{order_id} · {order.get('client_name') or order['client']}?\n\n"
            "El pedido quedará oculto de la vista principal pero se mantendrán todos sus datos.",
            parent=self
        ):
            return
        
        self.database.archive_order(order_id)
        self.refresh_orders()
        self.status.set(f"Pedido #{order_id} archivado correctamente.")

    def _delete_order(self, order_id: int):
        """Elimina permanentemente un pedido de la base de datos."""
        order = next((o for o in self.database.orders() if o["id"] == order_id), None)
        if not order:
            return
        
        if not messagebox.askyesno(
            "Eliminar pedido",
            f"¿ELIMINAR PERMANENTEMENTE el pedido #{order_id} · {order.get('client_name') or order['client']}?\n\n"
            "Esta acción NO se puede deshacer. Se eliminarán todos los datos, diseños vinculados, "
            "planchas, pagos y el historial completo del pedido.",
            icon="warning",
            parent=self
        ):
            return
        
        # Cerrar la pestaña del pedido si está abierta
        if order_id in self.order_tabs:
            tab = self.order_tabs[order_id]
            if tab.winfo_exists():
                self.tabs.forget(tab)
                tab.destroy()
            del self.order_tabs[order_id]
        
        self.database.delete_order(order_id)
        self.refresh_orders()
        self.status.set(f"Pedido #{order_id} eliminado permanentemente.")
    
    def show_attention_dashboard(self):
        """Abre el panel de pedidos que necesitan atención hoy."""
        show_attention_dashboard(
            parent=self,
            database=self.database,
            on_open_order=self.open_order_workspace
        )
    
    def refresh_order_timeline(self, order_id: int):
        """Sincroniza estado, porcentaje, opciones y visual de la línea de tiempo."""
        tab = self.order_tabs.get(order_id)
        if not tab or not hasattr(tab, "timeline_status"):
            return
        
        # Recargar el pedido desde la base de datos para tener el estado actualizado
        updated_order = self.database.order(order_id)
        if not updated_order:
            return
        
        # Simular el pedido con el nuevo estado para calcular la etapa
        temp_order = {
            "id": order_id,
            "status": updated_order.get("status", "Nuevo"),
            "material": updated_order.get("material", ""),
            "jobs": getattr(tab, "order_job_state", []),
            "design_count": len(tab.order_design_state),
            "confirmed_count": sum(1 for d in tab.order_design_state if d.get("status") == "Confirmado"),
        }
        
        stage = get_current_stage(temp_order)
        progress = get_stage_progress(temp_order)
        
        tab.timeline_status.set(f"{stage} · {int(progress * 100)}% completado")
        if hasattr(tab, "status_widget"):
            tab.status_widget.configure(values=order_statuses(temp_order))
        if hasattr(tab, "timeline_visual"):
            for widget in tab.timeline_visual.winfo_children():
                widget.destroy()
            self._render_order_timeline(tab.timeline_visual, temp_order)

    def _render_order_timeline(self, timeline_visual, order: dict):
        """Dibuja los hitos del flujo activo, incluido el específico por producto."""
        from app.workflow.timeline import workflow_stages
        
        timeline_stages = format_timeline(order)
        columns = min(6, len(timeline_stages))
        for column in range(columns):
            timeline_visual.columnconfigure(column, weight=1, uniform="timeline")

        order_id = order.get("id")
        available_stages = workflow_stages(order)
        
        for index, (stage_name, symbol) in enumerate(timeline_stages):
            row, column = divmod(index, columns)
            stage_col = tk.Frame(timeline_visual, background=COLORS.panel)
            stage_col.grid(row=row, column=column, padx=6, pady=(0, 8), sticky="nsew")
            is_current_or_done = symbol == "●"
            
            # Crear botón clicable para el círculo
            def make_stage_updater(stage, stage_index):
                def update_stage():
                    # Actualizar el estado del pedido a esta etapa
                    self.database.update_order_status(order_id, stage)
                    
                    # Recargar el pedido actualizado desde la base de datos
                    tab = self.order_tabs.get(order_id)
                    if tab:
                        updated_order = self.database.order(order_id)
                        if updated_order:
                            # Actualizar el StringVar del estado
                            tab.order_values["status"].set(updated_order.get("status", stage))
                    
                    # Refrescar la línea de tiempo
                    self.refresh_order_timeline(order_id)
                    
                    # Refrescar la lista de pedidos si está visible
                    self.refresh_orders()
                    
                    self.status.set(f"Estado actualizado a: {stage}")
                return update_stage
            
            # Botón con el círculo
            circle_btn = tk.Button(
                stage_col, text=symbol, background=COLORS.panel,
                foreground=COLORS.wine_active if is_current_or_done else COLORS.muted,
                font=(UI_FONT, 14, "bold"),
                relief="flat", bd=0, cursor="hand2",
                activebackground=COLORS.panel,
                activeforeground=COLORS.wine_active,
                command=make_stage_updater(stage_name, index)
            )
            circle_btn.pack()
            
            # Agregar efecto hover
            def on_enter(e, btn=circle_btn):
                btn.configure(foreground=COLORS.wine_active, font=(UI_FONT, 16, "bold"))
            
            def on_leave(e, btn=circle_btn, active=is_current_or_done):
                color = COLORS.wine_active if active else COLORS.muted
                btn.configure(foreground=color, font=(UI_FONT, 14, "bold"))
            
            circle_btn.bind("<Enter>", on_enter)
            circle_btn.bind("<Leave>", on_leave)
            
            # Label con el nombre de la etapa
            tk.Label(
                stage_col, text=stage_name.replace(" / ", "/\n").replace(" de ", "\nde "),
                background=COLORS.panel,
                foreground=COLORS.text if is_current_or_done else COLORS.muted,
                font=(UI_FONT, 8), justify="center",
            ).pack()

# Module-level export helpers (moved here so the class body is uninterrupted)
def write_orders_csv(orders: list[dict], path: str) -> None:
    fieldnames = ("id", "client", "created", "total", "paid", "pending", "status", "products")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for o in orders:
            row = {k: o.get(k, "") for k in fieldnames}
            writer.writerow(row)


def write_order_lines_csv(lines: list[dict], path: str) -> None:
    fieldnames = ("name", "quantity", "size", "price")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for l in lines:
            writer.writerow({k: l.get(k, "") for k in fieldnames})


def write_orders_zip(orders: list[dict], path: str | None, order_lines_map: dict[int, list[dict]] | None = None) -> None:
    if path is not None:
        tmpdir = Path(tempfile.mkdtemp(prefix="orders_export_"))
        try:
            files = []
            for o in orders:
                oid = o.get("id")
                summary_path = tmpdir / f"order_{oid}.csv"
                write_orders_csv([o], str(summary_path))
                files.append(summary_path)
                if order_lines_map and oid in order_lines_map:
                    lines = order_lines_map[oid]
                    lines_path = tmpdir / f"order_{oid}_lines.csv"
                    write_order_lines_csv(lines, str(lines_path))
                    files.append(lines_path)
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for f in files:
                    zf.write(f, arcname=f.name)
        finally:
            try:
                for p in tmpdir.iterdir():
                    p.unlink()
                tmpdir.rmdir()
            except Exception:
                pass

    def refresh_notifications(self):
        """Actualiza el panel de notificaciones con pedidos prioritarios."""
        if not hasattr(self, "notifications_frame"):
            return
        
        # Limpiar notificaciones existentes
        for widget in self.notifications_frame.winfo_children():
            widget.destroy()
        
        # Obtener pedidos activos (no archivados ni finalizados)
        all_orders = self.database.orders()
        active_orders = [o for o in all_orders if o.get("status") not in ("Finalizado", "Archivado")]
        
        # Si no hay pedidos activos
        if not active_orders:
            tk.Label(
                self.notifications_frame,
                text="Sin pedidos activos",
                background=COLORS.background_secondary,
                foreground=COLORS.disabled,
                font=(UI_FONT, 9),
                wraplength=145
            ).pack(pady=3)
            return
        
        # Calcular prioridad para cada pedido y ordenar
        orders_with_priority = []
        for order in active_orders:
            estimated_minutes = estimate_remaining_work(order)
            priority_level, priority_score, priority_reason = calculate_priority(order, estimated_minutes)
            orders_with_priority.append({
                "order": order,
                "level": priority_level,
                "score": priority_score,
                "reason": priority_reason
            })
        
        # Ordenar por score descendente (más urgentes primero)
        orders_with_priority.sort(key=lambda x: x["score"], reverse=True)
        
        # Mostrar solo los 5 pedidos más prioritarios
        top_orders = orders_with_priority[:5]
        
        for item in top_orders:
            order = item["order"]
            level = item["level"]
            emoji = get_priority_emoji(level)
            color = get_priority_color(level)
            payload = build_order_notification_payload(order, level, item["score"], item["reason"])
            if payload is None:
                continue

            # Frame para cada notificación
            notification = tk.Frame(
                self.notifications_frame,
                background=color,
                highlightthickness=1,
                highlightbackground=color
            )
            notification.pack(fill="x", pady=2)
            
            # Contenido interno con padding
            inner = tk.Frame(notification, background=COLORS.background_secondary)
            inner.pack(fill="both", expand=True, padx=1, pady=1)
            
            # Cliente y emoji
            client_name = payload["client_name"]
            
            header = tk.Frame(inner, background=COLORS.background_secondary)
            header.pack(fill="x", padx=6, pady=(4, 2))
            
            lbl_id = tk.Label(
                header,
                text=f"{emoji} #{payload['order_id']}",
                background=COLORS.background_secondary,
                foreground=color,
                font=(IDENTITY_FONT, 10, "bold")
            )
            lbl_id.pack(side="left")
            
            lbl_client = tk.Label(
                header,
                text=client_name,
                background=COLORS.background_secondary,
                foreground=color,
                font=(UI_FONT, 9)
            )
            lbl_client.pack(side="right")
            
            # Razón de prioridad
            reason = payload["reason"]
            
            lbl_reason = tk.Label(
                inner,
                text=reason,
                background=COLORS.background_secondary,
                foreground=color,
                font=(UI_FONT, 8),
                wraplength=145,
                justify="left"
            )
            lbl_reason.pack(anchor="w", padx=6, pady=(0, 4))
            
            # Doble clic abre el pedido; hover resalta el borde
            def make_open_handler(order_id):
                return lambda e: self.open_order_workspace(order_id)

            def make_hover_in(frame, inner_frame):
                def handler(e):
                    frame.configure(highlightthickness=2)
                    inner_frame.configure(background=COLORS.panel_elevated)
                return handler

            def make_hover_out(frame, inner_frame, orig_bg):
                def handler(e):
                    frame.configure(highlightthickness=1)
                    inner_frame.configure(background=orig_bg)
                return handler

            orig_inner_bg = inner.cget("background")
            for widget in (notification, inner, header, lbl_id, lbl_client, lbl_reason):
                widget.bind("<Double-1>", make_open_handler(payload["order_id"]))
                widget.bind("<Enter>", make_hover_in(notification, inner))
                widget.bind("<Leave>", make_hover_out(notification, inner, orig_inner_bg))
                widget.configure(cursor="hand2")
                
        # Resumen al final
        urgent_count = sum(1 for item in orders_with_priority if item["level"] in ("Urgente", "Alta"))
        summary_text = f"{urgent_count} urgentes de {len(active_orders)} activos"
        
        tk.Label(
            self.notifications_frame,
            text=summary_text,
            background=COLORS.background_secondary,
            foreground=COLORS.muted,
            font=(IDENTITY_FONT, 8, "bold")
        ).pack(pady=(6, 3))

    def open_notification_center(self):
        """Centro de notificaciones: historial de eventos, dispositivos y pruebas."""
        dialog = tk.Toplevel(self)
        dialog.title("Centro de notificaciones")
        dialog.configure(background=COLORS.background)
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("620x520")
        dialog.minsize(500, 420)

        # --- Encabezado ---
        header = tk.Frame(dialog, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        header.pack(fill="x", padx=12, pady=(12, 0))
        tk.Label(header, text="CENTRO DE NOTIFICACIONES", background=COLORS.panel, foreground=COLORS.wine_active,
                 font=(IDENTITY_FONT, 13, "bold")).pack(side="left", padx=14, pady=10)
        tk.Label(header, text="Historial · Dispositivos · Pruebas", background=COLORS.panel,
                 foreground=COLORS.muted, font=(UI_FONT, 9)).pack(side="left", padx=(0, 14), pady=10)

        # --- Pestañas internas ---
        notebook = ttk.Notebook(dialog)
        notebook.pack(fill="both", expand=True, padx=12, pady=12)

        # Pestaña Historial
        history_tab = ttk.Frame(notebook)
        notebook.add(history_tab, text="Historial")
        self._build_notification_history(history_tab)

        # Pestaña Dispositivos
        devices_tab = ttk.Frame(notebook)
        notebook.add(devices_tab, text="Dispositivos")
        self._build_devices_panel(devices_tab)

        # Pestaña Configuración
        settings_tab = ttk.Frame(notebook)
        notebook.add(settings_tab, text="Configuración")
        self._build_notification_settings(settings_tab)

        # Pie
        footer = tk.Frame(dialog, background=COLORS.background)
        footer.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(footer, text="Cerrar", command=dialog.destroy, style="Secondary.TButton").pack(side="right")
        stats = self._event_repo.outbox_stats()
        pending = stats.get("pending", 0)
        sent = stats.get("sent", 0)
        dead = stats.get("dead", 0)
        processing = stats.get("processing", 0)
        stats_text = f"Cola: {pending} pend · {processing} proc · {sent} enviados · {dead} muertos"
        tk.Label(footer, text=stats_text, background=COLORS.background, foreground=COLORS.muted,
                 font=(UI_FONT, 8)).pack(side="right", padx=(0, 12))
        ttk.Button(footer, text="Enviar prueba",
                   command=lambda: self._send_test_from_center(dialog),
                   style="Primary.TButton").pack(side="left")

    def _build_notification_history(self, parent):
        """Construye la lista de eventos recientes."""
        events = self._event_repo.recent_events(limit=30)
        if not events:
            tk.Label(parent, text="Aún no hay eventos registrados.\nLos eventos aparecen cuando creás pedidos, registrás cobros o hay errores de producción.",
                     background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 10),
                     justify="center", wraplength=400).pack(expand=True, pady=60)
            return

        # Canvas con scroll
        canvas = tk.Canvas(parent, background=COLORS.panel, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable = tk.Frame(canvas, background=COLORS.panel)
        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw", tags="inner")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Ajustar ancho del canvas al frame
        def _on_canvas_configure(event):
            canvas.itemconfig("inner", width=event.width - 4)
        canvas.bind("<Configure>", _on_canvas_configure)

        for event in events:
            icon = EVENT_ICONS.get(event["event_type"], "📋")
            priority = event.get("priority", "normal")
            if priority == "high":
                accent = COLORS.error
            elif priority == "normal":
                accent = COLORS.info
            else:
                accent = COLORS.muted

            row = tk.Frame(scrollable, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
            row.pack(fill="x", padx=8, pady=2)

            left = tk.Frame(row, background=COLORS.panel_elevated)
            left.pack(side="left", fill="x", expand=True, padx=10, pady=6)

            tk.Label(left, text=f"{icon} {event['title']}", background=COLORS.panel_elevated,
                     foreground=accent, font=(UI_FONT, 10, "bold"), anchor="w").pack(anchor="w")
            tk.Label(left, text=event["message"], background=COLORS.panel_elevated,
                     foreground=COLORS.text, font=(UI_FONT, 9), anchor="w", wraplength=380).pack(anchor="w")
            ts = event.get("created_at", "")[:16].replace("T", " ")
            tk.Label(left, text=ts, background=COLORS.panel_elevated,
                     foreground=COLORS.disabled, font=(UI_FONT, 8)).pack(anchor="w")

    def _build_devices_panel(self, parent):
        """Panel de gestión de dispositivos móviles."""
        devices = self._event_repo.active_devices()

        # Barra de acciones
        bar = tk.Frame(parent, background=COLORS.panel)
        bar.pack(fill="x", padx=10, pady=(10, 6))
        tk.Label(bar, text=f"{len(devices)} dispositivo(s) vinculado(s)",
                 background=COLORS.panel, foreground=COLORS.text, font=(UI_FONT, 10)).pack(side="left")
        ttk.Button(bar, text="Vincular nuevo", command=lambda: self._pair_device_dialog(parent),
                   style="Primary.TButton").pack(side="right")

        # Lista de dispositivos
        if not devices:
            tk.Label(parent, text="No hay dispositivos vinculados.\nUsá \"Vincular nuevo\" para conectar tu celular.",
                     background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 10),
                     justify="center", wraplength=350).pack(expand=True, pady=40)
            return

        for device in devices:
            row = tk.Frame(parent, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
            row.pack(fill="x", padx=10, pady=3)

            info = tk.Frame(row, background=COLORS.panel_elevated)
            info.pack(side="left", fill="x", expand=True, padx=10, pady=8)
            name = device.get("device_name") or "Sin nombre"
            platform = device.get("platform", "unknown")
            token_short = device["push_token"][:16] + "..."
            tk.Label(info, text=f"{name} ({platform})", background=COLORS.panel_elevated,
                     foreground=COLORS.text, font=(UI_FONT, 10, "bold"), anchor="w").pack(anchor="w")
            tk.Label(info, text=f"Token: {token_short}", background=COLORS.panel_elevated,
                     foreground=COLORS.muted, font=(UI_FONT, 8), anchor="w").pack(anchor="w")
            last = device.get("last_seen_at", "")[:16].replace("T", " ") if device.get("last_seen_at") else "Desconocido"
            tk.Label(info, text=f"Última vez: {last}", background=COLORS.panel_elevated,
                     foreground=COLORS.disabled, font=(UI_FONT, 8), anchor="w").pack(anchor="w")

            actions = tk.Frame(row, background=COLORS.panel_elevated)
            actions.pack(side="right", padx=10)
            
            # Botón de prueba
            ttk.Button(actions, text="Prueba",
                       command=lambda token=device["push_token"]: self._send_test_notification(token),
                       style="Secondary.TButton").pack(pady=(0, 2))
            
            # Botón de renombrar
            ttk.Button(actions, text="Renombrar",
                       command=lambda did=device["id"], name=device.get("device_name", ""), w=parent: self._rename_device(did, name, w),
                       style="Secondary.TButton").pack(pady=(0, 2))
            
            # Botón de pausar/reactivar
            if device.get("active", 1) == 1:
                ttk.Button(actions, text="Pausar",
                           command=lambda did=device["id"], w=parent: self._pause_device(did, w),
                           style="Secondary.TButton").pack(pady=(0, 2))
            else:
                ttk.Button(actions, text="Reactivar",
                           command=lambda did=device["id"], w=parent: self._resume_device(did, w),
                           style="Secondary.TButton").pack(pady=(0, 2))
            
            # Botón de desvincular
            ttk.Button(actions, text="Desvincular",
                       command=lambda did=device["id"], w=parent: self._deactivate_device(did, w),
                       style="Danger.TButton").pack()

    def _send_test_notification(self, token: str):
        """Envía una notificación de prueba al dispositivo."""
        ok = self._notification_service.send_test_notification(
            token,
            "🔔 Prueba de Doccione",
            "Si ves esto, las notificaciones están funcionando correctamente.",
        )
        if ok:
            self.status.set("Notificación de prueba enviada.")
            Toast(self, "Notificación enviada", tone="success")
        else:
            self.status.set("Error al enviar notificación de prueba.")
            Toast(self, "Error al enviar", tone="error")

    def _rename_device(self, device_id: int, current_name: str, panel):
        """Renombra un dispositivo."""
        new_name = simpledialog.askstring("Renombrar dispositivo", "Nuevo nombre:",
                                          initialvalue=current_name, parent=self)
        if new_name and new_name != current_name:
            self._event_repo.rename_device(device_id, new_name)
            self.status.set("Dispositivo renombrado.")
            for w in panel.winfo_children():
                w.destroy()
            self._build_devices_panel(panel)

    def _pause_device(self, device_id: int, panel):
        """Pausa temporalmente un dispositivo."""
        if messagebox.askyesno("Pausar dispositivo", "¿Pausar este dispositivo? No recibirá notificaciones.", parent=self):
            self._event_repo.pause_device(device_id)
            self.status.set("Dispositivo pausado.")
            for w in panel.winfo_children():
                w.destroy()
            self._build_devices_panel(panel)

    def _resume_device(self, device_id: int, panel):
        """Reactiva un dispositivo pausado."""
        self._event_repo.resume_device(device_id)
        self.status.set("Dispositivo reactivado.")
        for w in panel.winfo_children():
            w.destroy()
            self._build_devices_panel(panel)

    def _deactivate_device(self, device_id, panel):
        """Desvincula un dispositivo y refresca el panel."""
        if not messagebox.askyesno("Desvincular", "¿Desvincular este dispositivo?", parent=panel):
            return
        self._event_repo.deactivate_device(device_id)
        self.status.set("Dispositivo desvinculado.")
        # Reconstruir panel
        for w in panel.winfo_children():
            w.destroy()
        self._build_devices_panel(panel)

    def _pair_device_dialog(self, parent):
        """Abre un diálogo de emparejamiento con código temporal de 6 dígitos.

        Flujo seguro:
        1. PC genera código temporal (6 dígitos, válido 5 min, uso único, almacenado como hash).
        2. Celular ingresa el código manualmente en Doccione Mobile.
        3. Celular envía código + token FCM a la PC vía HTTP.
        4. PC valida el código y registra el dispositivo automáticamente.
        """
        import json as _json

        # Generar código en la base de datos
        code = self._event_repo.create_pairing_code()
        installation_id = "studio-principal"

        dialog = tk.Toplevel(parent)
        dialog.title("Vincular celular")
        dialog.configure(background=COLORS.background)
        dialog.transient(parent)
        dialog.grab_set()
        dialog.geometry("420x380")
        dialog.resizable(False, False)

        header = tk.Frame(dialog, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        header.pack(fill="x", padx=12, pady=(12, 0))
        tk.Label(header, text="VINCULAR CELULAR", background=COLORS.panel, foreground=COLORS.text,
                 font=(IDENTITY_FONT, 14, "bold")).pack(side="left", padx=14, pady=10)
        tk.Label(header, text="Código de un solo uso · Válido 5 minutos",
                 background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 9)).pack(side="left", padx=(0, 14), pady=10)

        body = tk.Frame(dialog, background=COLORS.background)
        body.pack(fill="both", expand=True, padx=20, pady=16)

        # Código
        tk.Label(body, text="Código de vinculación", background=COLORS.background,
                 foreground=COLORS.text, font=(UI_FONT, 10, "bold")).pack(anchor="w")
        tk.Label(body, text="Ingresá este código en Doccione Mobile para vincular el dispositivo.",
                 background=COLORS.background, foreground=COLORS.muted, font=(UI_FONT, 9)).pack(anchor="w", pady=(0, 8))

        code_frame = tk.Frame(body, background=COLORS.panel_elevated, highlightthickness=2, highlightbackground=COLORS.wine_active)
        code_frame.pack(fill="x", pady=(0, 12))
        tk.Label(code_frame, text=code, background=COLORS.panel_elevated, foreground=COLORS.wine_active,
                 font=("Consolas", 34, "bold")).pack(pady=16)

        # Instrucciones
        info_frame = tk.Frame(body, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
        info_frame.pack(fill="x", pady=(0, 12))
        tk.Label(info_frame, text="Instrucciones:", background=COLORS.panel_elevated,
                 foreground=COLORS.text, font=(UI_FONT, 9, "bold")).pack(anchor="w", padx=8, pady=(6, 4))
        tk.Label(info_frame, text="1. Abre Doccione Mobile en tu celular", background=COLORS.panel_elevated,
                 foreground=COLORS.text, font=(UI_FONT, 9)).pack(anchor="w", padx=8)
        tk.Label(info_frame, text="2. Ingresa el código de 6 dígitos", background=COLORS.panel_elevated,
                 foreground=COLORS.text, font=(UI_FONT, 9)).pack(anchor="w", padx=8)
        tk.Label(info_frame, text="3. El dispositivo se vinculará automáticamente", background=COLORS.panel_elevated,
                 foreground=COLORS.text, font=(UI_FONT, 9)).pack(anchor="w", padx=8, pady=(0, 6))

        # Botones
        btn_row = tk.Frame(body, background=COLORS.background)
        btn_row.pack(fill="x")

        def refresh_code():
            nonlocal code
            code = self._event_repo.create_pairing_code()
            for widget in code_frame.winfo_children():
                widget.destroy()
            tk.Label(code_frame, text=code, background=COLORS.panel_elevated, foreground=COLORS.wine_active,
                     font=("Consolas", 34, "bold")).pack(pady=16)

        def close_dialog():
            dialog.destroy()
            for w in parent.winfo_children():
                w.destroy()
            self._build_devices_panel(parent)

        ttk.Button(btn_row, text="Generar nuevo código", command=refresh_code, style="Secondary.TButton").pack(side="left")
        ttk.Button(btn_row, text="Cerrar", command=close_dialog, style="Secondary.TButton").pack(side="left", padx=(8, 0))

    def _build_notification_settings(self, parent):
        """Configuración global de notificaciones."""
        # Horario silencioso
        frame = tk.Frame(parent, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
        frame.pack(fill="x", padx=10, pady=10)
        inner = tk.Frame(frame, background=COLORS.panel_elevated)
        inner.pack(fill="x", padx=14, pady=12)
        tk.Label(inner, text="Horario silencioso", background=COLORS.panel_elevated,
                 foreground=COLORS.text, font=(UI_FONT, 11, "bold")).pack(anchor="w")
        tk.Label(inner, text="Durante este período no se envían notificaciones push.\nLos eventos quedan registrados localmente.",
                 background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 9),
                 wraplength=400).pack(anchor="w", pady=(4, 8))

        quiet_frame = tk.Frame(inner, background=COLORS.panel_elevated)
        quiet_frame.pack(anchor="w")
        tk.Label(quiet_frame, text="Desde:", background=COLORS.panel_elevated, foreground=COLORS.text,
                 font=(UI_FONT, 9)).pack(side="left")
        self._quiet_from = tk.StringVar(value="23:00")
        ttk.Combobox(quiet_frame, textvariable=self._quiet_from,
                     values=[f"{h:02d}:00" for h in range(24)], width=6, state="readonly").pack(side="left", padx=(4, 12))
        tk.Label(quiet_frame, text="Hasta:", background=COLORS.panel_elevated, foreground=COLORS.text,
                 font=(UI_FONT, 9)).pack(side="left")
        self._quiet_to = tk.StringVar(value="07:00")
        ttk.Combobox(quiet_frame, textvariable=self._quiet_to,
                     values=[f"{h:02d}:00" for h in range(24)], width=6, state="readonly").pack(side="left", padx=4)

        # Errores ignoran silencio
        self._errors_bypass_quiet = tk.BooleanVar(value=True)
        ttk.Checkbutton(inner, text="Errores urgentes ignoran horario silencioso",
                        variable=self._errors_bypass_quiet).pack(anchor="w", pady=(10, 0))

        # Info Firebase
        info = tk.Frame(parent, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
        info.pack(fill="x", padx=10, pady=10)
        info_inner = tk.Frame(info, background=COLORS.panel_elevated)
        info_inner.pack(fill="x", padx=14, pady=12)
        tk.Label(info_inner, text="Firebase Cloud Messaging", background=COLORS.panel_elevated,
                 foreground=COLORS.text, font=(UI_FONT, 11, "bold")).pack(anchor="w")
        stats = self._event_repo.outbox_stats()
        status_text = (
            f"Cola: {stats['pending']} pendiente(s) · "
            f"{stats.get('processing', 0)} procesando · "
            f"{stats['sent']} enviado(s) · "
            f"{stats['dead']} fallido(s)"
        )
        tk.Label(info_inner, text=status_text, background=COLORS.panel_elevated,
                 foreground=COLORS.muted, font=(UI_FONT, 9)).pack(anchor="w", pady=(4, 0))

    def _send_test_from_center(self, parent):
        """Envía una notificación de prueba al primer dispositivo activo."""
        devices = self._event_repo.active_devices()
        if not devices:
            messagebox.showinfo("Prueba", "No hay dispositivos vinculados. Vinculá un celular primero.", parent=parent)
            return
        token = devices[0]["push_token"]
        ok = self._notification_service.send_test_notification(
            token,
            "🔔 Prueba de Doccione",
            "Si ves esto, las notificaciones están funcionando correctamente.",
        )
        if ok:
            self.status.set("Notificación de prueba enviada.")
            try:
                Toast(parent, "Prueba enviada correctamente", tone="success")
            except Exception:
                pass
        else:
            self.status.set("No se pudo enviar la prueba. Verificá la configuración de Firebase.")
            try:
                Toast(parent, "Firebase no configurado o sin conexión", tone="warning")
            except Exception:
                pass

    def new_order_dialog(self):
        """Alta rápida: solo identifica el pedido antes de abrir su ficha completa."""
        dialog = tk.Toplevel(self)
        dialog.title("Crear pedido")
        dialog.configure(background=COLORS.background)
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("570x730")
        dialog.resizable(False, False)

        style = ttk.Style(dialog)
        style.configure(
            "QuickOrder.TCombobox", fieldbackground=COLORS.field,
            background=COLORS.panel_elevated, foreground=COLORS.text,
            arrowcolor=COLORS.text, padding=(8, 6),
        )
        client_var, delivery_var = tk.StringVar(), tk.StringVar()
        order_date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        concept_var = tk.StringVar(value="")
        description_var = tk.StringVar(value="")
        client_type_var = tk.StringVar(value="Particular")
        client_hint = tk.StringVar(value="Escribí para buscar un cliente existente.")
        last_query = {"value": ""}

        header = tk.Frame(dialog, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        header.pack(fill="x", padx=18, pady=(18, 12))
        tk.Label(header, text="CREAR PEDIDO", background=COLORS.panel, foreground=COLORS.text,
                 font=(IDENTITY_FONT, 19, "bold")).pack(anchor="w", padx=20, pady=(16, 3))
        tk.Label(
            header,
            text="Ingrese los datos mínimos para crear el pedido. Luego podrá completar el resto de la información.",
            background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 10), wraplength=500, justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 16))

        form = tk.Frame(dialog, background=COLORS.background)
        form.pack(fill="both", expand=True, padx=30, pady=(2, 0))
        form.columnconfigure(0, weight=1)

        def label(text, row, top=0):
            tk.Label(form, text=text, background=COLORS.background, foreground=COLORS.text,
                     font=(UI_FONT, 10, "bold")).grid(row=row, column=0, sticky="w", pady=(top, 6))

        label("Cliente", 0)
        client_combo = ttk.Combobox(form, textvariable=client_var, style="QuickOrder.TCombobox", font=(UI_FONT, 11))
        client_combo.grid(row=1, column=0, sticky="ew")
        tk.Label(form, textvariable=client_hint, background=COLORS.background, foreground=COLORS.muted,
                 font=(UI_FONT, 9)).grid(row=2, column=0, sticky="w", pady=(4, 17))

        def refresh_client_matches(_event=None):
            query = client_var.get().strip()
            if query.startswith("＋ Crear cliente nuevo"):
                return
            last_query["value"] = query
            rows = self.database.connection.execute(
                "SELECT name FROM clients WHERE name LIKE ? COLLATE NOCASE ORDER BY name LIMIT 8",
                (f"%{query}%",),
            ).fetchall()
            matches = [str(row[0]) for row in rows]
            if query and not matches:
                client_combo.configure(values=("＋ Crear cliente nuevo",))
                client_hint.set("No se encontró el cliente. Se podrá crear uno nuevo al confirmar.")
            else:
                client_combo.configure(values=matches)
                client_hint.set("Seleccioná un cliente existente o escribí uno nuevo.")

        def choose_client(_event=None):
            if client_var.get() == "＋ Crear cliente nuevo":
                client_var.set(last_query["value"])
                client_combo.icursor("end")
                client_hint.set("Cliente nuevo listo para crear al confirmar.")

        client_combo.bind("<KeyRelease>", refresh_client_matches)
        client_combo.bind("<<ComboboxSelected>>", choose_client)
        refresh_client_matches()

        label("Tipo de cliente", 3)
        type_combo = ttk.Combobox(
            form, textvariable=client_type_var,
            values=("Particular", "Empresa", "Revendedor", "VIP"),
            state="readonly", style="QuickOrder.TCombobox",
        )
        type_combo.grid(row=4, column=0, sticky="ew")
        tk.Label(form, text="Determina el ícono de la ficha del pedido.", background=COLORS.background,
                 foreground=COLORS.muted, font=(UI_FONT, 9)).grid(row=5, column=0, sticky="w", pady=(4, 17))

        label("Fecha de ingreso", 6)
        entry_date_field = self.date_field(form, order_date_var, width=33)
        entry_date_field.grid(row=7, column=0, sticky="ew")
        tk.Label(form, text="Fecha en que se recibe el pedido (por defecto: hoy).", background=COLORS.background,
                 foreground=COLORS.muted, font=(UI_FONT, 9)).grid(row=8, column=0, sticky="w", pady=(4, 17))

        label("Fecha de entrega", 9)
        delivery_field = self.date_field(form, delivery_var, width=33)
        delivery_field.grid(row=10, column=0, sticky="ew")
        tk.Label(form, text="Opcional · podés dejarla vacía y definirla después.", background=COLORS.background,
                 foreground=COLORS.muted, font=(UI_FONT, 9)).grid(row=11, column=0, sticky="w", pady=(4, 17))

        label("Concepto", 12)
        ttk.Entry(form, textvariable=concept_var, style="QuickOrder.TCombobox").grid(row=13, column=0, sticky="ew")
        tk.Label(form, text="Breve descripción del pedido para identificarlo rápido.", background=COLORS.background,
                 foreground=COLORS.muted, font=(UI_FONT, 9)).grid(row=14, column=0, sticky="w", pady=(4, 8))

        label("Descripción", 15)
        description_entry = tk.Text(
            form, height=3, background=COLORS.field, foreground=COLORS.text, insertbackground=COLORS.text,
            relief="flat", highlightthickness=1, highlightbackground=COLORS.border,
            highlightcolor=COLORS.wine_active, font=(UI_FONT, 11), wrap="word",
        )
        description_entry.grid(row=16, column=0, sticky="nsew")
        description_entry.insert("1.0", "")
        tk.Label(form, text="Detalle opcional para el pedido y la producción.", background=COLORS.background, foreground=COLORS.muted,
                 font=(UI_FONT, 9)).grid(row=17, column=0, sticky="w", pady=(4, 12))

        label("Observación rápida (opcional)", 18)
        notes = tk.Text(
            form, height=3, background=COLORS.field, foreground=COLORS.text, insertbackground=COLORS.text,
            relief="flat", highlightthickness=1, highlightbackground=COLORS.border,
            highlightcolor=COLORS.wine_active, font=(UI_FONT, 11), wrap="word",
        )
        notes.grid(row=19, column=0, sticky="nsew")
        tk.Label(form, text="Ejemplo: Stickers para termo.", background=COLORS.background, foreground=COLORS.muted,
                 font=(UI_FONT, 9)).grid(row=20, column=0, sticky="w", pady=(4, 0))

        def create():
            client = client_var.get().strip()
            if not client or client == "＋ Crear cliente nuevo":
                messagebox.showwarning("Crear pedido", "Indicá el cliente.", parent=dialog)
                client_combo.focus_set()
                return
            try:
                order_id = self.database.create_order(
                    client, order_date=order_date_var.get().strip() or datetime.now().isoformat(timespec="seconds"),
                    status="Recibido",
                    delivery_date=delivery_var.get().strip(), observations=notes.get("1.0", "end").strip(),
                    order_concept=concept_var.get().strip(),
                    order_description=description_entry.get("1.0", "end").strip(),
                )
                # Actualizar tipo de cliente si se especificó uno distinto al default
                client_type = client_type_var.get().strip()
                if client_type and client_type != "Particular":
                    order_row = self.database.connection.execute(
                        "SELECT client_id FROM orders WHERE id = ?", (order_id,)
                    ).fetchone()
                    if order_row and order_row[0]:
                        self.database.update_client_type(order_row[0], client_type)
                # Publicar evento de nuevo pedido
                try:
                    order_data = self.database.order(order_id)
                    total = float(order_data.get("budget_total", 0) or 0) if order_data else 0
                    self._event_bus.publish_order_created(order_id, client, total)
                except Exception:
                    pass
            except ValueError as error:
                messagebox.showwarning("Crear pedido", str(error), parent=dialog)
                return
            dialog.destroy()
            self.refresh_orders()
            self.open_order_workspace(order_id)

        actions = tk.Frame(dialog, background=COLORS.background)
        actions.pack(fill="x", padx=30, pady=(20, 24))
        ttk.Button(actions, text="Cancelar", command=dialog.destroy, style="Secondary.TButton").pack(side="right")
        ttk.Button(actions, text="Crear y abrir", command=create, style="Primary.TButton").pack(side="right", padx=(0, 9))
        def create_with_enter(_event):
            create()
            return "break"

        dialog.bind("<Return>", create_with_enter)
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        self.center_window(dialog)
        client_combo.focus_set()

    def edit_order_job_dialog(self, parent, job: dict | None, on_save):
        """Edita un trabajo individual sin modificar los demás ítems del pedido."""
        source = dict(job or {})
        dialog = tk.Toplevel(parent)
        dialog.title("Editar trabajo" if job else "Agregar trabajo")
        dialog.configure(background=COLORS.background)
        dialog.transient(parent)
        dialog.grab_set()
        dialog.geometry("520x650")
        dialog.resizable(False, False)
        
        style = ttk.Style(dialog)
        style.configure("Order.TCombobox", fieldbackground=COLORS.field, background=COLORS.panel_elevated,
                        foreground=COLORS.text, arrowcolor=COLORS.text, padding=(7, 5))
        
        values = {key: tk.StringVar(value=str(source.get(key, default))) for key, default in (
            ("title", ""), ("material", ""), ("size", ""), ("quantity", 1),
            ("discount_percent", 0), ("extra_services", 0), ("status", "Pendiente"),
        )}
        
        # Variables adicionales para mostrar info
        subtotal_var = tk.StringVar(value="$ 0,00")
        price_detail_var = tk.StringVar(value="Seleccioná material y tamaño")
        
        form = tk.Frame(dialog, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
        form.pack(fill="both", expand=True, padx=18, pady=18)
        tk.Label(form, text="DETALLE DEL TRABAJO", background=COLORS.panel_elevated, foreground=COLORS.wine_active,
                 font=(IDENTITY_FONT, 14, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(16, 12))
        form.columnconfigure(1, weight=1)

        def field_entry(value, state="normal"):
            return tk.Entry(form, textvariable=value, background=COLORS.field, foreground=COLORS.text,
                            insertbackground=COLORS.text, relief="flat", highlightthickness=1,
                            highlightbackground=COLORS.border, highlightcolor=COLORS.wine_active, 
                            font=(UI_FONT, 10), state=state)
        
        def get_available_sizes_for_material(material):
            """Obtiene los tamaños disponibles para un material específico desde la BD."""
            if not material or not material.strip():
                return []
            
            # Consultar reglas de precios activas para este material
            rows = self.database.connection.execute(
                """SELECT DISTINCT size FROM price_rules 
                   WHERE active = 1 AND material = ? AND size <> ''
                   ORDER BY CASE WHEN size = 'A4' THEN 99 
                            ELSE CAST(REPLACE(REPLACE(size, 'cm', ''), ' ', '') AS REAL) 
                            END DESC""",
                (material.strip(),)
            ).fetchall()
            
            return [row[0] for row in rows]
        
        def calculate_subtotal():
            """Calcula y actualiza el subtotal usando suggest_price de la BD."""
            try:
                material = values["material"].get().strip()
                size = values["size"].get().strip()
                quantity = max(1, int(values["quantity"].get() or 1))
                discount = max(0, min(100, float(values["discount_percent"].get() or 0)))
                extra = max(0, float(values["extra_services"].get() or 0))
                
                if not material or not size:
                    subtotal_var.set("$ 0,00")
                    price_detail_var.set("Seleccioná material y tamaño")
                    return
                
                # Usar el método suggest_price de la base de datos
                rule = self.database.suggest_price(material, size, quantity)
                
                if rule and rule.get("suggested_subtotal"):
                    subtotal_base = float(rule["suggested_subtotal"])
                    calculation_detail = rule.get("calculation_detail", "")
                    
                    # Aplicar descuento y servicios extra
                    importe_descuento = subtotal_base * discount / 100
                    subtotal_final = subtotal_base - importe_descuento + extra
                    
                    # Actualizar visualización
                    subtotal_var.set(f"$ {subtotal_final:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                    price_detail_var.set(calculation_detail)
                else:
                    subtotal_var.set("$ 0,00")
                    price_detail_var.set("No hay precio configurado para esta combinación")
                    
            except (ValueError, TypeError) as e:
                subtotal_var.set("$ 0,00")
                price_detail_var.set("Error al calcular")
        
        def on_material_change(*args):
            """Actualiza los tamaños disponibles cuando cambia el material."""
            material = values["material"].get().strip()
            current_title = values["title"].get().strip()
            if not current_title and material:
                values["title"].set(material)

            available_sizes = get_available_sizes_for_material(material)
            size_combo.configure(values=available_sizes)
            
            # Si el tamaño actual no está disponible, limpiar
            current_size = values["size"].get().strip()
            if current_size not in available_sizes:
                values["size"].set("")
            
            calculate_subtotal()
        
        # Conectar cambios a la calculadora
        values["material"].trace_add("write", on_material_change)
        values["size"].trace_add("write", lambda *args: calculate_subtotal())
        values["quantity"].trace_add("write", lambda *args: calculate_subtotal())
        values["discount_percent"].trace_add("write", lambda *args: calculate_subtotal())
        values["extra_services"].trace_add("write", lambda *args: calculate_subtotal())

        def build_presupuesto_text():
            material = values["material"].get().strip()
            size = values["size"].get().strip()
            quantity = max(1, int(values["quantity"].get() or 1))
            discount = max(0, min(100, float(values["discount_percent"].get() or 0)))
            extra = max(0, float(values["extra_services"].get() or 0))
            if " - " in material:
                title = values["title"].get().strip() or material.split(" - ", 1)[0]
                material_label = material.split(" - ", 1)[1] if material.split(" - ", 1)[1] else material
            else:
                title = values["title"].get().strip() or material or "Producto"
                material_label = material or "-"

            def format_amount(value: float) -> str:
                return f"$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

            rule = self.database.suggest_price(material, size, quantity)
            subtotal_base = float(rule["suggested_subtotal"]) if rule and rule.get("suggested_subtotal") else 0
            unit_price = subtotal_base / quantity if quantity and subtotal_base else 0
            precio_unitario = format_amount(unit_price) if unit_price else "-"
            base_text = format_amount(subtotal_base)
            extra_text = format_amount(extra) if extra else "$ 0,00"
            discount_text = f"{discount:g}%" if discount else "0%"
            final_total = max(0.0, subtotal_base - subtotal_base * discount / 100 + extra)
            final_total_text = format_amount(final_total)
            detail = rule.get("calculation_detail") if rule else ""
            detail = re.sub(r"\$\s*([0-9,]+\.[0-9]{2})", lambda m: format_amount(float(m.group(1).replace(",", ""))), detail) if detail else detail

            lines = [
                "📋 Presupuesto Doccione",
                "",
                "• Producto:",
                f"  • {title}",
                f"    • Material: {material_label}",
                f"    • Tamaño: {size or '-'}",
                f"    • Cantidad: {quantity}",
                f"    • Precio unitario: {precio_unitario}",
                f"    • Subtotal base: {base_text}",
                f"    • Descuento aplicado: {discount_text}",
                f"    • Servicios extra: {extra_text}",
                "",
                f"Total final: {final_total_text}",
                "",
                f"Precio sugerido: {detail}" if detail else "Precio sugerido: sin detalle disponible",
                "",
                "⏳ Tiempo de entrega: 3-5 días hábiles (estimado)",
                "💳 Seña: 0",
                "📦 Entrega: Retiro",
                "",
                "¡Gracias por elegir Doccione! Cualquier modificación en medidas, cantidad o material actualiza el presupuesto.",
            ]
            return "\n".join(lines)

        def open_presupuesto_modal():
            contenido = build_presupuesto_text()
            modal = tk.Toplevel(dialog)
            modal.title("Presupuesto Doccione")
            modal.configure(background=COLORS.background)
            modal.transient(dialog)
            modal.grab_set()
            modal.geometry("640x540")
            modal.resizable(False, False)

            frame = tk.Frame(modal, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
            frame.pack(fill="both", expand=True, padx=18, pady=18)

            tk.Label(frame, text="Presupuesto generado", background=COLORS.panel_elevated, foreground=COLORS.text, font=(IDENTITY_FONT, 14, "bold")).pack(anchor="w", padx=16, pady=(12, 8))
            text_box = tk.Text(frame, wrap="word", background=COLORS.field, foreground=COLORS.text, insertbackground=COLORS.text, relief="flat", highlightthickness=1, highlightbackground=COLORS.border, font=(UI_FONT, 10))
            text_box.pack(fill="both", expand=True, padx=16, pady=(0, 10))
            text_box.insert("1.0", contenido)
            text_box.configure(state="disabled")

            buttons = tk.Frame(modal, background=COLORS.background)
            buttons.pack(fill="x", padx=18, pady=(0, 16))
            def copy_to_clipboard():
                modal.clipboard_clear()
                modal.clipboard_append(contenido)
                modal.update()
            ttk.Button(buttons, text="Copiar al portapapeles", command=copy_to_clipboard, style="Secondary.TButton").pack(side="left")
            ttk.Button(buttons, text="Cerrar", command=modal.destroy, style="Secondary.TButton").pack(side="right")
            def apply_to_form():
                notes.delete("1.0", "end")
                notes.insert("1.0", contenido)
                if not contenido.strip().endswith("#presupuesto"):
                    notes.insert("end", "\n#presupuesto")
                modal.destroy()
            ttk.Button(buttons, text="Aplicar al formulario", command=apply_to_form, style="Primary.TButton").pack(side="right", padx=(0, 8))

        # Campos del formulario
        row = 1
        
        # Producto (Combobox editable con historial)
        tk.Label(form, text="Producto", background=COLORS.panel_elevated, foreground=COLORS.text,
                 font=(UI_FONT, 10, "bold")).grid(row=row, column=0, sticky="w", padx=16, pady=5)
        
        # Obtener lista de títulos existentes
        existing_titles = self.database.job_titles()
        
        product_combo = ttk.Combobox(form, textvariable=values["title"], values=existing_titles, style="Order.TCombobox")
        product_combo.grid(row=row, column=1, sticky="ew", padx=(0, 16), pady=5)
        row += 1

        # Material (selector — muestra solo la parte de material; mapea al valor completo)
        tk.Label(form, text="Material", background=COLORS.panel_elevated, foreground=COLORS.text,
             font=(UI_FONT, 10, "bold")).grid(row=row, column=0, sticky="w", padx=16, pady=5)

        # Preparar lista visible y mapa a valor almacenado en DB
        stored_materials = self.database.price_materials()
        material_display_map = {}
        material_display_list = []
        for m in stored_materials:
            if " - " in m:
                disp = m.split(" - ", 1)[1]
            else:
                disp = m
            if disp in material_display_map:
                # si ya existe visualmente, usar la forma completa para evitar ambigüedad
                disp = m
            material_display_map[disp] = m
            material_display_list.append(disp)

        material_display_var = tk.StringVar()
        # Inicializar vista desde valor almacenado si existe
        stored_current = values.get("material", tk.StringVar()).get()
        if stored_current:
            if " - " in stored_current:
                initial_disp = stored_current.split(" - ", 1)[1]
            else:
                initial_disp = stored_current
            material_display_var.set(initial_disp if initial_disp in material_display_map else initial_disp)

        material_combo = ttk.Combobox(form, textvariable=material_display_var, values=material_display_list, style="Order.TCombobox", state="readonly")
        material_combo.grid(row=row, column=1, sticky="ew", padx=(0, 16), pady=5)

        def on_material_select(_event=None):
            sel = material_display_var.get().strip()
            if not sel:
                values["material"].set("")
                return
            stored = material_display_map.get(sel, sel)
            values["material"].set(stored)

        material_combo.bind("<<ComboboxSelected>>", on_material_select)
        row += 1
        
        # Tamaño
        tk.Label(form, text="Tamaño", background=COLORS.panel_elevated, foreground=COLORS.text,
                 font=(UI_FONT, 10, "bold")).grid(row=row, column=0, sticky="w", padx=16, pady=5)
        size_combo = ttk.Combobox(form, textvariable=values["size"], values=[], style="Order.TCombobox")
        size_combo.grid(row=row, column=1, sticky="ew", padx=(0, 16), pady=5)
        row += 1
        
        # Cantidad
        tk.Label(form, text="Cantidad", background=COLORS.panel_elevated, foreground=COLORS.text,
                 font=(UI_FONT, 10, "bold")).grid(row=row, column=0, sticky="w", padx=16, pady=5)
        field_entry(values["quantity"]).grid(row=row, column=1, sticky="ew", padx=(0, 16), pady=5)
        row += 1
        
        # Detalle de precio (info)
        tk.Label(form, textvariable=price_detail_var, background=COLORS.panel_elevated, 
                 foreground=COLORS.muted, font=(UI_FONT, 9)).grid(row=row, column=0, columnspan=2, 
                                                                    sticky="w", padx=16, pady=(2, 5))
        row += 1
        
        # Descuento %
        tk.Label(form, text="Descuento %", background=COLORS.panel_elevated, foreground=COLORS.text,
                 font=(UI_FONT, 10, "bold")).grid(row=row, column=0, sticky="w", padx=16, pady=5)
        field_entry(values["discount_percent"]).grid(row=row, column=1, sticky="ew", padx=(0, 16), pady=5)
        row += 1
        
        # Servicios extra ($)
        tk.Label(form, text="Servicios extra ($)", background=COLORS.panel_elevated, foreground=COLORS.text,
                 font=(UI_FONT, 10, "bold")).grid(row=row, column=0, sticky="w", padx=16, pady=5)
        field_entry(values["extra_services"]).grid(row=row, column=1, sticky="ew", padx=(0, 16), pady=5)
        row += 1
        
        # Subtotal (solo lectura)
        tk.Label(form, text="Subtotal", background=COLORS.panel_elevated, foreground=COLORS.text,
                 font=(UI_FONT, 10, "bold")).grid(row=row, column=0, sticky="w", padx=16, pady=5)
        subtotal_label = tk.Label(form, textvariable=subtotal_var, background=COLORS.field, 
                                   foreground=COLORS.wine_active, anchor="e", relief="flat",
                                   font=(UI_FONT, 12, "bold"), padx=10, pady=8)
        subtotal_label.grid(row=row, column=1, sticky="ew", padx=(0, 16), pady=5)
        row += 1
        
        # Estado
        tk.Label(form, text="Estado", background=COLORS.panel_elevated, foreground=COLORS.text,
                 font=(UI_FONT, 10, "bold")).grid(row=row, column=0, sticky="w", padx=16, pady=5)
        ttk.Combobox(form, textvariable=values["status"], values=["Pendiente", "En proceso", "Completado"], 
                     state="readonly", style="Order.TCombobox").grid(row=row, column=1, sticky="ew", 
                                                                       padx=(0, 16), pady=5)
        row += 1
        
        # Notas
        tk.Label(form, text="Notas", background=COLORS.panel_elevated, foreground=COLORS.text,
                 font=(UI_FONT, 10, "bold")).grid(row=row, column=0, sticky="nw", padx=16, pady=(8, 5))
        notes = tk.Text(form, height=4, background=COLORS.field, foreground=COLORS.text, insertbackground=COLORS.text,
                        relief="flat", highlightthickness=1, highlightbackground=COLORS.border, font=(UI_FONT, 10), wrap="word")
        notes.grid(row=row, column=1, sticky="ew", padx=(0, 16), pady=(8, 5))
        notes.insert("1.0", source.get("notes", ""))

        button_row = row + 1
        ttk.Button(form, text="Generar presupuesto", command=open_presupuesto_modal, style="Primary.TButton").grid(row=button_row, column=0, columnspan=2, sticky="ew", padx=16, pady=(4, 10))
        row = button_row + 1
        
        # Inicializar tamaños si hay material previo
        if source.get("material"):
            on_material_change()
        
        # Calcular subtotal inicial
        calculate_subtotal()

        def save():
            # Calcular el subtotal numérico final
            try:
                material = values["material"].get().strip()
                size = values["size"].get().strip()
                quantity = max(1, int(values["quantity"].get() or 1))
                discount = max(0, min(100, float(values["discount_percent"].get() or 0)))
                extra = max(0, float(values["extra_services"].get() or 0))
                
                # Usar suggest_price para obtener el subtotal base
                rule = self.database.suggest_price(material, size, quantity)
                
                if rule and rule.get("suggested_subtotal"):
                    subtotal_base = float(rule["suggested_subtotal"])
                    importe_descuento = subtotal_base * discount / 100
                    subtotal_final = subtotal_base - importe_descuento + extra
                else:
                    subtotal_final = 0
                    
            except (ValueError, TypeError):
                subtotal_final = 0
            
            clean = self.database._clean_order_job({
                **source,
                "title": values["title"].get(),
                "material": values["material"].get(),
                "size": values["size"].get(),
                "quantity": int(values["quantity"].get() or 1),
                "subtotal": subtotal_final,
                "discount_percent": float(values["discount_percent"].get() or 0),
                "extra_services": float(values["extra_services"].get() or 0),
                "status": values["status"].get(),
                "notes": notes.get("1.0", "end").strip(),
            })
            on_save(clean)
            dialog.destroy()

        actions = tk.Frame(dialog, background=COLORS.background)
        actions.pack(fill="x", padx=18, pady=(0, 18))
        ttk.Button(actions, text="Cancelar", command=dialog.destroy, style="Secondary.TButton").pack(side="right")
        ttk.Button(actions, text="Guardar trabajo", command=save, style="Primary.TButton").pack(side="right", padx=(0, 8))
        self.center_window(dialog)

    def _recover_order_draft(self, order_id: int):
        draft = self.database.order_draft(order_id)
        if not draft:
            return
        choice = messagebox.askyesnocancel(
            "Recuperar cambios del pedido",
            f"Hay cambios sin confirmar guardados el {draft.get('saved_at', '')}.\n\n"
            "Sí: recuperar cambios\nNo: descartarlos\nCancelar: revisar sin tocar el borrador.",
            parent=self,
        )
        if choice is True:
            self.database.apply_order_draft(order_id)
            self.status.set(f"Se recuperaron los cambios del pedido #{order_id}.")
        elif choice is False:
            self.database.discard_order_draft(order_id)

    def open_order_workspace(self, order_id: int):
        if order_id in self.order_tabs:
            self.tabs.select(self.order_tabs[order_id])
            return
        self._recover_order_draft(order_id)
        order = self.database.order(order_id)
        if not order:
            return
        tab = ttk.Frame(self.tabs)
        self.order_tabs[order_id] = tab
        self.tabs.add(tab, text=f"Pedido #{order_id} · {order['client']}")
        self.tabs.select(tab)
        tab.order_id, tab.order_dirty, tab.order_save_after = order_id, False, None
        tab.order_design_state = self.database.order_designs(order_id)
        tab.order_job_state = self.database.order_jobs(order_id)
        tab.order_values = {
            "client": tk.StringVar(value=order.get("client_name") or order["client"]),
            "whatsapp": tk.StringVar(value=order.get("whatsapp") or ""),
            "client_type": tk.StringVar(value=order.get("client_type") or "Particular"),
            "order_date": tk.StringVar(value=self._format_datetime_display(order.get("order_date") or "")),
            "order_concept": tk.StringVar(value=order.get("order_concept") or ""),
            "order_description": tk.StringVar(value=order.get("order_description") or ""),
            "status": tk.StringVar(value=order.get("status") or "Nuevo"),
            "material": tk.StringVar(value=order.get("material") or ""),
            "size": tk.StringVar(value=order.get("size") or ""),
            "quantity": tk.StringVar(value=str(order.get("quantity") or 0)),
            "price": tk.StringVar(value=str(order.get("price") or 0)),
            "discount_percent": tk.StringVar(value=str(order.get("discount_percent") or 0)),
            "extra_services": tk.StringVar(value=order.get("extra_services") or ""),
            "assigned_to": tk.StringVar(value=order.get("assigned_to") or ""),
            "delivery_date": tk.StringVar(value=order.get("delivery_date") or ""),
            "print_priority": tk.StringVar(value=priority_label(order.get("print_priority"))),
            "pending_reason": tk.StringVar(value=order.get("pending_reason") or ""),
        }
        top = ttk.Frame(tab, padding=(12, 12, 12, 5))
        top.pack(fill="x")
        tab.order_title = tk.StringVar(value=f"Pedido #{order_id} · {order.get('client_name') or order['client']}")
        ttk.Label(top, textvariable=tab.order_title, style="Title.TLabel").pack(side="left")
        tab.order_saved = tk.StringVar(value="Guardado")
        ttk.Label(top, textvariable=tab.order_saved, style="Muted.TLabel").pack(side="right")
        ttk.Button(top, text="Guardar ahora", command=lambda: self.flush_order_autosave(order_id)).pack(side="right", padx=(0, 8))
        ttk.Button(top, text="Armado de planchas", command=lambda: self.open_plancha_for_order(order_id)).pack(side="right", padx=(0, 8))

        workspace = ttk.Frame(tab)
        workspace.pack(fill="both", expand=True)
        order_scrollbar = ttk.Scrollbar(workspace, orient="vertical")
        order_scrollbar.pack(side="right", fill="y", pady=(0, 12))
        order_canvas = tk.Canvas(
            workspace, background=COLORS.background, highlightthickness=0,
            yscrollcommand=order_scrollbar.set,
        )
        order_canvas.pack(side="left", fill="both", expand=True)
        order_scrollbar.configure(command=order_canvas.yview)
        body = ttk.Frame(order_canvas, padding=(12, 0, 12, 12))
        body_window = order_canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _event: order_canvas.configure(scrollregion=order_canvas.bbox("all")))
        order_canvas.bind("<Configure>", lambda event: order_canvas.itemconfigure(body_window, width=event.width))
        tab.order_scroll_canvas = order_canvas
        
        # Panel de línea de tiempo (arriba)
        timeline_panel = tk.Frame(body, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        timeline_panel.pack(fill="x", pady=(0, 12))
        tk.Label(
            timeline_panel,
            text="LÍNEA DE TIEMPO",
            background=COLORS.panel,
            foreground=COLORS.wine_active,
            font=(IDENTITY_FONT, 11, "bold")
        ).pack(anchor="w", padx=14, pady=(12, 2))
        
        # Etapa actual y progreso
        stage = get_current_stage(order)
        progress = get_stage_progress(order)
        tab.timeline_status = tk.StringVar(value=f"{stage} · {int(progress * 100)}% completado")
        tk.Label(
            timeline_panel,
            textvariable=tab.timeline_status,
            background=COLORS.panel,
            foreground=COLORS.text,
            font=(UI_FONT, 11)
        ).pack(anchor="w", padx=14, pady=(0, 10))
        
        # Visualización de la línea
        timeline_visual = tk.Frame(timeline_panel, background=COLORS.panel)
        timeline_visual.pack(fill="x", padx=14, pady=(0, 6))
        tab.timeline_visual = timeline_visual
        self._render_order_timeline(timeline_visual, {**order, "jobs": tab.order_job_state})
        
        # Mensaje informativo sobre interactividad
        tk.Label(
            timeline_panel,
            text="💡 Hacé clic en los círculos para actualizar el estado del pedido",
            background=COLORS.panel,
            foreground=COLORS.muted,
            font=(UI_FONT, 9)
        ).pack(anchor="w", padx=14, pady=(0, 12))
        
        form = ttk.Frame(body, padding=12)
        form.pack(side="left", fill="y")
        designs = ttk.Frame(body, padding=12)
        designs.pack(side="left", fill="both", expand=True, padx=(10, 0))
        ttk.Label(form, text="DATOS GENERALES", style="Tag.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        fields = (
            ("Cliente", "client"), ("WhatsApp", "whatsapp"), ("Tipo de cliente", "client_type"),
            ("Fecha de ingreso", "order_date"), ("Estado", "status"),
            ("Asignado a", "assigned_to"), ("Fecha de entrega", "delivery_date"),
            ("Prioridad", "print_priority"), ("Trabajo pendiente", "pending_reason"),
        )
        for row, (label, key) in enumerate(fields, start=1):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
            if key == "status":
                workflow_order = {**order, "jobs": tab.order_job_state}
                widget = ttk.Combobox(form, textvariable=tab.order_values[key], values=order_statuses(workflow_order), state="readonly", width=26)
                tab.status_widget = widget
            elif key == "client_type":
                widget = ttk.Combobox(
                    form, textvariable=tab.order_values[key],
                    values=("Particular", "Empresa", "Revendedor", "VIP"),
                    state="readonly", width=26,
                )
                # Al cambiar el tipo, actualizar avatar en la lista de fichas
                def _on_type_change(*_args, oid=order_id):
                    row_order = self.database.connection.execute(
                        "SELECT client_id FROM orders WHERE id = ?", (oid,)
                    ).fetchone()
                    if row_order and row_order[0]:
                        self.database.update_client_type(
                            row_order[0],
                            tab.order_values["client_type"].get(),
                        )
                    self.queue_orders_refresh()
                tab.order_values[key].trace_add("write", _on_type_change)
            elif key == "order_date":
                # Campo de fecha de creación: solo lectura, muestra fecha y hora
                widget = ttk.Entry(form, textvariable=tab.order_values[key], width=29, state="readonly")
            elif key == "delivery_date":
                widget = self.date_field(form, tab.order_values[key])
            elif key == "print_priority":
                widget = ttk.Combobox(form, textvariable=tab.order_values[key], values=PRIORITY_LABELS, state="readonly", width=26)
                # Sincronizar cambios de estado con la línea de tiempo
                def on_status_change(*args, order_id=order_id):
                    self.refresh_order_timeline(order_id)
                tab.order_values[key].trace_add("write", on_status_change)
            elif key == "material":
                widget = ttk.Combobox(form, textvariable=tab.order_values[key], values=self.database.price_materials(), width=26)
            elif key == "size":
                widget = ttk.Combobox(form, textvariable=tab.order_values[key], values=self.database.price_sizes(), width=26)
            else:
                widget = ttk.Entry(form, textvariable=tab.order_values[key], width=29)
            widget.grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Label(form, text="Concepto").grid(row=len(fields) + 1, column=0, sticky="nw", padx=(0, 10), pady=(9, 4))
        ttk.Entry(form, textvariable=tab.order_values["order_concept"], width=29).grid(row=len(fields) + 1, column=1, sticky="ew", pady=(9, 4))
        ttk.Label(form, text="Descripción").grid(row=len(fields) + 2, column=0, sticky="nw", padx=(0, 10), pady=(9, 4))
        ttk.Entry(form, textvariable=tab.order_values["order_description"], width=29).grid(row=len(fields) + 2, column=1, sticky="ew", pady=(9, 4))
        ttk.Label(form, text="Observaciones").grid(row=len(fields) + 3, column=0, sticky="nw", padx=(0, 10), pady=(9, 4))
        tab.order_notes = tk.Text(form, width=30, height=7, background="#050606", foreground="#e7d3c4", insertbackground="#e7d3c4", relief="flat")
        tab.order_notes.grid(row=len(fields) + 3, column=1, sticky="ew", pady=(9, 4))
        tab.order_notes.insert("1.0", order.get("observations") or "")
        form.columnconfigure(1, weight=1)
        ttk.Separator(form, orient="horizontal").grid(row=len(fields) + 4, column=0, columnspan=2, sticky="ew", pady=12)
        
        # Sección de prioridad y tiempo
        ttk.Label(form, text="PRIORIDAD Y TIEMPO", style="Tag.TLabel").grid(row=len(fields) + 5, column=0, columnspan=2, sticky="w")
        tab.priority_info = tk.StringVar()
        ttk.Label(form, textvariable=tab.priority_info, style="Muted.TLabel", wraplength=300).grid(row=len(fields) + 6, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Separator(form, orient="horizontal").grid(row=len(fields) + 7, column=0, columnspan=2, sticky="ew", pady=12)
        
        # Sección de progreso
        tab.order_progress = tk.StringVar()
        ttk.Label(form, text="PROGRESO", style="Tag.TLabel").grid(row=len(fields) + 8, column=0, columnspan=2, sticky="w")
        ttk.Label(form, textvariable=tab.order_progress, style="Muted.TLabel", wraplength=300).grid(row=len(fields) + 9, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Separator(form, orient="horizontal").grid(row=len(fields) + 10, column=0, columnspan=2, sticky="ew", pady=12)
        ttk.Label(form, text="PRESUPUESTO Y COBROS", style="Tag.TLabel").grid(row=len(fields) + 11, column=0, columnspan=2, sticky="w")

        # Panel de desglose de costos y margen
        fin_panel = tk.Frame(form, background=COLORS.panel,
                             highlightthickness=1, highlightbackground=COLORS.border)
        fin_panel.grid(row=len(fields) + 12, column=0, columnspan=2, sticky="ew", pady=(6, 4))
        fin_panel.columnconfigure(0, weight=1)
        fin_panel.columnconfigure(1, weight=0)

        _fin_rows = [
            ("Precio de venta",   "fin_price",    COLORS.text,       False),
            ("─────────────────", None,            COLORS.border,     False),
            ("M.P — Materia Prima","fin_cost_mp",  "#4E8AC7",         False),
            ("M.O — Mano de Obra", "fin_cost_mo",  "#4E8AC7",         False),
            ("C.F — Carga Fabril", "fin_cost_cf",  "#4E8AC7",         False),
            ("Costo total",        "fin_cost_total","#C98A27",         True),
            ("Margen bruto",       "fin_margin",    "#2D9B66",         True),
            ("─────────────────", None,            COLORS.border,     False),
            ("Cobrado",            "fin_paid",      "#2D9B66",         False),
            ("Pendiente",          "fin_pending",   "#C94B27",         False),
        ]
        tab.order_fin_vars = {}
        for r_idx, (label, var_key, color, bold) in enumerate(_fin_rows):
            if var_key is None:
                tk.Frame(fin_panel, height=1, background=color
                         ).grid(row=r_idx, column=0, columnspan=2, sticky="ew",
                                padx=8, pady=2)
                continue
            font = (IDENTITY_FONT if bold else UI_FONT, 9, "bold" if bold else "normal")
            tk.Label(fin_panel, text=label, background=COLORS.panel,
                     foreground=COLORS.muted, font=(UI_FONT, 9)
                     ).grid(row=r_idx, column=0, sticky="w", padx=(10, 4), pady=1)
            sv = tk.StringVar(value="—")
            tab.order_fin_vars[var_key] = sv
            tk.Label(fin_panel, textvariable=sv, background=COLORS.panel,
                     foreground=color, font=font
                     ).grid(row=r_idx, column=1, sticky="e", padx=(4, 10), pady=1)

        # Mantener la StringVar legacy que usa refresh_order_workspace
        tab.order_financials = tk.StringVar(value="")

        finances_actions = ttk.Frame(form)
        finances_actions.grid(row=len(fields) + 13, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        ttk.Button(finances_actions, text="Registrar cobro", command=lambda: self.register_order_payment(order_id)).pack(side="left")
        ttk.Button(finances_actions, text="Ver actividad", command=lambda: self.show_order_activity(order_id)).pack(side="left", padx=6)
        ttk.Button(finances_actions, text="Usar sugerido", command=lambda: self.apply_suggested_order_price(order_id)).pack(side="left")
        ttk.Separator(form, orient="horizontal").grid(row=len(fields) + 14, column=0, columnspan=2, sticky="ew", pady=12)
        ttk.Label(form, text="DISEÑOS", style="Tag.TLabel").grid(row=len(fields) + 15, column=0, columnspan=2, sticky="w")
        tab.preparation_summary = tk.StringVar(value="Agregá diseños al pedido desde la biblioteca.")
        ttk.Label(form, textvariable=tab.preparation_summary, style="Muted.TLabel", wraplength=300).grid(row=len(fields) + 16, column=0, columnspan=2, sticky="w", pady=(4, 6))
        prep_actions = ttk.Frame(form)
        prep_actions.grid(row=len(fields) + 17, column=0, columnspan=2, sticky="ew")
        ttk.Button(prep_actions, text="Crear Sticker", command=lambda: self.open_sticker_studio(), style="Primary.TButton").pack(side="left")
        ttk.Button(prep_actions, text="Agregar diseños", command=lambda: self.show_add_designs_dialog(order_id), style="Secondary.TButton").pack(side="left", padx=6)
        ttk.Label(form, text="Creá nuevos stickers o agregá desde la biblioteca.", style="Muted.TLabel", wraplength=300).grid(row=len(fields) + 18, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Separator(form, orient="horizontal").grid(row=len(fields) + 19, column=0, columnspan=2, sticky="ew", pady=12)
        ttk.Label(form, text="APROBACIÓN", style="Tag.TLabel").grid(row=len(fields) + 20, column=0, columnspan=2, sticky="w")
        tab.order_approval_summary = tk.StringVar(value="Sin planchas vinculadas.")
        ttk.Label(form, textvariable=tab.order_approval_summary, style="Muted.TLabel", wraplength=300).grid(row=len(fields) + 21, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(form, text="VISTAS PREVIAS", style="Tag.TLabel").grid(row=len(fields) + 22, column=0, columnspan=2, sticky="w", pady=(12, 0))
        tab.order_previews_summary = tk.StringVar(value="Sin vistas guardadas.")
        ttk.Label(form, textvariable=tab.order_previews_summary, style="Muted.TLabel", wraplength=300).grid(row=len(fields) + 23, column=0, columnspan=2, sticky="w", pady=(4, 6))
        ttk.Button(form, text="Abrir última vista", command=lambda: self.open_latest_order_preview(order_id)).grid(row=len(fields) + 24, column=0, columnspan=2, sticky="w")

        jobs_panel = ttk.Frame(designs, padding=(0, 0, 0, 10))
        jobs_panel.pack(fill="x")
        # Panel: Trabajos del pedido (filtrado de trabajos con estado 'Confirmado' o 'Entregado')
        products_panel = tk.Frame(jobs_panel, background=COLORS.panel_elevated, highlightbackground=COLORS.border, highlightthickness=1)
        products_panel.pack(fill="x", padx=14, pady=(0, 12))
        header_row = tk.Frame(products_panel, background=COLORS.panel_elevated)
        header_row.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(header_row, text="TRABAJOS DEL PEDIDO", background=COLORS.panel_elevated, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 10, "bold")).pack(side="left")
        tab.order_products_summary = tk.StringVar(value="")
        tk.Label(header_row, textvariable=tab.order_products_summary, background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 9)).pack(side="left", padx=10)
        ttk.Button(header_row, text="＋ Agregar", command=lambda oid=order_id: self.add_order_job(oid), style="Primary.TButton").pack(side="right")
        # Treeview para trabajos del pedido (columnas adaptables al espacio)
        prod_cols = ("title", "material", "quantity", "price")
        prod_tree = ttk.Treeview(products_panel, columns=prod_cols, show="headings", height=6)
        # Configurar columnas con stretch para que se adapten al espacio
        prod_tree.heading("title", text="Producto")
        prod_tree.column("title", width=180, minwidth=120, stretch=True, anchor="w")
        prod_tree.heading("material", text="Material")
        prod_tree.column("material", width=130, minwidth=80, stretch=True, anchor="w")
        prod_tree.heading("quantity", text="Cantidad")
        prod_tree.column("quantity", width=70, minwidth=60, stretch=True, anchor="center")
        prod_tree.heading("price", text="Precio")
        prod_tree.column("price", width=90, minwidth=70, stretch=True, anchor="center")
        prod_tree.tag_configure("done", foreground=COLORS.wine_active)
        prod_tree.tag_configure("pending", foreground=COLORS.muted)
        prod_tree.pack(fill="x", padx=10, pady=(0, 10))
        # Doble clic para editar trabajo
        prod_tree.bind("<Double-1>", lambda _event, oid=order_id: self.edit_order_job_from_products(oid))
        # Placeholder label shown when there are no products
        tab.order_products_placeholder = tk.Label(products_panel, text="Sin trabajos", background=COLORS.panel_elevated,
                              foreground=COLORS.muted, font=(UI_FONT, 10), anchor="center")
        tab.order_products_tree = prod_tree

        header = ttk.Frame(designs)
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="DISEÑOS DEL PEDIDO", style="Tag.TLabel").pack(side="left")
        tab.order_designs_summary = tk.StringVar(value="0 diseños")
        ttk.Label(header, textvariable=tab.order_designs_summary, style="Muted.TLabel").pack(side="left", padx=10)
        ttk.Button(header, text="Agregar seleccionados", command=lambda: self.link_selection_to_order(order_id)).pack(side="right")
        ttk.Button(header, text="Quitar", command=lambda: self.remove_order_designs(order_id)).pack(side="right", padx=(0, 6))
        ttk.Button(header, text="Cantidad", command=lambda: self.change_order_design_quantity(order_id)).pack(side="right", padx=(0, 6))
        ttk.Button(header, text="Confirmar", command=lambda: self.set_order_design_status(order_id, "Confirmado")).pack(side="right", padx=(0, 6))
        ttk.Button(header, text="Ver todos", command=lambda: self.show_all_order_designs(order_id)).pack(side="right", padx=(0, 6))
        
        # Contenedor con scroll para la lista de diseños con miniaturas
        designs_container = tk.Frame(designs, background=COLORS.panel)
        designs_container.pack(fill="both", expand=True)
        
        designs_canvas = tk.Canvas(designs_container, background=COLORS.panel, highlightthickness=0)
        designs_scrollbar = ttk.Scrollbar(designs_container, orient="vertical", command=designs_canvas.yview)
        designs_scrollable = tk.Frame(designs_canvas, background=COLORS.panel)
        
        designs_scrollable.bind(
            "<Configure>",
            lambda e: designs_canvas.configure(scrollregion=designs_canvas.bbox("all"))
        )
        
        designs_canvas.create_window((0, 0), window=designs_scrollable, anchor="nw")
        designs_canvas.configure(yscrollcommand=designs_scrollbar.set)
        
        designs_canvas.pack(side="left", fill="both", expand=True)
        designs_scrollbar.pack(side="right", fill="y")
        
        # Guardar referencias para uso posterior
        tab.order_designs_canvas = designs_canvas
        tab.order_designs_scrollable = designs_scrollable
        tab.order_design_items = []  # Lista para guardar referencias de widgets
        
        # Bind para scroll con mouse wheel
        def on_mousewheel(event):
            designs_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        designs_canvas.bind_all("<MouseWheel>", on_mousewheel)
        self._bind_order_mousewheel(tab, body)
        for variable in tab.order_values.values():
            variable.trace_add("write", lambda *_args, current=order_id: self.queue_order_autosave(current))
        tab.order_notes.bind("<KeyRelease>", lambda _event, current=order_id: self.queue_order_autosave(current))
        self.render_order_workspace(tab)
        self.after(1500, lambda current=order_id: self.poll_order_preparations(current))

    def _bind_order_mousewheel(self, tab, root) -> None:
        """Habilita desplazamiento vertical del pedido al usar la rueda."""
        def scroll(event):
            if isinstance(event.widget, ttk.Treeview):
                return None
            canvas = getattr(tab, "order_scroll_canvas", None)
            if not canvas or not canvas.winfo_exists():
                return None
            steps = -max(1, abs(event.delta) // 120) if event.delta < 0 else max(1, event.delta // 120)
            canvas.yview_scroll(steps, "units")
            return "break"

        def bind_descendants(widget):
            widget.bind("<MouseWheel>", scroll, add="+")
            for child in widget.winfo_children():
                bind_descendants(child)

        bind_descendants(root)

    def show_all_order_designs(self, order_id: int):
        """Muestra todos los diseños del pedido en un panel amplio y desplazable."""
        tab = self.order_tabs.get(order_id)
        if not tab:
            return
        dialog = tk.Toplevel(self)
        dialog.title(f"Diseños del pedido #{order_id}")
        dialog.configure(background=COLORS.background)
        dialog.geometry("980x580")
        dialog.minsize(720, 420)
        dialog.transient(self)

        content = ttk.Frame(dialog, padding=18)
        content.pack(fill="both", expand=True)
        total = len(tab.order_design_state)
        confirmed = sum(1 for design in tab.order_design_state if design.get("status") == "Confirmado")
        ttk.Label(content, text="TODOS LOS DISEÑOS DEL PEDIDO", style="Title.TLabel").pack(anchor="w")
        ttk.Label(content, text=f"{total} diseños vinculados · {confirmed} confirmados", style="Muted.TLabel").pack(anchor="w", pady=(2, 14))

        table_frame = ttk.Frame(content)
        table_frame.pack(fill="both", expand=True)
        columns = ("number", "name", "quantity", "size", "status", "tags", "path")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        for key, label, width in (
            ("number", "#", 45), ("name", "Diseño", 240), ("quantity", "Cantidad", 75),
            ("size", "Tamaño", 90), ("status", "Estado", 115), ("tags", "Etiquetas", 190),
            ("path", "Archivo", 280),
        ):
            tree.heading(key, text=label)
            tree.column(key, width=width, anchor="center" if key in {"number", "quantity", "size", "status"} else "w")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        for index, design in enumerate(tab.order_design_state, start=1):
            image_path = str(design.get("image_path", "") or "")
            tree.insert("", "end", values=(
                index,
                design.get("name") or Path(image_path).name or f"Diseño {index}",
                max(1, int(design.get("quantity", 1) or 1)),
                f"{float(design.get('size_cm', 5.9) or 5.9):g} cm",
                design.get("status") or "Pendiente",
                design.get("tags") or "Sin etiquetas",
                image_path or "Sin archivo",
            ))

        ttk.Button(content, text="Cerrar", command=dialog.destroy).pack(anchor="e", pady=(14, 0))
        self.center_window(dialog)

    def _order_values_from_tab(self, tab) -> dict:
        try:
            quantity = max(0, int(tab.order_values["quantity"].get() or 0))
        except ValueError:
            quantity = 0
        values = {key: value.get() for key, value in tab.order_values.items()}
        values["print_priority"] = PRIORITY_VALUES.get(values.get("print_priority"), 0)
        return {**values, "quantity": quantity,
                "observations": tab.order_notes.get("1.0", "end").strip()}

    def queue_order_autosave(self, order_id: int):
        tab = self.order_tabs.get(order_id)
        if not tab or not tab.winfo_exists():
            return
        tab.order_dirty = True
        self.database.save_order_draft(
            order_id, self._order_values_from_tab(tab), tab.order_design_state, getattr(tab, "order_job_state", None),
        )
        tab.order_saved.set("Cambios guardados localmente...")
        if tab.order_save_after:
            self.after_cancel(tab.order_save_after)
        tab.order_save_after = self.after(700, lambda: self.flush_order_autosave(order_id))
        client = tab.order_values["client"].get() or "Sin cliente"
        tab.order_title.set(f"Pedido #{order_id} · {client}")
        self.tabs.tab(tab, text=f"Pedido #{order_id} · {client}")

    def flush_order_autosave(self, order_id: int):
        tab = self.order_tabs.get(order_id)
        if not tab or not tab.winfo_exists() or not tab.order_dirty:
            return
        try:
            self.database.save_order_snapshot(
                order_id, self._order_values_from_tab(tab), tab.order_design_state, getattr(tab, "order_job_state", None),
            )
            # Recalcular costos automáticamente después de guardar
            self.database.recalculate_order_costs(order_id)
        except (ValueError, TypeError) as error:
            tab.order_saved.set(str(error))
            return
        tab.order_dirty, tab.order_save_after = False, None
        tab.order_saved.set("Guardado ahora")
        self.render_order_workspace(tab)
        self.refresh_orders()

    def render_order_workspace(self, tab):
        # Obtener datos actualizados del pedido
        order = self.database.order(tab.order_id)
        if not order:
            return
        
        # Calcular prioridad y tiempo
        estimated_minutes = estimate_remaining_work(order)
        priority_level, priority_score, priority_reason = calculate_priority(order, estimated_minutes)
        priority_emoji = get_priority_emoji(priority_level)
        
        # Actualizar línea de tiempo con el estado y los trabajos aún no guardados.
        if hasattr(tab, "timeline_status"):
            self.refresh_order_timeline(tab.order_id)
        
        # Actualizar información de prioridad y tiempo
        if hasattr(tab, "priority_info"):
            time_remaining_str = format_time_remaining(order)
            work_time_str = format_work_time(estimated_minutes)
            
            priority_text = (
                f"{priority_emoji} Prioridad: {priority_level}\n"
                f"{priority_reason}\n\n"
                f"Entrega: {time_remaining_str}\n"
                f"Trabajo estimado: {work_time_str}"
            )
            
            # Advertencia si hay riesgo
            if priority_level in ("Urgente", "Alta"):
                from app.workflow.estimator import get_time_pressure
                pressure_desc, ratio = get_time_pressure(order)
                priority_text += f"\n{pressure_desc}"
            
            tab.priority_info.set(priority_text)
        
        # Renderizar trabajos en el panel de productos
        if hasattr(tab, "order_products_tree"):
            prod_tree = tab.order_products_tree
            prod_tree.delete(*prod_tree.get_children())
            jobs = list(getattr(tab, "order_job_state", []) or [])
            prod_total = 0.0
            done_set = {"confirmado", "entregado", "listo", "hecho"}
            for idx, j in enumerate(jobs):
                subtotal = float(j.get("subtotal", 0) or 0)
                qty = int(j.get("quantity", 1) or 1)
                tag = "done" if (j.get("status") or "").lower() in done_set else "pending"
                prod_tree.insert("", "end", iid=f"prod:{idx}", tags=(tag,), values=(j.get("title") or f"Producto {idx+1}", j.get("material") or "", qty, f"${subtotal:,.2f}"))
                prod_total += subtotal
            if not jobs:
                # Hide the tree and show a centered placeholder label
                try:
                    prod_tree.pack_forget()
                except Exception:
                    pass
                try:
                    tab.order_products_placeholder.pack(fill="both", expand=True, pady=14)
                except Exception:
                    pass
            else:
                # Ensure the tree is visible and placeholder hidden
                try:
                    tab.order_products_placeholder.pack_forget()
                except Exception:
                    pass
                prod_tree.pack(fill="x", padx=10, pady=(0, 10))
            if hasattr(tab, "order_products_summary"):
                tab.order_products_summary.set(f"{len(jobs)} trabajo(s) · Total: ${prod_total:,.0f}")
        
        # Renderizar diseños con miniaturas
        if hasattr(tab, "order_designs_scrollable"):
            try:
                from PIL import Image, ImageTk
            except (ImportError, OSError):
                Image = ImageTk = None
            
            # Limpiar diseños anteriores
            for widget in tab.order_designs_scrollable.winfo_children():
                widget.destroy()
            tab.order_design_items = []
            
            # Inicializar set de selección si no existe
            if not hasattr(tab, "selected_design_indexes"):
                tab.selected_design_indexes = set()
            
            assigned = 0
            for index, design in enumerate(tab.order_design_state):
                quantity = max(1, int(design.get("quantity", 1) or 1))
                assigned += quantity
                name = design.get("name") or Path(str(design.get("image_path", ""))).name
                image_path = design.get("image_path", "")
                size_cm = f"{float(design.get('size_cm', 5.9) or 5.9):g} cm"
                status = design.get("status") or "Pendiente"
                tags = design.get("tags") or "Sin etiquetas"
                is_selected = index in tab.selected_design_indexes
                
                # Frame para cada diseño (resaltar si está seleccionado)
                bg_color = COLORS.wine_soft if is_selected else COLORS.panel_elevated
                item_frame = tk.Frame(
                    tab.order_designs_scrollable,
                    background=bg_color,
                    highlightbackground=COLORS.wine_active if is_selected else COLORS.border,
                    highlightthickness=2 if is_selected else 1
                )
                item_frame.pack(fill="x", padx=4, pady=2)
                item_frame.bind("<Button-1>", lambda e, idx=index: self.toggle_design_selection(tab, idx))
                
                # Menú contextual (click derecho)
                def show_context_menu(event, idx=index):
                    menu = tk.Menu(self, tearoff=0, background=COLORS.panel_elevated, 
                                  foreground=COLORS.text, activebackground=COLORS.wine_active,
                                  activeforeground=COLORS.text, font=(UI_FONT, 10))
                    menu.add_command(label="Eliminar diseño", 
                                    command=lambda: self.remove_single_design(tab, idx))
                    menu.add_separator()
                    menu.add_command(label="Cancelar", command=lambda: menu.unpost())
                    try:
                        menu.tk_popup(event.x_root, event.y_root)
                    finally:
                        menu.grab_release()
                
                item_frame.bind("<Button-3>", show_context_menu)
                
                # Miniatura (60x60)
                try:
                    if Image is not None and image_path and Path(image_path).exists():
                        img = Image.open(image_path)
                        img.thumbnail((60, 60), Image.Resampling.LANCZOS)
                        photo = ImageTk.PhotoImage(img)
                        thumb_label = tk.Label(item_frame, image=photo, background=bg_color)
                        thumb_label.image = photo  # Mantener referencia
                        thumb_label.pack(side="left", padx=5, pady=5)
                        thumb_label.bind("<Button-1>", lambda e, idx=index: self.toggle_design_selection(tab, idx))
                        thumb_label.bind("<Button-3>", show_context_menu)
                    else:
                        # Placeholder si no hay imagen
                        placeholder = tk.Label(item_frame, text="📷", font=(UI_FONT, 20), 
                                             background=bg_color, foreground=COLORS.muted)
                        placeholder.pack(side="left", padx=5, pady=5, width=60, height=60)
                        placeholder.bind("<Button-1>", lambda e, idx=index: self.toggle_design_selection(tab, idx))
                        placeholder.bind("<Button-3>", show_context_menu)
                except Exception:
                    # En caso de error, mostrar placeholder
                    placeholder = tk.Label(item_frame, text="📷", font=(UI_FONT, 20),
                                         background=bg_color, foreground=COLORS.muted)
                    placeholder.pack(side="left", padx=5, pady=5, width=60, height=60)
                    placeholder.bind("<Button-1>", lambda e, idx=index: self.toggle_design_selection(tab, idx))
                    placeholder.bind("<Button-3>", show_context_menu)
                
                # Información del diseño
                info_frame = tk.Frame(item_frame, background=bg_color)
                info_frame.pack(side="left", fill="both", expand=True, padx=10, pady=5)
                info_frame.bind("<Button-3>", show_context_menu)
                
                # Primera línea: Nombre (label que permite selección)
                name_frame = tk.Frame(info_frame, background=bg_color)
                name_frame.pack(fill="x", pady=(0, 3))
                name_display = name if len(name) <= 50 else name[:47] + "..."
                name_label = tk.Label(name_frame, text=name_display, background=bg_color,
                        foreground=COLORS.text, font=(UI_FONT, 10, "bold"), anchor="w")
                name_label.pack(side="left", fill="x", expand=True)
                name_label.bind("<Button-1>", lambda e, idx=index: self.toggle_design_selection(tab, idx))
                name_label.bind("<Button-3>", show_context_menu)
                
                # Segunda línea: Controles editables (Cantidad, Tamaño, Estado) + Etiquetas
                controls_frame = tk.Frame(info_frame, background=bg_color)
                controls_frame.pack(fill="x")
                
                # Cantidad (Spinbox pequeño)
                tk.Label(controls_frame, text="Cant:", background=bg_color, 
                        foreground=COLORS.muted, font=(UI_FONT, 9)).pack(side="left", padx=(0, 2))
                quantity_var = tk.IntVar(value=quantity)
                quantity_spin = tk.Spinbox(controls_frame, from_=1, to=999, textvariable=quantity_var,
                                          width=4, font=(UI_FONT, 9), relief="flat",
                                          background=COLORS.field, foreground=COLORS.text,
                                          buttonbackground=COLORS.panel, readonlybackground=COLORS.field)
                quantity_spin.pack(side="left", padx=(0, 8))
                quantity_spin.bind("<FocusOut>", lambda e, idx=index, var=quantity_var: 
                                  self.update_design_quantity(tab, idx, var.get()))
                quantity_spin.bind("<Return>", lambda e, idx=index, var=quantity_var: 
                                  self.update_design_quantity(tab, idx, var.get()))
                
                # Tamaño (Combobox pequeño con todos los tamaños de 5-29cm)
                tk.Label(controls_frame, text="Tamaño:", background=bg_color,
                        foreground=COLORS.muted, font=(UI_FONT, 9)).pack(side="left", padx=(0, 2))
                size_var = tk.StringVar(value=size_cm)
                # Crear lista de tamaños: enteros de 5 a 29cm
                all_sizes = [f"{i} cm" for i in range(5, 30)]
                size_combo = ttk.Combobox(controls_frame, textvariable=size_var, values=all_sizes,
                                         width=8, font=(UI_FONT, 9), state="readonly")
                size_combo.pack(side="left", padx=(0, 8))
                size_combo.bind("<<ComboboxSelected>>", lambda e, idx=index, var=size_var:
                               self.update_design_size(tab, idx, var.get()))
                
                # Estado (Combobox pequeño)
                tk.Label(controls_frame, text="Estado:", background=bg_color,
                        foreground=COLORS.muted, font=(UI_FONT, 9)).pack(side="left", padx=(0, 2))
                status_var = tk.StringVar(value=status)
                status_options = ["Pendiente", "Confirmado", "En proceso", "Completado"]
                status_combo = ttk.Combobox(controls_frame, textvariable=status_var, values=status_options,
                                           width=12, font=(UI_FONT, 9), state="readonly")
                status_combo.pack(side="left", padx=(0, 8))
                status_combo.bind("<<ComboboxSelected>>", lambda e, idx=index, var=status_var:
                                 self.update_design_status(tab, idx, var.get()))
                
                # Etiquetas (solo lectura, más pequeñas)
                tags_display = tags if len(tags) <= 30 else tags[:27] + "..."
                tk.Label(controls_frame, text=f"• {tags_display}", background=bg_color,
                        foreground=COLORS.muted, font=(UI_FONT, 8), anchor="w").pack(side="left", fill="x", expand=True)
                
                tab.order_design_items.append({"index": index, "frame": item_frame})
        
            target = self._order_values_from_tab(tab)["quantity"]
            completed = sum(1 for design in tab.order_design_state if design.get("status") == "Confirmado")
            tab.order_progress.set(f"{assigned} diseños asignados para {target} unidades · {completed}/{len(tab.order_design_state)} diseños confirmados.")
            if hasattr(tab, "order_designs_summary"):
                tab.order_designs_summary.set(f"{len(tab.order_design_state)} diseños · {completed} confirmados")
        
        # Actualizar panel de costos desglosado
        financials = self.database.order_financials(tab.order_id)
        
        if hasattr(tab, "order_fin_vars"):
            # Precio de venta
            tab.order_fin_vars["fin_price"].set(f"${financials['budget_total']:,.2f}")
            # Costos
            tab.order_fin_vars["fin_cost_mp"].set(f"${financials['cost_mp']:,.2f}")
            tab.order_fin_vars["fin_cost_mo"].set(f"${financials['cost_mo']:,.2f}")
            tab.order_fin_vars["fin_cost_cf"].set(f"${financials['cost_cf']:,.2f}")
            tab.order_fin_vars["fin_cost_total"].set(f"${financials['cost_total']:,.2f}")
            # Margen
            margin = financials['margin']
            margin_pct = (margin / financials['budget_total'] * 100) if financials['budget_total'] > 0 else 0
            tab.order_fin_vars["fin_margin"].set(f"${margin:,.2f} ({margin_pct:.1f}%)")
            # Cobros
            tab.order_fin_vars["fin_paid"].set(f"${financials['paid_amount']:,.2f}")
            tab.order_fin_vars["fin_pending"].set(f"${financials['pending_amount']:,.2f}")
        
        # Mantener la variable legacy por compatibilidad
        if hasattr(tab, "order_financials"):
            tab.order_financials.set(
                f"Presupuesto: ${financials['budget_total']:,.2f}\n"
                f"Cobrado: ${financials['paid_amount']:,.2f} · Pendiente: ${financials['pending_amount']:,.2f}\n"
                f"Estado de cobro: {financials['payment_status']}"
            )
        
        # Actualizar aprobación de planchas
        if hasattr(tab, "order_approval_summary"):
            planchas = self.database.order_planchas(tab.order_id)
            if not planchas:
                tab.order_approval_summary.set("Sin planchas vinculadas todavía.")
            else:
                approved = sum(1 for plancha in planchas if plancha.get("approval_status") == "Aprobada")
                requested = sum(1 for plancha in planchas if plancha.get("approval_status") == "Enviada")
                changes = sum(1 for plancha in planchas if plancha.get("approval_status") == "Cambios solicitados")
                tab.order_approval_summary.set(
                    f"{approved}/{len(planchas)} planchas aprobadas"
                    + (f" · {requested} esperando respuesta" if requested else "")
                    + (f" · {changes} con cambios" if changes else "")
                )
        if hasattr(tab, "order_previews_summary"):
            previews = self.database.order_previews(tab.order_id)
            if previews:
                last_saved = str(previews[0].get("created_at", "")).replace("T", " ")
                tab.order_previews_summary.set(f"{len(previews)} vista(s) guardada(s) · última: {last_saved}")
            else:
                tab.order_previews_summary.set("Sin vistas guardadas todavía.")
        
        self.refresh_preparation_summary(tab.order_id)

    def toggle_design_selection(self, tab, index):
        """Alterna la selección de un diseño."""
        if not hasattr(tab, "selected_design_indexes"):
            tab.selected_design_indexes = set()
        
        if index in tab.selected_design_indexes:
            tab.selected_design_indexes.remove(index)
        else:
            tab.selected_design_indexes.add(index)
        
        self.render_order_workspace(tab)

    def update_design_quantity(self, tab, index, new_quantity):
        """Actualiza la cantidad de un diseño."""
        try:
            quantity = max(1, int(new_quantity))
            if 0 <= index < len(tab.order_design_state):
                tab.order_design_state[index]["quantity"] = quantity
                self.render_order_workspace(tab)
                self.queue_order_autosave(tab.order_id)
        except (ValueError, TypeError):
            pass

    def update_design_size(self, tab, index, new_size):
        """Actualiza el tamaño de un diseño."""
        if 0 <= index < len(tab.order_design_state):
            # Extraer valor numérico del tamaño (ej: "5.9 cm" -> 5.9)
            size_str = new_size.replace("cm", "").strip()
            try:
                size_value = float(size_str)
                tab.order_design_state[index]["size_cm"] = size_value
                self.render_order_workspace(tab)
                self.queue_order_autosave(tab.order_id)
            except ValueError:
                pass

    def update_design_status(self, tab, index, new_status):
        """Actualiza el estado de un diseño."""
        if 0 <= index < len(tab.order_design_state):
            tab.order_design_state[index]["status"] = new_status
            self.render_order_workspace(tab)
            self.queue_order_autosave(tab.order_id)

    def remove_single_design(self, tab, index):
        """Elimina un diseño específico del pedido."""
        if 0 <= index < len(tab.order_design_state):
            removed_design = tab.order_design_state[index]
            design_name = removed_design.get("name") or Path(str(removed_design.get("image_path", ""))).name
            
            # Confirmar eliminación
            from tkinter import messagebox
            confirm = messagebox.askyesno(
                "Eliminar diseño",
                f"¿Eliminar '{design_name}' del pedido?",
                parent=self
            )
            
            if confirm:
                # Eliminar el diseño
                tab.order_design_state.pop(index)
                
                # Limpiar selección si estaba seleccionado
                if hasattr(tab, "selected_design_indexes") and index in tab.selected_design_indexes:
                    tab.selected_design_indexes.remove(index)
                
                # Actualizar índices de selección (los que estaban después del eliminado)
                if hasattr(tab, "selected_design_indexes"):
                    tab.selected_design_indexes = {
                        (idx - 1 if idx > index else idx) 
                        for idx in tab.selected_design_indexes
                    }
                
                self.render_order_workspace(tab)
                self.queue_order_autosave(tab.order_id)
                self.database.add_order_event(tab.order_id, "Diseños", f"Se eliminó el diseño: {design_name}")

    def edit_order_job_from_products(self, order_id: int):
        """Edita un trabajo desde el panel de productos haciendo doble clic."""
        tab = self.order_tabs.get(order_id)
        if not tab or not hasattr(tab, "order_products_tree"):
            return
        
        selected = tab.order_products_tree.selection()
        if not selected:
            return
        
        try:
            # Extraer el índice del id del item (formato "prod:N")
            index = int(selected[0].split(":", 1)[1])
            if 0 <= index < len(tab.order_job_state):
                self.edit_order_job_dialog(
                    tab, tab.order_job_state[index],
                    lambda job, current=index: (tab.order_job_state.__setitem__(current, job), self.render_order_workspace(tab), self.queue_order_autosave(order_id)),
                )
        except (IndexError, ValueError):
            pass

    def _selected_order_job_index(self, tab) -> int | None:
        if not tab or not hasattr(tab, "order_job_tree"):
            return None
        selected = tab.order_job_tree.selection()
        if not selected:
            return None
        try:
            return int(selected[0].split(":", 1)[1])
        except (IndexError, ValueError):
            return None

    def add_order_job(self, order_id: int):
        tab = self.order_tabs.get(order_id)
        if not tab:
            return
        self.edit_order_job_dialog(
            tab, None,
            lambda job: (tab.order_job_state.append(job), self.render_order_workspace(tab), self.queue_order_autosave(order_id)),
        )

    def open_order_job_item(self, order_id: int):
        """Abre el editor del trabajo elegido o agrega uno desde la tabla."""
        tab = self.order_tabs.get(order_id)
        if tab and tab.order_job_tree.selection() == ("add-job",):
            self.add_order_job(order_id)
            return
        self.edit_selected_order_job(order_id)

    def edit_selected_order_job(self, order_id: int):
        tab = self.order_tabs.get(order_id)
        index = self._selected_order_job_index(tab)
        if tab is None or index is None:
            messagebox.showinfo("Trabajos", "Elegí un trabajo para editar.", parent=self)
            return
        self.edit_order_job_dialog(
            tab, tab.order_job_state[index],
            lambda job, current=index: (tab.order_job_state.__setitem__(current, job), self.render_order_workspace(tab), self.queue_order_autosave(order_id)),
        )

    def remove_order_job(self, order_id: int):
        tab = self.order_tabs.get(order_id)
        index = self._selected_order_job_index(tab)
        if tab is None or index is None:
            messagebox.showinfo("Trabajos", "Elegí un trabajo para quitar.", parent=self)
            return
        if len(tab.order_job_state) <= 1:
            messagebox.showwarning("Trabajos", "El pedido debe conservar al menos un trabajo.", parent=self)
            return
        removed = tab.order_job_state.pop(index)
        self.render_order_workspace(tab)
        self.queue_order_autosave(order_id)
        self.database.add_order_event(order_id, "Trabajos", f"Se quitó el trabajo: {removed.get('title') or 'Sin nombre'}.")

    def _selected_order_design_indexes(self, tab) -> list[int]:
        """Retorna los índices de diseños seleccionados."""
        if hasattr(tab, "selected_design_indexes"):
            return sorted(list(tab.selected_design_indexes))
        return []

    def change_order_design_quantity(self, order_id: int):
        tab = self.order_tabs.get(order_id)
        indexes = self._selected_order_design_indexes(tab) if tab else []
        if not indexes:
            messagebox.showinfo("Pedido", "Elegí uno o más diseños del pedido.", parent=self)
            return
        quantity = simpledialog.askinteger("Cantidad de diseños", "Cantidad para los diseños elegidos:", initialvalue=tab.order_design_state[indexes[0]].get("quantity", 1), minvalue=1, parent=self)
        if quantity is None:
            return
        for index in indexes:
            tab.order_design_state[index]["quantity"] = quantity
        self.render_order_workspace(tab)
        self.queue_order_autosave(order_id)

    def set_order_design_status(self, order_id: int, status: str):
        tab = self.order_tabs.get(order_id)
        indexes = self._selected_order_design_indexes(tab) if tab else []
        if not indexes:
            messagebox.showinfo("Pedido", "Elegí los diseños a actualizar.", parent=self)
            return
        for index in indexes:
            tab.order_design_state[index]["status"] = status
        self.render_order_workspace(tab)
        self.queue_order_autosave(order_id)
        self.database.add_order_event(order_id, "Diseños", f"{len(indexes)} diseño(s) marcados como {status.lower()}.")

    def open_latest_order_preview(self, order_id: int):
        """Abre todas las vistas previas guardadas en una ventana modal."""
        previews = self.database.order_previews(order_id)
        if not previews:
            messagebox.showinfo("Vistas previas", "Todavía no hay vistas previas guardadas para este pedido.", parent=self)
            return
        
        # Abrir ventana con todas las vistas
        self.show_all_previews_window(order_id, previews)
    
    def show_all_previews_window(self, order_id: int, previews: list[dict]):
        """Muestra una ventana con todas las vistas previas del pedido."""
        from PIL import Image, ImageTk
        
        # Crear ventana modal
        preview_window = tk.Toplevel(self)
        preview_window.title(f"Vistas Previas - Pedido #{order_id}")
        preview_window.configure(background=COLORS.background)
        preview_window.transient(self)
        preview_window.grab_set()
        preview_window.geometry("1000x700")
        
        # Frame principal
        main_frame = tk.Frame(preview_window, background=COLORS.background)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Header
        order = self.database.order(order_id)
        client = order.get("client_name") or order.get("client", "Sin cliente")
        
        header = tk.Frame(main_frame, background=COLORS.panel_elevated,
                        highlightthickness=1, highlightbackground=COLORS.border)
        header.pack(fill="x", pady=(0, 12))
        
        tk.Label(header, text=f"Vistas Previas del Pedido #{order_id}",
                background=COLORS.panel_elevated, foreground=COLORS.wine_active,
                font=(IDENTITY_FONT, 14, "bold")).pack(anchor="w", padx=14, pady=(12, 4))
        
        tk.Label(header, text=f"Cliente: {client} • {len(previews)} vista(s) guardada(s)",
                background=COLORS.panel_elevated, foreground=COLORS.text,
                font=(UI_FONT, 11)).pack(anchor="w", padx=14, pady=(0, 12))
        
        # Contenedor con scroll para las miniaturas
        canvas_frame = tk.Frame(main_frame, background=COLORS.panel,
                               highlightthickness=1, highlightbackground=COLORS.border)
        canvas_frame.pack(fill="both", expand=True)
        
        canvas = tk.Canvas(canvas_frame, background=COLORS.panel, highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        
        scrollable = tk.Frame(canvas, background=COLORS.panel)
        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Cargar y mostrar cada vista previa
        for idx, preview in enumerate(previews, 1):
            path = Path(preview["preview_path"])
            if not path.exists():
                continue
            
            try:
                # Card para cada vista
                card = tk.Frame(scrollable, background=COLORS.panel_elevated,
                              highlightthickness=1, highlightbackground=COLORS.border)
                card.pack(fill="x", padx=10, pady=5)
                
                # Info header
                info_frame = tk.Frame(card, background=COLORS.panel_elevated)
                info_frame.pack(fill="x", padx=10, pady=8)
                
                created_at = preview.get("created_at", "").replace("T", " ")
                plancha_id = preview.get("plancha_id", "N/A")
                
                tk.Label(info_frame, text=f"Vista #{idx}  •  Plancha #{plancha_id}  •  {created_at}",
                        background=COLORS.panel_elevated, foreground=COLORS.text,
                        font=(UI_FONT, 10, "bold")).pack(side="left")
                
                # Botón para abrir en grande
                ttk.Button(info_frame, text="Ver completa",
                          command=lambda p=path: self.show_preview_window(order_id, p),
                          style="Secondary.TButton").pack(side="right", padx=(0, 4))
                
                ttk.Button(info_frame, text="Abrir archivo",
                          command=lambda p=path: os.startfile(str(p)),
                          style="Secondary.TButton").pack(side="right", padx=(0, 4))
                
                ttk.Button(info_frame, text="Eliminar",
                          command=lambda pid=preview["id"], pw=preview_window: self.delete_order_preview(order_id, pid, pw),
                          style="Secondary.TButton").pack(side="right", padx=(0, 4))
                
                # Miniatura
                img = Image.open(path)
                img.thumbnail((900, 250), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                
                img_label = tk.Label(card, image=photo, background=COLORS.panel_elevated,
                                   cursor="hand2")
                img_label.image = photo  # Mantener referencia
                img_label.pack(padx=10, pady=(0, 10))
                
                # Click en miniatura para ver completa
                img_label.bind("<Button-1>", lambda e, p=path: self.show_preview_window(order_id, p))
                
            except Exception as error:
                tk.Label(scrollable, text=f"Error al cargar vista #{idx}: {error}",
                        background=COLORS.panel, foreground=COLORS.muted,
                        font=(UI_FONT, 9)).pack(padx=10, pady=5)
        
        # Botón cerrar
        button_frame = tk.Frame(main_frame, background=COLORS.background)
        button_frame.pack(fill="x", pady=(12, 0))
        
        ttk.Button(button_frame, text="Cerrar",
                  command=preview_window.destroy,
                  style="Secondary.TButton").pack(side="right")
        
        # Mouse wheel scroll
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", on_mousewheel)
        
        # Centrar
        preview_window.update_idletasks()
        x = (preview_window.winfo_screenwidth() - preview_window.winfo_width()) // 2
        y = (preview_window.winfo_screenheight() - preview_window.winfo_height()) // 2
        preview_window.geometry(f"+{x}+{y}")
    
    def show_preview_window(self, order_id: int, image_path: Path):
        """Muestra una ventana con la vista previa del pedido con fondo de marca."""
        from PIL import Image, ImageTk
    
    def delete_order_preview(self, order_id: int, preview_id: int, parent_window=None):
        """Elimina una vista previa del pedido (archivo y registro en BD)."""
        confirm = messagebox.askyesno(
            "Eliminar vista previa",
            "¿Estás seguro de que querés eliminar esta vista previa? Esta acción no se puede deshacer.",
            parent=parent_window or self
        )
        
        if not confirm:
            return
        
        try:
            # Obtener info de la vista previa
            previews = self.database.order_previews(order_id)
            preview = next((p for p in previews if p["id"] == preview_id), None)
            
            if not preview:
                messagebox.showerror("Error", "No se encontró la vista previa.", parent=parent_window or self)
                return
            
            # Eliminar archivo físico
            preview_path = Path(preview["preview_path"])
            if preview_path.exists():
                try:
                    preview_path.unlink()
                except OSError as error:
                    messagebox.showwarning("Advertencia", f"No se pudo eliminar el archivo: {error}", parent=parent_window or self)
            
            # Eliminar registro de la base de datos
            self.database.delete_order_preview(preview_id)
            
            # Agregar evento al pedido
            self.database.add_order_event(
                order_id, 
                "Vista previa eliminada", 
                f"Se eliminó la vista previa #{preview_id}",
                {"preview_id": preview_id, "plancha_id": preview.get("plancha_id")}
            )
            
            messagebox.showinfo("Éxito", "Vista previa eliminada correctamente.", parent=parent_window or self)
            
            # Refrescar la ventana de vistas previas si existe
            if parent_window:
                parent_window.destroy()
                previews_updated = self.database.order_previews(order_id)
                if previews_updated:
                    self.show_all_previews_window(order_id, previews_updated)
            
            # Actualizar el tab del pedido si está abierto
            self.refresh_order_tab(order_id)
            
        except Exception as error:
            messagebox.showerror("Error", f"No se pudo eliminar la vista previa: {error}", parent=parent_window or self)

        
        # Crear ventana modal
        preview_window = tk.Toplevel(self)
        preview_window.title(f"Vista Previa - Pedido #{order_id}")
        preview_window.configure(background=COLORS.background)
        preview_window.transient(self)
        preview_window.grab_set()
        
        # Cargar imagen de la vista previa
        try:
            preview_img = Image.open(image_path)
            
            # Calcular tamaño para la ventana (máximo 90% de la pantalla)
            screen_width = self.winfo_screenwidth()
            screen_height = self.winfo_screenheight()
            max_width = int(screen_width * 0.9)
            max_height = int(screen_height * 0.85)
            
            # Calcular escala manteniendo aspecto
            img_width, img_height = preview_img.size
            scale = min(max_width / img_width, max_height / img_height, 1.0)
            
            if scale < 1.0:
                new_width = int(img_width * scale)
                new_height = int(img_height * scale)
                preview_img = preview_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Cargar fondo con patrón Doccione
            asset = Path(__file__).parents[1] / "assets" / "fondo_doccione_bw.png"
            with Image.open(asset) as fondo_source:
                # Crear fondo del tamaño de la imagen de vista previa
                fondo_width = preview_img.width + 80  # Padding
                fondo_height = preview_img.height + 80
                
                # Tile del patrón
                fondo = Image.new("RGBA", (fondo_width, fondo_height), (255, 255, 255, 255))
                pattern = fondo_source.convert("RGBA")
                
                # Reducir opacidad del patrón (más sutil)
                pattern_data = pattern.getdata()
                new_data = []
                for item in pattern_data:
                    if item[3] > 0:  # Si tiene alpha
                        new_data.append((item[0], item[1], item[2], int(item[3] * 0.15)))  # 15% opacidad
                    else:
                        new_data.append(item)
                pattern.putdata(new_data)
                
                # Repetir patrón para cubrir todo el fondo
                for y in range(0, fondo_height, pattern.height):
                    for x in range(0, fondo_width, pattern.width):
                        fondo.paste(pattern, (x, y), pattern)
                
                # Centrar la vista previa sobre el fondo
                x_offset = (fondo_width - preview_img.width) // 2
                y_offset = (fondo_height - preview_img.height) // 2
                fondo.paste(preview_img, (x_offset, y_offset), preview_img if preview_img.mode == 'RGBA' else None)
                
                # Convertir a PhotoImage
                photo = ImageTk.PhotoImage(fondo)
            
            # Frame principal
            main_frame = tk.Frame(preview_window, background=COLORS.background)
            main_frame.pack(fill="both", expand=True, padx=20, pady=20)
            
            # Header con info
            header = tk.Frame(main_frame, background=COLORS.panel_elevated, 
                            highlightthickness=1, highlightbackground=COLORS.border)
            header.pack(fill="x", pady=(0, 12))
            
            order = self.database.order(order_id)
            client = order.get("client_name") or order.get("client", "Sin cliente")
            
            tk.Label(header, text=f"Vista Previa del Pedido #{order_id}", 
                    background=COLORS.panel_elevated, foreground=COLORS.wine_active,
                    font=(IDENTITY_FONT, 14, "bold")).pack(anchor="w", padx=14, pady=(12, 4))
            
            tk.Label(header, text=f"Cliente: {client}", 
                    background=COLORS.panel_elevated, foreground=COLORS.text,
                    font=(UI_FONT, 11)).pack(anchor="w", padx=14, pady=(0, 12))
            
            # Contenedor de imagen con scroll
            canvas_frame = tk.Frame(main_frame, background=COLORS.panel, 
                                   highlightthickness=1, highlightbackground=COLORS.border)
            canvas_frame.pack(fill="both", expand=True)
            
            canvas = tk.Canvas(canvas_frame, background=COLORS.panel, highlightthickness=0)
            v_scroll = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
            h_scroll = ttk.Scrollbar(canvas_frame, orient="horizontal", command=canvas.xview)
            
            canvas.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
            
            # Label con la imagen con fondo
            img_label = tk.Label(canvas, image=photo, background=COLORS.panel)
            img_label.image = photo  # Mantener referencia
            
            canvas_window = canvas.create_window((0, 0), window=img_label, anchor="nw")
            
            canvas.pack(side="left", fill="both", expand=True)
            v_scroll.pack(side="right", fill="y")
            h_scroll.pack(side="bottom", fill="x")
            
            # Configurar región de scroll
            img_label.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox("all"))
            
            # Botones
            button_frame = tk.Frame(main_frame, background=COLORS.background)
            button_frame.pack(fill="x", pady=(12, 0))
            
            ttk.Button(button_frame, text="Cerrar", 
                      command=preview_window.destroy, 
                      style="Secondary.TButton").pack(side="right")
            
            ttk.Button(button_frame, text="Abrir en visor externo", 
                      command=lambda: os.startfile(str(image_path)),
                      style="Secondary.TButton").pack(side="right", padx=(0, 8))
            
            # Ajustar tamaño de ventana
            preview_window.geometry(f"{fondo.width + 40}x{fondo.height + 180}")
            
            # Centrar en pantalla
            preview_window.update_idletasks()
            x = (screen_width - preview_window.winfo_width()) // 2
            y = (screen_height - preview_window.winfo_height()) // 2
            preview_window.geometry(f"+{x}+{y}")
            
        except Exception as error:
            messagebox.showerror("Vista previa", f"Error al cargar la imagen: {error}", parent=self)
            preview_window.destroy()

    def remove_order_designs(self, order_id: int):
        tab = self.order_tabs.get(order_id)
        indexes = self._selected_order_design_indexes(tab) if tab else []
        if not indexes:
            messagebox.showinfo("Pedido", "Elegí los diseños a quitar.", parent=self)
            return
        selected = set(indexes)
        tab.order_design_state = [design for index, design in enumerate(tab.order_design_state) if index not in selected]
        self.render_order_workspace(tab)
        self.queue_order_autosave(order_id)
        self.database.add_order_event(order_id, "Diseños", f"Se quitaron {len(indexes)} diseño(s) del pedido.")

    def register_order_payment(self, order_id: int):
        tab = self.order_tabs.get(order_id)
        if tab:
            self.flush_order_autosave(order_id)
        amount = simpledialog.askfloat("Registrar cobro", "Importe recibido:", minvalue=0.01, parent=self)
        if amount is None:
            return
        method = simpledialog.askstring("Registrar cobro", "Medio de pago (opcional):", parent=self) or ""
        note = simpledialog.askstring("Registrar cobro", "Detalle (opcional):", parent=self) or ""
        try:
            self.database.register_order_payment(order_id, amount, method, note)
        except ValueError as error:
            messagebox.showwarning("Registrar cobro", str(error), parent=self)
            return
        # Publicar evento de pago
        try:
            self._event_bus.publish_payment_received(order_id, amount, method)
        except Exception:
            pass
        if tab:
            self.render_order_workspace(tab)
        self.refresh_orders()
        self.status.set(f"Cobro de ${amount:,.2f} registrado en el pedido #{order_id}.")

    def apply_suggested_order_price(self, order_id: int):
        tab = self.order_tabs.get(order_id)
        if not tab:
            return
        jobs = getattr(tab, "order_job_state", [])
        if jobs:
            selected = self._selected_order_job_index(tab)
            if selected is None:
                selected = 0 if len(jobs) == 1 else None
            if selected is None:
                messagebox.showinfo("Precios", "Elegí el trabajo al que querés aplicar el precio sugerido.", parent=self)
                return
            job = jobs[selected]
            rule = self.database.suggest_price(job.get("material", ""), job.get("size", ""), int(job.get("quantity", 1) or 1))
            if not rule:
                messagebox.showinfo("Precios", "No hay una regla compatible para ese trabajo.", parent=self)
                return
            price = float(rule.get("suggested_subtotal") or rule.get("price") or 0)
            discount = float(rule.get("discount_percent") or 0)
            detail = rule.get("calculation_detail") or "Precio configurado"
            if not messagebox.askyesno("Aplicar precio sugerido", f"{detail}\nSubtotal sugerido: ${price:,.2f}\nDescuento: {discount:g}%\n¿Aplicarlo a {job.get('title') or 'este trabajo'}?", parent=self):
                return
            job["subtotal"], job["discount_percent"] = price, discount
            if rule.get("extra_service"):
                job["extra_services"] = rule["extra_service"]
            self.render_order_workspace(tab)
            self.database.add_order_event(order_id, "Presupuesto", f"Se aplicó una propuesta de precio a {job.get('title') or 'un trabajo'}.", {"price_rule": rule.get("id")})
            self.queue_order_autosave(order_id)
            return
        try:
            quantity = int(tab.order_values["quantity"].get() or 0)
        except ValueError:
            quantity = 0
        rule = self.database.suggest_price(
            tab.order_values["material"].get(), tab.order_values["size"].get(), quantity,
        )
        if not rule:
            messagebox.showinfo("Precios", "No hay una regla compatible. Podés cargar el subtotal manualmente o crear una regla en Precios.", parent=self)
            return
        price = float(rule.get("suggested_subtotal") or rule.get("price") or 0)
        discount = float(rule.get("discount_percent") or 0)
        calculation = rule.get("calculation_detail") or "Precio configurado"
        text = f"{calculation}\nSubtotal sugerido: ${price:,.2f}\nDescuento: {discount:g}%\n¿Aplicarlo al pedido?"
        if not messagebox.askyesno("Aplicar precio sugerido", text, parent=self):
            return
        tab.order_values["price"].set(f"{price:.2f}")
        tab.order_values["discount_percent"].set(f"{discount:g}")
        if rule.get("extra_service"):
            tab.order_values["extra_services"].set(rule["extra_service"])
        self.database.add_order_event(order_id, "Presupuesto", "Se aplicó una propuesta de precio configurable.", {"price_rule": rule.get("id")})
        self.queue_order_autosave(order_id)

    def configure_price_rules(self):
        dialog = tk.Toplevel(self)
        dialog.title("Precios configurables")
        dialog.configure(background=COLORS.background)
        dialog.transient(self)
        dialog.geometry("1120x620")
        dialog.minsize(920, 500)
        price_style = ttk.Style(dialog)
        price_style.configure(
            "Price.Treeview",
            background=COLORS.panel,
            fieldbackground=COLORS.panel,
            foreground=COLORS.text,
            rowheight=30,
            borderwidth=0,
            font=(UI_FONT, 10),
        )
        price_style.configure(
            "Price.Treeview.Heading",
            background=COLORS.panel_elevated,
            foreground=COLORS.text,
            relief="flat",
            font=(UI_FONT, 10, "bold"),
            padding=(8, 7),
        )
        price_style.map(
            "Price.Treeview",
            background=[("selected", COLORS.wine)],
            foreground=[("selected", COLORS.text)],
        )
        header = tk.Frame(dialog, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        header.pack(fill="x", padx=16, pady=(16, 10))
        tk.Label(header, text="PRECIOS CONFIGURABLES", background=COLORS.panel, foreground=COLORS.text,
                 font=(IDENTITY_FONT, 17, "bold")).pack(anchor="w", padx=16, pady=(13, 2))
        tk.Label(header, text="Las reglas proponen el subtotal; nunca modifican un pedido sin tu confirmación.",
                 background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 10)).pack(anchor="w", padx=16, pady=(0, 13))
        holder = tk.Frame(dialog, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        holder.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        _COLS = ("product", "material", "size", "quantity", "mode", "price",
                 "model", "cost_total", "margin", "status", "detail", "discount", "extra")
        tree = ttk.Treeview(holder, columns=_COLS, show="headings", selectmode="browse")
        _COL_DEFS = (
            ("product",    "Producto",    160, "w"),
            ("material",   "Material",    140, "w"),
            ("size",       "Tamaño",       70, "center"),
            ("quantity",   "Desde",        55, "center"),
            ("mode",       "Cálculo",      90, "center"),
            ("price",      "Precio venta", 100, "center"),
            ("model",      "Modelo de costos", 160, "w"),
            ("cost_total", "Costo total",  90, "center"),
            ("margin",     "Margen",       120, "center"),
            ("status",     "Estado",       100, "center"),
            ("detail",     "Desglose",     260, "w"),
            ("discount",   "Desc.",        55, "center"),
            ("extra",      "Servicio",    130, "w"),
        )
        for key, title, width, anchor in _COL_DEFS:
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=max(40, width - 20), anchor=anchor)
        tree.configure(style="Price.Treeview")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)
        scroll.pack(side="right", fill="y", padx=(0, 1), pady=1)

        def refresh_rules():
            tree.delete(*tree.get_children())
            for rule in self.database.price_rule_presentations():
                mode = {"unitario": "Por unidad", "pack": "Por pack", "fijo": "Precio fijo"}.get(
                    str(rule.get("price_mode") or "fijo").casefold(), "Precio fijo")
                material_value = str(rule.get("material") or "Cualquiera")
                if " - " in material_value:
                    product_value, material_display = material_value.split(" - ", 1)
                else:
                    product_value, material_display = material_value, material_value
                qty = int(rule.get("min_quantity") or 1)
                price = float(rule.get("price") or 0)
                cost_total = float(rule.get("cost_total") or 0)
                margin_value = float(rule.get("margin") or 0)
                margin_pct = f"{float(rule.get('margin_pct') or 0):.1f}%"
                margin_str = f"${margin_value:,.2f} ({margin_pct})"
                warning = rule.get("warning")
                detail = rule.get("detail") or "Sin detalle"
                tree.insert("", "end", iid=str(rule["id"]), values=(
                    product_value,
                    material_display or "Cualquiera",
                    rule.get("size") or "Cualquiera",
                    qty,
                    mode,
                    f"${price:,.2f}",
                    str(rule.get("model_name") or "—"),
                    f"${cost_total:,.2f}",
                    margin_str,
                    str(rule.get("status") or "Sin datos"),
                    detail,
                    f"{float(rule.get('discount_percent') or 0):g}%",
                    rule.get("extra_service") or "—",
                ))

        def _open_rule_editor(rule: dict | None = None):
            """Editor unificado para crear o modificar una regla de precio."""
            is_new = rule is None
            rule = rule or {}
            material_value = str(rule.get("material", ""))
            if " - " in material_value:
                product_default, material_default = material_value.split(" - ", 1)
            else:
                product_default, material_default = material_value, ""

            editor = tk.Toplevel(dialog)
            editor.title("Nueva regla de precio" if is_new else "Modificar regla de precio")
            editor.configure(background=COLORS.background)
            editor.transient(dialog)
            editor.grab_set()
            editor.geometry("640x720")
            editor.minsize(580, 640)

            def _f(key, default="0"):
                return f"{float(rule.get(key) or 0):g}" if not is_new else default

            v = {k: tk.StringVar() for k in (
                "product", "material", "size", "quantity", "price",
                "discount", "extra", "mode", "pack",
                "cost_model_id",
                "mp_fixed", "mp_unit",
                "mo_fixed", "mo_unit",
                "cf_fixed", "cf_unit",
            )}
            v["product"].set(product_default)
            v["material"].set(material_default)
            v["size"].set(str(rule.get("size", "")))
            v["quantity"].set(str(rule.get("min_quantity", 1)))
            v["price"].set(_f("price"))
            v["discount"].set(_f("discount_percent"))
            v["extra"].set(str(rule.get("extra_service", "")))
            v["mode"].set(str(rule.get("price_mode") or "fijo"))
            v["pack"].set(str(rule.get("pack_quantity", 1)))
            v["cost_model_id"].set(str(rule.get("cost_model_id") or ""))

            margin_var = tk.StringVar(value="—")

            def _recalc_margin(*_):
                try:
                    qty   = max(1, int(v["quantity"].get() or 1))
                    price = float(v["price"].get().replace(",", ".") or 0)
                    margin = round(price - 0, 2)
                    margin_var.set(f"${margin:,.2f}  (sin modelo)" if price else "—")
                except (ValueError, ZeroDivisionError):
                    margin_var.set("—")

            for key in ("price", "quantity"):
                v[key].trace_add("write", _recalc_margin)

            # ── Layout del editor ─────────────────────────────────────────────
            canvas_e = tk.Canvas(editor, background=COLORS.background, highlightthickness=0)
            scrollbar_e = ttk.Scrollbar(editor, orient="vertical", command=canvas_e.yview)
            canvas_e.configure(yscrollcommand=scrollbar_e.set)
            form = tk.Frame(canvas_e, background=COLORS.background)
            canvas_e.create_window((0, 0), window=form, anchor="nw")
            form.bind("<Configure>", lambda e: canvas_e.configure(scrollregion=canvas_e.bbox("all")))
            canvas_e.pack(side="left", fill="both", expand=True)
            scrollbar_e.pack(side="right", fill="y")
            form.columnconfigure(1, weight=1)
            form.columnconfigure(3, weight=1)

            row = 0
            def _lbl(text, r, c, **kw):
                tk.Label(form, text=text, background=COLORS.background,
                         foreground=COLORS.muted, font=(UI_FONT, 9), **kw
                         ).grid(row=r, column=c, sticky="w", padx=(14, 6), pady=3)
            def _entry(var, r, c, width=18, **kw):
                e = ttk.Entry(form, textvariable=var, width=width, **kw)
                e.grid(row=r, column=c, sticky="ew", padx=(0, 14), pady=3)
                return e
            def _section(text, r):
                tk.Label(form, text=text, background=COLORS.background,
                         foreground=COLORS.wine_active, font=(IDENTITY_FONT, 10, "bold")
                         ).grid(row=r, column=0, columnspan=4, sticky="w", padx=14, pady=(14, 4))
                tk.Frame(form, height=1, background=COLORS.border
                         ).grid(row=r+1, column=0, columnspan=4, sticky="ew", padx=14)

            # Sección: Identificación
            _section("IDENTIFICACIÓN DEL PRODUCTO", row); row += 2
            _lbl("Producto",        row, 0); _entry(v["product"],  row, 1)
            _lbl("Material",        row, 2)
            mat_cb = ttk.Combobox(form, textvariable=v["material"],
                                  values=self.database.price_materials(), width=18)
            mat_cb.grid(row=row, column=3, sticky="ew", padx=(0, 14), pady=3)
            row += 1
            _lbl("Tamaño",          row, 0)
            sz_cb = ttk.Combobox(form, textvariable=v["size"],
                                 values=self.database.price_sizes(), width=18)
            sz_cb.grid(row=row, column=1, sticky="ew", padx=(0, 14), pady=3)
            _lbl("Desde cantidad",  row, 2); _entry(v["quantity"], row, 3)
            row += 1

            # Sección: Precio de venta
            _section("PRECIO DE VENTA", row); row += 2
            _lbl("Modo de cálculo", row, 0)
            ttk.Combobox(form, textvariable=v["mode"],
                         values=("fijo", "unitario", "pack"),
                         state="readonly", width=18
                         ).grid(row=row, column=1, sticky="ew", padx=(0, 14), pady=3)
            _lbl("Unidades por pack", row, 2); _entry(v["pack"],     row, 3)
            row += 1
            _lbl("Precio ($)",      row, 0); _entry(v["price"],    row, 1)
            _lbl("Descuento (%)",   row, 2); _entry(v["discount"], row, 3)
            row += 1
            _lbl("Servicio / detalle", row, 0)
            ttk.Entry(form, textvariable=v["extra"], width=18
                      ).grid(row=row, column=1, columnspan=3, sticky="ew", padx=(0, 14), pady=3)
            row += 1

            # Sección: Estructura de costos
            _section("MODELO DE COSTOS", row); row += 2
            _lbl("Modelo de costos", row, 0)
            model_names = self.database.cost_model_names()
            model_combo = ttk.Combobox(form, textvariable=v["cost_model_id"], values=model_names, width=28, state="readonly")
            model_combo.grid(row=row, column=1, sticky="ew", padx=(0, 14), pady=3)
            row += 1

            selected_model = None
            if v["cost_model_id"].get():
                selected_model = self.database.cost_model(int(v["cost_model_id"].get()))

            model_summary_var = tk.StringVar(value=selected_model.get("description", "Sin modelo seleccionado") if selected_model else "Sin modelo seleccionado")
            tk.Label(form, textvariable=model_summary_var, background=COLORS.background, foreground=COLORS.muted, font=(UI_FONT, 9), wraplength=560, justify="left").grid(row=row, column=0, columnspan=4, sticky="w", padx=14, pady=(4, 8))
            row += 1

            def _refresh_model_summary(*_):
                model_id = v["cost_model_id"].get().strip()
                if not model_id:
                    model_summary_var.set("Sin modelo seleccionado")
                    return
                try:
                    model = self.database.cost_model(int(model_id))
                except ValueError:
                    model_summary_var.set("Modelo no válido")
                    return
                if not model:
                    model_summary_var.set("Modelo no encontrado")
                    return
                details = []
                for component in model.get("components") or []:
                    details.append(f"• {component.get('name')}: {component.get('value_type')} = {component.get('value')}")
                model_summary_var.set(model.get("description") or "Sin descripción") + ("\n" + "\n".join(details) if details else "")

            v["cost_model_id"].trace_add("write", _refresh_model_summary)
            _refresh_model_summary()

            tk.Frame(form, height=1, background=COLORS.border).grid(row=row, column=0, columnspan=4, sticky="ew", padx=14, pady=(6, 2))
            row += 1
            tk.Label(form, text="Margen estimado (para la cantidad mínima):", background=COLORS.background, foreground=COLORS.muted, font=(UI_FONT, 9)).grid(row=row, column=0, columnspan=2, sticky="w", padx=14, pady=4)
            margin_lbl = tk.Label(form, textvariable=margin_var, background=COLORS.background, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 11, "bold"))
            margin_lbl.grid(row=row, column=2, columnspan=2, sticky="w", padx=14, pady=4)
            row += 1

            _recalc_margin()

            # ── Botones ───────────────────────────────────────────────────────
            btn_frame = tk.Frame(form, background=COLORS.background)
            btn_frame.grid(row=row, column=0, columnspan=4, sticky="ew", padx=14, pady=(16, 14))

            def _save():
                try:
                    def _fv(key): return float(v[key].get().replace(",", ".") or 0)
                    stored_material = v["product"].get().strip()
                    if v["material"].get().strip():
                        stored_material = (f"{stored_material} - {v['material'].get().strip()}"
                                           if stored_material else v["material"].get().strip())
                    kwargs = dict(
                        material=stored_material,
                        size=v["size"].get(),
                        min_quantity=int(v["quantity"].get() or 1),
                        price=_fv("price"),
                        extra_service=v["extra"].get(),
                        discount_percent=_fv("discount"),
                        price_mode=v["mode"].get(),
                        pack_quantity=int(v["pack"].get() or 1),
                        cost_model_id=(int(v["cost_model_id"].get()) if v["cost_model_id"].get().strip() else None),
                    )
                    if is_new:
                        self.database.save_price_rule(**kwargs)
                    else:
                        updated = self.database.update_price_rule(int(rule["id"]), **kwargs)
                        if not updated:
                            messagebox.showerror("Precios", "No se pudo actualizar la regla.", parent=editor)
                            return
                except ValueError:
                    messagebox.showwarning("Precios", "Revisá que los valores numéricos sean válidos.", parent=editor)
                    return
                editor.destroy()
                refresh_rules()
                if not is_new:
                    tree.selection_set(str(rule["id"]))
                    tree.focus(str(rule["id"]))

            ttk.Button(btn_frame, text="Cancelar", command=editor.destroy,
                       style="Secondary.TButton").pack(side="right")
            ttk.Button(btn_frame, text="Guardar regla" if is_new else "Guardar cambios",
                       command=_save, style="Primary.TButton").pack(side="right", padx=(0, 8))

        def add_rule():
            _open_rule_editor(rule=None)

        def modify_rule(_event=None):
            selected = tree.selection()
            if not selected:
                messagebox.showinfo("Precios", "Elegí una regla para modificar.", parent=dialog)
                return
            rule = self.database.price_rule(int(selected[0]))
            if not rule:
                refresh_rules()
                return
            _open_rule_editor(rule=rule)

        def remove_rule():
            selected = tree.selection()
            if not selected:
                return
            if messagebox.askyesno("Eliminar regla", "¿Eliminar esta regla de precios?", parent=dialog):
                self.database.remove_price_rule(int(selected[0]))
                refresh_rules()

        def remove_all_rules():
            if messagebox.askyesno("Eliminar todos los precios", "¿Eliminar todas las reglas de precios? Esta acción no se puede deshacer.", parent=dialog):
                self.database.remove_all_price_rules()
                refresh_rules()

        tree.bind("<Double-1>", modify_rule)
        actions = tk.Frame(dialog, background=COLORS.background)
        actions.pack(fill="x", padx=16, pady=(0, 16))
        ttk.Button(actions, text="Nueva regla", command=add_rule, style="Primary.TButton").pack(side="left")
        ttk.Button(actions, text="Modificar", command=modify_rule, style="Secondary.TButton").pack(side="left", padx=7)
        ttk.Button(actions, text="Eliminar", command=remove_rule, style="Danger.TButton").pack(side="left")
        ttk.Button(actions, text="Eliminar todo", command=remove_all_rules, style="Danger.TButton").pack(side="left", padx=7)
        ttk.Button(actions, text="Cerrar", command=dialog.destroy, style="Secondary.TButton").pack(side="right")
        refresh_rules()

    def configure_cost_rules(self):
        """Editor de costos con pestañas: Costos Fijos y Costos Variables."""
        self._open_costs_dialog()

    def _open_costs_dialog(self):
        """Diálogo principal de costos con dos pestañas independientes."""
        dialog = tk.Toplevel(self)
        dialog.title("Costos")
        dialog.configure(background=COLORS.background)
        dialog.transient(self)
        dialog.geometry("1000x620")
        dialog.minsize(880, 520)

        header = tk.Frame(dialog, background=COLORS.panel,
                         highlightthickness=1, highlightbackground=COLORS.border)
        header.pack(fill="x", padx=16, pady=(16, 10))
        tk.Label(header, text="COSTOS", background=COLORS.panel,
                foreground=COLORS.text, font=(IDENTITY_FONT, 17, "bold")
                ).pack(anchor="w", padx=16, pady=(13, 2))
        tk.Label(header, text="Administrá los costos fijos globales y los costos variables por producto.",
                background=COLORS.panel, foreground=COLORS.muted, font=(UI_FONT, 10)
                ).pack(anchor="w", padx=16, pady=(0, 13))

        notebook = ttk.Notebook(dialog)
        notebook.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        fixed_tab = ttk.Frame(notebook)
        variable_tab = ttk.Frame(notebook)
        notebook.add(fixed_tab, text="  Costos Fijos  ")
        notebook.add(variable_tab, text="  Costos Variables  ")

        # ── Pestaña: Costos Fijos ──────────────────────────────────────────

        fixed_holder = tk.Frame(fixed_tab, background=COLORS.panel,
                               highlightthickness=1, highlightbackground=COLORS.border)
        fixed_holder.pack(fill="both", expand=True)

        _COLS = ("name", "condition", "model", "summary")
        fixed_tree = ttk.Treeview(fixed_holder, columns=_COLS, show="headings", selectmode="browse")

        _COL_DEFS = (
            ("name",      "Nombre",              180, "w"),
            ("condition", "Condición",           150, "w"),
            ("model",     "Modelo",              180, "w"),
            ("summary",   "Resumen",             260, "w"),
        )

        for key, title, width, anchor in _COL_DEFS:
            fixed_tree.heading(key, text=title)
            fixed_tree.column(key, width=width, minwidth=max(40, width - 20), anchor=anchor)

        scroll = ttk.Scrollbar(fixed_holder, orient="vertical", command=fixed_tree.yview)
        fixed_tree.configure(yscrollcommand=scroll.set)
        fixed_tree.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)
        scroll.pack(side="right", fill="y", padx=(0, 1), pady=1)

        def refresh_fixed_rules():
            fixed_tree.delete(*fixed_tree.get_children())
            for rule in self.database.all_cost_rules():
                model = self.database.cost_model(rule["id"]) if rule.get("id") else None
                summary = "Sin modelo asociado" if not model else (model.get("description") or "Modelo de costos")
                fixed_tree.insert("", "end", iid=str(rule["id"]), values=(
                    rule.get("name") or "Sin nombre",
                    rule.get("condition") or "Siempre",
                    model.get("name") if model else "—",
                    summary,
                ))

        def add_fixed_rule():
            self._open_cost_rule_editor(dialog, fixed_tree, None)

        def modify_fixed_rule(*_):
            selected = fixed_tree.selection()
            if not selected:
                messagebox.showinfo("Costos", "Elegí una regla para modificar.", parent=dialog)
                return
            rule = self.database.cost_rule(int(selected[0]))
            if not rule:
                refresh_fixed_rules()
                return
            self._open_cost_rule_editor(dialog, fixed_tree, rule)

        def remove_fixed_rule():
            selected = fixed_tree.selection()
            if not selected:
                return
            if messagebox.askyesno("Eliminar regla", "¿Eliminar esta regla de costos?", parent=dialog):
                self.database.remove_cost_rule(int(selected[0]))
                refresh_fixed_rules()

        fixed_tree.bind("<Double-1>", modify_fixed_rule)

        fixed_actions = tk.Frame(fixed_tab, background=COLORS.background)
        fixed_actions.pack(fill="x", pady=(8, 0))
        ttk.Button(fixed_actions, text="Nueva regla", command=add_fixed_rule,
                   style="Primary.TButton").pack(side="left")
        ttk.Button(fixed_actions, text="Modificar", command=modify_fixed_rule,
                   style="Secondary.TButton").pack(side="left", padx=7)
        ttk.Button(fixed_actions, text="Eliminar", command=remove_fixed_rule,
                   style="Danger.TButton").pack(side="left")

        # ── Pestaña: Costos Variables ──────────────────────────────────────

        var_search_frame = tk.Frame(variable_tab, background=COLORS.background)
        var_search_frame.pack(fill="x", pady=(0, 6))

        tk.Label(var_search_frame, text="Buscar:", background=COLORS.background,
                foreground=COLORS.muted, font=(UI_FONT, 10)).pack(side="left", padx=(0, 6))
        var_search_var = tk.StringVar()
        var_search_entry = ttk.Entry(var_search_frame, textvariable=var_search_var, width=25)
        var_search_entry.pack(side="left", padx=(0, 10))

        tk.Label(var_search_frame, text="Categoría:", background=COLORS.background,
                foreground=COLORS.muted, font=(UI_FONT, 10)).pack(side="left", padx=(0, 6))
        var_cat_filter = tk.StringVar(value="Todas")
        var_cat_combo = ttk.Combobox(var_search_frame, textvariable=var_cat_filter,
                                    values=["Todas"], state="readonly", width=16)
        var_cat_combo.pack(side="left", padx=(0, 10))

        tk.Label(var_search_frame, text="Estado:", background=COLORS.background,
                foreground=COLORS.muted, font=(UI_FONT, 10)).pack(side="left", padx=(0, 6))
        var_status_filter = tk.StringVar(value="Todos")
        var_status_combo = ttk.Combobox(var_search_frame, textvariable=var_status_filter,
                                       values=["Todos", "Activos", "Inactivos"], state="readonly", width=12)
        var_status_combo.pack(side="left")

        var_holder = tk.Frame(variable_tab, background=COLORS.panel,
                             highlightthickness=1, highlightbackground=COLORS.border)
        var_holder.pack(fill="both", expand=True)

        _VCOLS = ("name", "product", "category", "unit_cost", "sale_price", "margin", "updated", "status")
        var_tree = ttk.Treeview(var_holder, columns=_VCOLS, show="headings", selectmode="browse")

        _VCOL_DEFS = (
            ("name",      "Modelo",             160, "w"),
            ("product",   "Producto",           160, "w"),
            ("category",  "Categoría",          110, "w"),
            ("unit_cost", "Costo variable",     110, "center"),
            ("sale_price","Precio venta",       100, "center"),
            ("margin",    "Margen",             120, "center"),
            ("updated",   "Actualizado",        100, "center"),
            ("status",    "Estado",              80, "center"),
        )

        for key, title, width, anchor in _VCOL_DEFS:
            var_tree.heading(key, text=title)
            var_tree.column(key, width=width, minwidth=max(40, width - 20), anchor=anchor)

        var_scroll = ttk.Scrollbar(var_holder, orient="vertical", command=var_tree.yview)
        var_tree.configure(yscrollcommand=var_scroll.set)
        var_tree.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)
        var_scroll.pack(side="right", fill="y", padx=(0, 1), pady=1)

        def refresh_variable_models():
            var_tree.delete(*var_tree.get_children())
            search = var_search_var.get().strip().lower()
            cat_filter = var_cat_filter.get()
            status_filter = var_status_filter.get()

            all_models = self.database.all_variable_cost_models()

            categories = set()
            for m in all_models:
                cat = str(m.get("category") or "").strip()
                if cat:
                    categories.add(cat)
            cat_values = ["Todas"] + sorted(categories)
            var_cat_combo.config(values=cat_values)

            for m in all_models:
                name = str(m.get("name") or "").strip()
                product_name = str(m.get("product_name") or "").strip()
                category = str(m.get("category") or "").strip()
                active = bool(m.get("active", 1))
                updated = str(m.get("updated_at") or "").replace("T", " ")[:16]

                if search and search not in name.lower() and search not in product_name.lower() and search not in category.lower():
                    continue
                if cat_filter != "Todas" and category.lower() != cat_filter.lower():
                    continue
                if status_filter == "Activos" and not active:
                    continue
                if status_filter == "Inactivos" and active:
                    continue

                components = self.database.variable_cost_model_components(m["id"])
                total_cost = 0.0
                for comp in components:
                    if not comp.get("active", 1):
                        continue
                    qty = float(comp.get("quantity") or 0)
                    val = float(comp.get("unit_value") or 0)
                    waste = float(comp.get("waste_pct") or 0)
                    mode = str(comp.get("calc_mode") or "per_unit")
                    if mode == "percentage":
                        pass
                    else:
                        raw = qty * val
                        if waste > 0:
                            raw *= (1.0 + waste / 100.0)
                        total_cost += raw

                sale_price = 0.0
                sale_price_str = "—"
                margin_str = "—"

                price_rows = self.database.connection.execute(
                    "SELECT price FROM price_rules WHERE material LIKE ? LIMIT 1",
                    (f"%{product_name}%",),
                ).fetchall() if product_name else []
                if price_rows:
                    sale_price = float(price_rows[0][0])
                    margin = sale_price - total_cost
                    margin_pct = (margin / sale_price * 100) if sale_price > 0 else 0
                    sale_price_str = f"${sale_price:,.2f}"
                    margin_str = f"${margin:,.2f} ({margin_pct:.1f}%)"

                var_tree.insert("", "end", iid=str(m["id"]), values=(
                    name,
                    product_name or "—",
                    category or "—",
                    f"${total_cost:,.2f}",
                    sale_price_str,
                    margin_str,
                    updated,
                    "Activo" if active else "Inactivo",
                ))

        def add_variable_model():
            self._open_variable_cost_editor(dialog, var_tree, None)

        def modify_variable_model(*_):
            selected = var_tree.selection()
            if not selected:
                messagebox.showinfo("Costos Variables", "Elegí un modelo para editar.", parent=dialog)
                return
            model = self.database.variable_cost_model(int(selected[0]))
            if not model:
                refresh_variable_models()
                return
            self._open_variable_cost_editor(dialog, var_tree, model)

        def duplicate_variable_model():
            selected = var_tree.selection()
            if not selected:
                return
            new_id = self.database.duplicate_variable_cost_model(int(selected[0]))
            if new_id:
                refresh_variable_models()
                var_tree.selection_set(str(new_id))

        def remove_variable_model():
            selected = var_tree.selection()
            if not selected:
                return
            model = self.database.variable_cost_model(int(selected[0]))
            if not model:
                return
            if messagebox.askyesno("Eliminar modelo",
                                   f"¿Eliminar el modelo «{model.get('name', '')}» y todos sus componentes?",
                                   parent=dialog):
                self.database.remove_variable_cost_model(int(selected[0]))
                refresh_variable_models()

        var_tree.bind("<Double-1>", modify_variable_model)
        var_search_var.trace_add("write", lambda *_: refresh_variable_models())
        var_cat_filter.trace_add("write", lambda *_: refresh_variable_models())
        var_status_filter.trace_add("write", lambda *_: refresh_variable_models())

        var_actions = tk.Frame(variable_tab, background=COLORS.background)
        var_actions.pack(fill="x", pady=(8, 0))
        ttk.Button(var_actions, text="Nuevo modelo", command=add_variable_model,
                   style="Primary.TButton").pack(side="left")
        ttk.Button(var_actions, text="Editar", command=modify_variable_model,
                   style="Secondary.TButton").pack(side="left", padx=7)
        ttk.Button(var_actions, text="Duplicar", command=duplicate_variable_model,
                   style="Secondary.TButton").pack(side="left")
        ttk.Button(var_actions, text="Eliminar", command=remove_variable_model,
                   style="Danger.TButton").pack(side="left", padx=7)

        close_frame = tk.Frame(dialog, background=COLORS.background)
        close_frame.pack(fill="x", padx=16, pady=(0, 12))
        ttk.Button(close_frame, text="Cerrar", command=dialog.destroy,
                   style="Secondary.TButton").pack(side="right")

        refresh_fixed_rules()
        refresh_variable_models()
    
    def _open_cost_rule_editor(self, parent_dialog, tree, rule: dict | None):
        """Editor unificado para crear o modificar una regla de costos."""
        is_new = rule is None
        rule = rule or {}
        
        editor = tk.Toplevel(parent_dialog)
        editor.title("Nuevo modelo de costos" if is_new else "Modificar modelo de costos")
        editor.configure(background=COLORS.background)
        editor.transient(parent_dialog)
        editor.grab_set()
        editor.geometry("980x620")
        editor.minsize(860, 560)
        
        # Variables
        MODE_LABELS = {
            "percent": "Porcentaje",
            "fixed": "Fijo",
            "per_unit": "Por unidad",
            "per_hour": "Por hora",
            "per_square_meter": "Por superficie",
        }
        MODE_KEYS = {label: key for key, label in MODE_LABELS.items()}

        name_var = tk.StringVar(value=str(rule.get("name", "")))
        product_var = tk.StringVar(value=str(rule.get("material") or rule.get("product_type") or ""))
        condition_var = tk.StringVar(value=str(rule.get("condition", "")))
        mp_mode = self.database._normalize_cost_mode(rule.get("cost_mp_mode"))
        mo_mode = self.database._normalize_cost_mode(rule.get("cost_mo_mode"))
        cf_mode = self.database._normalize_cost_mode(rule.get("cost_cf_mode"))
        mp_mode_var = tk.StringVar(value=MODE_LABELS.get(mp_mode, "Porcentaje"))
        mo_mode_var = tk.StringVar(value=MODE_LABELS.get(mo_mode, "Porcentaje"))
        cf_mode_var = tk.StringVar(value=MODE_LABELS.get(cf_mode, "Porcentaje"))
        mp_mode_internal = tk.StringVar(value=mp_mode)
        mo_mode_internal = tk.StringVar(value=mo_mode)
        cf_mode_internal = tk.StringVar(value=cf_mode)
        mp_percent_var = tk.StringVar(value=f"{float(rule.get('cost_mp_percent') or 0):g}")
        mo_percent_var = tk.StringVar(value=f"{float(rule.get('cost_mo_percent') or 0):g}")
        cf_percent_var = tk.StringVar(value=f"{float(rule.get('cost_cf_percent') or 0):g}")
        mp_fixed_var = tk.StringVar(value=f"{float(rule.get('cost_mp_fixed') or 0):g}")
        mo_fixed_var = tk.StringVar(value=f"{float(rule.get('cost_mo_fixed') or 0):g}")
        cf_fixed_var = tk.StringVar(value=f"{float(rule.get('cost_cf_fixed') or 0):g}")
        mp_unit_var = tk.StringVar(value=f"{float(rule.get('cost_mp_unit') or 0):g}")
        mo_unit_var = tk.StringVar(value=f"{float(rule.get('cost_mo_unit') or 0):g}")
        cf_unit_var = tk.StringVar(value=f"{float(rule.get('cost_cf_unit') or 0):g}")
        
        sale_price_var = tk.StringVar(value="100")
        quantity_var = tk.StringVar(value="1")
        hours_var = tk.StringVar(value="1")
        surface_var = tk.StringVar(value="1")
        total_var = tk.StringVar(value="$0.00")
        profit_var = tk.StringVar(value="$0.00")
        margin_var = tk.StringVar(value="0.00%")
        markup_var = tk.StringVar(value="0.00%")
        recommended_price_var = tk.StringVar(value="—")
        status_var = tk.StringVar(value="Sin datos")
        rule_summary_var = tk.StringVar(value="Sin nombre")
        product_summary_var = tk.StringVar(value="General")
        condition_summary_var = tk.StringVar(value="Siempre")
        rule_status_text_var = tk.StringVar(value="Sin datos")
        component_tree = None
        stats_tree = None

        def _parse_number(raw, default=0.0):
            text = str(raw or "").strip().replace(",", ".")
            if not text:
                return default
            try:
                return float(text)
            except (TypeError, ValueError):
                return None

        def _build_rule_from_form() -> CostRule:
            rule_obj = CostRule(name=name_var.get().strip(), product_type=product_var.get().strip(), minimum_margin=0.0, active=True)

            def _add_component(label: str, code: str, mode: str, percent_var: tk.StringVar, fixed_var: tk.StringVar, unit_var: tk.StringVar):
                if mode == "percent":
                    value = _parse_number(percent_var.get(), 0.0)
                    value_type = "percentage"
                elif mode == "fixed":
                    value = _parse_number(fixed_var.get(), 0.0)
                    value_type = "fixed"
                elif mode == "per_unit":
                    value = _parse_number(unit_var.get(), 0.0)
                    value_type = "per_unit"
                elif mode == "per_hour":
                    value = _parse_number(unit_var.get(), 0.0)
                    value_type = "per_hour"
                else:
                    value = _parse_number(unit_var.get(), 0.0)
                    value_type = "per_square_meter"

                if value is None:
                    value = 0.0
                component = CostComponent(name=label, code=code, value_type=value_type, value=value)
                rule_obj.add_component(component)

            _add_component("Materia Prima", "mp", mp_mode_internal.get(), mp_percent_var, mp_fixed_var, mp_unit_var)
            _add_component("Mano de Obra", "mo", mo_mode_internal.get(), mo_percent_var, mo_fixed_var, mo_unit_var)
            _add_component("Carga Fabril", "cf", cf_mode_internal.get(), cf_percent_var, cf_fixed_var, cf_unit_var)
            return rule_obj

        def _set_summary_values(cost_total, gross_profit, margin_percentage, markup_percentage, status_text, recommended_price):
            total_var.set(f"${float(cost_total):,.2f}" if cost_total is not None else "—")
            profit_var.set(f"${float(gross_profit):,.2f}" if gross_profit is not None else "—")
            margin_var.set(f"{float(margin_percentage):.2f}%" if margin_percentage is not None else "—")
            markup_var.set(f"{float(markup_percentage):.2f}%" if markup_percentage is not None else "—")
            recommended_price_var.set(f"${float(recommended_price):,.2f}" if recommended_price is not None else "—")
            status_var.set(status_text)
            rule_status_text_var.set(status_text)

        def _format_component_display(component):
            if component.value_type == "percentage":
                return f"{component.value:g}%"
            if component.value_type == "fixed":
                return f"${component.value:g}"
            if component.value_type == "per_unit":
                return f"${component.value:g}/u"
            if component.value_type == "per_hour":
                return f"${component.value:g}/h"
            if component.value_type == "per_square_meter":
                return f"${component.value:g}/m²"
            return str(component.value)

        def _update_component_tables(rule, sale_price, quantity, hours, surface):
            nonlocal component_tree, stats_tree
            for table in (component_tree, stats_tree):
                if table is None or not table.winfo_exists():
                    continue
                table.delete(*table.get_children())
                for component in rule.components:
                    amount = component.evaluate(
                        sale_price=sale_price,
                        quantity=max(1, int(quantity)),
                        hours=hours,
                        surface=surface,
                    )
                    table.insert("", "end", values=(
                        component.name or component.code or "Componente",
                        component.value_type,
                        _format_component_display(component),
                        _unit_label(component.value_type),
                        f"${amount:,.2f}",
                    ))

        def _recalc(*_):
            sale_price = _parse_number(sale_price_var.get(), 0.0)
            quantity = _parse_number(quantity_var.get(), 1.0)
            hours = _parse_number(hours_var.get(), 0.0)
            surface = _parse_number(surface_var.get(), 0.0)

            if sale_price is None or quantity is None or hours is None or surface is None:
                _set_summary_values(None, None, None, None, "Datos incompletos", None)
                return

            rule = _build_rule_from_form()
            validation_errors = CostRuleValidator.validate(rule)
            if validation_errors:
                _set_summary_values(None, None, None, None, "Datos incompletos", None)
                return

            try:
                metrics = CostCalculator.calculate(
                    rule,
                    sale_price=sale_price,
                    quantity=max(1, int(quantity)),
                    hours=hours,
                    surface=surface,
                )
            except Exception as exc:
                print(f"[cost_rule_editor] Error inesperado en el simulador: {exc}")
                _set_summary_values(None, None, None, None, "Datos incompletos", None)
                rule_summary_var.set(name_var.get().strip() or "Sin nombre")
                product_summary_var.set(product_var.get().strip() or "General")
                condition_summary_var.set(condition_var.get().strip() or "Siempre")
                if component_tree is not None and component_tree.winfo_exists():
                    component_tree.delete(*component_tree.get_children())
                if stats_tree is not None and stats_tree.winfo_exists():
                    stats_tree.delete(*stats_tree.get_children())
                return

            recommended_price = CostCalculator.recommended_price(
                rule,
                quantity=max(1, int(quantity)),
                hours=hours,
                surface=surface,
                target_margin=20.0,
            )
            markup_value = None if metrics.profitability_status == "no_costs" else float(metrics.markup_percentage)
            status_text = {
                "profitable": "Rentable",
                "margin_low": "Margen bajo",
                "loss": "Pérdida",
                "no_costs": "Sin costos configurados",
            }.get(metrics.profitability_status, "Datos incompletos")
            _set_summary_values(
                float(metrics.cost_total),
                float(metrics.gross_profit),
                float(metrics.margin_percentage),
                markup_value,
                status_text,
                recommended_price if metrics.profitability_status != "no_costs" else None,
            )
            rule_summary_var.set(name_var.get().strip() or "Sin nombre")
            product_summary_var.set(product_var.get().strip() or "General")
            condition_summary_var.set(condition_var.get().strip() or "Siempre")
            _update_component_tables(rule, sale_price, quantity, hours, surface)

        for var in (name_var, product_var, mp_percent_var, mo_percent_var, cf_percent_var, mp_fixed_var, mo_fixed_var, cf_fixed_var, mp_unit_var, mo_unit_var, cf_unit_var, mp_mode_var, mo_mode_var, cf_mode_var, sale_price_var, quantity_var, hours_var, surface_var):
            var.trace_add("write", _recalc)
        
        # Header del editor
        header = tk.Frame(editor, background=COLORS.panel,
                         highlightthickness=1, highlightbackground=COLORS.border)
        header.pack(fill="x", padx=16, pady=(16, 12))
        tk.Label(header, text="MODELO DE COSTOS",
                background=COLORS.panel, foreground=COLORS.text,
                font=(IDENTITY_FONT, 14, "bold")
                ).pack(anchor="w", padx=14, pady=(10, 2))
        tk.Label(header, text="Definí el modelo y dejá que las reglas de precio solo elijan la estrategia comercial.",
                background=COLORS.panel, foreground=COLORS.muted,
                font=(UI_FONT, 9)
                ).pack(anchor="w", padx=14, pady=(0, 10))

        notebook = ttk.Notebook(editor)
        notebook.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        definition_tab = ttk.Frame(notebook)
        simulator_tab = ttk.Frame(notebook)
        stats_tab = ttk.Frame(notebook)

        notebook.add(definition_tab, text="Definición")
        notebook.add(simulator_tab, text="Simulador")
        notebook.add(stats_tab, text="Estadísticas")

        definition_canvas = tk.Canvas(definition_tab, background=COLORS.background, highlightthickness=0)
        definition_scrollbar = ttk.Scrollbar(definition_tab, orient="vertical", command=definition_canvas.yview)
        definition_canvas.configure(yscrollcommand=definition_scrollbar.set)
        definition_form = tk.Frame(definition_canvas, background=COLORS.background)
        definition_canvas.create_window((0, 0), window=definition_form, anchor="nw")
        definition_form.bind("<Configure>", lambda e: definition_canvas.configure(scrollregion=definition_canvas.bbox("all")))
        definition_canvas.pack(side="left", fill="both", expand=True)
        definition_scrollbar.pack(side="right", fill="y")

        definition_form.columnconfigure(0, weight=1)
        row = 0

        name_frame = tk.Frame(definition_form, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
        name_frame.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        name_frame.columnconfigure(0, weight=1)
        row += 1

        tk.Label(name_frame, text="NOMBRE DE LA REGLA", background=COLORS.panel_elevated, foreground=COLORS.muted, font=(IDENTITY_FONT, 9, "bold")).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 6))
        name_entry = ttk.Entry(name_frame, textvariable=name_var, font=(UI_FONT, 11))
        name_entry.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))
        name_entry.focus()

        product_frame = tk.Frame(definition_form, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
        product_frame.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        product_frame.columnconfigure(0, weight=1)
        row += 1

        tk.Label(product_frame, text="PRODUCTO O CATEGORÍA (opcional)", background=COLORS.panel_elevated, foreground=COLORS.muted, font=(IDENTITY_FONT, 9, "bold")).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 6))
        ttk.Entry(product_frame, textvariable=product_var, font=(UI_FONT, 10)).grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))

        cond_frame = tk.Frame(definition_form, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
        cond_frame.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        cond_frame.columnconfigure(0, weight=1)
        row += 1

        tk.Label(cond_frame, text="CONDICIÓN (opcional)", background=COLORS.panel_elevated, foreground=COLORS.muted, font=(IDENTITY_FONT, 9, "bold")).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 6))
        ttk.Entry(cond_frame, textvariable=condition_var, font=(UI_FONT, 10)).grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 4))
        tk.Label(cond_frame, text="Ejemplos: budget > 5000  •  quantity >= 100  •  Dejar vacío para aplicar siempre", background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 8), wraplength=550).grid(row=2, column=0, sticky="w", padx=14, pady=(0, 12))

        costs_frame = tk.Frame(definition_form, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
        costs_frame.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        costs_frame.columnconfigure(1, weight=1)
        row += 1

        tk.Label(costs_frame, text="ESTRUCTURA DE COSTOS", background=COLORS.panel_elevated, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 10, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(12, 4))
        tk.Label(costs_frame, text="Definí cómo se calcula cada componente del costo.", background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 9), wraplength=550).grid(row=1, column=0, columnspan=3, sticky="w", padx=14, pady=(0, 14))

        def _unit_label(mode: str) -> str:
            return {
                "percentage": "%",
                "fixed": "$",
                "per_unit": "$/u",
                "per_hour": "$/h",
                "per_square_meter": "$/m²",
            }.get(mode, "%")

        def _cost_row(label, desc, display_var, internal_var, percent_var, fixed_var, unit_var, r, color="#4E8AC7"):
            label_frame = tk.Frame(costs_frame, background=COLORS.panel_elevated)
            label_frame.grid(row=r, column=0, sticky="w", padx=14, pady=8)
            tk.Label(label_frame, text=label, background=COLORS.panel_elevated, foreground=color, font=(IDENTITY_FONT, 11, "bold")).pack(anchor="w")
            tk.Label(label_frame, text=desc, background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 9)).pack(anchor="w", pady=(2, 0))

            controls_frame = tk.Frame(costs_frame, background=COLORS.panel_elevated)
            controls_frame.grid(row=r, column=2, sticky="e", padx=14, pady=8)
            mode_cb = ttk.Combobox(controls_frame, textvariable=display_var, values=tuple(MODE_LABELS.values()), width=12, state="readonly")
            mode_cb.pack(side="left")
            percent_entry = ttk.Entry(controls_frame, textvariable=percent_var, width=8, font=(UI_FONT, 11), justify="right")
            fixed_entry = ttk.Entry(controls_frame, textvariable=fixed_var, width=8, font=(UI_FONT, 11), justify="right")
            unit_entry = ttk.Entry(controls_frame, textvariable=unit_var, width=8, font=(UI_FONT, 11), justify="right")

            def _refresh_visibility(*_):
                mode = internal_var.get()
                percent_entry.pack_forget()
                fixed_entry.pack_forget()
                unit_entry.pack_forget()
                if mode == "percent":
                    percent_entry.pack(side="left", padx=(8, 0))
                    tk.Label(controls_frame, text="%", background=COLORS.panel_elevated, foreground=COLORS.text, font=(UI_FONT, 11)).pack(side="left", padx=(4, 0))
                elif mode == "fixed":
                    fixed_entry.pack(side="left", padx=(8, 0))
                    tk.Label(controls_frame, text="$", background=COLORS.panel_elevated, foreground=COLORS.text, font=(UI_FONT, 11)).pack(side="left", padx=(4, 0))
                else:
                    unit_entry.pack(side="left", padx=(8, 0))
                    tk.Label(controls_frame, text=_unit_label(mode), background=COLORS.panel_elevated, foreground=COLORS.text, font=(UI_FONT, 10)).pack(side="left", padx=(4, 0))

            def _sync_mode(*_):
                internal_var.set(MODE_KEYS.get(display_var.get(), "percent"))

            display_var.trace_add("write", _sync_mode)
            internal_var.trace_add("write", _refresh_visibility)
            _sync_mode()

        _cost_row("M.P", "Materia Prima", mp_mode_var, mp_mode_internal, mp_percent_var, mp_fixed_var, mp_unit_var, 2)
        _cost_row("M.O", "Mano de Obra", mo_mode_var, mo_mode_internal, mo_percent_var, mo_fixed_var, mo_unit_var, 3)
        _cost_row("C.F", "Carga Fabril", cf_mode_var, cf_mode_internal, cf_percent_var, cf_fixed_var, cf_unit_var, 4)

        tk.Frame(costs_frame, height=1, background=COLORS.border).grid(row=5, column=0, columnspan=3, sticky="ew", padx=14, pady=14)

        component_tree = ttk.Treeview(definition_tab, columns=("name", "mode", "value", "unit", "amount"), show="headings", height=8)
        component_tree.heading("name", text="Componente")
        component_tree.heading("mode", text="Modo")
        component_tree.heading("value", text="Valor")
        component_tree.heading("unit", text="Unidad")
        component_tree.heading("amount", text="Importe")
        component_tree.column("name", width=180, anchor="w")
        component_tree.column("mode", width=140, anchor="w")
        component_tree.column("value", width=120, anchor="center")
        component_tree.column("unit", width=100, anchor="center")
        component_tree.column("amount", width=140, anchor="e")
        component_tree.pack(fill="both", expand=True)
        ttk.Button(definition_tab, text="Actualizar vista", command=_recalc, style="Secondary.TButton").pack(anchor="e", padx=16, pady=(10, 0))

        simulator_panel = tk.Frame(simulator_tab, background=COLORS.background)
        simulator_panel.pack(fill="both", expand=True, padx=16, pady=16)
        summary_inner = tk.Frame(simulator_panel, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
        summary_inner.pack(fill="both", expand=True)
        summary_inner.columnconfigure(1, weight=1)

        tk.Label(summary_inner, text="SIMULADOR DE RENTABILIDAD", background=COLORS.panel_elevated, foreground=COLORS.wine_active, font=(IDENTITY_FONT, 10, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 12))
        inputs = [("Precio venta", sale_price_var), ("Cantidad", quantity_var)]
        for idx, (label, var) in enumerate(inputs):
            tk.Label(summary_inner, text=label, background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 10)).grid(row=idx + 1, column=0, sticky="w", padx=14, pady=(0, 6))
            ttk.Entry(summary_inner, textvariable=var, width=14, justify="right").grid(row=idx + 1, column=1, sticky="e", padx=14, pady=(0, 6))

        hours_row = 3
        surface_row = 4
        hours_label = tk.Label(summary_inner, text="Horas", background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 10))
        hours_entry = ttk.Entry(summary_inner, textvariable=hours_var, width=14, justify="right")
        surface_label = tk.Label(summary_inner, text="Superficie", background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 10))
        surface_entry = ttk.Entry(summary_inner, textvariable=surface_var, width=14, justify="right")

        def _refresh_simulator_fields(*_):
            has_hour_component = any(mode == "per_hour" for mode in (mp_mode_internal.get(), mo_mode_internal.get(), cf_mode_internal.get()))
            has_surface_component = any(mode == "per_square_meter" for mode in (mp_mode_internal.get(), mo_mode_internal.get(), cf_mode_internal.get()))
            if has_hour_component:
                hours_label.grid(row=hours_row, column=0, sticky="w", padx=14, pady=(0, 6))
                hours_entry.grid(row=hours_row, column=1, sticky="e", padx=14, pady=(0, 6))
            else:
                hours_label.grid_remove()
                hours_entry.grid_remove()
            if has_surface_component:
                surface_label.grid(row=surface_row, column=0, sticky="w", padx=14, pady=(0, 8))
                surface_entry.grid(row=surface_row, column=1, sticky="e", padx=14, pady=(0, 8))
            else:
                surface_label.grid_remove()
                surface_entry.grid_remove()

        for var in (mp_mode_internal, mo_mode_internal, cf_mode_internal):
            var.trace_add("write", _refresh_simulator_fields)
        _refresh_simulator_fields()

        tk.Label(summary_inner, text="Costo total", background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 10)).grid(row=5, column=0, sticky="w", padx=14, pady=(8, 6))
        tk.Label(summary_inner, textvariable=total_var, background=COLORS.panel_elevated, foreground="#C98A27", font=(IDENTITY_FONT, 15, "bold")).grid(row=5, column=1, sticky="e", padx=14, pady=(8, 6))
        tk.Label(summary_inner, text="Ganancia bruta", background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 10)).grid(row=6, column=0, sticky="w", padx=14, pady=(0, 6))
        tk.Label(summary_inner, textvariable=profit_var, background=COLORS.panel_elevated, foreground="#2D9B66", font=(IDENTITY_FONT, 12, "bold")).grid(row=6, column=1, sticky="e", padx=14, pady=(0, 6))
        tk.Label(summary_inner, text="Margen", background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 10)).grid(row=7, column=0, sticky="w", padx=14, pady=(0, 6))
        tk.Label(summary_inner, textvariable=margin_var, background=COLORS.panel_elevated, foreground="#2D9B66", font=(IDENTITY_FONT, 12, "bold")).grid(row=7, column=1, sticky="e", padx=14, pady=(0, 6))
        tk.Label(summary_inner, text="Markup", background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 10)).grid(row=8, column=0, sticky="w", padx=14, pady=(0, 6))
        tk.Label(summary_inner, textvariable=markup_var, background=COLORS.panel_elevated, foreground="#4E8AC7", font=(IDENTITY_FONT, 12, "bold")).grid(row=8, column=1, sticky="e", padx=14, pady=(0, 6))
        tk.Label(summary_inner, text="Precio recomendado", background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 10)).grid(row=9, column=0, sticky="w", padx=14, pady=(0, 6))
        tk.Label(summary_inner, textvariable=recommended_price_var, background=COLORS.panel_elevated, foreground="#4E8AC7", font=(IDENTITY_FONT, 12, "bold")).grid(row=9, column=1, sticky="e", padx=14, pady=(0, 6))
        tk.Label(summary_inner, text="Estado", background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 10)).grid(row=10, column=0, sticky="w", padx=14, pady=(0, 10))
        tk.Label(summary_inner, textvariable=status_var, background=COLORS.panel_elevated, foreground="#C98A27", font=(IDENTITY_FONT, 12, "bold")).grid(row=10, column=1, sticky="e", padx=14, pady=(0, 10))

        stats_panel = tk.Frame(stats_tab, background=COLORS.background)
        stats_panel.pack(fill="both", expand=True, padx=16, pady=16)
        tk.Label(stats_panel, text="ESTADÍSTICAS DE RENTABILIDAD", background=COLORS.background, foreground=COLORS.text, font=(IDENTITY_FONT, 12, "bold")).pack(anchor="w")
        tk.Label(stats_panel, text="Mide el impacto de la regla actual con cifras reales y recomendaciones de precio.", background=COLORS.background, foreground=COLORS.muted, font=(UI_FONT, 10), wraplength=700).pack(anchor="w", pady=(6, 12))

        summary_frame = tk.Frame(stats_panel, background=COLORS.panel_elevated, highlightthickness=1, highlightbackground=COLORS.border)
        summary_frame.pack(fill="x", pady=(0, 14), padx=(0, 0))
        for idx, (label_text, var) in enumerate((
            ("Regla", rule_summary_var),
            ("Producto", product_summary_var),
            ("Condición", condition_summary_var),
            ("Estado", rule_status_text_var),
            ("Costo total", total_var),
            ("Margen", margin_var),
            ("Markup", markup_var),
            ("Precio recomendado", recommended_price_var),
        )):
            tk.Label(summary_frame, text=label_text + ":", background=COLORS.panel_elevated, foreground=COLORS.muted, font=(UI_FONT, 9, "bold")).grid(row=idx, column=0, sticky="w", padx=14, pady=(10 if idx == 0 else 3, 0))
            tk.Label(summary_frame, textvariable=var, background=COLORS.panel_elevated, foreground=COLORS.text, font=(UI_FONT, 9)).grid(row=idx, column=1, sticky="w", padx=(6, 14), pady=(10 if idx == 0 else 3, 0))

        stats_tree = ttk.Treeview(stats_panel, columns=("name", "mode", "value", "unit", "amount"), show="headings", height=8)
        stats_tree.heading("name", text="Componente")
        stats_tree.heading("mode", text="Modo")
        stats_tree.heading("value", text="Valor")
        stats_tree.heading("unit", text="Unidad")
        stats_tree.heading("amount", text="Importe")
        stats_tree.column("name", width=180, anchor="w")
        stats_tree.column("mode", width=140, anchor="w")
        stats_tree.column("value", width=120, anchor="center")
        stats_tree.column("unit", width=100, anchor="center")
        stats_tree.column("amount", width=140, anchor="e")
        stats_tree.pack(fill="both", expand=True, pady=(0, 0))

        _recalc()

        btn_frame = tk.Frame(editor, background=COLORS.background)
        btn_frame.pack(fill="x", padx=16, pady=(0, 16))
        
        def _save():
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning("Costos", "Ingresá un nombre para la regla.", parent=editor)
                name_entry.focus()
                return
            try:
                rule = _build_rule_from_form()
                validation_errors = CostRuleValidator.validate(rule)
                if validation_errors:
                    messagebox.showwarning("Costos", "\n".join(validation_errors), parent=editor)
                    return

                if is_new:
                    self.database.save_cost_rule(
                        name=name,
                        condition=condition_var.get().strip(),
                        cost_mp_mode=mp_mode_internal.get(),
                        cost_mp_percent=float(mp_percent_var.get().replace(",", ".") or 0) if mp_mode_internal.get() == "percent" else 0,
                        cost_mp_fixed=float(mp_fixed_var.get().replace(",", ".") or 0),
                        cost_mp_unit=float(mp_unit_var.get().replace(",", ".") or 0),
                        cost_mo_mode=mo_mode_internal.get(),
                        cost_mo_percent=float(mo_percent_var.get().replace(",", ".") or 0) if mo_mode_internal.get() == "percent" else 0,
                        cost_mo_fixed=float(mo_fixed_var.get().replace(",", ".") or 0),
                        cost_mo_unit=float(mo_unit_var.get().replace(",", ".") or 0),
                        cost_cf_mode=cf_mode_internal.get(),
                        cost_cf_percent=float(cf_percent_var.get().replace(",", ".") or 0) if cf_mode_internal.get() == "percent" else 0,
                        cost_cf_fixed=float(cf_fixed_var.get().replace(",", ".") or 0),
                        cost_cf_unit=float(cf_unit_var.get().replace(",", ".") or 0),
                    )
                else:
                    updated = self.database.update_cost_rule(
                        int(rule["id"]),
                        name=name,
                        condition=condition_var.get().strip(),
                        cost_mp_mode=mp_mode_internal.get(),
                        cost_mp_percent=float(mp_percent_var.get().replace(",", ".") or 0) if mp_mode_internal.get() == "percent" else 0,
                        cost_mp_fixed=float(mp_fixed_var.get().replace(",", ".") or 0),
                        cost_mp_unit=float(mp_unit_var.get().replace(",", ".") or 0),
                        cost_mo_mode=mo_mode_internal.get(),
                        cost_mo_percent=float(mo_percent_var.get().replace(",", ".") or 0) if mo_mode_internal.get() == "percent" else 0,
                        cost_mo_fixed=float(mo_fixed_var.get().replace(",", ".") or 0),
                        cost_mo_unit=float(mo_unit_var.get().replace(",", ".") or 0),
                        cost_cf_mode=cf_mode_internal.get(),
                        cost_cf_percent=float(cf_percent_var.get().replace(",", ".") or 0) if cf_mode_internal.get() == "percent" else 0,
                        cost_cf_fixed=float(cf_fixed_var.get().replace(",", ".") or 0),
                        cost_cf_unit=float(cf_unit_var.get().replace(",", ".") or 0),
                    )
                    if not updated:
                        messagebox.showerror("Costos", "No se pudo actualizar la regla.", parent=editor)
                        return
            except ValueError:
                messagebox.showwarning("Costos", "Revisá que los porcentajes sean valores numéricos válidos.", parent=editor)
                return
            
            editor.destroy()
            # Refrescar tabla principal
            tree.delete(*tree.get_children())
            for r in self.database.all_cost_rules():
                model = self.database.cost_model(r["id"]) if r.get("id") else None
                summary = "Sin modelo asociado" if not model else (model.get("description") or "Modelo de costos")
                tree.insert("", "end", iid=str(r["id"]), values=(
                    r.get("name") or "Sin nombre",
                    r.get("condition") or "Siempre",
                    model.get("name") if model else "—",
                    summary,
                ))
            if not is_new:
                tree.selection_set(str(rule["id"]))
                tree.focus(str(rule["id"]))
        
        ttk.Button(btn_frame, text="Cancelar", command=editor.destroy,
                   style="Secondary.TButton").pack(side="right")
        ttk.Button(btn_frame, text="Guardar modelo" if is_new else "Guardar cambios",
                   command=_save, style="Primary.TButton").pack(side="right", padx=(0, 8))

    def _open_variable_cost_editor(self, parent_dialog, var_tree, model_data: dict | None):
        """Editor de modelo de costo variable con tabla de componentes editable."""
        is_new = model_data is None
        model_data = model_data or {}

        editor = tk.Toplevel(parent_dialog)
        editor.title("Nuevo modelo de costo variable" if is_new else "Editar modelo de costo variable")
        editor.configure(background=COLORS.background)
        editor.transient(parent_dialog)
        editor.grab_set()
        editor.geometry("1050x700")
        editor.minsize(900, 600)

        CALC_MODE_LABELS = {
            "per_unit": "Por unidad",
            "per_sheet": "Por hoja",
            "per_plancha": "Por plancha",
            "per_meter": "Por metro",
            "per_sqm": "Por metro cuadrado",
            "per_ml": "Por mililitro",
            "per_gram": "Por gramo",
            "per_print": "Por impresión",
            "per_minute": "Por minuto",
            "per_hour": "Por hora",
            "fixed": "Fijo por producción",
            "percentage": "Porcentaje",
        }
        CALC_MODE_KEYS = {label: key for key, label in CALC_MODE_LABELS.items()}
        PERCENTAGE_BASES = ["Precio de venta", "Materia prima", "Subtotal seleccionado", "Total de otros componentes"]

        name_var = tk.StringVar(value=str(model_data.get("name", "")))
        product_var = tk.StringVar(value=str(model_data.get("product_name", "")))
        category_var = tk.StringVar(value=str(model_data.get("category", "")))
        active_var = tk.BooleanVar(value=bool(model_data.get("active", 1)))

        sale_price_var = tk.StringVar(value="0")
        total_cost_var = tk.StringVar(value="$0.00")
        margin_var = tk.StringVar(value="$0.00")
        margin_pct_var = tk.StringVar(value="0.00%")

        component_rows: list[dict] = []

        def _load_existing_components():
            nonlocal component_rows
            if model_data and model_data.get("id"):
                comps = self.database.variable_cost_model_components(int(model_data["id"]))
                component_rows = []
                for c in comps:
                    component_rows.append({
                        "id": c.get("id"),
                        "name": str(c.get("name") or ""),
                        "category": str(c.get("category") or ""),
                        "origin": str(c.get("origin") or "manual"),
                        "source_id": c.get("source_id"),
                        "calc_mode": str(c.get("calc_mode") or "per_unit"),
                        "quantity": float(c.get("quantity") or 0),
                        "unit_value": float(c.get("unit_value") or 0),
                        "waste_pct": float(c.get("waste_pct") or 0),
                        "unit": str(c.get("unit") or ""),
                        "percentage_base": str(c.get("percentage_base") or ""),
                        "active": bool(c.get("active", 1)),
                    })
            else:
                component_rows = []

        _load_existing_components()

        header = tk.Frame(editor, background=COLORS.panel,
                         highlightthickness=1, highlightbackground=COLORS.border)
        header.pack(fill="x", padx=16, pady=(16, 12))
        tk.Label(header, text="MODELO DE COSTO VARIABLE",
                background=COLORS.panel, foreground=COLORS.text,
                font=(IDENTITY_FONT, 14, "bold")
                ).pack(anchor="w", padx=14, pady=(10, 2))
        tk.Label(header, text="Definí los componentes variables que componen el costo unitario de cada producto.",
                background=COLORS.panel, foreground=COLORS.muted,
                font=(UI_FONT, 9)
                ).pack(anchor="w", padx=14, pady=(0, 4))
        tk.Label(header, text="Los costos fijos se administran por separado y no se configuran en este modelo.",
                background=COLORS.panel, foreground=COLORS.warning,
                font=(UI_FONT, 9, "italic")
                ).pack(anchor="w", padx=14, pady=(0, 10))

        editor_notebook = ttk.Notebook(editor)
        editor_notebook.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        definition_tab = ttk.Frame(editor_notebook)
        editor_notebook.add(definition_tab, text="  Información general  ")
        editor_notebook.add(ttk.Frame(editor_notebook), text="  Componentes  ")
        components_tab = editor_notebook.children[list(editor_notebook.children.keys())[-1]]

        # ── Tab: Información general ────────────────────────────────────────

        info_frame = tk.Frame(definition_tab, background=COLORS.panel,
                             highlightthickness=1, highlightbackground=COLORS.border)
        info_frame.pack(fill="x", padx=0, pady=(0, 8))
        info_frame.columnconfigure(1, weight=1)

        tk.Label(info_frame, text="NOMBRE DEL MODELO", background=COLORS.panel,
                foreground=COLORS.muted, font=(IDENTITY_FONT, 9, "bold")).grid(
                row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 4))
        ttk.Entry(info_frame, textvariable=name_var, font=(UI_FONT, 11)).grid(
                row=1, column=0, columnspan=2, sticky="ew", padx=14, pady=(0, 10))

        tk.Label(info_frame, text="PRODUCTO", background=COLORS.panel,
                foreground=COLORS.muted, font=(IDENTITY_FONT, 9, "bold")).grid(
                row=2, column=0, sticky="w", padx=14, pady=(4, 4))

        products = self.database.price_rule_products()
        product_names = [p["name"] for p in products]
        product_combo = ttk.Combobox(info_frame, textvariable=product_var,
                                    values=product_names, font=(UI_FONT, 10), width=30)
        product_combo.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 10))

        tk.Label(info_frame, text="CATEGORÍA", background=COLORS.panel,
                foreground=COLORS.muted, font=(IDENTITY_FONT, 9, "bold")).grid(
                row=2, column=1, sticky="w", padx=14, pady=(4, 4))
        ttk.Entry(info_frame, textvariable=category_var, font=(UI_FONT, 10)).grid(
                row=3, column=1, sticky="ew", padx=14, pady=(0, 10))

        tk.Checkbutton(info_frame, text="Activo", variable=active_var,
                      background=COLORS.panel, foreground=COLORS.text,
                      font=(UI_FONT, 10), selectcolor=COLORS.field).grid(
                row=4, column=0, sticky="w", padx=14, pady=(4, 12))

        # ── Tab: Componentes ────────────────────────────────────────────────

        comp_toolbar = tk.Frame(components_tab, background=COLORS.background)
        comp_toolbar.pack(fill="x", pady=(0, 6))

        comp_tree_frame = tk.Frame(components_tab, background=COLORS.panel,
                                  highlightthickness=1, highlightbackground=COLORS.border)
        comp_tree_frame.pack(fill="both", expand=True)

        _CCOLS = ("name", "category", "mode", "quantity", "unit_value", "waste", "unit", "amount")
        comp_tree = ttk.Treeview(comp_tree_frame, columns=_CCOLS, show="headings", selectmode="browse")

        _CCOL_DEFS = (
            ("name",       "Componente",       140, "w"),
            ("category",   "Origen/Base",      100, "w"),
            ("mode",       "Modo",             120, "center"),
            ("quantity",   "Cantidad",          70, "center"),
            ("unit_value", "Valor unitario",   100, "center"),
            ("waste",      "Desperdicio %",     80, "center"),
            ("unit",       "Unidad",            70, "center"),
            ("amount",     "Importe",          100, "e"),
        )

        for key, title, width, anchor in _CCOL_DEFS:
            comp_tree.heading(key, text=title)
            comp_tree.column(key, width=width, minwidth=max(40, width - 20), anchor=anchor)

        comp_scroll = ttk.Scrollbar(comp_tree_frame, orient="vertical", command=comp_tree.yview)
        comp_tree.configure(yscrollcommand=comp_scroll.set)
        comp_tree.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)
        comp_scroll.pack(side="right", fill="y", padx=(0, 1), pady=1)

        def _refresh_comp_tree():
            comp_tree.delete(*comp_tree.get_children())
            for idx, row in enumerate(component_rows):
                if not row.get("active", True):
                    continue
                mode_label = CALC_MODE_LABELS.get(row.get("calc_mode", ""), row.get("calc_mode", ""))
                qty = float(row.get("quantity") or 0)
                val = float(row.get("unit_value") or 0)
                waste = float(row.get("waste_pct") or 0)
                calc_mode = row.get("calc_mode", "per_unit")
                if calc_mode == "percentage":
                    amount = 0.0
                else:
                    raw = qty * val
                    if waste > 0:
                        raw *= (1.0 + waste / 100.0)
                    amount = round(raw, 2)
                row["amount"] = amount
                comp_tree.insert("", "end", iid=str(idx), values=(
                    row.get("name", ""),
                    row.get("category", ""),
                    mode_label,
                    f"{qty:g}",
                    f"${val:,.2f}",
                    f"{waste:g}%",
                    row.get("unit", ""),
                    f"${amount:,.2f}",
                ))
            _recalc_summary()

        def _recalc_summary():
            sale_price = 0.0
            try:
                sale_price = float(sale_price_var.get().replace(",", ".") or 0)
            except (ValueError, TypeError):
                pass
            total = sum(r.get("amount", 0) for r in component_rows if r.get("active", True))
            total_cost_var.set(f"${total:,.2f}")
            margin_val = sale_price - total
            margin_var.set(f"${margin_val:,.2f}")
            margin_pct = (margin_val / sale_price * 100) if sale_price > 0 else 0
            margin_pct_var.set(f"{margin_pct:.2f}%")

        def _add_component():
            component_rows.append({
                "name": "", "category": "", "origin": "manual",
                "source_id": None, "calc_mode": "per_unit",
                "quantity": 1.0, "unit_value": 0.0, "waste_pct": 0.0,
                "unit": "", "percentage_base": "", "active": True,
            })
            _refresh_comp_tree()
            new_idx = len(component_rows) - 1
            comp_tree.selection_set(str(new_idx))
            comp_tree.see(str(new_idx))
            _open_component_dialog(new_idx)

        def _edit_component(*_):
            selected = comp_tree.selection()
            if not selected:
                return
            _open_component_dialog(int(selected[0]))

        def _remove_component():
            selected = comp_tree.selection()
            if not selected:
                return
            idx = int(selected[0])
            if idx < len(component_rows):
                comp_name = component_rows[idx].get("name", "")
                if comp_name and not messagebox.askyesno("Eliminar componente",
                        f"¿Eliminar el componente «{comp_name}»?", parent=editor):
                    return
                elif not comp_name:
                    component_rows.pop(idx)
                    _refresh_comp_tree()
                    return
                component_rows.pop(idx)
                _refresh_comp_tree()

        def _move_component_up():
            selected = comp_tree.selection()
            if not selected:
                return
            idx = int(selected[0])
            if idx > 0:
                component_rows[idx], component_rows[idx - 1] = component_rows[idx - 1], component_rows[idx]
                _refresh_comp_tree()
                comp_tree.selection_set(str(idx - 1))

        def _move_component_down():
            selected = comp_tree.selection()
            if not selected:
                return
            idx = int(selected[0])
            if idx < len(component_rows) - 1:
                component_rows[idx], component_rows[idx + 1] = component_rows[idx + 1], component_rows[idx]
                _refresh_comp_tree()
                comp_tree.selection_set(str(idx + 1))

        def _open_component_dialog(comp_idx: int):
            comp = component_rows[comp_idx] if comp_idx < len(component_rows) else {}
            is_comp_new = not comp.get("name")

            dlg = tk.Toplevel(editor)
            dlg.title("Nuevo componente" if is_comp_new else f"Editar: {comp.get('name', '')}")
            dlg.configure(background=COLORS.background)
            dlg.transient(editor)
            dlg.grab_set()
            dlg.geometry("520x520")
            dlg.minsize(460, 480)

            c_name = tk.StringVar(value=comp.get("name", ""))
            c_category = tk.StringVar(value=comp.get("category", ""))
            c_mode = tk.StringVar(value=CALC_MODE_LABELS.get(comp.get("calc_mode", "per_unit"), "Por unidad"))
            c_quantity = tk.StringVar(value=f"{float(comp.get('quantity') or 0):g}")
            c_unit_value = tk.StringVar(value=f"{float(comp.get('unit_value') or 0):g}")
            c_waste = tk.StringVar(value=f"{float(comp.get('waste_pct') or 0):g}")
            c_unit = tk.StringVar(value=comp.get("unit", ""))
            c_pct_base = tk.StringVar(value=comp.get("percentage_base", "Precio de venta"))

            form = tk.Frame(dlg, background=COLORS.panel,
                           highlightthickness=1, highlightbackground=COLORS.border)
            form.pack(fill="both", expand=True, padx=16, pady=(16, 0))
            form.columnconfigure(1, weight=1)

            r = 0
            tk.Label(form, text="NOMBRE *", background=COLORS.panel, foreground=COLORS.muted,
                    font=(IDENTITY_FONT, 9, "bold")).grid(row=r, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 4))
            r += 1
            ttk.Entry(form, textvariable=c_name, font=(UI_FONT, 11)).grid(row=r, column=0, columnspan=2, sticky="ew", padx=14, pady=(0, 10))
            r += 1

            tk.Label(form, text="CATEGORÍA / ORIGEN", background=COLORS.panel, foreground=COLORS.muted,
                    font=(IDENTITY_FONT, 9, "bold")).grid(row=r, column=0, columnspan=2, sticky="w", padx=14, pady=(4, 4))
            r += 1
            ttk.Combobox(form, textvariable=c_category, font=(UI_FONT, 10),
                        values=["Materia prima", "Insumo", "Mano de obra", "Packaging", "Comisión", "Diseño", "Otro"],
                        state="readonly").grid(row=r, column=0, columnspan=2, sticky="ew", padx=14, pady=(0, 10))
            r += 1

            tk.Label(form, text="MODO DE CÁLCULO", background=COLORS.panel, foreground=COLORS.muted,
                    font=(IDENTITY_FONT, 9, "bold")).grid(row=r, column=0, columnspan=2, sticky="w", padx=14, pady=(4, 4))
            r += 1
            ttk.Combobox(form, textvariable=c_mode, font=(UI_FONT, 10),
                        values=tuple(CALC_MODE_LABELS.values()), state="readonly").grid(
                        row=r, column=0, columnspan=2, sticky="ew", padx=14, pady=(0, 10))
            r += 1

            quantity_frame = tk.Frame(form, background=COLORS.panel)
            quantity_frame.grid(row=r, column=0, columnspan=2, sticky="ew", padx=14, pady=(4, 4))
            quantity_frame.columnconfigure(1, weight=1)
            tk.Label(quantity_frame, text="CANTIDAD", background=COLORS.panel, foreground=COLORS.muted,
                    font=(IDENTITY_FONT, 9, "bold")).grid(row=0, column=0, sticky="w", pady=(4, 4))
            ttk.Entry(quantity_frame, textvariable=c_quantity, width=10, font=(UI_FONT, 10)).grid(row=0, column=1, sticky="e", pady=(4, 4))
            r += 1

            value_frame = tk.Frame(form, background=COLORS.panel)
            value_frame.grid(row=r, column=0, columnspan=2, sticky="ew", padx=14, pady=(4, 4))
            value_frame.columnconfigure(1, weight=1)
            tk.Label(value_frame, text="VALOR UNITARIO", background=COLORS.panel, foreground=COLORS.muted,
                    font=(IDENTITY_FONT, 9, "bold")).grid(row=0, column=0, sticky="w", pady=(4, 4))
            ttk.Entry(value_frame, textvariable=c_unit_value, width=10, font=(UI_FONT, 10)).grid(row=0, column=1, sticky="e", pady=(4, 4))
            r += 1

            waste_frame = tk.Frame(form, background=COLORS.panel)
            waste_frame.grid(row=r, column=0, columnspan=2, sticky="ew", padx=14, pady=(4, 4))
            waste_frame.columnconfigure(1, weight=1)
            tk.Label(waste_frame, text="DESPERDICIO %", background=COLORS.panel, foreground=COLORS.muted,
                    font=(IDENTITY_FONT, 9, "bold")).grid(row=0, column=0, sticky="w", pady=(4, 4))
            ttk.Entry(waste_frame, textvariable=c_waste, width=10, font=(UI_FONT, 10)).grid(row=0, column=1, sticky="e", pady=(4, 4))
            r += 1

            unit_frame = tk.Frame(form, background=COLORS.panel)
            unit_frame.grid(row=r, column=0, columnspan=2, sticky="ew", padx=14, pady=(4, 4))
            unit_frame.columnconfigure(1, weight=1)
            tk.Label(unit_frame, text="UNIDAD", background=COLORS.panel, foreground=COLORS.muted,
                    font=(IDENTITY_FONT, 9, "bold")).grid(row=0, column=0, sticky="w", pady=(4, 4))
            ttk.Combobox(unit_frame, textvariable=c_unit, font=(UI_FONT, 10),
                        values=["u", "hoja", "plancha", "m", "m²", "ml", "g", "imp", "min", "h", "fijo", "%"],
                        state="readonly", width=8).grid(row=0, column=1, sticky="e", pady=(4, 4))
            r += 1

            pct_frame = tk.Frame(form, background=COLORS.panel)
            pct_frame.grid(row=r, column=0, columnspan=2, sticky="ew", padx=14, pady=(4, 10))

            def _refresh_pct_visibility(*_):
                if c_mode.get() == "Porcentaje":
                    pct_frame.grid()
                else:
                    pct_frame.grid_remove()

            c_mode.trace_add("write", _refresh_pct_visibility)

            tk.Label(pct_frame, text="CALCULAR SOBRE", background=COLORS.panel, foreground=COLORS.muted,
                    font=(IDENTITY_FONT, 9, "bold")).grid(row=0, column=0, sticky="w", pady=(4, 4))
            ttk.Combobox(pct_frame, textvariable=c_pct_base, font=(UI_FONT, 10),
                        values=PERCENTAGE_BASES, state="readonly", width=24).grid(row=0, column=1, sticky="e", pady=(4, 4))
            _refresh_pct_visibility()

            btn_frame = tk.Frame(dlg, background=COLORS.background)
            btn_frame.pack(fill="x", padx=16, pady=(0, 16))

            def _save_comp():
                comp_name_val = c_name.get().strip()
                if not comp_name_val:
                    messagebox.showwarning("Componente", "El nombre del componente es obligatorio.", parent=dlg)
                    return
                try:
                    qty_val = float(c_quantity.get().replace(",", ".") or 0)
                    val_val = float(c_unit_value.get().replace(",", ".") or 0)
                    waste_val = float(c_waste.get().replace(",", ".") or 0)
                except (ValueError, TypeError):
                    messagebox.showwarning("Componente", "Ingresá valores numéricos válidos.", parent=dlg)
                    return
                if qty_val < 0:
                    messagebox.showwarning("Componente", "La cantidad no puede ser negativa.", parent=dlg)
                    return
                if val_val < 0:
                    messagebox.showwarning("Componente", "El valor unitario no puede ser negativo.", parent=dlg)
                    return
                if waste_val < 0 or waste_val > 100:
                    messagebox.showwarning("Componente", "El desperdicio debe estar entre 0% y 100%.", parent=dlg)
                    return

                component_rows[comp_idx] = {
                    "name": comp_name_val,
                    "category": c_category.get().strip(),
                    "origin": comp.get("origin", "manual"),
                    "source_id": comp.get("source_id"),
                    "calc_mode": CALC_MODE_KEYS.get(c_mode.get(), "per_unit"),
                    "quantity": qty_val,
                    "unit_value": val_val,
                    "waste_pct": waste_val,
                    "unit": c_unit.get().strip(),
                    "percentage_base": c_pct_base.get().strip() if c_mode.get() == "Porcentaje" else "",
                    "active": True,
                }
                dlg.destroy()
                _refresh_comp_tree()

            ttk.Button(btn_frame, text="Cancelar", command=dlg.destroy,
                       style="Secondary.TButton").pack(side="right")
            ttk.Button(btn_frame, text="Guardar componente", command=_save_comp,
                       style="Primary.TButton").pack(side="right", padx=(0, 8))

        ttk.Button(comp_toolbar, text="Agregar componente", command=_add_component,
                   style="Primary.TButton").pack(side="left")
        ttk.Button(comp_toolbar, text="Editar", command=_edit_component,
                   style="Secondary.TButton").pack(side="left", padx=7)
        ttk.Button(comp_toolbar, text="Eliminar", command=_remove_component,
                   style="Danger.TButton").pack(side="left")
        ttk.Button(comp_toolbar, text="Subir", command=_move_component_up,
                   style="Secondary.TButton").pack(side="left", padx=(7, 0))
        ttk.Button(comp_toolbar, text="Bajar", command=_move_component_down,
                   style="Secondary.TButton").pack(side="left", padx=4)

        comp_tree.bind("<Double-1>", _edit_component)

        # ── Resumen inferior ────────────────────────────────────────────────

        summary_frame = tk.Frame(editor, background=COLORS.panel_elevated,
                                highlightthickness=1, highlightbackground=COLORS.border)
        summary_frame.pack(fill="x", padx=16, pady=(0, 4))
        summary_frame.columnconfigure(1, weight=1)
        summary_frame.columnconfigure(3, weight=1)
        summary_frame.columnconfigure(5, weight=1)

        tk.Label(summary_frame, text="Costo variable unitario:", background=COLORS.panel_elevated,
                foreground=COLORS.muted, font=(UI_FONT, 9)).grid(row=0, column=0, sticky="w", padx=14, pady=8)
        tk.Label(summary_frame, textvariable=total_cost_var, background=COLORS.panel_elevated,
                foreground="#C98A27", font=(IDENTITY_FONT, 12, "bold")).grid(row=0, column=1, sticky="w", padx=(6, 20), pady=8)

        tk.Label(summary_frame, text="Precio venta:", background=COLORS.panel_elevated,
                foreground=COLORS.muted, font=(UI_FONT, 9)).grid(row=0, column=2, sticky="w", pady=8)
        sale_price_entry = ttk.Entry(summary_frame, textvariable=sale_price_var, width=10, font=(UI_FONT, 10))
        sale_price_entry.grid(row=0, column=3, sticky="w", padx=(6, 20), pady=8)

        tk.Label(summary_frame, text="Margen:", background=COLORS.panel_elevated,
                foreground=COLORS.muted, font=(UI_FONT, 9)).grid(row=0, column=4, sticky="w", pady=8)
        tk.Label(summary_frame, textvariable=margin_var, background=COLORS.panel_elevated,
                foreground="#2D9B66", font=(IDENTITY_FONT, 11, "bold")).grid(row=0, column=5, sticky="w", padx=(6, 14), pady=8)

        tk.Label(summary_frame, textvariable=margin_pct_var, background=COLORS.panel_elevated,
                foreground="#2D9B66", font=(UI_FONT, 9)).grid(row=1, column=5, sticky="w", padx=(6, 14), pady=(0, 8))

        sale_price_var.trace_add("write", lambda *_: _recalc_summary())

        # ── Botones finales ─────────────────────────────────────────────────

        btn_frame = tk.Frame(editor, background=COLORS.background)
        btn_frame.pack(fill="x", padx=16, pady=(0, 16))

        def _save_model():
            m_name = name_var.get().strip()
            if not m_name:
                messagebox.showwarning("Costos Variables", "Ingresá un nombre para el modelo.", parent=editor)
                return
            m_product = product_var.get().strip()
            m_category = category_var.get().strip()
            if not m_product and not m_category:
                messagebox.showwarning("Costos Variables", "Asociá el modelo a un producto o categoría.", parent=editor)
                return
            if not any(c.get("active", True) for c in component_rows):
                messagebox.showwarning("Costos Variables", "Agregá al menos un componente activo.", parent=editor)
                return

            components_payload = []
            for idx, c in enumerate(component_rows):
                components_payload.append({
                    "name": c.get("name", ""),
                    "category": c.get("category", ""),
                    "origin": c.get("origin", "manual"),
                    "source_id": c.get("source_id"),
                    "calc_mode": c.get("calc_mode", "per_unit"),
                    "quantity": float(c.get("quantity") or 0),
                    "unit_value": float(c.get("unit_value") or 0),
                    "waste_pct": float(c.get("waste_pct") or 0),
                    "unit": c.get("unit", ""),
                    "percentage_base": c.get("percentage_base", ""),
                    "amount": float(c.get("amount") or 0),
                    "sort_order": idx,
                    "active": int(c.get("active", 1)),
                })

            if is_new:
                new_id = self.database.save_variable_cost_model(
                    name=m_name, product_name=m_product, category=m_category,
                    active=active_var.get(), components=components_payload,
                )
                if new_id:
                    editor.destroy()
            else:
                updated = self.database.update_variable_cost_model(
                    int(model_data["id"]), name=m_name, product_name=m_product,
                    category=m_category, active=active_var.get(),
                    components=components_payload,
                )
                if not updated:
                    messagebox.showerror("Costos Variables", "No se pudo actualizar.", parent=editor)
                    return
                editor.destroy()

        ttk.Button(btn_frame, text="Cancelar", command=editor.destroy,
                   style="Secondary.TButton").pack(side="right")
        ttk.Button(btn_frame, text="Guardar modelo" if is_new else "Guardar cambios",
                   command=_save_model, style="Primary.TButton").pack(side="right", padx=(0, 8))

        _refresh_comp_tree()

    def show_order_activity(self, order_id: int):
        events = self.database.order_events(order_id)
        dialog = tk.Toplevel(self)
        dialog.title(f"Actividad · Pedido #{order_id}")
        dialog.configure(background="#111314")
        dialog.transient(self)
        dialog.geometry("660x430")
        ttk.Label(dialog, text=f"ACTIVIDAD · PEDIDO #{order_id}", style="Tag.TLabel", padding=(16, 14, 16, 8)).pack(anchor="w")
        tree = ttk.Treeview(dialog, columns=("date", "type", "message"), show="headings")
        for key, title, width in (("date", "Fecha", 150), ("type", "Tipo", 115), ("message", "Detalle", 355)):
            tree.heading(key, text=title)
            tree.column(key, width=width, anchor="w")
        for event in events:
            tree.insert("", "end", values=(event.get("created_at", "").replace("T", " "), event.get("event_type", ""), event.get("message", "")))
        scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True, padx=(16, 0), pady=(0, 16))
        scrollbar.pack(side="right", fill="y", padx=(0, 16), pady=(0, 16))

    # Preparación segura con Photoshop ----------------------------------
    def configure_photoshop(self):
        current = self.database.app_setting("photoshop_path")
        path = filedialog.askopenfilename(
            title="Seleccionar Photoshop.exe",
            initialfile=Path(current).name if current else "Photoshop.exe",
            filetypes=[("Photoshop", "Photoshop.exe"), ("Ejecutables", "*.exe"), ("Todos los archivos", "*.*")],
        )
        if path:
            self.database.save_app_setting("photoshop_path", path)
            self.status.set("Photoshop configurado para copias de trabajo.")

    def _selected_order_designs(self, order_id: int) -> list[dict]:
        tab = self.order_tabs.get(order_id)
        if not tab:
            return []
        return [tab.order_design_state[index] for index in self._selected_order_design_indexes(tab) if index < len(tab.order_design_state)]

    def prepare_selected_design(self, order_id: int):
        designs = self._selected_order_designs(order_id)
        if len(designs) != 1:
            messagebox.showinfo("Preparación", "Elegí un único diseño del pedido para editarlo en Photoshop.", parent=self)
            return
        from app.preparation.photoshop import create_work_copy, open_work_copy

        original_path = str(designs[0].get("image_path", ""))
        if not original_path:
            return
        existing = self.database.latest_preparation(order_id, original_path)
        if existing and existing.get("status") in {"En edición", "Actualizado"} and Path(existing.get("work_path", "")).exists():
            preparation = self.database.refresh_preparation_file(existing["id"])
        else:
            try:
                work_path = create_work_copy(original_path, order_id)
                preparation_id = self.database.create_preparation(order_id, original_path, str(work_path), Path(original_path).stat().st_mtime)
                preparation = self.database.preparation(preparation_id)
            except (OSError, FileNotFoundError) as error:
                messagebox.showerror("Preparación", str(error), parent=self)
                return
        success, detail = open_work_copy(str(preparation["work_path"]), self.database.app_setting("photoshop_path"))
        if not success:
            messagebox.showerror("Photoshop", detail, parent=self)
            return
        self.refresh_preparation_summary(order_id)
        self.status.set(detail + " Al guardar, Doccione detectará la actualización.")

    def confirm_selected_preparation(self, order_id: int):
        designs = self._selected_order_designs(order_id)
        if len(designs) != 1:
            messagebox.showinfo("Preparación", "Elegí el diseño editado que querés confirmar.", parent=self)
            return
        preparation = self.database.latest_preparation(order_id, str(designs[0].get("image_path", "")))
        if not preparation:
            messagebox.showinfo("Preparación", "Ese diseño todavía no tiene una copia de trabajo.", parent=self)
            return
        preparation = self.database.refresh_preparation_file(preparation["id"])
        if not preparation or preparation.get("status") not in {"En edición", "Actualizado"}:
            messagebox.showwarning("Preparación", "La copia de trabajo no está disponible para confirmar.", parent=self)
            return
        if not messagebox.askyesno("Confirmar edición", "La copia editada reemplazará solo la versión del pedido. El original seguirá intacto.", parent=self):
            return
        try:
            self.database.confirm_preparation(int(preparation["id"]))
        except ValueError as error:
            messagebox.showerror("Preparación", str(error), parent=self)
            return
        tab = self.order_tabs.get(order_id)
        if tab:
            tab.order_dirty = False
            tab.order_design_state = self.database.order_designs(order_id)
            self.render_order_workspace(tab)
        self.refresh_orders()
        self.status.set("Copia editada confirmada para el pedido. El original no fue modificado.")

    def refresh_preparation_summary(self, order_id: int):
        tab = self.order_tabs.get(order_id)
        if not tab or not hasattr(tab, "preparation_summary"):
            return
        # Actualizar el resumen de diseños del pedido
        design_count = len(tab.order_design_state) if hasattr(tab, "order_design_state") else 0
        if design_count == 0:
            tab.preparation_summary.set("Agregá diseños al pedido desde la biblioteca.")
        else:
            confirmed = sum(1 for d in tab.order_design_state if d.get("status") == "Confirmado")
            tab.preparation_summary.set(f"{design_count} diseños en el pedido · {confirmed} confirmados.")

    def poll_order_preparations(self, order_id: int):
        tab = self.order_tabs.get(order_id)
        if not tab or not tab.winfo_exists():
            return
        changed = False
        for preparation in self.database.order_preparations(order_id):
            if preparation.get("status") == "En edición":
                before = preparation.get("status")
                updated = self.database.refresh_preparation_file(preparation["id"])
                changed = changed or bool(updated and updated.get("status") != before)
        self.refresh_preparation_summary(order_id)
        if changed:
            self.status.set("Se detectó un guardado de Photoshop. Revisá y confirmá la copia editada.")
        self.after(1800, lambda current=order_id: self.poll_order_preparations(current))

    def refresh_order_workspace(self, order_id: int):
        tab = self.order_tabs.get(order_id)
        if not tab or tab.order_dirty:
            return
        tab.order_design_state = self.database.order_designs(order_id)
        self.render_order_workspace(tab)

    def link_selection_to_order(self, order_id: int):
        if not self.selected_images:
            messagebox.showinfo("Pedido", "Seleccioná diseños en la pestaña Diseños antes de vincularlos.", parent=self)
            return
        if order_id not in self.order_tabs:
            self.open_order_workspace(order_id)
        tab = self.order_tabs.get(order_id)
        if not tab:
            return
        existing = {design.get("image_path") for design in tab.order_design_state}
        added = 0
        for image in self.selected_images.values():
            if image["path"] in existing:
                continue
            tab.order_design_state.append({
                "image_path": image["path"], "name": image.get("caption") or image.get("name") or Path(image["path"]).name,
                "tags": image.get("tags") or "", "category": image.get("category") or "", "quantity": 1,
                "size_cm": 5.9, "rotation": 0, "status": "Pendiente",
            })
            existing.add(image["path"])
            added += 1
        if not added:
            self.status.set("Los diseños seleccionados ya estaban vinculados al pedido.")
            return
        self.render_order_workspace(tab)
        self.queue_order_autosave(order_id)
        self.status.set(f"Se vincularon {added} diseños al pedido #{order_id}.")

    def show_add_designs_dialog(self, order_id: int):
        """Muestra una ventana para buscar y agregar diseños al pedido."""
        dialog = tk.Toplevel(self)
        dialog.title("Agregar diseños a la plancha")
        dialog.configure(background=COLORS.background)
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("1100x700")
        dialog.minsize(900, 600)
        
        # Header
        header = tk.Frame(dialog, background=COLORS.panel_elevated, 
                         highlightthickness=1, highlightbackground=COLORS.border)
        header.pack(fill="x", padx=16, pady=(16, 12))
        
        tk.Label(header, text="AGREGAR DISEÑOS", background=COLORS.panel_elevated,
                foreground=COLORS.text, font=(IDENTITY_FONT, 17, "bold")).pack(
                anchor="w", padx=16, pady=(12, 2))
        
        tk.Label(header, text="Buscá por información del diseño, no por el nombre técnico del archivo.",
                background=COLORS.panel_elevated, foreground=COLORS.muted,
                font=(UI_FONT, 10)).pack(anchor="w", padx=16, pady=(0, 12))
        
        # Contenedor principal
        content = tk.Frame(dialog, background=COLORS.background)
        content.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        
        # Panel izquierdo: búsqueda y filtros
        left_panel = tk.Frame(content, background=COLORS.background)
        left_panel.pack(side="left", fill="both", expand=True, padx=(0, 8))
        
        # Filtros de búsqueda
        filters = tk.Frame(left_panel, background=COLORS.panel_elevated,
                          highlightthickness=1, highlightbackground=COLORS.border)
        filters.pack(fill="x", pady=(0, 8))
        
        filters_content = tk.Frame(filters, background=COLORS.panel_elevated)
        filters_content.pack(fill="x", padx=14, pady=10)
        
        # Primera fila de filtros
        row1 = tk.Frame(filters_content, background=COLORS.panel_elevated)
        row1.pack(fill="x", pady=(0, 8))
        
        tk.Label(row1, text="BUSCAR", background=COLORS.panel_elevated,
                foreground=COLORS.muted, font=(IDENTITY_FONT, 9, "bold")).pack(side="left", padx=(0, 8))
        
        search_var = tk.StringVar()
        search_entry = ttk.Entry(row1, textvariable=search_var, width=30)
        search_entry.pack(side="left", padx=(0, 12))
        
        tk.Label(row1, text="BUSCAR POR", background=COLORS.panel_elevated,
                foreground=COLORS.muted, font=(IDENTITY_FONT, 9, "bold")).pack(side="left", padx=(0, 8))
        
        search_by_var = tk.StringVar(value="Todo")
        search_by_combo = ttk.Combobox(row1, textvariable=search_by_var,
                                      values=("Todo", "Etiqueta", "Colección", "Categoría"),
                                      state="readonly", width=15)
        search_by_combo.pack(side="left")
        
        # Segunda fila de filtros
        row2 = tk.Frame(filters_content, background=COLORS.panel_elevated)
        row2.pack(fill="x")
        
        tk.Label(row2, text="CATEGORÍA", background=COLORS.panel_elevated,
                foreground=COLORS.muted, font=(IDENTITY_FONT, 9, "bold")).pack(side="left", padx=(0, 8))
        
        category_var = tk.StringVar(value="Todas las categorías")
        categories_list = ["Todas las categorías"] + [cat for cat, _ in self.database.category_counts()]
        category_combo = ttk.Combobox(row2, textvariable=category_var,
                                     values=categories_list, state="readonly", width=22)
        category_combo.pack(side="left", padx=(0, 12))
        
        tk.Label(row2, text="COLECCIÓN", background=COLORS.panel_elevated,
                foreground=COLORS.muted, font=(IDENTITY_FONT, 9, "bold")).pack(side="left", padx=(0, 8))
        
        collection_var = tk.StringVar(value="Todas las colecciones")
        collection_combo = ttk.Combobox(row2, textvariable=collection_var,
                                       values=["Todas las colecciones"] + self.database.collection_names(),
                                       state="readonly", width=22)
        collection_combo.pack(side="left", padx=(0, 12))
        
        # Botón buscar
        def perform_search():
            search_text = search_var.get().strip()
            category = category_var.get()
            if category == "Todas las categorías":
                category = ""
            collection = collection_var.get()
            if collection == "Todas las colecciones":
                collection = ""
            
            # Buscar diseños
            results = self.database.plancha_browser_images(
                query=search_text,
                mode=search_by_var.get(),
                category=category,
                collection=collection,
                limit=100,
            )
            
            # Actualizar tabla - solo mostrar categoría, etiquetas y colección
            results_tree.delete(*results_tree.get_children())
            for idx, img in enumerate(results):
                # Usar caption si existe, sino el nombre sin extensión
                display_name = img.get("caption") or Path(img["path"]).stem
                
                results_tree.insert("", "end", iid=str(idx), values=(
                    display_name,
                    img.get("category") or "—",
                    img.get("tags") or "—",
                    img.get("collections") or "—"
                ))
                # Guardar referencia completa del diseño
                results_tree.item(str(idx), tags=(img["path"],))
            
            status_label.set(f"{len(results)} diseños encontrados")
            
            # Limpiar vista previa
            preview_label.configure(image="", text="Elegí un diseño")
            preview_label.image = None
            info_text.set("")
        
        ttk.Button(row2, text="Buscar", command=perform_search,
                  style="Primary.TButton").pack(side="right")
        
        # Tabla de resultados
        table_frame = tk.Frame(left_panel, background=COLORS.panel,
                              highlightthickness=1, highlightbackground=COLORS.border)
        table_frame.pack(fill="both", expand=True)
        
        columns = ("design", "category", "tags", "collection")
        results_tree = ttk.Treeview(table_frame, columns=columns, show="headings",
                                   selectmode="extended")
        
        results_tree.heading("design", text="Diseño")
        results_tree.heading("category", text="Categoría")
        results_tree.heading("tags", text="Etiquetas")
        results_tree.heading("collection", text="Colecciones")
        
        results_tree.column("design", width=250, anchor="w")
        results_tree.column("category", width=150, anchor="w")
        results_tree.column("tags", width=250, anchor="w")
        results_tree.column("collection", width=120, anchor="w")
        
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=results_tree.yview)
        results_tree.configure(yscrollcommand=scrollbar.set)
        
        results_tree.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)
        scrollbar.pack(side="right", fill="y", pady=1, padx=(0, 1))
        
        # Panel derecho: vista previa
        right_panel = tk.Frame(content, width=280, background=COLORS.panel,
                              highlightthickness=1, highlightbackground=COLORS.border)
        right_panel.pack(side="right", fill="y")
        right_panel.pack_propagate(False)
        
        tk.Label(right_panel, text="VISTA PREVIA", background=COLORS.panel,
                foreground=COLORS.wine_active, font=(IDENTITY_FONT, 10, "bold")).pack(
                anchor="w", padx=14, pady=(14, 8))
        
        # Vista previa de imagen - más grande
        preview_container = tk.Frame(right_panel, background=COLORS.panel_elevated,
                                highlightthickness=1, highlightbackground=COLORS.border)
        preview_container.pack(padx=14, pady=(0, 12), fill="both", expand=True)
        
        preview_label = tk.Label(preview_container, text="Elegí un diseño",
                                background=COLORS.panel_elevated, foreground=COLORS.muted,
                                font=(UI_FONT, 10))
        preview_label.pack(expand=True, fill="both")
        
        # Info del diseño seleccionado
        info_frame = tk.Frame(right_panel, background=COLORS.panel)
        info_frame.pack(fill="x", padx=14, pady=(0, 14))
        
        info_text = tk.StringVar(value="")
        info_label = tk.Label(info_frame, textvariable=info_text, background=COLORS.panel,
                foreground=COLORS.text, font=(UI_FONT, 9), justify="left",
                wraplength=240, anchor="nw")
        info_label.pack(fill="both")
        
        # Actualizar vista previa al seleccionar
        def on_select(event):
            selected = results_tree.selection()
            if not selected:
                preview_label.configure(image="", text="Elegí un diseño")
                preview_label.image = None
                info_text.set("")
                return
            
            # Obtener el path del primer seleccionado
            item = results_tree.item(selected[0])
            tags = item.get("tags", ())
            if not tags:
                return
            
            image_path = tags[0]
            
            # Cargar miniatura más grande
            from app.indexer.thumbnails import load_thumbnail
            thumbnail = load_thumbnail(image_path, (240, 240))
            
            if thumbnail:
                preview_label.configure(image=thumbnail, text="")
                preview_label.image = thumbnail
            else:
                preview_label.configure(image="", text="Sin vista previa disponible")
                preview_label.image = None
            
            # Mostrar info sin el nombre del archivo
            values = item.get("values", ())
            if values:
                info_parts = []
                
                # Nombre/Caption del diseño
                if values[0]:
                    info_parts.append(f"Diseño: {values[0]}")
                
                # Categoría
                if values[1] and values[1] != "—":
                    info_parts.append(f"Categoría: {values[1]}")
                
                # Etiquetas
                if values[2] and values[2] != "—":
                    # Limitar longitud de etiquetas
                    tags_str = values[2]
                    if len(tags_str) > 80:
                        tags_str = tags_str[:77] + "..."
                    info_parts.append(f"Etiquetas: {tags_str}")
                
                # Colección
                if values[3] and values[3] != "—":
                    info_parts.append(f"Colección: {values[3]}")
                
                if not info_parts:
                    info_parts.append("Sin etiquetas todavía")
                
                info_text.set("\n\n".join(info_parts))
        
        results_tree.bind("<<TreeviewSelect>>", on_select)
        
        # Doble clic para agregar directamente
        def on_double_click(event):
            add_selected_designs()
        
        results_tree.bind("<Double-1>", on_double_click)
        
        # Botones de acción
        actions = tk.Frame(dialog, background=COLORS.background)
        actions.pack(fill="x", padx=16, pady=(0, 16))
        
        status_label = tk.StringVar(value="Realizá una búsqueda para ver diseños")
        tk.Label(actions, textvariable=status_label, background=COLORS.background,
                foreground=COLORS.muted, font=(UI_FONT, 10)).pack(side="left")
        
        def add_selected_designs():
            selected = results_tree.selection()
            if not selected:
                messagebox.showinfo("Agregar diseños", 
                                   "Seleccioná uno o más diseños de la tabla.",
                                   parent=dialog)
                return
            
            # Obtener el tab del pedido
            if order_id not in self.order_tabs:
                self.open_order_workspace(order_id)
            tab = self.order_tabs.get(order_id)
            if not tab:
                return
            
            existing = {design.get("image_path") for design in tab.order_design_state}
            added = 0
            
            for item_id in selected:
                item = results_tree.item(item_id)
                tags = item.get("tags", ())
                if not tags:
                    continue
                
                image_path = tags[0]
                if image_path in existing:
                    continue
                
                # Obtener info del diseño
                values = item.get("values", ())
                name = values[0] if values else Path(image_path).stem
                category = values[1] if len(values) > 1 and values[1] != "—" else ""
                tags_str = values[2] if len(values) > 2 and values[2] != "—" else ""
                
                tab.order_design_state.append({
                    "image_path": image_path,
                    "name": name,
                    "tags": tags_str,
                    "category": category,
                    "quantity": 1,
                    "size_cm": 5.9,
                    "rotation": 0,
                    "status": "Pendiente",
                })
                existing.add(image_path)
                added += 1
            
            if added > 0:
                self.render_order_workspace(tab)
                self.queue_order_autosave(order_id)
                self.status.set(f"Se agregaron {added} diseños al pedido #{order_id}.")
                dialog.destroy()
            else:
                messagebox.showinfo("Agregar diseños",
                                   "Los diseños seleccionados ya están en el pedido.",
                                   parent=dialog)
        
        ttk.Button(actions, text="Cancelar", command=dialog.destroy,
                  style="Secondary.TButton").pack(side="right")
        ttk.Button(actions, text="Agregar seleccionados", command=add_selected_designs,
                  style="Primary.TButton").pack(side="right", padx=(0, 8))
        
        # Centrar ventana
        self.center_window(dialog)
        
        # Hacer búsqueda inicial
        self.after(100, perform_search)

    def open_plancha_for_order(self, order_id: int):
        """Abre una plancha vinculada al pedido sin duplicar ni mover originales."""
        self.flush_order_autosave(order_id)
        designs = self.database.order_designs(order_id)
        if not designs:
            messagebox.showinfo("Armado de planchas", "Agregá al menos un diseño al pedido antes de crear la plancha.", parent=self)
            return
        
        # Ordenar diseños: 5cm primero, luego el resto por tamaño
        designs_sorted = sorted(designs, key=lambda d: (
            0 if float(d.get("size_cm", 5.9)) == 5.0 else 1,  # 5cm primero
            float(d.get("size_cm", 5.9))  # Luego ordenar por tamaño ascendente
        ))
        
        paths = [design["image_path"] for design in designs_sorted]
        images = self.database.images_by_paths(paths)
        if not images:
            messagebox.showwarning("Armado de planchas", "No se pudieron cargar los diseños vinculados al pedido.", parent=self)
            return
        
        # Reordenar images según el orden de paths y agregar cantidad y tamaño del pedido
        path_to_image = {img["path"]: img for img in images}
        path_to_design = {design["image_path"]: design for design in designs_sorted}
        
        images_sorted = []
        for path in paths:
            if path in path_to_image:
                img = path_to_image[path].copy()  # Copiar para no modificar el original
                design = path_to_design.get(path, {})
                # Agregar cantidad y tamaño desde el diseño del pedido
                img["order_quantity"] = int(design.get("quantity", 1) or 1)
                img["order_size_cm"] = float(design.get("size_cm", 5.9) or 5.9)
                images_sorted.append(img)
        
        from app.planchas.editor import PlanchaEditor
        PlanchaEditor(self, images_sorted, database=self.database, library_images=self.database.search(limit=10000), order_id=order_id)

    def build_production_module(self, parent):
        """Panel de Producción: tabla de planchas + ficha lateral con detalle."""
        # --- Header ---
        header = tk.Frame(parent, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        header.pack(fill="x", padx=10, pady=(10, 8))
        header_content = tk.Frame(header, background=COLORS.panel)
        header_content.pack(fill="x", padx=14, pady=11)
        tk.Label(header_content, text="PRODUCCIÓN · PLANCHAS", background=COLORS.panel, foreground=COLORS.wine_active,
                 font=(IDENTITY_FONT, 12, "bold")).pack(side="left")
        self.production_summary = tk.StringVar(value="Cargando planchas…")
        tk.Label(header_content, textvariable=self.production_summary, background=COLORS.panel, foreground=COLORS.muted,
                 font=(UI_FONT, 10)).pack(side="left", padx=14)
        ttk.Button(header_content, text="Actualizar", command=lambda: self.refresh_production(), style="Secondary.TButton").pack(side="right")
        ttk.Button(header_content, text="Producción continua", command=lambda: self._open_continuous_from_production(), style="Secondary.TButton").pack(side="right", padx=(0, 7))
        ttk.Button(header_content, text="Abrir cola de impresión", command=lambda: self.open_print_queue_window(), style="Primary.TButton").pack(side="right", padx=(0, 7))

        # --- PanedWindow: tabla (izq) + ficha (der) ---
        self._production_pane = ttk.PanedWindow(parent, orient="horizontal")
        self._production_pane.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # --- Left pane: filtro + treeview ---
        left_pane = tk.Frame(self._production_pane, background=COLORS.background)
        self._production_pane.add(left_pane, weight=3)

        # Filtro por estado
        filter_frame = tk.Frame(left_pane, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        filter_frame.pack(fill="x", pady=(0, 4))
        filter_inner = tk.Frame(filter_frame, background=COLORS.panel)
        filter_inner.pack(fill="x", padx=14, pady=6)
        tk.Label(filter_inner, text="Filtrar:", background=COLORS.panel, foreground=COLORS.muted,
                 font=(UI_FONT, 10)).pack(side="left")
        self.production_filter = tk.StringVar(value="Todas")
        filter_values = ["Todas", "Guardadas", "Listas", "En cola", "Impresas", "Con errores"]
        for label in filter_values:
            ttk.Radiobutton(filter_inner, text=label, variable=self.production_filter, value=label,
                           command=lambda: self.refresh_production()).pack(side="left", padx=(8, 0))

        # Estilo del treeview con fila más alta para preview
        production_style = ttk.Style(parent)
        production_style.configure(
            "Production.Treeview",
            background=COLORS.panel,
            fieldbackground=COLORS.panel,
            foreground=COLORS.text,
            rowheight=64,
            borderwidth=0,
            font=(UI_FONT, 10),
        )
        production_style.configure(
            "Production.Treeview.Heading",
            background=COLORS.panel_elevated,
            foreground=COLORS.text,
            relief="flat",
            font=(UI_FONT, 10, "bold"),
            padding=(8, 8),
        )
        production_style.map(
            "Production.Treeview",
            background=[("selected", COLORS.wine)],
            foreground=[("selected", COLORS.text)],
        )
        columns = ("preview", "order", "plancha", "material", "state", "prints", "delivery")
        self.production_tree = ttk.Treeview(left_pane, columns=columns, show="headings", style="Production.Treeview", selectmode="browse")
        headings = {
            "preview": ("", 70), "order": ("Pedido", 160), "plancha": ("Plancha", 185),
            "material": ("Material", 120), "state": ("Estado", 120),
            "prints": ("Impresiones", 90), "delivery": ("Entrega", 105),
        }
        for key in columns:
            title, width = headings[key]
            self.production_tree.heading(key, text=title)
            self.production_tree.column(key, width=width, anchor="center" if key in {"preview", "state", "prints", "delivery"} else "w")
        scroll = ttk.Scrollbar(left_pane, orient="vertical", command=lambda *a: self.production_tree.yview(*a))
        self.production_tree.configure(yscrollcommand=scroll.set)
        self.production_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # --- Right pane: ficha de detalle ---
        detail_outer = tk.Frame(self._production_pane, background=COLORS.panel, highlightthickness=1, highlightbackground=COLORS.border)
        self._production_pane.add(detail_outer, weight=1)

        detail_canvas = tk.Canvas(detail_outer, background=COLORS.panel, highlightthickness=0, bd=0)
        detail_scroll = ttk.Scrollbar(detail_outer, orient="vertical", command=detail_canvas.yview)
        detail_inner = tk.Frame(detail_canvas, background=COLORS.panel)
        detail_inner.bind("<Configure>", lambda e: detail_canvas.configure(scrollregion=detail_canvas.bbox("all")))
        detail_canvas.create_window((0, 0), window=detail_inner, anchor="nw")
        detail_canvas.configure(yscrollcommand=detail_scroll.set)
        detail_scroll.pack(side="right", fill="y")
        detail_canvas.pack(side="left", fill="both", expand=True)
        self._production_detail_inner = detail_inner
        self._production_detail_canvas = detail_canvas
        # Soporte scroll con mouse wheel
        def _on_detail_mousewheel(event):
            detail_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        detail_canvas.bind("<MouseWheel>", _on_detail_mousewheel)
        detail_inner.bind("<MouseWheel>", _on_detail_mousewheel)

        # --- Preview con tabs: Impresión / Cliente ---
        self._preview_mode = tk.StringVar(value="print")
        preview_nb = ttk.Notebook(detail_inner)
        preview_nb.pack(fill="x", padx=10, pady=(10, 2))

        # --- Tab Impresión ---
        print_tab = tk.Frame(preview_nb, background=COLORS.canvas)
        preview_nb.add(print_tab, text=" Impresión ")
        self._prod_detail_preview_label = tk.Label(print_tab, text="Seleccioná una plancha\npara ver sus datos",
                                                    background=COLORS.canvas, foreground=COLORS.muted,
                                                    font=(UI_FONT, 10), anchor="center")
        self._prod_detail_preview_label.pack(fill="both", expand=True, padx=2, pady=2, ipady=30)
        self._prod_detail_preview_photo = None
        self._prod_detail_preview_zoom = tk.DoubleVar(value=1.0)
        preview_controls = tk.Frame(print_tab, background=COLORS.canvas)
        preview_controls.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(preview_controls, text="Zoom:", background=COLORS.canvas, foreground=COLORS.muted,
                  font=(UI_FONT, 9)).pack(side="left")
        zoom_slider = ttk.Scale(preview_controls, from_=0.3, to=3.0, variable=self._prod_detail_preview_zoom,
                                orient="horizontal", command=lambda _: self._update_production_detail_preview())
        zoom_slider.pack(side="left", fill="x", expand=True, padx=(4, 4))
        ttk.Button(preview_controls, text="Abrir PNG", command=self._production_view_png,
                  style="Secondary.TButton").pack(side="right")

        # --- Tab Cliente ---
        client_tab = tk.Frame(preview_nb, background=COLORS.canvas)
        preview_nb.add(client_tab, text=" Cliente ")
        self._preview_nb = preview_nb

        # Fondo selector
        bg_frame = tk.Frame(client_tab, background=COLORS.panel)
        bg_frame.pack(fill="x", padx=6, pady=(6, 2))
        ttk.Label(bg_frame, text="Fondo:", background=COLORS.panel, foreground=COLORS.muted,
                  font=(UI_FONT, 9)).pack(side="left", padx=(0, 4))
        self._client_bg_type = tk.StringVar(value="white")
        bg_options = [("Blanco", "white"), ("Gris claro", "gray"), ("Marca", "brand"), ("Imagen", "custom")]
        for label, value in bg_options:
            ttk.Radiobutton(bg_frame, text=label, variable=self._client_bg_type, value=value,
                           command=self._on_client_bg_change).pack(side="left", padx=(2, 0))
        self._client_bg_custom_path = tk.StringVar(value="")
        ttk.Button(bg_frame, text="Elegir imagen…", command=self._pick_custom_bg,
                  style="Secondary.TButton").pack(side="left", padx=(6, 0))
        self._client_custom_bg_label = tk.Label(bg_frame, text="", background=COLORS.panel,
                                                 foreground=COLORS.muted, font=(UI_FONT, 8))
        self._client_custom_bg_label.pack(side="left", padx=(4, 0))

        # Preview del cliente
        self._client_preview_label = tk.Label(client_tab, text="Generá la vista\npara el cliente",
                                               background=COLORS.canvas, foreground=COLORS.muted,
                                               font=(UI_FONT, 10), anchor="center")
        self._client_preview_label.pack(fill="both", expand=True, padx=6, pady=6, ipady=30)
        self._client_preview_photo = None

        # Botones de acción cliente
        client_actions = tk.Frame(client_tab, background=COLORS.canvas)
        client_actions.pack(fill="x", padx=6, pady=(0, 6))
        self._btn_generate_client = ttk.Button(client_actions, text="Generar vista cliente",
                                               command=self._generate_client_preview, style="Primary.TButton")
        self._btn_generate_client.pack(side="left")
        self._btn_export_client = ttk.Button(client_actions, text="Exportar vista cliente",
                                              command=self._export_client_preview, style="Secondary.TButton")
        self._btn_export_client.pack(side="left", padx=(6, 0))
        self._client_status_label = tk.Label(client_actions, text="", background=COLORS.canvas,
                                              foreground=COLORS.muted, font=(UI_FONT, 8))
        self._client_status_label.pack(side="right")

        ttk.Label(detail_inner, text="Proporción real A4 · tamaño físico según calibración del monitor",
                  background=COLORS.panel, foreground=COLORS.disabled,
                  font=(UI_FONT, 8)).pack(fill="x", padx=10, pady=(1, 0))

        # --- Sección Datos del pedido ---
        self._prod_detail_order_frame = self._build_detail_section(detail_inner, "DATOS DEL PEDIDO")
        self._prod_detail_order_labels = {}
        for key, label in [("order", "Pedido"), ("client", "Cliente"), ("name", "Plancha"),
                           ("material", "Material"), ("format", "Formato"), ("stickers", "Stickers"),
                           ("usuario", "Usuario"), ("delivery", "Entrega"), ("saved", "Guardado")]:
            row = tk.Frame(self._prod_detail_order_frame, background=COLORS.panel)
            row.pack(fill="x", padx=10, pady=1)
            tk.Label(row, text=f"{label}:", background=COLORS.panel, foreground=COLORS.muted,
                     font=(UI_FONT, 9), width=10, anchor="e").pack(side="left")
            val = tk.Label(row, text="—", background=COLORS.panel, foreground=COLORS.text,
                          font=(UI_FONT, 10, "bold"), anchor="w")
            val.pack(side="left", padx=(6, 0))
            self._prod_detail_order_labels[key] = val

        # --- Sección Producción ---
        self._prod_detail_prod_frame = self._build_detail_section(detail_inner, "ESTADO DE PRODUCCIÓN")
        self._prod_detail_prod_labels = {}
        for key, label in [("status", "Estado"), ("prints_ok", "Impresiones OK"), ("errors", "Errores"),
                           ("reprints", "Reimpresiones"), ("last_print", "Última impresión"),
                           ("mode", "Modo"), ("queue_pos", "Posición en cola")]:
            row = tk.Frame(self._prod_detail_prod_frame, background=COLORS.panel)
            row.pack(fill="x", padx=10, pady=1)
            tk.Label(row, text=f"{label}:", background=COLORS.panel, foreground=COLORS.muted,
                     font=(UI_FONT, 9), width=14, anchor="e").pack(side="left")
            val = tk.Label(row, text="—", background=COLORS.panel, foreground=COLORS.text,
                          font=(UI_FONT, 10, "bold"), anchor="w")
            val.pack(side="left", padx=(6, 0))
            self._prod_detail_prod_labels[key] = val

        # --- Barra de acciones ---
        actions_frame = tk.Frame(detail_inner, background=COLORS.panel)
        actions_frame.pack(fill="x", padx=10, pady=(10, 10))
        ttk.Label(actions_frame, text="ACCIONES", background=COLORS.panel, foreground=COLORS.muted,
                  font=(IDENTITY_FONT, 9, "bold")).pack(anchor="w", pady=(0, 6))
        action_btns = tk.Frame(actions_frame, background=COLORS.panel)
        action_btns.pack(fill="x")
        btn_specs = [
            ("open_editor", "Abrir editor", self._production_open_editor, "Primary.TButton"),
            ("send_print", "Enviar a impresión", self._production_send_to_print, "Primary.TButton"),
            ("reprint", "Reimprimir", self._production_reprint, "Secondary.TButton"),
            ("add_continuous", "Agregar a continua", self._production_add_to_continuous, "Secondary.TButton"),
            ("register_error", "Registrar error", self._production_register_error, "Secondary.TButton"),
            ("view_history", "Ver historial", self._production_view_history, "Secondary.TButton"),
        ]
        self._production_action_btns = {}
        for i, (key, text, cmd, style) in enumerate(btn_specs):
            row_idx = i // 2
            col_idx = i % 2
            btn = ttk.Button(action_btns, text=text, command=cmd, style=style)
            btn.grid(row=row_idx, column=col_idx, sticky="ew", padx=2, pady=2)
            self._production_action_btns[key] = btn
        action_btns.columnconfigure(0, weight=1)
        action_btns.columnconfigure(1, weight=1)

        # --- State ---
        self._production_preview_cache: dict[int, object] = {}
        self._production_plancha_data: dict[str, dict] = {}
        self._production_detail_current_preview_path: str = ""

        # --- Bindings ---
        self.production_tree.bind("<<TreeviewSelect>>", self._on_production_select)
        self.production_tree.bind("<Double-1>", self._on_production_double_click)
        self._production_menu = tk.Menu(self.production_tree, tearoff=0)
        self._production_menu.add_command(label="Abrir en editor", command=self._production_open_editor)
        self._production_menu.add_command(label="Enviar a impresión", command=self._production_send_to_print)
        self._production_menu.add_separator()
        self._production_menu.add_command(label="Ver PNG final", command=self._production_view_png)
        self._production_menu.add_command(label="Reimprimir", command=self._production_reprint)
        self._production_menu.add_separator()
        self._production_menu.add_command(label="Agregar a producción continua", command=self._production_add_to_continuous)
        self.production_tree.bind("<Button-3>", self._show_production_menu)

        self.refresh_production()

    def open_print_queue_window(self):
        """Administrador flotante de planchas listas para impresión + jobs activos."""
        existing = getattr(self, "print_queue_window", None)
        if existing and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return
        dialog = tk.Toplevel(self)
        dialog.title("Cola de impresión · Producción")
        dialog.configure(background=COLORS.background)
        dialog.geometry("1100x600")
        dialog.minsize(850, 440)
        dialog.transient(self)
        self.print_queue_window = dialog

        content = ttk.Frame(dialog, padding=16)
        content.pack(fill="both", expand=True)
        ttk.Label(content, text="COLA DE IMPRESIÓN", style="Title.TLabel").pack(anchor="w")
        queue_summary = tk.StringVar(value="Cargando…")
        ttk.Label(content, textvariable=queue_summary, style="Muted.TLabel").pack(anchor="w", pady=(3, 12))

        # Notebook con pestañas: Planchas listas / Jobs activos
        queue_nb = ttk.Notebook(content)
        queue_nb.pack(fill="both", expand=True)

        # --- Pestaña 1: Planchas listas para enviar ---
        sheets_frame = ttk.Frame(queue_nb)
        queue_nb.add(sheets_frame, text=" Planchas listas ")
        sheet_cols = ("order", "plancha", "material", "prints", "state")
        sheet_tree = ttk.Treeview(sheets_frame, columns=sheet_cols, show="headings", selectmode="browse")
        for key, label, width in (
            ("order", "Pedido", 180), ("plancha", "Plancha", 200),
            ("material", "Material", 130), ("prints", "Impresiones", 90), ("state", "Estado", 120),
        ):
            sheet_tree.heading(key, text=label)
            sheet_tree.column(key, width=width, anchor="center" if key in {"prints", "state"} else "w")
        sheet_scroll = ttk.Scrollbar(sheets_frame, orient="vertical", command=sheet_tree.yview)
        sheet_tree.configure(yscrollcommand=sheet_scroll.set)
        sheet_tree.pack(side="left", fill="both", expand=True)
        sheet_scroll.pack(side="right", fill="y")

        # --- Pestaña 2: Jobs activos en Windows ---
        jobs_frame = ttk.Frame(queue_nb)
        queue_nb.add(jobs_frame, text=" Jobs activos ")
        job_cols = ("order", "plancha", "file", "printer", "status")
        job_tree = ttk.Treeview(jobs_frame, columns=job_cols, show="headings", selectmode="browse")
        for key, label, width in (
            ("order", "Pedido", 170), ("plancha", "Plancha", 180),
            ("file", "PNG final", 290), ("printer", "Impresora", 170), ("status", "Estado", 130),
        ):
            job_tree.heading(key, text=label)
            job_tree.column(key, width=width, anchor="center" if key == "status" else "w")
        job_scroll = ttk.Scrollbar(jobs_frame, orient="vertical", command=job_tree.yview)
        job_tree.configure(yscrollcommand=job_scroll.set)
        job_tree.pack(side="left", fill="both", expand=True)
        job_scroll.pack(side="right", fill="y")

        def refresh_queue():
            # Pestaña 1: planchas listas
            sheet_tree.delete(*sheet_tree.get_children())
            available = self.database.production_planchas_by_status("lista")
            available += self.database.production_planchas_by_status("en_cola")
            available += self.database.production_planchas_by_status("impresa")
            production_status_labels = {"lista": "Lista", "en_cola": "En cola", "impresa": "Impresa"}
            for p in available:
                pid = int(p["id"])
                order_label = f"#{p.get('order_id', '?')} · {p.get('order_client') or 'Sin cliente'}" if p.get("order_id") else "Sin pedido"
                name = p.get("name") or f"Plancha #{pid}"
                material = p.get("material") or "-"
                print_count = int(p.get("print_count") or 0)
                error_count = int(p.get("error_count") or 0)
                prints_label = f"{print_count}OK" + (f" / {error_count}✗" if error_count else "")
                status = production_status_labels.get(p.get("production_status") or "lista", "?")
                sheet_tree.insert("", "end", iid=f"p:{pid}", values=(
                    order_label, name, material, prints_label, status,
                ))
            # Pestaña 2: jobs activos
            job_tree.delete(*job_tree.get_children())
            rows = self.database.print_queue()
            for job in rows:
                order = f"#{job['order_id']} · {job.get('client') or 'Sin cliente'}" if job.get("order_id") else "Sin pedido"
                job_tree.insert("", "end", iid=str(job["id"]), values=(
                    order, job.get("plancha_name") or f"Plancha #{job['plancha_id']}",
                    Path(job.get("final_png_path") or "").name or "Sin PNG",
                    job.get("printer_name") or "Sin configurar",
                    job.get("status") or "Pendiente",
                ))
            counts = self.database.print_queue_counts()
            queue_summary.set(
                f"Pendientes: {counts['Pendiente']} · Enviando: {counts['Enviando a impresora']} · "
                f"En cola: {counts['En cola']} · Errores: {counts['Error de impresión']} · "
                f"Planchas listas: {len(available)}"
            )
            self.refresh_production()

        def selected_job():
            sel = job_tree.selection()
            return self.database.print_job(int(sel[0])) if sel else None

        def selected_plancha_id():
            sel = sheet_tree.selection()
            if not sel:
                return None
            iid = sel[0]
            if iid.startswith("p:"):
                return int(iid[2:])
            return None

        def open_png():
            job = selected_job()
            if not job:
                messagebox.showinfo("Cola de impresión", "Elegí un job en la pestaña Jobs activos.", parent=dialog)
                return
            path = Path(job["final_png_path"])
            if not path.exists():
                messagebox.showerror("Cola de impresión", "No se encontró el PNG final guardado.", parent=dialog)
                return
            os.startfile(str(path))

        def send_to_printer():
            job = selected_job()
            if not job:
                messagebox.showinfo("Cola de impresión", "Elegí un job pendiente o con error.", parent=dialog)
                return
            if job["status"] not in {"Pendiente", "Error de impresión"}:
                messagebox.showinfo("Cola de impresión", "Elegí una plancha pendiente o con error.", parent=dialog)
                return
            if not Path(job["final_png_path"]).exists():
                messagebox.showerror("Cola de impresión", "No se encontró el PNG final de esta plancha.", parent=dialog)
                return
            self.database.update_print_job(job["id"], "Enviando a impresora")
            refresh_queue()

            def work():
                from app.printing.windows_print import print_png_strip
                result = print_png_strip(job["printer_name"], job["final_png_path"], job["copies"], f"Doccione · Plancha {job['plancha_id']}")
                def finish():
                    self.database.update_print_job(job["id"], "En cola" if result.success else "Error de impresión", result.message, result.spool_job_id if result.success else None)
                    # Publicar evento de error de producción
                    if not result.success:
                        try:
                            order_id = job.get("order_id")
                            if order_id:
                                self._event_bus.publish_production_error(order_id, f"Plancha #{job['plancha_id']}: {result.message}")
                        except Exception:
                            pass
                    refresh_queue()
                self.after(0, finish)

            threading.Thread(target=work, daemon=True).start()

        def mark_printed():
            job = selected_job()
            if not job or job["status"] != "En cola":
                messagebox.showinfo("Cola de impresión", "Elegí una plancha que ya esté en cola de Windows.", parent=dialog)
                return
            if messagebox.askyesno("Confirmar impresión", "¿La plancha terminó de imprimirse correctamente?", parent=dialog):
                self.database.update_print_job(job["id"], "Impresa", "Confirmada desde Producción.")
                # Publicar evento de producción completada
                try:
                    order_id = job.get("order_id")
                    if order_id:
                        self._event_bus.publish_production_completed(order_id, f"Plancha #{job['plancha_id']}")
                except Exception:
                    pass
                refresh_queue()

        actions = ttk.Frame(content)
        actions.pack(fill="x", pady=(13, 0))
        ttk.Button(actions, text="Actualizar", command=refresh_queue).pack(side="left")
        ttk.Button(actions, text="Abrir PNG", command=open_png).pack(side="left", padx=6)
        ttk.Button(actions, text="Enviar a impresora", command=send_to_printer, style="Primary.TButton").pack(side="right")
        ttk.Button(actions, text="Marcar impresa", command=mark_printed).pack(side="right", padx=(0, 6))
        ttk.Button(actions, text="Cerrar", command=dialog.destroy).pack(side="right", padx=(0, 14))
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        refresh_queue()

    def refresh_production(self):
        if not hasattr(self, "production_tree"):
            return
        # Guardar selección actual para restaurarla después
        prev_sel = self.production_tree.selection()
        prev_plancha_id = None
        if prev_sel:
            prev_data = self._production_plancha_data.get(prev_sel[0])
            if prev_data:
                prev_plancha_id = f"plancha:{int(prev_data['id'])}"
        self._production_preview_cache.clear()
        self._production_plancha_data.clear()
        self.production_tree.delete(*self.production_tree.get_children())
        rows = self.database.production_planchas()
        # Aplicar filtro
        filter_value = getattr(self, "production_filter", tk.StringVar(value="Todas")).get()
        status_map = {
            "Guardadas": "guardada", "Listas": "lista", "En cola": "en_cola",
            "Impresas": "impresa", "Con errores": None,
        }
        if filter_value == "Con errores":
            rows = [r for r in rows if int(r.get("error_count") or 0) > 0]
        elif filter_value in status_map and status_map[filter_value]:
            rows = [r for r in rows if r.get("production_status") == status_map[filter_value]]

        production_status_labels = {
            "borrador": "Borrador", "guardada": "Guardada", "lista": "Lista",
            "en_cola": "En cola", "impresa": "Impresa",
            "disponible_para_continua": "Disponible", "usada_en_continua": "Usada en tira",
        }

        restored = False
        for plancha in rows:
            plancha_id = int(plancha["id"])
            order_label = f"#{plancha.get('order_id', '?')} · {plancha.get('order_client') or 'Sin cliente'}" if plancha.get("order_id") else "Sin pedido"
            name = plancha.get("name") or f"Plancha #{plancha_id}"
            material = plancha.get("material") or "-"
            status = production_status_labels.get(plancha.get("production_status") or "borrador", "Borrador")
            print_count = int(plancha.get("print_count") or 0)
            error_count = int(plancha.get("error_count") or 0)
            prints_label = f"{print_count}OK" + (f" / {error_count}✗" if error_count else "")
            delivery = plancha.get("delivery_date") or "-"
            # Mini preview placeholder
            iid = f"plancha:{plancha_id}"
            preview_path = plancha.get("preview_path") or plancha.get("final_png_path") or ""
            has_preview = preview_path and Path(preview_path).exists()
            preview_marker = "" if has_preview else "–"
            self.production_tree.insert("", "end", iid=iid, values=(
                preview_marker, order_label, name, material, status, prints_label, delivery,
            ))
            self._production_plancha_data[iid] = plancha
            if has_preview:
                self._load_production_preview(iid, preview_path, plancha_id)
            # Restaurar selección previa si el item sigue en la tabla
            if prev_plancha_id == iid and not restored:
                self.after_idle(lambda i=iid: (self.production_tree.selection_set(i),
                                               self.production_tree.see(i),
                                               self._refresh_production_detail()))
                restored = True

        if not restored and hasattr(self, "_clear_production_detail"):
            self._clear_production_detail()

        total = len(rows)
        lists = sum(1 for r in rows if r.get("production_status") == "lista")
        queued = sum(1 for r in rows if r.get("production_status") == "en_cola")
        printed = sum(1 for r in rows if r.get("production_status") == "impresa")
        errors = sum(1 for r in rows if int(r.get("error_count") or 0) > 0)
        if not total:
            self.production_summary.set("No hay planchas guardadas. Creá una plancha desde un pedido para que aparezca acá.")
        else:
            self.production_summary.set(
                f"Total: {total} · Listas: {lists} · En cola: {queued} · "
                f"Impresas: {printed}" + (f" · Con errores: {errors}" if errors else "")
            )

    def _load_production_preview(self, iid: str, path: str, plancha_id: int):
        """Carga un mini thumbnail para la columna de preview de forma segura."""
        try:
            from PIL import Image, ImageTk
            with Image.open(path) as img:
                img = img.convert("RGBA")
                thumb = img.copy()
                thumb.thumbnail((56, 52), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(thumb)
                self._production_preview_cache[plancha_id] = photo
                self.production_tree.set(iid, "preview", "✓")
                # Usar tag para mostrar el ítem como referencia visual
                self.production_tree.item(iid, tags=(f"preview:{plancha_id}",))
        except Exception:
            pass

    def _selected_production_plancha(self) -> dict | None:
        """Devuelve el dict de plancha seleccionado en la tabla de Producción."""
        sel = self.production_tree.selection()
        if not sel:
            return None
        return self._production_plancha_data.get(sel[0])

    def _show_production_menu(self, event):
        iid = self.production_tree.identify_row(event.y)
        if iid:
            self.production_tree.selection_set(iid)
            self._production_menu.post(event.x_root, event.y_root)

    def _on_production_double_click(self, _event):
        self._production_open_editor()

    def _production_open_editor(self):
        plancha = self._selected_production_plancha()
        if not plancha:
            return
        self._open_plancha_editor(int(plancha["id"]))

    def _open_plancha_editor(self, plancha_id: int):
        """Abre el editor de plancha existente por su ID."""
        saved = self.database.plancha_project(plancha_id)
        if not saved:
            messagebox.showinfo("Producción", "No se encontró la plancha.", parent=self)
            return
        project_path = saved.get("project_path") or ""
        if not project_path or not Path(project_path).exists():
            messagebox.showinfo("Producción", "No se encontró el archivo del proyecto de plancha.", parent=self)
            return
        try:
            from app.planchas.model import PlanchaProject
            from app.planchas.editor import PlanchaEditor
            project = PlanchaProject.load(project_path)
            order_id = saved.get("order_id")
            images = []
            if order_id:
                designs = self.database.order_designs(order_id)
                path_map = {d["image_path"]: d for d in designs}
                all_images = self.database.search(limit=10000)
                path_to_image = {img["path"]: img for img in all_images}
                for item in project.items:
                    if item.path in path_to_image:
                        img = path_to_image[item.path].copy()
                        design = path_map.get(item.path, {})
                        img["order_quantity"] = int(design.get("quantity", 1) or 1)
                        img["order_size_cm"] = float(design.get("size_cm", 5.9) or 5.9)
                        images.append(img)
            if not images:
                images = self.database.search(limit=10000)
            editor = PlanchaEditor(
                self, images, database=self.database, library_images=self.database.search(limit=10000),
                project=project, order_id=order_id, plancha_id=plancha_id, preserve_layout=True,
            )
            # Refrescar Producción al cerrar el editor (guardado/imprimir/etc.)
            editor.bind("<Destroy>", lambda e: self.after_idle(self.refresh_production) if e.widget == editor else None)
        except Exception as error:
            messagebox.showerror("No se pudo abrir", str(error), parent=self)

    def _production_send_to_print(self):
        plancha = self._selected_production_plancha()
        if not plancha:
            return
        plancha_id = int(plancha["id"])
        final_png = plancha.get("final_png_path") or ""
        if not final_png or not Path(final_png).exists():
            messagebox.showinfo("Impresión", "Esta plancha no tiene PNG final. Exportala desde el editor primero.", parent=self)
            return
        # Abrir el editor directamente en modo impresión
        self._open_plancha_editor(plancha_id)

    def _production_view_png(self):
        plancha = self._selected_production_plancha()
        if not plancha:
            return
        path = plancha.get("final_png_path") or ""
        if not path or not Path(path).exists():
            messagebox.showinfo("Producción", "No se encontró el PNG final.", parent=self)
            return
        os.startfile(str(path))

    def _production_reprint(self):
        plancha = self._selected_production_plancha()
        if not plancha:
            return
        self._open_plancha_editor(int(plancha["id"]))

    def _production_add_to_continuous(self):
        plancha = self._selected_production_plancha()
        if not plancha:
            return
        plancha_id = int(plancha["id"])
        final_png = plancha.get("final_png_path") or ""
        if not final_png or not Path(final_png).exists():
            messagebox.showinfo("Producción continua", "La plancha necesita un PNG final para agregarse a una tira.", parent=self)
            return
        from app.planchas.continuous_editor import ContinuousProductionEditor
        ContinuousProductionEditor(self, self.database, initial_plancha_id=plancha_id)

    # --- Ficha de detalle de producción ---

    @staticmethod
    def _build_detail_section(parent, title):
        """Crea una sección colapsable con título y devuelve el frame interno."""
        outer = tk.Frame(parent, background=COLORS.panel)
        outer.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(outer, text=title, background=COLORS.panel, foreground=COLORS.wine_active,
                 font=(IDENTITY_FONT, 9, "bold")).pack(anchor="w", pady=(0, 4))
        sep = tk.Frame(outer, background=COLORS.border, height=1)
        sep.pack(fill="x", pady=(0, 4))
        inner = tk.Frame(outer, background=COLORS.panel)
        inner.pack(fill="x")
        return inner

    def _on_production_select(self, _event=None):
        """Cuando cambia la selección en el Treeview, actualizar la ficha lateral."""
        self._refresh_production_detail()

    def _refresh_production_detail(self):
        """Poblar la ficha lateral con los datos de la plancha seleccionada."""
        plancha = self._selected_production_plancha()
        if not plancha:
            self._clear_production_detail()
            return
        pid = int(plancha["id"])

        # --- Datos del pedido ---
        order_label = f"#{plancha.get('order_id', '?')}" if plancha.get("order_id") else "Sin pedido"
        client = plancha.get("order_client") or plancha.get("client") or "—"
        name = plancha.get("name") or f"Plancha #{pid}"
        material = plancha.get("material") or "—"
        fmt = plancha.get("format") or plancha.get("project_format") or "—"
        stickers_raw = plancha.get("sticker_count") or plancha.get("stickers")
        stickers = str(stickers_raw) if stickers_raw else "—"
        usuario = plancha.get("usuario") or "—"
        delivery = plancha.get("delivery_date") or "—"
        saved = plancha.get("created_at") or "—"
        order_data = [
            ("order", order_label), ("client", client), ("name", name),
            ("material", material), ("format", fmt), ("stickers", stickers),
            ("usuario", usuario), ("delivery", delivery), ("saved", saved),
        ]
        for key, val in order_data:
            lbl = self._prod_detail_order_labels.get(key)
            if lbl:
                lbl.config(text=str(val) if val else "—")

        # --- Estado de producción ---
        status_raw = plancha.get("production_status") or "borrador"
        status_labels = {
            "borrador": "Borrador", "guardada": "Guardada", "lista": "Lista",
            "en_cola": "En cola", "impresa": "Impresa",
            "disponible_para_continua": "Disponible", "usada_en_continua": "Usada en tira",
        }
        status = status_labels.get(status_raw, status_raw)
        print_count = int(plancha.get("print_count") or 0)
        error_count = int(plancha.get("error_count") or 0)
        total_jobs = int(plancha.get("total_jobs") or 0)
        printed_jobs = int(plancha.get("printed_jobs") or 0)
        reprints = max(0, printed_jobs - 1) if printed_jobs > 0 else 0
        last_printed = plancha.get("last_printed_at") or "—"
        # Determinar modo
        has_continuous = status_raw in {"usada_en_continua", "disponible_para_continua"}
        mode = "Continua" if has_continuous else "Normal"
        # Posición en cola
        queue_pos = "—"
        if status_raw == "en_cola":
            queue_jobs = self.database.print_queue()
            pos_list = [j for j in queue_jobs if j.get("plancha_id") == pid]
            queue_pos = f"#{len(pos_list)}" if pos_list else "Enviando…"
        elif status_raw == "impresa":
            queue_pos = "Completada"

        prod_data = [
            ("status", status), ("prints_ok", str(print_count)),
            ("errors", str(error_count)), ("reprints", str(reprints)),
            ("last_print", last_printed), ("mode", mode), ("queue_pos", queue_pos),
        ]
        for key, val in prod_data:
            lbl = self._prod_detail_prod_labels.get(key)
            if lbl:
                lbl.config(text=str(val))
                # Colorear estado
                if key == "status":
                    color_map = {
                        "lista": COLORS.success, "impresa": COLORS.info,
                        "en_cola": COLORS.warning, "borrador": COLORS.muted,
                        "guardada": COLORS.muted, "usada_en_continua": COLORS.wine_active,
                    }
                    lbl.config(foreground=color_map.get(status_raw, COLORS.text))
                if key == "errors" and error_count > 0:
                    lbl.config(foreground=COLORS.error)

        # --- Preview impresión ---
        preview_path = plancha.get("final_png_path") or plancha.get("preview_path") or ""
        self._update_production_detail_preview(path=preview_path if preview_path and Path(preview_path).exists() else "")

        # --- Preview cliente ---
        client_cfg = self.database.client_preview_config(pid)
        client_path = client_cfg.get("path") or ""
        if client_path and Path(client_path).exists():
            self._show_client_preview(client_path)
            saved_bg = client_cfg.get("bg_type") or "white"
            self._client_bg_type.set(saved_bg)
            if saved_bg == "custom":
                self._client_bg_custom_path.set(client_cfg.get("bg_value") or "")
                self._client_custom_bg_label.config(
                    text=Path(client_cfg.get("bg_value") or "").name if client_cfg.get("bg_value") else "")
            else:
                self._client_bg_custom_path.set("")
                self._client_custom_bg_label.config(text="")
            updated = client_cfg.get("updated_at") or ""
            self._client_status_label.config(text=f"Guardado {updated}" if updated else "")
        else:
            self._client_preview_label.config(image="", text="Generá la vista\npara el cliente")
            self._client_preview_photo = None
            self._client_status_label.config(text="")
            self._client_bg_type.set("white")
            self._client_bg_custom_path.set("")
            self._client_custom_bg_label.config(text="")

        # --- Estado de botones de acción ---
        has_final_png = bool((plancha.get("final_png_path") or "").strip())
        self._production_action_btns["open_editor"].configure(state="normal")
        self._production_action_btns["send_print"].configure(state="normal" if has_final_png and status_raw not in {"en_cola", "usada_en_continua"} else "disabled")
        self._production_action_btns["reprint"].configure(state="normal" if has_final_png and status_raw not in {"borrador", "guardada"} else "disabled")
        self._production_action_btns["add_continuous"].configure(state="normal" if has_final_png and status_raw != "usada_en_continua" else "disabled")
        self._production_action_btns["register_error"].configure(state="normal" if status_raw not in {"borrador"} else "disabled")
        self._production_action_btns["view_history"].configure(state="normal" if total_jobs > 0 else "disabled")

    def _clear_production_detail(self):
        """Limpiar la ficha cuando no hay selección."""
        self._prod_detail_preview_label.config(image="", text="Seleccioná una plancha\npara ver sus datos",
                                                foreground=COLORS.muted)
        self._prod_detail_preview_photo = None
        self._production_detail_current_preview_path = ""
        # Limpiar vista cliente
        self._client_preview_label.config(image="", text="Generá la vista\npara el cliente")
        self._client_preview_photo = None
        self._client_bg_type.set("white")
        self._client_bg_custom_path.set("")
        self._client_custom_bg_label.config(text="")
        self._client_status_label.config(text="")
        self._preview_mode.set("print")
        for lbl in self._prod_detail_order_labels.values():
            lbl.config(text="—")
        for lbl in self._prod_detail_prod_labels.values():
            lbl.config(text="—")
        # Deshabilitar todos los botones de acción
        for btn in self._production_action_btns.values():
            btn.configure(state="disabled")

    def _update_production_detail_preview(self, path: str = ""):
        """Actualizar la imagen de preview en la ficha con zoom variable."""
        if not path:
            path = getattr(self, "_production_detail_current_preview_path", "")
        self._production_detail_current_preview_path = path
        if not path:
            self._prod_detail_preview_label.config(image="", text="Sin selección")
            self._prod_detail_preview_photo = None
            return
        try:
            from PIL import Image, ImageTk
            with Image.open(path) as img:
                img = img.convert("RGB")
                zoom = self._prod_detail_preview_zoom.get()
                # A4 proporción: 210x297 → ancho fijo ~240px a zoom 1.0
                base_w = 240
                w = int(base_w * zoom)
                h = int(w * (297 / 210))
                img = img.resize((w, h), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self._prod_detail_preview_photo = photo
                self._prod_detail_preview_label.config(image=photo, text="")
        except Exception:
            self._prod_detail_preview_label.config(image="", text="Error al cargar")

    # --- Vista previa para cliente ---

    _CLIENT_BG_COLORS = {
        "white": (255, 255, 255),
        "gray": (230, 230, 230),
        "brand": (0x1B, 0x1B, 0x1E),  # COLORS.panel oscuro
    }

    def _pick_custom_bg(self):
        """Elegir una imagen de fondo personalizada."""
        path = filedialog.askopenfilename(
            title="Elegir imagen de fondo",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.bmp *.webp"), ("Todos", "*.*")],
            parent=self,
        )
        if path:
            self._client_bg_custom_path.set(path)
            self._client_custom_bg_label.config(text=Path(path).name)

    def _on_client_bg_change(self):
        """Cuando cambia el tipo de fondo, actualizar el label informativo."""
        bg = self._client_bg_type.get()
        if bg == "custom":
            self._client_custom_bg_label.config(
                text=Path(self._client_bg_custom_path.get()).name if self._client_bg_custom_path.get() else "Sin imagen"
            )
        else:
            self._client_custom_bg_label.config(text="")

    def _generate_client_preview(self):
        """Generar la vista previa para cliente compositando el PNG final sobre un fondo."""
        plancha = self._selected_production_plancha()
        if not plancha:
            return
        pid = int(plancha["id"])
        final_png = (plancha.get("final_png_path") or "").strip()
        if not final_png or not Path(final_png).exists():
            messagebox.showinfo("Vista cliente", "No se encontró el PNG final de la plancha.", parent=self)
            return
        try:
            from PIL import Image, ImageTk, ImageOps
        except ImportError:
            messagebox.showerror("Vista cliente", "Se requiere Pillow para generar la vista cliente.", parent=self)
            return
        bg_type = self._client_bg_type.get()
        try:
            with Image.open(final_png) as fg:
                fg = fg.convert("RGBA")
                fg_w, fg_h = fg.size
                # Crear fondo del mismo tamaño que el PNG
                if bg_type == "custom":
                    bg_path = self._client_bg_custom_path.get()
                    if not bg_path or not Path(bg_path).exists():
                        messagebox.showwarning("Vista cliente", "Elegí una imagen de fondo válida.", parent=self)
                        return
                    with Image.open(bg_path) as bg_img:
                        bg_img = bg_img.convert("RGBA")
                        bg_img = ImageOps.fit(bg_img, (fg_w, fg_h), Image.Resampling.LANCZOS)
                        bg_img.paste(fg, (0, 0), fg)
                        result = bg_img
                else:
                    color = self._CLIENT_BG_COLORS.get(bg_type, (255, 255, 255))
                    result = Image.new("RGBA", (fg_w, fg_h), (*color, 255))
                    result.paste(fg, (0, 0), fg)
                # Guardar como archivo derivado (nunca tocar final_png_path)
                output_dir = Path(final_png).parent
                output_path = output_dir / f"client_preview_{pid}.png"
                result.convert("RGB").save(str(output_path), "PNG")
                self.database.save_client_preview(pid, str(output_path), bg_type,
                                                  self._client_bg_custom_path.get() if bg_type == "custom" else "")
                # Mostrar en el tab cliente
                self._show_client_preview(str(output_path))
                self.status.set(f"Vista cliente generada para plancha #{pid}")
        except Exception as error:
            messagebox.showerror("Vista cliente", f"Error al generar la vista:\n{error}", parent=self)

    def _show_client_preview(self, path: str):
        """Mostrar la imagen del cliente en el tab de cliente."""
        try:
            from PIL import Image, ImageTk
            with Image.open(path) as img:
                img = img.convert("RGB")
                zoom = self._prod_detail_preview_zoom.get()
                base_w = 240
                w = int(base_w * zoom)
                h = int(w * (297 / 210))
                img = img.resize((w, h), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self._client_preview_photo = photo
                self._client_preview_label.config(image=photo, text="")
                self._client_status_label.config(text=f"Generado: {Path(path).name}")
        except Exception:
            self._client_preview_label.config(image="", text="Error al cargar")

    def _export_client_preview(self):
        """Exportar la vista cliente a una ubicación elegida por el usuario."""
        plancha = self._selected_production_plancha()
        if not plancha:
            return
        pid = int(plancha["id"])
        config = self.database.client_preview_config(pid)
        src_path = config.get("path") or ""
        if not src_path or not Path(src_path).exists():
            messagebox.showinfo("Exportar", "Primero generá la vista cliente.", parent=self)
            return
        ext = Path(src_path).suffix or ".png"
        default_name = Path(src_path).name
        dest = filedialog.asksaveasfilename(
            title="Exportar vista cliente",
            initialfile=default_name,
            defaultextension=ext,
            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg"), ("Todos", "*.*")],
            parent=self,
        )
        if not dest:
            return
        try:
            import shutil
            shutil.copy2(src_path, dest)
            self.status.set(f"Vista cliente exportada: {Path(dest).name}")
        except Exception as error:
            messagebox.showerror("Exportar", f"Error al exportar:\n{error}", parent=self)

    def _production_register_error(self):
        """Registrar un error de impresión manualmente con motivo predefinido."""
        plancha = self._selected_production_plancha()
        if not plancha:
            return
        pid = int(plancha["id"])
        name = plancha.get("name") or f"Plancha #{pid}"
        if not messagebox.askyesno("Registrar error",
                                   f"¿Registrar un error de impresión para «{name}»?\n\n"
                                   "Esto incrementará el contador de errores de la plancha.",
                                   parent=self):
            return
        # Elegir motivo
        reasons = [
            "Atasco de papel",
            "Color incorrecto",
            "Corte desfasado",
            "Material dañado",
            "Archivo incorrecto",
        ]
        reason_win = tk.Toplevel(self)
        reason_win.title("Motivo del error")
        reason_win.configure(background=COLORS.background)
        reason_win.geometry("380x320")
        reason_win.transient(self)
        reason_win.grab_set()
        selected_reason = tk.StringVar(value="")
        content = ttk.Frame(reason_win, padding=16)
        content.pack(fill="both", expand=True)
        ttk.Label(content, text="Seleccioná el motivo del error:", style="Module.TLabel").pack(anchor="w", pady=(0, 10))
        for reason in reasons:
            ttk.Radiobutton(content, text=reason, variable=selected_reason, value=reason).pack(anchor="w", pady=2)
        ttk.Radiobutton(content, text="Otro (escribir manually)", variable=selected_reason, value="__custom__").pack(anchor="w", pady=(8, 2))
        custom_entry = ttk.Entry(content)
        custom_entry.pack(fill="x", padx=(20, 0), pady=(0, 4))
        custom_entry.configure(state="disabled")
        def _toggle_custom(*_args):
            if selected_reason.get() == "__custom__":
                custom_entry.configure(state="normal")
                custom_entry.focus_set()
            else:
                custom_entry.configure(state="disabled")
        selected_reason.trace_add("write", _toggle_custom)
        result_box = {"reason": ""}
        def _confirm():
            r = selected_reason.get()
            if not r:
                messagebox.showwarning("Motivo requerido", "Elegí un motivo o escribí uno personalizado.", parent=reason_win)
                return
            if r == "__custom__":
                custom = custom_entry.get().strip()
                if not custom:
                    messagebox.showwarning("Motivo requerido", "Escribí una descripción del error.", parent=reason_win)
                    return
                result_box["reason"] = custom
            else:
                result_box["reason"] = r
            reason_win.destroy()
        def _cancel():
            result_box["reason"] = ""
            reason_win.destroy()
        btn_frame = ttk.Frame(content)
        btn_frame.pack(fill="x", pady=(12, 0))
        ttk.Button(btn_frame, text="Cancelar", command=_cancel, style="Secondary.TButton").pack(side="left")
        ttk.Button(btn_frame, text="Registrar", command=_confirm, style="Primary.TButton").pack(side="right")
        reason_win.protocol("WM_DELETE_WINDOW", _cancel)
        reason_win.wait_window()
        reason_text = result_box["reason"]
        if not reason_text:
            return
        # Registrar el error
        self.database.increment_plancha_print_count(pid, success=False)
        now = datetime.now().isoformat(timespec="seconds")
        self.database.connection.execute(
            "UPDATE plancha_projects SET last_printed_at = ?, updated_at = ? WHERE id = ?",
            (now, now, pid),
        )
        self.database.connection.execute(
            """INSERT INTO print_history(print_job_id, plancha_id, order_id, user_name, printer_name,
               configuration_json, copies, status, message, final_png_path, created_at)
               VALUES(0, ?, ?, '', '', '', 0, 'Error manual', ?, '', ?)""",
            (pid, plancha.get("order_id"), reason_text, now),
        )
        self.database.connection.commit()
        self.refresh_production()
        self.status.set(f"Error registrado para plancha #{pid}: {reason_text}")

    def _production_view_history(self):
        """Mostrar historial de impresión de la plancha seleccionada."""
        plancha = self._selected_production_plancha()
        if not plancha:
            return
        pid = int(plancha["id"])
        history = self.database.print_history(pid)
        if not history:
            messagebox.showinfo("Historial", "No hay eventos de impresión para esta plancha.", parent=self)
            return
        win = tk.Toplevel(self)
        win.title(f"Historial de impresión · Plancha #{pid}")
        win.configure(background=COLORS.background)
        win.geometry("780x400")
        win.transient(self)
        content = ttk.Frame(win, padding=12)
        content.pack(fill="both", expand=True)
        ttk.Label(content, text=f"HISTORIAL · PLANCHA #{pid}", style="Title.TLabel").pack(anchor="w", pady=(0, 10))
        cols = ("date", "status", "printer", "user", "message")
        tree = ttk.Treeview(content, columns=cols, show="headings", selectmode="browse")
        for key, label, width in (
            ("date", "Fecha", 150), ("status", "Estado", 120), ("printer", "Impresora", 160),
            ("user", "Usuario", 110), ("message", "Mensaje", 200),
        ):
            tree.heading(key, text=label)
            tree.column(key, width=width)
        scroll = ttk.Scrollbar(content, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        for row in history:
            tree.insert("", "end", values=(
                row.get("created_at", ""), row.get("status", ""),
                row.get("printer_name", ""), row.get("user_name", ""), row.get("message", ""),
            ))
        ttk.Button(content, text="Cerrar", command=win.destroy).pack(pady=(8, 0))

    def _open_continuous_from_production(self):
        from app.planchas.continuous_editor import ContinuousProductionEditor
        ContinuousProductionEditor(self, self.database)

    def choose_search_image(self, parent=None):
        path = filedialog.askopenfilename(
            parent=parent,
            title="Elegir imagen de referencia",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"), ("Todos los archivos", "*.*")],
        )
        if path:
            self.load_search_image(path)

    def show_visual_search_dialog(self):
        if getattr(self, "visual_search_dialog", None) and self.visual_search_dialog.winfo_exists():
            self.visual_search_dialog.lift()
            return
        dialog = tk.Toplevel(self)
        dialog.title("Buscar sticker")
        dialog.configure(background=COLORS.background)
        dialog.transient(self)
        dialog.grab_set()
        dialog.protocol("WM_DELETE_WINDOW", lambda: self.close_visual_search_dialog())
        self.visual_search_dialog = dialog

        content = ttk.Frame(dialog, padding=12, style="Panel.TFrame")
        content.pack(fill="both", expand=True)

        actions = ttk.Frame(content)
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text="Pegar imagen", command=lambda: self.paste_search_image(dialog)).pack(side="left")
        ttk.Button(actions, text="Elegir archivo", command=lambda: self.choose_search_image(dialog)).pack(side="left", padx=(8, 0))

        self.visual_status = tk.StringVar(value="Búsqueda local: pegá una imagen para buscar coincidencias visuales en la biblioteca.")
        ttk.Label(actions, textvariable=self.visual_status, style="Muted.TLabel").pack(side="left", padx=12)

        # Inicializar variables de búsqueda visual si no existen
        if not hasattr(self, "visual_search_mode"):
            self.visual_search_mode = tk.StringVar(value="Estricto")
            self.visual_search_threshold = tk.DoubleVar(value=90.0)
            self.visual_search_duplicates = tk.BooleanVar(value=False)
            self.visual_search_ignore_bg = tk.BooleanVar(value=True)

        # Panel de controles para la búsqueda visual avanzada
        settings_frame = ttk.Frame(content, style="Panel.TFrame")
        settings_frame.pack(fill="x", pady=(4, 8))

        ttk.Label(settings_frame, text="Modo:", style="Muted.TLabel").pack(side="left", padx=(4, 4))
        mode_cb = ttk.Combobox(
            settings_frame,
            textvariable=self.visual_search_mode,
            values=["Relacionado", "Estricto", "Casi exacto"],
            state="readonly",
            width=12
        )
        mode_cb.pack(side="left", padx=(0, 16))

        def on_mode_change(event):
            mode = self.visual_search_mode.get()
            if mode == "Relacionado":
                self.visual_search_threshold.set(75.0)
            elif mode == "Estricto":
                self.visual_search_threshold.set(90.0)
            elif mode == "Casi exacto":
                self.visual_search_threshold.set(96.0)
            self.start_visual_search()

        mode_cb.bind("<<ComboboxSelected>>", on_mode_change)

        ttk.Label(settings_frame, text="Similitud mín (%):", style="Muted.TLabel").pack(side="left", padx=(4, 4))
        threshold_spin = tk.Spinbox(
            settings_frame,
            from_=70.0,
            to=99.0,
            increment=1.0,
            textvariable=self.visual_search_threshold,
            width=5,
            command=self.start_visual_search,
            background=COLORS.panel,
            foreground=COLORS.text,
            buttonbackground=COLORS.panel
        )
        threshold_spin.pack(side="left", padx=(0, 16))
        threshold_spin.bind("<Return>", lambda e: self.start_visual_search())
        threshold_spin.bind("<FocusOut>", lambda e: self.start_visual_search())

        dup_cb = tk.Checkbutton(
            settings_frame,
            text="Buscar sólo duplicados",
            variable=self.visual_search_duplicates,
            command=self.start_visual_search,
            background=COLORS.background,
            foreground=COLORS.text,
            activebackground=COLORS.background,
            activeforeground=COLORS.text,
            selectcolor=COLORS.wine,
            font=(UI_FONT, 9),
            highlightthickness=0
        )
        dup_cb.pack(side="left", padx=(0, 16))

        bg_cb = tk.Checkbutton(
            settings_frame,
            text="Ignorar fondo y transparencia",
            variable=self.visual_search_ignore_bg,
            command=self.start_visual_search,
            background=COLORS.background,
            foreground=COLORS.text,
            activebackground=COLORS.background,
            activeforeground=COLORS.text,
            selectcolor=COLORS.wine,
            font=(UI_FONT, 9),
            highlightthickness=0
        )
        bg_cb.pack(side="left", padx=(0, 4))

        self.visual_preview = ttk.Label(content, text="Sin imagen de referencia", anchor="center", style="Muted.TLabel")
        self.visual_preview.pack(fill="x", padx=8, pady=(2, 6))

        self.visual_gallery = Gallery(content, self.preview_image, self.add_tag, self.remove_tag, lambda: None, self.toggle_selection, self.is_selected, self.dragged_paths, on_trash=self.trash_sticker)
        self.visual_gallery.pack(fill="both", expand=True)

        self.visual_query_path = None
        self.visual_search_cancel = None
        self.visual_search_id = 0

        self.center_window(dialog)

    def close_visual_search_dialog(self):
        if getattr(self, "visual_search_dialog", None) and self.visual_search_dialog.winfo_exists():
            self.visual_search_dialog.destroy()
            self.visual_search_dialog = None

    def paste_search_image(self, parent=None):
        try:
            from PIL import Image, ImageGrab

            clipboard = ImageGrab.grabclipboard()
            if isinstance(clipboard, Image.Image):
                cache = Path(__file__).parents[2] / ".cache"
                cache.mkdir(exist_ok=True)
                path = cache / "busqueda_visual.png"
                clipboard.save(path, "PNG")
                self.load_search_image(str(path))
                return
            if isinstance(clipboard, list) and clipboard:
                self.load_search_image(clipboard[0])
                return
            messagebox.showinfo("Buscador de stickers", "Copiá una imagen al portapapeles e intentá de nuevo.", parent=self)
        except Exception as error:
            messagebox.showerror("No se pudo pegar la imagen", str(error), parent=self)

    def load_search_image(self, path: str):
        from app.indexer.thumbnails import load_thumbnail

        preview = load_thumbnail(path, (160, 120))
        if not preview:
            messagebox.showwarning("Imagen no válida", "No se pudo leer esa imagen.", parent=self)
            return
        self.visual_query_path = path
        self.visual_preview.configure(image=preview, text="")
        self.visual_preview.image = preview
        self.start_visual_search()

    def start_visual_search(self):
        if not self.visual_query_path:
            return
        self.cancel_visual_search(silent=True)
        self.visual_search_id += 1
        search_id = self.visual_search_id
        self._visual_search_started[search_id] = time.perf_counter()
        cancel_event = threading.Event()
        self.visual_search_cancel = cancel_event
        candidates = self.database.visual_search_images()
        query_path = self.visual_query_path
        try:
            query_modified = Path(query_path).stat().st_mtime
        except OSError:
            query_modified = -1.0

        is_default = (
            self.visual_search_mode.get() == "Estricto" and
            abs(self.visual_search_threshold.get() - 90.0) < 0.1 and
            not self.visual_search_duplicates.get() and
            self.visual_search_ignore_bg.get()
        )

        cached_matches = self.database.cached_visual_matches(query_path, query_modified) if is_default else None
        if cached_matches:
            self.visual_search_cancel = None
            started = self._visual_search_started.pop(search_id, time.perf_counter())
            record_performance(
                "visual_search_cached",
                (time.perf_counter() - started) * 1000,
                candidates=len(candidates), results=len(cached_matches),
            )
            self.visual_status.set(f"Coincidencias recuperadas de la base local: {len(cached_matches)}.")
            self.show_visual_matches(cached_matches)
            return

        query_tags = self.database.tags_for_image(query_path)
        candidate_modified = {item["path"]: float(item.get("modified", -1)) for item in candidates}
        self.visual_status.set(f"Analizando coincidencias visuales: 0 de {len(candidates)}…")
        if hasattr(self, "visual_cancel_button"):
            self.visual_cancel_button.configure(state="normal")

        search_options = {
            "mode": self.visual_search_mode.get().lower().replace(" ", "_"),
            "minimum_score": self.visual_search_threshold.get(),
            "search_duplicates_only": self.visual_search_duplicates.get(),
            "ignore_background": self.visual_search_ignore_bg.get()
        }

        threading.Thread(
            target=self.run_visual_search,
            args=(query_path, candidates, cancel_event, search_id, query_tags, query_modified, candidate_modified, is_default, search_options),
            daemon=True
        ).start()

    def cancel_visual_search(self, silent: bool = False):
        if self.visual_search_cancel:
            self.visual_search_cancel.set()
            self.visual_search_cancel = None
            self._visual_search_started.pop(self.visual_search_id, None)
            if not silent:
                self.visual_status.set("Búsqueda cancelada.")

    def run_visual_search(self, query_path: str, candidates: list[dict], cancel_event: threading.Event, search_id: int, query_tags: str, query_modified: float, candidate_modified: dict[str, float], is_default: bool, search_options: dict):
        from app.ai.visual_search import find_similar

        def progress(done, total):
            self.after(0, lambda: self.visual_status.set(f"Analizando coincidencias visuales: {done} de {total}…"))
        def save_signatures(rows):
            self.after(0, lambda values=list(rows): self.database.update_visual_signatures(values))

        matches = find_similar(
            query_path,
            candidates,
            progress=progress,
            limit=50,
            cancelled=cancel_event.is_set,
            signature_ready=save_signatures,
            query_tags=query_tags,
            mode=search_options["mode"],
            minimum_score=search_options["minimum_score"],
            search_duplicates_only=search_options["search_duplicates_only"],
            ignore_background=search_options["ignore_background"]
        )

        if matches and is_default and not cancel_event.is_set():
            self.after(0, lambda values=matches: self.database.save_visual_matches(query_path, query_modified, values, candidate_modified))
        self.after(0, lambda: self.finish_visual_search(matches, cancel_event, search_id))

    def finish_visual_search(self, matches, cancel_event: threading.Event, search_id: int):
        if search_id != self.visual_search_id or cancel_event.is_set():
            return
        self.visual_search_cancel = None
        if hasattr(self, "visual_cancel_button"):
            self.visual_cancel_button.configure(state="disabled")
        started = self._visual_search_started.pop(search_id, time.perf_counter())
        record_performance(
            "visual_search_full",
            (time.perf_counter() - started) * 1000,
            results=len(matches or []),
        )
        self.show_visual_matches(matches or [])

    def show_visual_matches(self, matches: list[tuple[str, float]]):
        if not matches:
            self.visual_gallery.show_images([])
            self.visual_status.set("No se encontraron stickers con una similitud suficiente en el banco de imágenes.")
            return
        paths = [path for path, _score in matches]
        images = self.database.images_by_paths(paths)
        scores = {path: score for path, score in matches}
        for image in images:
            image["visual_match_score"] = scores[image["path"]]
            image["tags"] = (image.get("tags") or "") + f" · Coincidencia visual: {scores[image['path']]:.1f}%"
        self.visual_gallery.show_images(images)
        exact = sum(score == 100 for _path, score in matches)
        strongest = max(scores.values())
        level = "exacta" if strongest >= 99.95 else ("muy alta" if strongest >= 88 else ("probable" if strongest >= 76 else "baja"))
        self.visual_status.set(
            f"{len(images)} coincidencias visuales · mejor resultado: {strongest:.1f}% ({level}) · "
            f"exactas: {exact}. Las tarjetas muestran su puntuación."
        )

    def is_selected(self, image: dict) -> bool:
        return image.get("path") in self.selected_images

    def refresh_order_selection_highlights(self):
        """Actualiza el resaltado 'in_selection' en todos los tabs de pedido abiertos."""
        for tab in self.order_tabs.values():
            # Con el nuevo sistema de vista con miniaturas, simplemente re-renderizamos
            if hasattr(tab, "order_designs_scrollable"):
                self.render_order_workspace(tab)

    def toggle_selection(self, image: dict) -> bool:
        path = image["path"]
        if path in self.selected_images:
            del self.selected_images[path]
            selected = False
            action = "Se quitó de Seleccionados"
        else:
            self.selected_images[path] = image.copy()
            selected = True
            action = "Se agregó a Seleccionados"
        self.selected_gallery.show_images(list(self.selected_images.values()))
        self.gallery.set_selection_visual(path, selected)
        self.tabs.tab(self.selected_tab, text=f"Seleccionados ({len(self.selected_images)})")
        if hasattr(self, "selected_navigation_button"):
            self.selected_navigation_button.configure(text=f"Seleccionados ({len(self.selected_images)})")
        self.status.set(f"{action}: {len(self.selected_images)} diseño(s).")
        self.refresh_order_selection_highlights()
        return selected

    def clear_selected(self):
        if not self.selected_images:
            return
        self.selected_images.clear()
        self.selected_gallery.show_images([])
        self.gallery.clear_selection_visuals()
        self.tabs.tab(self.selected_tab, text="Seleccionados (0)")
        if hasattr(self, "selected_navigation_button"):
            self.selected_navigation_button.configure(text="Seleccionados (0)")
        self.status.set("Se deseleccionaron todos los diseños.")
        self.refresh_order_selection_highlights()

    def select_all_visible(self):
        """Selecciona en bloque los diseños disponibles con los filtros actuales."""
        images = self.gallery.current_items
        if not images:
            messagebox.showinfo("Seleccionar todos", "No hay diseños visibles para seleccionar.", parent=self)
            return
        added = 0
        for image in images:
            if image["path"] not in self.selected_images:
                self.selected_images[image["path"]] = image.copy()
                added += 1
            self.gallery.set_selection_visual(image["path"], True)
        self.selected_gallery.show_images(list(self.selected_images.values()))
        self.tabs.tab(self.selected_tab, text=f"Seleccionados ({len(self.selected_images)})")
        if hasattr(self, "selected_navigation_button"):
            self.selected_navigation_button.configure(text=f"Seleccionados ({len(self.selected_images)})")
        self.status.set(f"{added} diseño(s) visibles agregados a Seleccionados.")
        self.refresh_order_selection_highlights()

    def add_tag_to_selected(self):
        if not self.selected_images:
            messagebox.showinfo("Seleccionados", "Primero seleccioná uno o más stickers posando el mouse y tocando Ctrl.", parent=self)
            return
        def add_to_all(tag: str):
            try:
                for image in self.selected_images.values():
                    self.database.add_tag(image["path"], tag, commit=False)
                self.database.commit()
                self.refresh_tags()
                self.status.set(f"Etiqueta «{tag.title()}» agregada a {len(self.selected_images)} diseño(s).")
                return True
            except ValueError as error:
                messagebox.showwarning("Etiqueta inválida", str(error), parent=self)
                return False

        self.ask_tag_with_suggestion("Agregar etiqueta", "Etiqueta para todos los seleccionados:", add_to_all)

    def ask_plancha_mode(self) -> str | None:
        """Permite elegir el modo antes de crear una nueva plancha."""
        dialog = tk.Toplevel(self)
        dialog.title("Nueva plancha")
        dialog.configure(background="#111314")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("620x300")
        selected = {"value": None}
        tk.Label(dialog, text="¿Cómo querés armar la plancha?", background="#111314", foreground="#fff4ec", font=("Bahnschrift SemiCondensed", 18, "bold")).pack(anchor="w", padx=22, pady=(22, 7))
        tk.Label(dialog, text="Elegí un modo de trabajo. Ambos conservan intactos los archivos originales.", background="#111314", foreground="#b9a79b").pack(anchor="w", padx=22, pady=(0, 15))
        options = tk.Frame(dialog, background="#111314")
        options.pack(fill="both", expand=True, padx=20, pady=(0, 14))

        def choose(value: str):
            selected["value"] = value
            dialog.destroy()

        for title, detail, value in (
            ("Plancha libre", "Ubicá stickers, optimizá los espacios y editá una plancha A4 con libertad.", "free"),
            ("Plancha regular", "Trabajá con patrones de casillas fijas sin duplicar los archivos originales.", "regular"),
        ):
            card = tk.Frame(options, background="#1b1e1f", highlightbackground="#d60916", highlightthickness=1, cursor="hand2")
            card.pack(side="left", fill="both", expand=True, padx=5)
            tk.Label(card, text=title, background="#1b1e1f", foreground="#f3e0d2", font=("Bahnschrift SemiCondensed", 14, "bold"), cursor="hand2").pack(anchor="w", padx=15, pady=(18, 5))
            tk.Label(card, text=detail, background="#1b1e1f", foreground="#c7b6aa", wraplength=245, justify="left", cursor="hand2").pack(anchor="w", padx=15, pady=(0, 14))
            ttk.Button(card, text="Elegir", command=lambda choice=value: choose(choice)).pack(anchor="w", padx=15, pady=(0, 16))
            card.bind("<Button-1>", lambda _event, choice=value: choose(choice))
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        self.wait_window(dialog)
        return selected["value"]

    def open_plancha_constructor(self):
        mode = self.ask_plancha_mode()
        if not mode:
            return
        if mode == "regular":
            from app.planchas.template_editor import RegularTemplateEditor
            RegularTemplateEditor(
                self,
                list(self.selected_images.values()),
                database=self.database,
                library_images=self.database.search(limit=10000),
            )
            return
        if not self.selected_images:
            messagebox.showinfo("Plancha libre", "Seleccioná uno o más diseños con Ctrl y abrí Seleccionados.", parent=self)
            return
        from app.planchas.editor import PlanchaEditor

        PlanchaEditor(
            self,
            list(self.selected_images.values()),
            database=self.database,
            library_images=self.database.search(limit=10000),
        )

    def ask_tag_with_suggestion(self, title: str, prompt: str, on_add=None) -> str | None:
        """Pide una etiqueta mostrando en vivo la coincidencia existente más cercana."""
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.configure(background="#111314")
        dialog.transient(self)
        dialog.resizable(False, False)
        value = tk.StringVar()
        suggestion = tk.StringVar(value="Escribí para ver una sugerencia.")
        selected = {"value": None}
        tk.Label(dialog, text=prompt, background="#111314", foreground="#e7d3c4").pack(anchor="w", padx=16, pady=(14, 5))
        entry = ttk.Combobox(dialog, textvariable=value, width=36, style="Search.TCombobox")
        entry.pack(fill="x", padx=16)
        hint = tk.Label(dialog, textvariable=suggestion, background="#111314", foreground="#b9a79b", cursor="hand2", anchor="w")
        hint.pack(fill="x", padx=16, pady=(7, 0))

        def update_suggestion(*_args):
            matches = self.database.suggestions(value.get(), limit=1)
            if matches:
                closest = matches[0]
                entry["values"] = self.database.suggestions(value.get(), limit=6)
                suggestion.set(f"Sugerencia: {closest}")
                hint.closest = closest
            else:
                entry["values"] = ()
                suggestion.set("Sin etiqueta similar.")
                hint.closest = ""

        def use_suggestion(_event=None):
            if getattr(hint, "closest", ""):
                value.set(hint.closest)
                entry.icursor(tk.END)

        def accept(_event=None):
            tag = value.get().strip()
            if not tag:
                return
            if on_add is None:
                selected["value"] = tag
                dialog.destroy()
                return
            if on_add(tag):
                value.set("")
                entry.focus_set()

        value.trace_add("write", update_suggestion)
        hint.bind("<Button-1>", use_suggestion)
        buttons = ttk.Frame(dialog, padding=(16, 12))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Listo" if on_add else "Cancelar", command=dialog.destroy).pack(side="right")
        ttk.Button(buttons, text="Agregar", command=accept).pack(side="right", padx=(0, 8))
        dialog.bind("<Return>", accept)
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        self.center_window(dialog)
        dialog.grab_set()
        entry.focus_set()
        self.wait_window(dialog)
        return selected["value"]

    def dragged_paths(self, image: dict) -> list[str]:
        """Un seleccionado arrastra el conjunto; uno suelto arrastra solo ese archivo."""
        if image["path"] in self.selected_images:
            return list(self.selected_images)
        return [image["path"]]

    def refresh_collections(self):
        self.refresh_categories()
        self.refresh_tags()

    def open_sticker_studio(self, initial_paths=None):
        """Abre una única cola no destructiva de construcción y revisión."""
        try:
            window = self.sticker_studio_window
            if window is not None and window.winfo_exists():
                if initial_paths:
                    window.add_paths([Path(path) for path in initial_paths if path])
                window.deiconify()
                window.lift()
                window.focus_force()
                return

            def refresh_library():
                self.refresh_collections()
                self.refresh(self.search.query.get())

            semantic_analyzer = None
            if self.ai_provider.get() == "Gemini" and self.gemini_api_key:
                api_key, model = self.gemini_api_key, self.gemini_model

                def semantic_analyzer(path, progress):
                    from app.ai.gemini import analyze_image
                    return analyze_image(path, api_key, model, progress)

            self.sticker_studio_window = StickerStudio(
                self, self.database, refresh_library, semantic_analyzer=semantic_analyzer,
            )
            if initial_paths:
                self.sticker_studio_window.add_paths([Path(path) for path in initial_paths if path])
            self.sticker_studio_window.bind(
                "<Destroy>",
                lambda event: setattr(self, "sticker_studio_window", None)
                if event.widget is self.sticker_studio_window else None,
                add="+",
            )
                
        except Exception as e:
            import traceback
            from tkinter import messagebox
            error_details = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            
            # Guardar el error en un archivo de log
            log_path = Path("error_sticker_studio.log")
            try:
                log_path.write_text(error_details, encoding="utf-8")
                messagebox.showerror(
                    "Error al abrir el Creador de Stickers",
                    f"No se pudo abrir el creador de stickers.\n\n"
                    f"Error: {e}\n\n"
                    f"El detalle completo se guardó en:\n{log_path.absolute()}",
                    parent=self
                )
            except:
                messagebox.showerror(
                    "Error al abrir el Creador de Stickers",
                    f"No se pudo abrir el creador de stickers.\n\nError: {e}",
                    parent=self
                )

    def refresh_categories(self):
        for widget in self.categories_frame.winfo_children():
            widget.destroy()
        active = {name for name, value in self.selected_categories.items() if value.get()}
        self.selected_categories = {}
        categories = self.database.category_counts()
        if hasattr(self, "tag_category_picker"):
            names = [category for category, _count in categories]
            self.tag_category_picker["values"] = ["Todas las categorías", *names]
            if self.tag_category_filter.get() not in {"Todas las categorías", *names}:
                self.tag_category_filter.set("Todas las categorías")
        for category, count in categories:
            value = tk.BooleanVar(value=category in active)
            self.selected_categories[category] = value
            item = tk.Checkbutton(self.categories_frame, text=f"▸ {category.title()}  ({count})", variable=value, command=lambda: self.refresh(), anchor="w", justify="left", background=COLORS.panel, foreground=COLORS.text, activebackground=COLORS.panel, activeforeground=COLORS.text, selectcolor=COLORS.wine, font=(UI_FONT, 10), highlightthickness=0)
            item.pack(fill="x", anchor="w", padx=5, pady=1)
            item.bind("<Button-3>", lambda event, name=category: self.show_category_context(event, name))
            item.bind("<MouseWheel>", lambda e: self.scroll_tags_with_wheel(e))

    def refresh_tags(self):
        for widget in self.tags_frame.winfo_children():
            widget.destroy()
        active = {tag for tag, value in self.selected_tags.items() if value.get()}
        self.selected_tags = {}
        term = self.tag_filter_query.get().strip() if hasattr(self, "tag_filter_query") else ""
        category = self.tag_category_filter.get() if hasattr(self, "tag_category_filter") else ""
        if category == "Todas las categorías":
            category = ""
        tags = self.database.tag_counts(limit=200, query=term, category=category)
        for tag, count in tags:
            value = tk.BooleanVar(value=tag in active)
            self.selected_tags[tag] = value
            item = tk.Checkbutton(self.tags_frame, text=f"{tag.title()}  ({count})", variable=value, command=lambda: self.refresh(), anchor="w", justify="left", background=COLORS.panel, foreground=COLORS.text, activebackground=COLORS.panel, activeforeground=COLORS.text, selectcolor=COLORS.wine, font=(UI_FONT, 10), highlightthickness=0)
            item.pack(fill="x", anchor="w", padx=5, pady=1)
            item.bind("<Button-3>", lambda event, name=tag: self.show_tag_context(event, name))
            item.bind("<MouseWheel>", lambda e: self.scroll_tags_with_wheel(e))
        if self.database.tag_total() > len(tags) and not term and not category:
            tk.Label(self.tags_frame, text="Mostrando las 200 etiquetas más usadas.\nUsá el buscador para el resto.", background=COLORS.panel, foreground=COLORS.muted, justify="left", wraplength=185, font=(UI_FONT, 10)).pack(fill="x", padx=6, pady=(8, 2))

    def scroll_tags_with_wheel(self, event):
        """Desplaza el panel contextual aunque el cursor esté sobre una etiqueta."""
        delta = int(-event.delta / 120) if event.delta else 0
        if delta:
            self.tags_canvas.yview_scroll(delta, "units")
        return "break"

    def show_category_context(self, event, category: str):
        menu = tk.Menu(self, tearoff=0)
        configure_menu(menu)
        menu.add_command(label="Quitar categoría de los diseños", command=lambda: self.delete_category_from_library(category))
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()
        return "break"

    def delete_category_from_library(self, category: str):
        message = f"¿Quitar la categoría «{category.title()}» de todos los diseños?\n\nLos archivos y etiquetas no se modificarán."
        if not messagebox.askyesno("Quitar categoría", message, parent=self):
            return
        count = self.database.clear_category(category)
        self.refresh_collections()
        self.refresh()
        self.status.set(f"Se quitó la categoría «{category.title()}» de {count} diseño(s).")

    def show_tag_context(self, event, tag: str):
        menu = tk.Menu(self, tearoff=0)
        configure_menu(menu)
        menu.add_command(label="Eliminar etiqueta", command=lambda: self.delete_tag_from_library(tag))
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()
        return "break"

    def delete_tag_from_library(self, tag: str):
        if not messagebox.askyesno("Eliminar etiqueta", f"¿Eliminar «{tag.title()}» de todos los stickers?", parent=self):
            return
        self.database.delete_tag(tag)
        self.refresh_tags()
        self.refresh()
        self.status.set(f"Etiqueta «{tag.title()}» eliminada de la biblioteca.")

    def active_tags(self) -> list[str]:
        return [tag for tag, value in self.selected_tags.items() if value.get()]

    def active_categories(self) -> list[str]:
        return [category for category, value in self.selected_categories.items() if value.get()]

    def clear_all_tags(self):
        for value in self.selected_tags.values():
            value.set(False)
        for value in self.selected_categories.values():
            value.set(False)
        self.refresh()
        self.status.set("Filtros desmarcados.")

    def index_folder(self):
        folder = filedialog.askdirectory(title="Elige la carpeta con diseños")
        if not folder:
            return
        try:
            count = 0
            for image in scan_folder(folder):
                self.database.upsert(image)
                count += 1
            self.database.remove_missing()
            self.database.commit()
            self.status.set(f"Se indexaron {count} diseños.")
            self.refresh_collections()
            self.refresh(self.search.query.get())
        except OSError as error:
            messagebox.showerror("No se pudo indexar", str(error))

    def refresh(self, query=None):
        query = self.search.query.get() if query is None else query
        tags = self.active_tags()
        categories = self.active_categories()
        total = self.database.count(query, self.current_extension, tags, categories)
        images = self.database.search(
            query, limit=self.gallery.display_capacity(), extension=self.current_extension, tags=tags, categories=categories, random_order=True
        )
        self.gallery.show_images(images)

    def predict_search(self, query: str):
        """Busca por etiquetas, categorías, clientes y planchas, nunca por nombre de archivo."""
        if not query.strip():
            return
        tags = self.active_tags()
        categories = self.active_categories()
        total = self.database.count(query, self.current_extension, tags, categories)
        images = self.database.search(
            query, limit=50, extension=self.current_extension, tags=tags, categories=categories, random_order=False
        )
        self.gallery.show_images(images)
        self.status.set(f"Coincidencias predictivas: {len(images)} de {total} diseños (máximo 50)." if total else "No hay coincidencias predictivas.")

    def show_random_grid(self):
        """Llena la cuadrícula con la cantidad de diseños elegida por el usuario."""
        self.update_idletasks()
        total = self.database.count()
        images = self.database.featured_random(self.gallery.display_capacity())
        self.gallery.show_images(images)
        self.status.set(f"Aleatorios destacados: {len(images)} de {total} diseños." if total else "No hay diseños para mostrar.")

    def prepare_visual_scores(self):
        candidates = self.database.images_missing_visual_score()
        if not candidates:
            return

        def work():
            from app.ai.visual_search import visual_impact

            batch = []
            for item in candidates:
                try:
                    batch.append((visual_impact(item["path"]), item["path"]))
                except Exception:
                    batch.append((0.0, item["path"]))
                if len(batch) == 60:
                    completed = batch
                    batch = []
                    self.after(0, lambda values=completed: self.database.update_visual_scores(values))
            if batch:
                self.after(0, lambda values=batch: self.database.update_visual_scores(values))

        threading.Thread(target=work, daemon=True).start()

    def preview_image(self, image):
        if not image:
            return
        from app.indexer.thumbnails import load_thumbnail

        preview = tk.Toplevel(self)
        preview.title(image["name"])
        preview.geometry("1080x720")
        preview.minsize(760, 520)
        preview.configure(background="#080909")
        preview.transient(self)
        self.center_window(preview)
        content = tk.Frame(preview, background="#080909")
        content.pack(fill="both", expand=True, padx=16, pady=16)
        visual = tk.Frame(content, background="#080909")
        visual.pack(side="left", fill="both", expand=True)
        photo = load_thumbnail(image["path"], (760, 650))
        if photo:
            label = ttk.Label(visual, image=photo, style="Card.TLabel")
            label.image = photo
            label.pack(expand=True)
        else:
            ttk.Label(visual, text="No se pudo generar la vista previa.", padding=24).pack(expand=True)

        details = tk.Frame(content, width=290, background="#1c1c1c")
        details.pack(side="right", fill="y", padx=(16, 0))
        details.pack_propagate(False)
        tk.Label(details, text="Información", background="#1c1c1c", foreground="#f3e0d2", font=("Bahnschrift SemiCondensed", 13, "bold")).pack(pady=(14, 10))
        source = Path(image["path"])
        stat = source.stat()
        dimensions = self.image_dimensions(source)
        entries = (
            ("Archivo", image["name"]),
            ("Dimensiones", dimensions),
            ("Tamaño", self.human_size(stat.st_size)),
            ("Creado", datetime.fromtimestamp(stat.st_ctime).strftime("%d/%m/%Y %H:%M")),
            ("Modificado", datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M")),
        )
        for title, value in entries:
            row = tk.Frame(details, background="#1c1c1c")
            row.pack(fill="x", padx=14, pady=3)
            tk.Label(row, text=title, width=11, anchor="w", background="#1c1c1c", foreground="#a9a9a9").pack(side="left")
            tk.Label(row, text=value, anchor="w", background="#1c1c1c", foreground="#f3e0d2", wraplength=150).pack(side="left", fill="x", expand=True)
        tk.Label(details, text="Ruta del archivo", background="#1c1c1c", foreground="#f3e0d2", font=("Bahnschrift SemiCondensed", 11, "bold")).pack(pady=(18, 5))
        path_box = ttk.Entry(details)
        path_box.insert(0, str(source))
        path_box.configure(state="readonly")
        path_box.pack(fill="x", padx=14)
        ttk.Button(details, text="Buscar archivo", command=lambda: self.reveal_in_folder(source)).pack(anchor="e", padx=14, pady=(6, 0))
        ttk.Button(details, text="Buscar con Google Lens", command=lambda: self.open_google_lens()).pack(anchor="e", padx=14, pady=(6, 0))
        ttk.Button(
            details,
            text="Eliminar archivo",
            command=lambda current=image, window=preview: self.delete_sticker_file(current, window),
            style="Danger.TButton",
        ).pack(fill="x", padx=14, pady=(10, 0))
        category = (image.get("category") or "").strip()
        tk.Label(details, text="Categoría", background="#1c1c1c", foreground="#f3e0d2", font=("Bahnschrift SemiCondensed", 11, "bold")).pack(pady=(15, 5))
        category_row = tk.Frame(details, background="#1c1c1c")
        category_row.pack(fill="x", padx=14)
        category_value = tk.StringVar(value=category)
        category_options = [name for name, _count in self.database.category_counts()]
        category_box = ttk.Combobox(category_row, textvariable=category_value, values=category_options, state="normal")
        category_box.pack(side="left", fill="x", expand=True)
        ttk.Button(
            category_row,
            text="Guardar",
            command=lambda current=image: self.set_preview_category(current, category_value.get(), preview),
        ).pack(side="left", padx=(6, 0))
        category_box.bind("<Return>", lambda _event, current=image: self.set_preview_category(current, category_value.get(), preview))
        if category:
            ttk.Button(category_row, text="Quitar", style="Secondary.TButton", command=lambda current=image, value=category: self.clear_preview_category(current, value, preview)).pack(side="left", padx=(6, 0))
        tk.Label(details, text="Etiquetas", background="#1c1c1c", foreground="#f3e0d2", font=("Bahnschrift SemiCondensed", 11, "bold")).pack(pady=(18, 5))
        tags_text = tk.StringVar(value=image.get("tags") or "Sin etiquetas")
        tk.Label(details, textvariable=tags_text, anchor="w", justify="left", wraplength=245, background="#101010", foreground="#b9a79b", padx=8, pady=7).pack(fill="x", padx=14)
        tag_value = tk.StringVar()
        tag_bar = tk.Frame(details, background="#1c1c1c")
        tag_bar.pack(fill="x", padx=14, pady=(8, 0))
        tag_entry = ttk.Entry(tag_bar, textvariable=tag_value, style="Search.TEntry")
        tag_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(tag_bar, text="Agregar", command=lambda: self.add_preview_tag(image, tag_value, tags_text)).pack(side="left", padx=(6, 0))
        tag_entry.bind("<Return>", lambda _event: self.add_preview_tag(image, tag_value, tags_text))
        existing_tags = [tag.strip() for tag in (image.get("tags") or "").split(" · ") if tag.strip()]
        if existing_tags:
            remove_bar = tk.Frame(details, background="#1c1c1c")
            remove_bar.pack(fill="x", padx=14, pady=(6, 0))
            remove_tag_value = tk.StringVar(value=existing_tags[0])
            ttk.Combobox(remove_bar, textvariable=remove_tag_value, values=existing_tags, state="readonly", width=19).pack(side="left", fill="x", expand=True)
            ttk.Button(remove_bar, text="Quitar", style="Secondary.TButton", command=lambda: self.remove_preview_tag(image, remove_tag_value.get(), tags_text, preview)).pack(side="left", padx=(6, 0))
        tag_hint = tk.StringVar(value="")
        hint_label = tk.Label(details, textvariable=tag_hint, anchor="w", background="#1c1c1c", foreground="#b9a79b", cursor="hand2")
        hint_label.pack(fill="x", padx=14, pady=(3, 0))

        def update_preview_suggestion(*_args):
            matches = self.database.suggestions(tag_value.get(), limit=1)
            closest = matches[0] if matches else ""
            hint_label.closest = closest
            tag_hint.set(f"Sugerencia: {closest}" if closest else "")

        tag_value.trace_add("write", update_preview_suggestion)
        hint_label.bind("<Button-1>", lambda _event: tag_value.set(getattr(hint_label, "closest", "")) if getattr(hint_label, "closest", "") else None)
        ttk.Button(details, text="Analizar con IA", command=lambda: self.analyze_image(image, preview)).pack(fill="x", padx=14, pady=(12, 0))

    @staticmethod
    def human_size(size: int) -> str:
        return f"{size / (1024 * 1024):.1f} MiB" if size >= 1024 * 1024 else f"{size / 1024:.0f} KiB"

    def center_window(self, window):
        """Centra cuadros auxiliares respecto de la pantalla disponible."""
        window.update_idletasks()
        width, height = window.winfo_width(), window.winfo_height()
        x = (window.winfo_screenwidth() - width) // 2
        y = (window.winfo_screenheight() - height) // 2
        window.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")

    @staticmethod
    def image_dimensions(path: Path) -> str:
        try:
            from PIL import Image
            with Image.open(path) as photo:
                return f"{photo.width} × {photo.height}"
        except Exception:
            return "No disponible"

    def reveal_in_folder(self, path: Path):
        """Abre el Explorador de Windows con el archivo de origen seleccionado."""
        if not path.exists():
            messagebox.showwarning("Archivo no encontrado", "El archivo ya no existe en su carpeta de origen.", parent=self)
            return
        try:
            # Explorer requiere que /select, y la ruta sean argumentos separados.
            subprocess.Popen(["explorer.exe", "/select,", str(path)])
        except OSError as error:
            messagebox.showerror("No se pudo abrir la carpeta", str(error), parent=self)

    def delete_sticker_file(self, image: dict, preview=None):
        """Borra de forma explícita el archivo y su ficha de la biblioteca."""
        source = Path(image["path"])
        confirmation = (
            f"Vas a eliminar definitivamente este sticker:\n\n{source.name}\n\n"
            "También se quitarán sus etiquetas, historial y referencias internas. Esta acción no se puede deshacer."
        )
        if not messagebox.askyesno("Eliminar archivo definitivamente", confirmation, icon="warning", parent=preview or self):
            return
        try:
            if source.exists():
                source.unlink()
            self.database.delete_image(image["path"])
        except OSError as error:
            messagebox.showerror("No se pudo eliminar el archivo", str(error), parent=preview or self)
            return
        self.selected_images.pop(image["path"], None)
        if preview is not None and preview.winfo_exists():
            preview.destroy()
        self.selected_gallery.show_images(list(self.selected_images.values()))
        self.tabs.tab(self.selected_tab, text=f"Seleccionados ({len(self.selected_images)})")
        if hasattr(self, "selected_navigation_button"):
            self.selected_navigation_button.configure(text=f"Seleccionados ({len(self.selected_images)})")
        self.refresh_collections()
        self.refresh(self.search.query.get())
        self.status.set(f"Se eliminó definitivamente «{source.name}».")

    def open_google_lens(self):
        webbrowser.open("https://lens.google.com/")
        self.status.set("Google Lens abierto. Elegí o arrastrá allí el archivo desde su carpeta.")

    def add_preview_tag(self, image, tag_value, tags_text):
        tag = tag_value.get().strip()
        if not tag:
            return
        try:
            self.database.add_tag(image["path"], tag)
            existing = [] if tags_text.get() == "Sin etiquetas" else tags_text.get().split(" | ")
            if tag not in existing:
                existing.append(tag)
            tags_text.set(" | ".join(existing))
            tag_value.set("")
            self.refresh_tags()
            self.status.set("Etiqueta agregada. Pulsa Refrescar para actualizar los diseños.")
        except ValueError as error:
            messagebox.showwarning("Etiqueta inválida", str(error), parent=self)

    def remove_preview_tag(self, image, tag: str, tags_text, preview):
        tag = tag.strip()
        if not tag:
            return
        self.database.remove_tag(image["path"], tag)
        tags = [value.strip() for value in tags_text.get().split(" | ") if value.strip() and value.strip() != tag]
        tags_text.set(" | ".join(tags) if tags else "Sin etiquetas")
        image["tags"] = " · ".join(tags)
        self.refresh_tags()
        self.status.set(f"Se quitó la etiqueta «{tag.title()}» del diseño.")
        # Se reconstruye el cuadro para actualizar la lista de etiquetas.
        if preview.winfo_exists():
            self.after_idle(lambda: (preview.destroy(), self.preview_image(image)))

    def clear_preview_category(self, image, category: str, preview):
        if not messagebox.askyesno(
            "Quitar categoría",
            f"¿Quitar «{category.title()}» solamente de este diseño?",
            parent=preview,
        ):
            return
        self.database.clear_image_category(image["path"])
        image["category"] = ""
        self.refresh_collections()
        self.refresh(self.search.query.get())
        self.status.set(f"Se quitó la categoría «{category.title()}» del diseño.")
        if preview.winfo_exists():
            preview.destroy()
        self.preview_image(image)

    def set_preview_category(self, image, category: str, preview):
        """Asigna una categoría manual desde la ficha del diseño."""
        category = category.strip()
        if not category:
            messagebox.showwarning("Categoría requerida", "Escribí o elegí una categoría para guardarla.", parent=preview)
            return
        self.database.set_image_category(image["path"], category)
        image["category"] = category.title()
        self.refresh_collections()
        self.refresh(self.search.query.get())
        self.status.set(f"Categoría «{image['category']}» agregada al diseño.")
        if preview.winfo_exists():
            preview.destroy()
        self.preview_image(image)

    def analyze_image(self, image, preview):
        dialog = tk.Toplevel(preview)
        dialog.title("Análisis con IA")
        dialog.configure(background="#080909")
        dialog.transient(preview)
        dialog.geometry("430x190")
        dialog.resizable(False, False)
        status = tk.StringVar(value="Preparando el análisis…")
        ttk.Label(dialog, text="Analizando sticker con IA", style="Title.TLabel", padding=(22, 22, 22, 8)).pack(anchor="w")
        ttk.Label(dialog, textvariable=status, style="Muted.TLabel", padding=(22, 0, 22, 12)).pack(anchor="w")
        progress = ttk.Progressbar(dialog, mode="indeterminate", length=370)
        progress.pack(padx=22, fill="x")
        progress.start(12)

        provider = self.ai_provider.get()
        model = self.gemini_model if provider == "Gemini" else "local-v1"
        cache_model = f"{model}:structured-v3" if provider == "Gemini" else model
        cached = self.database.ai_result(image["path"], provider, cache_model, image["modified"])
        if cached:
            status.set("Resultado recuperado al instante desde la caché.")
            self.after(60, lambda: self.show_analysis_result(dialog, image, cached))
            return

        def update_progress(message):
            if dialog.winfo_exists():
                self.after(0, lambda: status.set(message))

        def work():
            if provider == "Gemini":
                from app.ai.gemini import analyze_image
                result = analyze_image(image["path"], self.gemini_api_key, self.gemini_model, update_progress)
            else:
                from app.ai.analyzer import analyze_image
                result = analyze_image(image["path"], update_progress)
            def complete():
                if not result.get("missing") and not result.get("errors"):
                    self.database.save_ai_result(image["path"], provider, cache_model, image["modified"], result)
                self.show_analysis_result(dialog, image, result)
            self.after(0, complete)

        threading.Thread(target=work, daemon=True).start()

    def show_analysis_result(self, dialog, image, result):
        from app.ai.naming import sticker_names

        for widget in dialog.winfo_children():
            widget.destroy()
        dialog.geometry("560x560")
        ttk.Label(dialog, text="Resultados de IA", style="Title.TLabel", padding=(18, 14, 18, 4)).pack(anchor="w")
        if result["missing"]:
            ttk.Label(dialog, text="Instala las dependencias de IA para activar: " + ", ".join(result["missing"]), style="Muted.TLabel", padding=(18, 0, 18, 8), wraplength=470).pack(anchor="w")
        if result["errors"]:
            ttk.Label(dialog, text="Detalle técnico: " + " · ".join(result["errors"]), style="Muted.TLabel", padding=(18, 0, 18, 8), wraplength=470).pack(anchor="w")
        ttk.Label(dialog, text="Texto reconocido (español, inglés y números): " + (result["text"] or "No se detectó texto"), padding=(18, 4), wraplength=470).pack(anchor="w")
        ttk.Label(dialog, text="Descripción visual: " + (result["caption"] or "No se pudo identificar el contenido"), padding=(18, 4), wraplength=470).pack(anchor="w")
        if result.get("confidence"):
            ttk.Label(dialog, text="Confianza de identificación: " + result["confidence"], padding=(18, 4), style="Tag.TLabel").pack(anchor="w")
        reference = (result.get("references") or [None])[0]
        category, generated_names = sticker_names(result["caption"], result["text"], reference)
        category = result.get("category") or category
        names = result.get("names") or generated_names
        if reference:
            ttk.Label(dialog, text=f"Referencia reconocida: {reference['name']} · {reference['kind']}", padding=(18, 10, 18, 2), style="Tag.TLabel").pack(anchor="w")
        ttk.Label(dialog, text="Categoría sugerida: " + category, padding=(18, 12, 18, 2), style="Tag.TLabel").pack(anchor="w")
        category_value = tk.StringVar(value=category)
        category_options = [category] + [name for name, _count in self.database.category_counts() if name != category]
        ttk.Combobox(dialog, textvariable=category_value, values=category_options, state="readonly", width=42).pack(anchor="w", padx=18, pady=(0, 6))
        ttk.Label(dialog, text="Posibles nombres para Doccione:", padding=(18, 0, 18, 3)).pack(anchor="w")
        name_value = tk.StringVar(value=names[0])
        for name in names[:5]:
            tk.Radiobutton(dialog, text=name, variable=name_value, value=name, anchor="w", justify="left", background="#080909", foreground="#e7d3c4", activebackground="#080909", activeforeground="#fff4ec", selectcolor="#d60916", wraplength=500).pack(fill="x", padx=18)
        ttk.Button(dialog, text="Usar este nombre", command=lambda: self.save_sticker_name(image, name_value.get(), category_value.get())).pack(anchor="e", padx=18, pady=(5, 2))
        ttk.Label(dialog, text="Elige las palabras o descripciones que quieras guardar como etiqueta:", padding=(18, 14, 18, 5), wraplength=470).pack(anchor="w")
        choices = []
        dismissed = self.database.dismissed_ai_tags(image["path"])
        suggestions = [tag for tag in result["suggestions"] if tag.strip().casefold() not in dismissed]

        def discard_suggestion(tag: str, row: tk.Widget):
            self.database.dismiss_ai_tag(image["path"], tag)
            choices[:] = [choice for choice in choices if choice[0].casefold() != tag.casefold()]
            row.destroy()
            self.status.set(f"Etiqueta descartada: {tag}")

        for suggestion in suggestions:
            selected = tk.BooleanVar(value=True)
            choices.append((suggestion, selected))
            row = tk.Frame(dialog, background="#080909")
            row.pack(fill="x", padx=18)
            tk.Checkbutton(row, text=suggestion, variable=selected, anchor="w", justify="left", background="#080909", foreground="#e7d3c4", activebackground="#080909", activeforeground="#fff4ec", selectcolor="#d60916", wraplength=420).pack(side="left", fill="x", expand=True)
            tk.Button(row, text="🗑", command=lambda tag=suggestion, widget=row: discard_suggestion(tag, widget), background="#080909", foreground="#e7d3c4", activebackground="#2a1010", activeforeground="#ff7777", borderwidth=0, cursor="hand2", padx=6).pack(side="right")
        if choices:
            ttk.Button(dialog, text="Guardar seleccionadas", command=lambda: self.save_ai_tags(image, choices, dialog)).pack(anchor="e", padx=18, pady=16)

    def save_ai_tags(self, image, choices, dialog):
        for tag, selected in choices:
            if selected.get():
                self.database.add_tag(image["path"], tag, commit=False)
        self.database.commit()
        self.refresh_tags()
        self.status.set("Etiquetas guardadas. Pulsa Refrescar para actualizar los diseños.")
        dialog.destroy()

    def save_sticker_name(self, image, name: str, category: str):
        self.database.set_classification(image["path"], name, category)
        image["caption"] = name
        image["category"] = category
        self.refresh_categories()
        self.status.set(f"Nombre interno guardado en {category}: {name}")

    def add_tag(self, image):
        if not image:
            return
        def add_to_image(tag: str):
            try:
                self.database.add_tag(image["path"], tag)
                self.refresh_tags()
                self.status.set("Etiqueta agregada al diseño.")
                return True
            except ValueError as error:
                messagebox.showwarning("Etiqueta inválida", str(error), parent=self)
                return False

        self.ask_tag_with_suggestion("Agregar etiqueta", "Nombre de la etiqueta:", add_to_image)

    def remove_tag(self, image, tag: str):
        self.database.remove_tag(image["path"], tag)
        self.refresh_tags()
        self.status.set(f"Se borró la etiqueta «{tag}». Pulsa Refrescar para actualizar los diseños.")

    def trash_sticker(self, image) -> None:
        """Envía un diseño a la papelera oculta y lo elimina de la biblioteca.

        La papelera es una subcarpeta `.trash` dentro del mismo directorio del
        archivo. No se muestra en la UI y puede recuperarse desde el explorador
        de archivos si fuese necesario.
        """
        import shutil

        if not image:
            return
        path = Path(image["path"])
        if not path.exists():
            # El archivo ya no está; basta con sacarlo de la base.
            self.database.remove_image(str(path))
            self.refresh(self.search.query.get())
            self.status.set(f"Diseño «{path.name}» eliminado de la biblioteca.")
            return

        trash_dir = path.parent / ".trash"
        try:
            trash_dir.mkdir(exist_ok=True)
            # Ocultar la carpeta en Windows (atributo +H); falla silenciosamente
            # en otros sistemas o si el usuario no tiene permisos.
            try:
                import subprocess
                subprocess.run(
                    ["attrib", "+H", str(trash_dir)],
                    check=False, capture_output=True,
                )
            except Exception:
                pass
            dest = trash_dir / path.name
            # Evita colisiones si el nombre ya existe en la papelera.
            if dest.exists():
                stem, suffix = path.stem, path.suffix
                counter = 1
                while dest.exists():
                    dest = trash_dir / f"{stem}_{counter}{suffix}"
                    counter += 1
            shutil.move(str(path), str(dest))
        except OSError as error:
            messagebox.showerror(
                "Error al mover a papelera",
                f"No se pudo mover «{path.name}»:\n{error}",
                parent=self,
            )
            return

        self.database.remove_image(str(path))
        # Quitar de la selección activa si estuviese ahí.
        self.selected_images.pop(str(path), None)
        self.refresh(self.search.query.get())
        self.status.set(f"«{path.name}» enviado a la papelera.")

    def close(self):
        # Detener el worker de notificaciones antes de cerrar
        try:
            self._notification_service.stop_worker()
        except Exception:
            pass
        # Detener servidores HTTP
        try:
            self._pairing_server.stop()
        except Exception:
            pass
        try:
            self._mobile_jobs_server.stop()
        except Exception:
            pass
        # Una ficha puede tener hasta 700 ms de cambios en cola. Antes de
        # cerrar se confirma la última versión y se conserva el borrador si
        # algún dato no pudiese validarse.
        for order_id, tab in list(getattr(self, "order_tabs", {}).items()):
            if getattr(tab, "order_save_after", None):
                try:
                    self.after_cancel(tab.order_save_after)
                except tk.TclError:
                    pass
                tab.order_save_after = None
            if getattr(tab, "order_dirty", False):
                self.flush_order_autosave(order_id)
        self.database.close()
        self.destroy()

    # Durante una edición anterior estos métodos quedaron dentro de este
    # ayudante de exportación. Al instalarlos explícitamente en la clase se
    # conserva la compatibilidad sin reescribir el archivo completo y la
    # Biblioteca vuelve a poder actualizarse desde el primer arranque.
    for _method_name, _method in tuple(locals().items()):
        if (
            callable(_method)
            and getattr(_method, "__module__", None) == __name__
            and _method.__qualname__.startswith("write_orders_zip.<locals>.")
        ):
            setattr(VisionVaultApp, _method_name, _method)


# Ejecuta únicamente la instalación de métodos; no genera archivos de exportación.
write_orders_zip([], None)
