"""Prueba A/B aislada para medir saltos físicos entre páginas Epson.

No envía RAW/ESC/P ni compensa el avance. Sólo compara la estructura GDI:
dos documentos de una página contra un documento de dos páginas.
"""

from __future__ import annotations

import ctypes
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from threading import Event

from app.planchas.experimental_roll import PRINT_DPI, ROLL_WIDTH_MM, mm_to_pixels


TEST_LENGTH_MM = 300
# Igual que la calibración establecida para la producción existente. No es una
# compensación entre bloques: se aplica idénticamente a A y B.
TEST_SCALE_PERCENT = 97.27
RESULTS_FILENAME = "continuity_results.json"


@dataclass(frozen=True)
class EpsonContinuityRun:
    method: str
    success: bool
    message: str
    job_ids: tuple[int, ...] = ()
    gdi_error: str = ""


def experimental_output_folder() -> Path:
    return Path(__file__).resolve().parents[2] / "outputs" / "bloques_rollo_experimental"


def generate_continuity_patterns() -> tuple[Path, Path]:
    """Crea dos PNG idénticos en tamaño, con referencias opuestas al borde."""
    from PIL import Image, ImageDraw, ImageFont

    folder = experimental_output_folder()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    width, height = mm_to_pixels(ROLL_WIDTH_MM), mm_to_pixels(TEST_LENGTH_MM)
    try:
        title_font = ImageFont.truetype("arialbd.ttf", 72)
        rule_font = ImageFont.truetype("arial.ttf", 40)
    except OSError:
        title_font = rule_font = ImageFont.load_default()

    def build(label: str, at_end: bool, output: Path) -> None:
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)
        # La regla se sitúa en los 25 mm contiguos al borde que se compara.
        origin = height - mm_to_pixels(25) if at_end else 0
        draw.rectangle((0, origin, width - 1, min(height - 1, origin + mm_to_pixels(25))), outline="black", width=3)
        text_y = origin + 8
        draw.text((40, text_y), label, fill="black", font=title_font)
        for value in (0, 5, 10, 15, 20):
            y = origin + mm_to_pixels(value)
            if y >= height:
                continue
            draw.line((0, y, width - 1, y), fill="black", width=3)
            draw.text((width - 180, max(0, y - 18)), f"{value} mm", fill="black", font=rule_font)
        image.save(output, "PNG", dpi=(PRINT_DPI, PRINT_DPI), compress_level=3)

    block_1 = folder / f"continuidad_{stamp}_bloque_1.png"
    block_2 = folder / f"continuidad_{stamp}_bloque_2.png"
    build("FINAL BLOQUE 1", True, block_1)
    build("INICIO BLOQUE 2", False, block_2)
    return block_1, block_2


def _validate_pattern(path: str | Path) -> tuple[bool, str]:
    from PIL import Image

    try:
        with Image.open(path) as image:
            expected = (mm_to_pixels(ROLL_WIDTH_MM), mm_to_pixels(TEST_LENGTH_MM))
            if image.size != expected:
                return False, f"El patrón debe medir {expected[0]} × {expected[1]} px."
            dpi = image.info.get("dpi", (0, 0))
            if not dpi or any(abs(float(value) - PRINT_DPI) > 2 for value in dpi[:2]):
                return False, "El patrón debe conservar 300 DPI."
    except Exception as error:
        return False, f"No se pudo leer el patrón: {error}"
    return True, "Patrón válido."


def _load_bitmap(path: Path):
    from PIL import Image

    with Image.open(path) as source:
        image = source.convert("RGB").convert("RGBA")
        return image.size, image.tobytes("raw", "BGRA")


def _send_document(printer_name: str, paths: tuple[Path, ...], document_name: str, devmode_bytes: bytes | None, stop_event: Event | None) -> EpsonContinuityRun:
    """Envía N páginas bajo un único StartDoc. Se usa internamente para A y B."""
    class DOCINFOW(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_int), ("lpszDocName", ctypes.c_wchar_p), ("lpszOutput", ctypes.c_wchar_p), ("lpszDatatype", ctypes.c_wchar_p), ("fwType", ctypes.c_int)]
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long), ("biPlanes", ctypes.c_ushort), ("biBitCount", ctypes.c_ushort), ("biCompression", ctypes.c_uint32), ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]
    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 1)]

    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    gdi.CreateDCW.argtypes, gdi.CreateDCW.restype = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p], ctypes.c_void_p
    gdi.DeleteDC.argtypes = [ctypes.c_void_p]
    gdi.GetDeviceCaps.argtypes, gdi.GetDeviceCaps.restype = [ctypes.c_void_p, ctypes.c_int], ctypes.c_int
    gdi.StartDocW.argtypes, gdi.StartDocW.restype = [ctypes.c_void_p, ctypes.POINTER(DOCINFOW)], ctypes.c_int
    for name in ("StartPage", "EndPage", "EndDoc", "AbortDoc"):
        getattr(gdi, name).argtypes = [ctypes.c_void_p]
        getattr(gdi, name).restype = ctypes.c_int
    gdi.SetStretchBltMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
    gdi.SetViewportOrgEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    gdi.StretchDIBits.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
    gdi.StretchDIBits.restype = ctypes.c_int
    dm_buffer = ctypes.create_string_buffer(devmode_bytes, len(devmode_bytes)) if devmode_bytes else None
    hdc = gdi.CreateDCW("WINSPOOL", printer_name, None, ctypes.cast(dm_buffer, ctypes.c_void_p) if dm_buffer else None)
    if not hdc:
        return EpsonContinuityRun("", False, "No se pudo crear el contexto GDI.", gdi_error=f"CreateDCW={ctypes.get_last_error()}")
    started = False
    try:
        dpi_x, dpi_y = gdi.GetDeviceCaps(hdc, 88) or PRINT_DPI, gdi.GetDeviceCaps(hdc, 90) or PRINT_DPI
        offset_x, offset_y = gdi.GetDeviceCaps(hdc, 112), gdi.GetDeviceCaps(hdc, 113)
        printable_w, printable_h = gdi.GetDeviceCaps(hdc, 8), gdi.GetDeviceCaps(hdc, 10)
        expected_w, expected_h = mm_to_pixels(ROLL_WIDTH_MM), mm_to_pixels(TEST_LENGTH_MM)
        scale = TEST_SCALE_PERCENT / 100.0
        target_w, target_h = round(expected_w * dpi_x / PRINT_DPI * scale), round(expected_h * dpi_y / PRINT_DPI * scale)
        if not printable_w or not printable_h or target_w > printable_w or target_h > printable_h:
            return EpsonContinuityRun("", False, "El driver rechazó o no expone un tamaño imprimible de 210 × 300 mm.")
        job_id = gdi.StartDocW(hdc, ctypes.byref(DOCINFOW(ctypes.sizeof(DOCINFOW), document_name, None, None, 0)))
        if job_id <= 0:
            return EpsonContinuityRun("", False, "Windows rechazó StartDoc.", gdi_error=f"StartDocW={ctypes.get_last_error()}")
        started = True
        for page_number, path in enumerate(paths, 1):
            if stop_event and stop_event.is_set():
                gdi.AbortDoc(hdc)
                return EpsonContinuityRun("", False, "Prueba detenida antes del siguiente bloque.", (int(job_id),))
            (width, height), pixels = _load_bitmap(path)
            bitmap = BITMAPINFO(BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, len(pixels), 0, 0, 0, 0), (ctypes.c_uint32 * 1)(0))
            buffer = ctypes.create_string_buffer(pixels)
            if gdi.StartPage(hdc) <= 0:
                gdi.AbortDoc(hdc)
                return EpsonContinuityRun("", False, f"GDI no pudo iniciar la página {page_number}.", (int(job_id),), f"StartPage={ctypes.get_last_error()}")
            gdi.SetViewportOrgEx(hdc, -offset_x, -offset_y, None)
            gdi.SetStretchBltMode(hdc, 4)
            drawn = gdi.StretchDIBits(hdc, offset_x, offset_y, target_w, target_h, 0, 0, width, height, buffer, ctypes.byref(bitmap), 0, 0x00CC0020)
            if drawn in (0, -1) or gdi.EndPage(hdc) <= 0:
                gdi.AbortDoc(hdc)
                return EpsonContinuityRun("", False, f"GDI rechazó la página {page_number}.", (int(job_id),), f"Stretch/EndPage={ctypes.get_last_error()}")
        if gdi.EndDoc(hdc) <= 0:
            return EpsonContinuityRun("", False, "GDI no pudo finalizar el documento.", (int(job_id),), f"EndDoc={ctypes.get_last_error()}")
        started = False
        return EpsonContinuityRun("", True, "Trabajo enviado a Windows.", (int(job_id),))
    except Exception as error:
        if started:
            gdi.AbortDoc(hdc)
        return EpsonContinuityRun("", False, f"Error GDI: {error}", gdi_error=str(error))
    finally:
        gdi.DeleteDC(hdc)


def run_continuity_test(printer_name: str, block_1: str | Path, block_2: str | Path, method: str, devmode_bytes: bytes | None = None, stop_event: Event | None = None) -> EpsonContinuityRun:
    """Ejecuta A (dos StartDoc) o B (un StartDoc y dos StartPage)."""
    if os.name != "nt" or not printer_name.strip():
        return EpsonContinuityRun(method, False, "Seleccioná una impresora de Windows.")
    paths = tuple(Path(item) for item in (block_1, block_2))
    for path in paths:
        valid, message = _validate_pattern(path)
        if not valid:
            return EpsonContinuityRun(method, False, message)
    normalized = method.upper().strip()
    if normalized == "A":
        first = _send_document(printer_name, (paths[0],), "Epson continuity A · bloque 1", devmode_bytes, stop_event)
        if not first.success:
            return EpsonContinuityRun("A", False, first.message, first.job_ids, first.gdi_error)
        second = _send_document(printer_name, (paths[1],), "Epson continuity A · bloque 2", devmode_bytes, stop_event)
        return EpsonContinuityRun("A", second.success, second.message, first.job_ids + second.job_ids, second.gdi_error)
    if normalized == "B":
        result = _send_document(printer_name, paths, "Epson continuity B · dos páginas", devmode_bytes, stop_event)
        return EpsonContinuityRun("B", result.success, result.message, result.job_ids, result.gdi_error)
    return EpsonContinuityRun(method, False, "El método debe ser A o B.")


def save_continuity_measurement(run: EpsonContinuityRun, printer_name: str, devmode_used: bool, measurements: dict[str, object]) -> Path:
    """Añade resultados automáticos y manuales a un JSON aislado del historial."""
    output = experimental_output_folder() / RESULTS_FILENAME
    try:
        records = json.loads(output.read_text(encoding="utf-8")) if output.exists() else []
    except (ValueError, OSError):
        records = []
    records.append({
        "timestamp": datetime.now().isoformat(timespec="seconds"), "printer": printer_name,
        "method": run.method, "success": run.success, "message": run.message,
        "job_ids": list(run.job_ids), "gdi_error": run.gdi_error, "width_mm": ROLL_WIDTH_MM,
        "length_mm": TEST_LENGTH_MM, "dpi": PRINT_DPI, "scale_percent": TEST_SCALE_PERCENT,
        "devmode_used": bool(devmode_used), "measurements": measurements,
    })
    output.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def latest_measurements() -> dict[str, dict] :
    """Obtiene el último registro exitoso de cada método para compararlo en UI."""
    path = experimental_output_folder() / RESULTS_FILENAME
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    result: dict[str, dict] = {}
    for record in records:
        if record.get("success") and record.get("method") in {"A", "B"}:
            result[str(record["method"])] = record
    return result
