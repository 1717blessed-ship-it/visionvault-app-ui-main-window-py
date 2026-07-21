"""Puente nativo con la cola de impresión de Windows, sin abrir otra aplicación."""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PrintResult:
    success: bool
    message: str
    spool_job_id: int | None = None


def _windows_only() -> bool:
    return os.name == "nt"


def default_printer() -> str:
    """Devuelve la impresora predeterminada de Windows, si existe."""
    if not _windows_only():
        return ""
    winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
    required = ctypes.c_uint32(0)
    winspool.GetDefaultPrinterW(None, ctypes.byref(required))
    if not required.value:
        return ""
    buffer = ctypes.create_unicode_buffer(required.value)
    if not winspool.GetDefaultPrinterW(buffer, ctypes.byref(required)):
        return ""
    return buffer.value


def list_printers() -> list[str]:
    """Lista impresoras locales y conexiones visibles para el usuario actual."""
    if not _windows_only():
        return []

    class PRINTER_INFO_4W(ctypes.Structure):
        _fields_ = [("pPrinterName", ctypes.c_wchar_p), ("pServerName", ctypes.c_wchar_p), ("Attributes", ctypes.c_uint32)]

    winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
    needed, returned = ctypes.c_uint32(0), ctypes.c_uint32(0)
    flags = 2 | 4  # PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
    winspool.EnumPrintersW(flags, None, 4, None, 0, ctypes.byref(needed), ctypes.byref(returned))
    if not needed.value:
        fallback = default_printer()
        return [fallback] if fallback else []
    data = ctypes.create_string_buffer(needed.value)
    ok = winspool.EnumPrintersW(flags, None, 4, data, needed.value, ctypes.byref(needed), ctypes.byref(returned))
    if not ok:
        fallback = default_printer()
        return [fallback] if fallback else []
    rows = ctypes.cast(data, ctypes.POINTER(PRINTER_INFO_4W * returned.value)).contents
    names = [row.pPrinterName for row in rows if row.pPrinterName]
    default = default_printer()
    if default and default not in names:
        names.insert(0, default)
    return sorted(set(names), key=lambda value: (value != default, value.casefold()))


def printer_status(printer_name: str) -> tuple[bool, str]:
    """Comprueba que Windows puede abrir la impresora antes de crear la cola."""
    if not _windows_only():
        return False, "La impresión directa solo está disponible en Windows."
    if not printer_name:
        return False, "No se detectó la impresora configurada."
    winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
    handle = ctypes.c_void_p()
    if not winspool.OpenPrinterW(printer_name, ctypes.byref(handle), None):
        return False, "No se detectó la impresora configurada o no está disponible."
    winspool.ClosePrinter(handle)
    return True, "Disponible"


def validate_a4_png(path: str | Path) -> tuple[bool, str]:
    """Valida una plancha final independiente de la miniatura de pantalla."""
    path = Path(path)
    if not path.exists():
        return False, "El archivo final generado no existe."
    try:
        from PIL import Image

        with Image.open(path) as source:
            source.verify()
        with Image.open(path) as image:
            width, height = image.size
            dpi = image.info.get("dpi", (0, 0))
    except Exception:
        return False, "El archivo final está dañado o no se pudo leer."
    expected = (round(21 / 2.54 * 300), round(29.7 / 2.54 * 300))
    if abs(width - expected[0]) > 1 or abs(height - expected[1]) > 1:
        return False, "La plancha no está en formato A4 vertical a tamaño real."
    if not dpi or len(dpi) < 2 or abs(float(dpi[0]) - 300) > 2 or abs(float(dpi[1]) - 300) > 2:
        return False, "La resolución no coincide con 300 DPI."
    return True, "Archivo A4 a 300 DPI verificado."


def print_png(printer_name: str, path: str | Path, copies: int = 1, document_name: str = "Doccione Studio") -> PrintResult:
    """Envía el PNG A4 en color, al 100 %, mediante GDI y la cola de Windows."""
    valid, message = validate_a4_png(path)
    if not valid:
        return PrintResult(False, message)
    available, message = printer_status(printer_name)
    if not available:
        return PrintResult(False, message)
    if not _windows_only():
        return PrintResult(False, "La impresión directa solo está disponible en Windows.")
    try:
        from PIL import Image

        with Image.open(path) as source:
            source = source.convert("RGBA")
            page = Image.new("RGBA", source.size, "white")
            page.alpha_composite(source)
            page = page.convert("RGBA")
            width, height = page.size
            pixels = page.tobytes("raw", "BGRA")
    except Exception:
        return PrintResult(False, "No se pudo preparar el archivo final para impresión.")

    class DOCINFOW(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_int), ("lpszDocName", ctypes.c_wchar_p), ("lpszOutput", ctypes.c_wchar_p),
                    ("lpszDatatype", ctypes.c_wchar_p), ("fwType", ctypes.c_int)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", ctypes.c_ushort), ("biBitCount", ctypes.c_ushort), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                    ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 1)]

    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    # En Windows de 64 bits los HDC son punteros: declarar sus firmas evita
    # truncarlos antes de llamar a la impresora real.
    gdi.CreateDCW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p]
    gdi.CreateDCW.restype = ctypes.c_void_p
    gdi.DeleteDC.argtypes = [ctypes.c_void_p]
    gdi.GetDeviceCaps.argtypes = [ctypes.c_void_p, ctypes.c_int]
    gdi.GetDeviceCaps.restype = ctypes.c_int
    gdi.StartDocW.argtypes = [ctypes.c_void_p, ctypes.POINTER(DOCINFOW)]
    gdi.StartDocW.restype = ctypes.c_int
    gdi.StartPage.argtypes = [ctypes.c_void_p]
    gdi.EndPage.argtypes = [ctypes.c_void_p]
    gdi.EndDoc.argtypes = [ctypes.c_void_p]
    gdi.AbortDoc.argtypes = [ctypes.c_void_p]
    gdi.SetStretchBltMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
    gdi.SetViewportOrgEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    hdc = gdi.CreateDCW("WINSPOOL", printer_name, None, None)
    if not hdc:
        return PrintResult(False, "No se pudo crear la conexión con la impresora configurada.")
    try:
        # La resolución de destino conserva el tamaño físico A4 sin ajustar.
        dpi_x, dpi_y = gdi.GetDeviceCaps(hdc, 88), gdi.GetDeviceCaps(hdc, 90)  # LOGPIXELSX/Y
        physical_w, physical_h = gdi.GetDeviceCaps(hdc, 110), gdi.GetDeviceCaps(hdc, 111)  # PHYSICALWIDTH/HEIGHT
        offset_x, offset_y = gdi.GetDeviceCaps(hdc, 112), gdi.GetDeviceCaps(hdc, 113)  # PHYSICALOFFSETX/Y
        target_w, target_h = round(21 / 2.54 * dpi_x), round(29.7 / 2.54 * dpi_y)
        if physical_w and physical_h and (target_w > physical_w + 2 or target_h > physical_h + 2):
            return PrintResult(False, "La impresora no admite A4 vertical al 100 % con su configuración actual.")
        info = DOCINFOW(ctypes.sizeof(DOCINFOW), document_name, None, None, 0)
        spool_job_id = gdi.StartDocW(hdc, ctypes.byref(info))
        if spool_job_id <= 0:
            return PrintResult(False, "Windows rechazó el trabajo de impresión.")
        bitmap = BITMAPINFO(BITMAPINFOHEADER(
            ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, len(pixels), 0, 0, 0, 0,
        ), (ctypes.c_uint32 * 1)(0))
        buffer = ctypes.create_string_buffer(pixels)
        for _copy in range(max(1, int(copies))):
            if gdi.StartPage(hdc) <= 0:
                gdi.AbortDoc(hdc)
                return PrintResult(False, "La impresora no pudo iniciar la página A4.")
            # Se dibuja desde el origen físico de la hoja: no se ajusta,
            # expande ni reduce al área útil del driver de la impresora.
            gdi.SetViewportOrgEx(hdc, -offset_x, -offset_y, None)
            gdi.SetStretchBltMode(hdc, 4)  # HALFTONE
            drawn = gdi.StretchDIBits(
                hdc, 0, 0, target_w, target_h, 0, 0, width, height, buffer,
                ctypes.byref(bitmap), 0, 0x00CC0020,  # DIB_RGB_COLORS · SRCCOPY
            )
            if drawn in (0, -1) or gdi.EndPage(hdc) <= 0:
                gdi.AbortDoc(hdc)
                return PrintResult(False, "La impresora rechazó la página durante el envío.")
        if gdi.EndDoc(hdc) <= 0:
            return PrintResult(False, "Windows no pudo finalizar el envío a la impresora.")
        return PrintResult(True, "Trabajo enviado a la cola de impresión.", int(spool_job_id))
    except Exception as error:
        try:
            gdi.AbortDoc(hdc)
        except Exception:
            pass
        return PrintResult(False, f"Error de impresión: {error}")
    finally:
        gdi.DeleteDC(hdc)


def cancel_spool_job(printer_name: str, spool_job_id: int | None) -> PrintResult:
    """Solicita a Windows cancelar un trabajo que ya alcanzó la cola."""
    if not spool_job_id:
        return PrintResult(False, "El trabajo todavía no llegó a la cola de impresión.")
    available, message = printer_status(printer_name)
    if not available:
        return PrintResult(False, message)
    winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
    handle = ctypes.c_void_p()
    if not winspool.OpenPrinterW(printer_name, ctypes.byref(handle), None):
        return PrintResult(False, "No se detectó la impresora configurada.")
    try:
        if not winspool.SetJobW(handle, int(spool_job_id), 0, None, 3):  # JOB_CONTROL_CANCEL
            return PrintResult(False, "Windows no pudo cancelar el trabajo en cola.")
        return PrintResult(True, "Cancelación enviada a la cola de impresión.", spool_job_id)
    finally:
        winspool.ClosePrinter(handle)


def open_printer_properties(printer_name: str, parent_hwnd: int = 0) -> bytes | None:
    """Abre el cuadro de propiedades nativo de la impresora (p.ej. Epson L3210).

    Muestra el diálogo del driver real de Windows (exactamente el mismo que
    aparece al hacer clic en «Propiedades» desde el Panel de control).
    Devuelve los bytes del DEVMODE elegido por el usuario, o None si canceló.

    El ``parent_hwnd`` puede ser el HWND de la ventana Tk:
        ``int(root.wm_frame(), 16)``

    El DEVMODE devuelto se puede guardar en la base de datos (serializado como
    base64) y pasarlo a ``print_png_strip`` para que la impresora aplique
    exactamente la configuración elegida.
    """
    if not _windows_only():
        return None

    winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
    handle = ctypes.c_void_p()
    if not winspool.OpenPrinterW(printer_name, ctypes.byref(handle), None):
        return None

    try:
        # Paso 1: averiguar el tamaño del DEVMODE actual.
        needed = winspool.DocumentPropertiesW(
            parent_hwnd, handle, printer_name, None, None, 0
        )
        if needed <= 0:
            return None

        # Paso 2: obtener el DEVMODE actual como punto de partida.
        current_dm = ctypes.create_string_buffer(needed)
        ret = winspool.DocumentPropertiesW(
            parent_hwnd, handle, printer_name,
            current_dm, None,
            0x0002,  # DM_OUT_BUFFER — solo salida, sin diálogo
        )
        if ret < 0:
            current_dm = None

        # Paso 3: abrir el diálogo y dejar que el usuario configure la impresora.
        output_dm = ctypes.create_string_buffer(needed)
        DM_IN_BUFFER = 0x0008
        DM_OUT_BUFFER = 0x0002
        DM_IN_PROMPT = 0x0004   # Muestra el diálogo
        flags = DM_IN_PROMPT | DM_OUT_BUFFER
        if current_dm:
            flags |= DM_IN_BUFFER
            result = winspool.DocumentPropertiesW(
                parent_hwnd, handle, printer_name,
                output_dm, current_dm, flags,
            )
        else:
            result = winspool.DocumentPropertiesW(
                parent_hwnd, handle, printer_name,
                output_dm, None, flags,
            )

        # result == IDOK (1) → el usuario aceptó; IDCANCEL (2) o negativo → canceló.
        if result == 1:
            return bytes(output_dm)
        return None
    finally:
        winspool.ClosePrinter(handle)


def open_print_dialog(printer_name: str, parent_hwnd: int = 0) -> bytes | None:
    """Abre el cuadro de propiedades de la impresora con todas las opciones.

    Muestra el diálogo estándar de configuración de la impresora con todas
    las opciones disponibles (copias, orientación, escala, formato, etc).
    
    Devuelve los bytes del DEVMODE elegido por el usuario, o None si canceló.
    """
    if not _windows_only():
        return None

    winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
    handle = ctypes.c_void_p()
    if not winspool.OpenPrinterW(printer_name, ctypes.byref(handle), None):
        return None

    try:
        # Paso 1: averiguar el tamaño del DEVMODE actual.
        needed = winspool.DocumentPropertiesW(
            parent_hwnd, handle, printer_name, None, None, 0
        )
        if needed <= 0:
            return None

        # Paso 2: obtener el DEVMODE actual como punto de partida.
        current_dm = ctypes.create_string_buffer(needed)
        ret = winspool.DocumentPropertiesW(
            parent_hwnd, handle, printer_name,
            current_dm, None,
            0x0002,  # DM_OUT_BUFFER — solo salida, sin diálogo
        )
        if ret < 0:
            current_dm = None

        # Paso 3: abrir el diálogo y dejar que el usuario configure la impresora.
        output_dm = ctypes.create_string_buffer(needed)
        DM_IN_BUFFER = 0x0008
        DM_OUT_BUFFER = 0x0002
        DM_IN_PROMPT = 0x0004   # Muestra el diálogo
        flags = DM_IN_PROMPT | DM_OUT_BUFFER
        if current_dm:
            flags |= DM_IN_BUFFER
            result = winspool.DocumentPropertiesW(
                parent_hwnd, handle, printer_name,
                output_dm, current_dm, flags,
            )
        else:
            result = winspool.DocumentPropertiesW(
                parent_hwnd, handle, printer_name,
                output_dm, None, flags,
            )

        # result == IDOK (1) → el usuario aceptó; IDCANCEL (2) o negativo → canceló.
        if result == 1:
            return bytes(output_dm)
        return None
    finally:
        winspool.ClosePrinter(handle)


def print_png_strip(
    printer_name: str,
    path: str | Path,
    copies: int = 1,
    document_name: str = "Doccione Continua",
    devmode_bytes: bytes | None = None,
) -> PrintResult:
    """Envía una tira continua (alto variable) a la impresora mediante GDI.

    A diferencia de ``print_png`` — que valida estrictamente el formato A4 —
    esta función acepta cualquier PNG válido independientemente de sus
    dimensiones.  Si ``devmode_bytes`` contiene un DEVMODE serializado
    (obtenido de ``open_printer_properties``), se aplica antes de crear el DC
    para que el driver Epson u otro use exactamente la configuración elegida.
    """
    path = Path(path)
    if not path.exists():
        return PrintResult(False, "El archivo de la tira no existe.")

    available, message = printer_status(printer_name)
    if not available:
        return PrintResult(False, message)

    if not _windows_only():
        return PrintResult(False, "La impresión directa solo está disponible en Windows.")

    try:
        from PIL import Image

        with Image.open(path) as source:
            source = source.convert("RGBA")
            page = Image.new("RGBA", source.size, "white")
            page.alpha_composite(source)
            page = page.convert("RGBA")
            strip_width, strip_height = page.size
            pixels = page.tobytes("raw", "BGRA")
    except Exception as error:
        return PrintResult(False, f"No se pudo preparar la tira para impresión: {error}")

    class DOCINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_int), ("lpszDocName", ctypes.c_wchar_p),
            ("lpszOutput", ctypes.c_wchar_p), ("lpszDatatype", ctypes.c_wchar_p),
            ("fwType", ctypes.c_int),
        ]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
            ("biPlanes", ctypes.c_ushort), ("biBitCount", ctypes.c_ushort),
            ("biCompression", ctypes.c_uint32), ("biSizeImage", ctypes.c_uint32),
            ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 1)]

    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)

    gdi.CreateDCW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p]
    gdi.CreateDCW.restype = ctypes.c_void_p
    gdi.DeleteDC.argtypes = [ctypes.c_void_p]
    gdi.GetDeviceCaps.argtypes = [ctypes.c_void_p, ctypes.c_int]
    gdi.GetDeviceCaps.restype = ctypes.c_int
    gdi.StartDocW.argtypes = [ctypes.c_void_p, ctypes.POINTER(DOCINFOW)]
    gdi.StartDocW.restype = ctypes.c_int
    gdi.StartPage.argtypes = [ctypes.c_void_p]
    gdi.EndPage.argtypes = [ctypes.c_void_p]
    gdi.EndDoc.argtypes = [ctypes.c_void_p]
    gdi.AbortDoc.argtypes = [ctypes.c_void_p]
    gdi.SetStretchBltMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
    gdi.SetViewportOrgEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]

    # Aplicar el DEVMODE elegido por el usuario si está disponible.
    dm_buffer = None
    if devmode_bytes:
        dm_buffer = ctypes.create_string_buffer(devmode_bytes, len(devmode_bytes))

    hdc = gdi.CreateDCW("WINSPOOL", printer_name, None,
                         ctypes.cast(dm_buffer, ctypes.c_void_p) if dm_buffer else None)
    if not hdc:
        return PrintResult(False, "No se pudo crear la conexión con la impresora configurada.")

    try:
        dpi_x = gdi.GetDeviceCaps(hdc, 88)   # LOGPIXELSX
        dpi_y = gdi.GetDeviceCaps(hdc, 90)   # LOGPIXELSY
        physical_w = gdi.GetDeviceCaps(hdc, 110)  # PHYSICALWIDTH
        physical_h = gdi.GetDeviceCaps(hdc, 111)  # PHYSICALHEIGHT
        offset_x = gdi.GetDeviceCaps(hdc, 112)    # PHYSICALOFFSETX
        offset_y = gdi.GetDeviceCaps(hdc, 113)    # PHYSICALOFFSETY

        if not dpi_x or not dpi_y:
            dpi_x = dpi_y = 300

        # Escalar la imagen al tamaño físico real de la página configurada.
        # Si la impresora no reporta dimensiones físicas se usa la resolución
        # del PNG como referencia directa (sin escalar).
        if physical_w and physical_h:
            target_w, target_h = physical_w, physical_h
        else:
            target_w = round(strip_width * dpi_x / 300)
            target_h = round(strip_height * dpi_y / 300)

        info = DOCINFOW(ctypes.sizeof(DOCINFOW), document_name, None, None, 0)
        spool_job_id = gdi.StartDocW(hdc, ctypes.byref(info))
        if spool_job_id <= 0:
            return PrintResult(False, "Windows rechazó el trabajo de impresión.")

        bitmap = BITMAPINFO(BITMAPINFOHEADER(
            ctypes.sizeof(BITMAPINFOHEADER),
            strip_width, -strip_height,  # negativo = top-down
            1, 32, 0, len(pixels), 0, 0, 0, 0,
        ), (ctypes.c_uint32 * 1)(0))
        buffer = ctypes.create_string_buffer(pixels)

        for _copy in range(max(1, int(copies))):
            if gdi.StartPage(hdc) <= 0:
                gdi.AbortDoc(hdc)
                return PrintResult(False, "La impresora no pudo iniciar la página.")
            gdi.SetViewportOrgEx(hdc, -offset_x, -offset_y, None)
            gdi.SetStretchBltMode(hdc, 4)  # HALFTONE
            drawn = gdi.StretchDIBits(
                hdc, 0, 0, target_w, target_h,
                0, 0, strip_width, strip_height,
                buffer, ctypes.byref(bitmap),
                0, 0x00CC0020,  # DIB_RGB_COLORS · SRCCOPY
            )
            if drawn in (0, -1) or gdi.EndPage(hdc) <= 0:
                gdi.AbortDoc(hdc)
                return PrintResult(False, "La impresora rechazó la página durante el envío.")

        if gdi.EndDoc(hdc) <= 0:
            return PrintResult(False, "Windows no pudo finalizar el envío a la impresora.")
        return PrintResult(True, "Tira enviada a la cola de impresión.", int(spool_job_id))

    except Exception as error:
        try:
            gdi.AbortDoc(hdc)
        except Exception:
            pass
        return PrintResult(False, f"Error de impresión: {error}")
    finally:
        gdi.DeleteDC(hdc)
