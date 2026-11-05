"""Herramientas diagnósticas para validar físicamente la cadena de plancha.

No cambia la política productiva: prepara muestras reales con el Creator y
las renderiza con ``PlanchaEditor.render_sheet``. Las mediciones físicas se
registran aparte y nunca se usan para cambiar constantes automáticamente.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Iterable

from PIL import Image, ImageDraw

from app.planchas.editor import PlanchaEditor
from app.planchas.model import PlanchaItem, PlanchaProject
from app.planchas.production_geometry import (
    CUT_INSET_MM,
    PRINT_SCALE,
    expected_final_size,
    production_max_for_nominal,
    production_min_for_nominal,
)
from app.stickers.models import ProcessingProfile
from app.stickers.pipeline import StickerProcessor


CALIBRATION_NOMINALS = (5.0, 8.0, 10.0, 15.0)
MEASUREMENT_TOLERANCE_CM = 0.02


class CalibrationValidationError(ValueError):
    """Una medición física no puede analizarse de forma segura."""


@dataclass(frozen=True)
class CalibrationSample:
    sample: str
    nominal_cm: float
    variant: str
    production_cm: float
    production_min_cm: float
    production_max_cm: float
    expected_printed_cm: float
    expected_final_cm: float
    output_px: int
    white_border_px: int = 30
    black_stroke_px: int = 2
    print_scale: float = PRINT_SCALE
    cut_inset_mm: float = CUT_INSET_MM
    measured_printed_cm: float | None = None
    measured_cut_cm: float | None = None
    measured_white_margin_mm: float | None = None

    def measurement_row(self) -> dict:
        return asdict(self)


def calibration_samples() -> list[CalibrationSample]:
    """Las ocho muestras del rango comercial, sin datos físicos inventados."""
    result: list[CalibrationSample] = []
    for nominal in CALIBRATION_NOMINALS:
        minimum = production_min_for_nominal(nominal)
        maximum = production_max_for_nominal(nominal)
        for variant, production in (("MIN", minimum), ("MAX", maximum)):
            profile = ProcessingProfile(nominal_size_cm=nominal)
            result.append(CalibrationSample(
                sample=f"{int(nominal)}-{variant}",
                nominal_cm=nominal,
                variant=variant,
                production_cm=production,
                production_min_cm=minimum,
                production_max_cm=maximum,
                expected_printed_cm=production * PRINT_SCALE,
                expected_final_cm=expected_final_size(production),
                output_px=profile.master_pixels,
                white_border_px=profile.final_white_px,
                black_stroke_px=profile.control_black_px,
            ))
    return result


def observed_print_scale(samples: Iterable[dict]) -> dict[str, float | None]:
    """Resume escala observada sólo a partir de mediciones impresas reales."""
    values = [float(row["measured_printed_cm"]) / float(row["production_cm"])
              for row in samples if row.get("measured_printed_cm") is not None]
    if not values:
        return {"mean": None, "min": None, "max": None, "deviation": None}
    average = mean(values)
    return {"mean": average, "min": min(values), "max": max(values),
            "deviation": max(abs(value - average) for value in values)}


def observed_cut_inset_mm(samples: Iterable[dict]) -> dict[str, float | None]:
    """Resume inset físico sólo cuando existen ambas medidas reales."""
    values = [((float(row["measured_printed_cm"]) - float(row["measured_cut_cm"])) / 2) * 10
              for row in samples
              if row.get("measured_printed_cm") is not None and row.get("measured_cut_cm") is not None]
    if not values:
        return {"mean": None, "min": None, "max": None, "deviation": None}
    average = mean(values)
    return {"mean": average, "min": min(values), "max": max(values),
            "deviation": max(abs(value - average) for value in values)}


def measurement_error_mm(row: dict) -> float | None:
    measured = row.get("measured_cut_cm")
    return None if measured is None else (float(measured) - float(row["expected_final_cm"])) * 10


def _measurement(value, field: str) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise CalibrationValidationError(f"{field}: se esperaba un número decimal.") from error
    if parsed <= 0:
        raise CalibrationValidationError(f"{field}: debe ser mayor que cero.")
    return parsed


def validate_calibration_rows(rows: Iterable[dict]) -> list[dict]:
    """Normaliza sólo tipos; no inventa ni corrige mediciones ingresadas."""
    expected = {sample.sample: sample for sample in calibration_samples()}
    validated: list[dict] = []
    for raw in rows:
        row = dict(raw)
        sample_name = str(row.get("sample") or "").strip()
        if sample_name not in expected:
            raise CalibrationValidationError(f"Muestra desconocida: {sample_name or '(vacía)'}.")
        baseline = expected[sample_name]
        for key, value in baseline.measurement_row().items():
            row.setdefault(key, value)
        # El manifiesto es la fuente teórica; no se permite cambiar desde CSV.
        for field in ("nominal_cm", "production_cm", "expected_printed_cm", "expected_final_cm"):
            if abs(float(row[field]) - float(getattr(baseline, field))) > 0.0001:
                raise CalibrationValidationError(f"{sample_name}: {field} no coincide con la muestra generada.")
        printed = _measurement(row.get("measured_printed_cm"), f"{sample_name}.measured_printed_cm")
        cut = _measurement(row.get("measured_cut_cm"), f"{sample_name}.measured_cut_cm")
        white = _measurement(row.get("measured_white_margin_mm"), f"{sample_name}.measured_white_margin_mm")
        if printed is not None and not 0.80 <= printed / baseline.production_cm <= 1.10:
            raise CalibrationValidationError(f"{sample_name}: medida impresa incompatible con la producción.")
        if cut is not None and not 0.80 <= cut / baseline.nominal_cm <= 1.20:
            raise CalibrationValidationError(f"{sample_name}: medida cortada incompatible con la muestra.")
        if printed is not None and cut is not None and cut > printed:
            raise CalibrationValidationError(f"{sample_name}: la medida cortada no puede superar la impresa.")
        row["measured_printed_cm"] = printed
        row["measured_cut_cm"] = cut
        row["measured_white_margin_mm"] = white
        validated.append(row)
    names = {row["sample"] for row in validated}
    if len(names) != len(validated):
        raise CalibrationValidationError("Cada muestra sólo puede aparecer una vez.")
    return validated


def load_calibration_measurements(path: str | Path) -> list[dict]:
    """Carga directamente el CSV o JSON producido por Fase 3K."""
    source = Path(path)
    if source.suffix.lower() == ".csv":
        with source.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
    elif source.suffix.lower() == ".json":
        rows = json.loads(source.read_text(encoding="utf-8"))
    else:
        raise CalibrationValidationError("El archivo debe ser CSV o JSON.")
    if not isinstance(rows, list):
        raise CalibrationValidationError("El registro debe contener una lista de muestras.")
    return validate_calibration_rows(rows)


def _statistics(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "median": None, "min": None, "max": None, "stddev": None}
    return {"mean": mean(values), "median": median(values), "min": min(values),
            "max": max(values), "stddev": pstdev(values)}


def _linear_regression(points: list[tuple[float, float]]) -> dict[str, float | None]:
    if len(points) < 2:
        return {"a": None, "b": None, "r_squared": None}
    x_mean, y_mean = mean(x for x, _ in points), mean(y for _, y in points)
    denominator = sum((x - x_mean) ** 2 for x, _ in points)
    if denominator == 0:
        return {"a": None, "b": None, "r_squared": None}
    slope = sum((x - x_mean) * (y - y_mean) for x, y in points) / denominator
    intercept = y_mean - slope * x_mean
    residual = sum((y - (slope * x + intercept)) ** 2 for x, y in points)
    total = sum((y - y_mean) ** 2 for _, y in points)
    return {"a": slope, "b": intercept,
            "r_squared": 1.0 if total == 0 else 1 - residual / total}


def _error_pattern(rows: list[dict]) -> str:
    complete = [row for row in rows if row["measured_printed_cm"] is not None]
    if len(complete) < 4:
        return "Evidencia insuficiente para clasificar escala u offset."
    errors = [(float(row["production_cm"]),
               (float(row["measured_printed_cm"]) - float(row["expected_printed_cm"])) * 10)
              for row in complete]
    regression = _linear_regression(errors)
    error_values = [error for _, error in errors]
    if pstdev(error_values) <= 0.12:
        return "Evidencia compatible con un offset aproximadamente constante."
    if regression["r_squared"] is not None and regression["r_squared"] >= 0.80:
        return "Evidencia compatible con un error proporcional de escala."
    return "Evidencia compatible con un comportamiento mixto o variable."


def _final_status(row: dict) -> str | None:
    cut = row["measured_cut_cm"]
    if cut is None:
        return None
    nominal = float(row["nominal_cm"])
    if row["variant"] == "MIN":
        if cut >= nominal:
            return "CUMPLE"
        return "AJUSTADO" if cut >= nominal - MEASUREMENT_TOLERANCE_CM else "NO CUMPLE"
    maximum = nominal + 0.50
    if nominal <= cut <= maximum:
        return "CUMPLE"
    if nominal - MEASUREMENT_TOLERANCE_CM <= cut <= maximum + MEASUREMENT_TOLERANCE_CM:
        return "AJUSTADO"
    return "NO CUMPLE"


def analyze_calibration_samples(rows: Iterable[dict]) -> dict:
    """Diagnóstico puro: no escribe constantes ni modifica la entrada."""
    samples = validate_calibration_rows(rows)
    per_sample: list[dict] = []
    scale_values: list[float] = []
    inset_values: list[float] = []
    final_errors: list[float] = []
    white_margins: list[float] = []
    for row in samples:
        report = dict(row)
        printed, cut = row["measured_printed_cm"], row["measured_cut_cm"]
        report["observed_print_scale"] = None if printed is None else printed / float(row["production_cm"])
        report["print_error_mm"] = None if printed is None else (printed - float(row["expected_printed_cm"])) * 10
        report["observed_inset_mm"] = None if printed is None or cut is None else (printed - cut) / 2 * 10
        report["final_error_mm"] = measurement_error_mm(row)
        report["actual_bonus_cm"] = None if cut is None else cut - float(row["nominal_cm"])
        report["status"] = _final_status(row)
        if report["observed_print_scale"] is not None:
            scale_values.append(report["observed_print_scale"])
        if report["observed_inset_mm"] is not None:
            inset_values.append(report["observed_inset_mm"])
        if report["final_error_mm"] is not None:
            final_errors.append(report["final_error_mm"])
        if row["measured_white_margin_mm"] is not None:
            white_margins.append(row["measured_white_margin_mm"])
        per_sample.append(report)
    complete = sum(row["measured_printed_cm"] is not None and row["measured_cut_cm"] is not None for row in samples)
    by_variant = {variant: _statistics([row["observed_print_scale"] for row in per_sample
                                        if row["variant"] == variant and row["observed_print_scale"] is not None])
                  for variant in ("MIN", "MAX")}
    regression = _linear_regression([(float(row["production_cm"]), float(row["measured_printed_cm"]))
                                     for row in samples if row["measured_printed_cm"] is not None])
    white_status = None
    if white_margins:
        white_status = "INVADE ARTE" if min(white_margins) <= 0 else ("AJUSTADO" if min(white_margins) < 0.5 else "SEGURO")
    statuses = [row["status"] for row in per_sample if row["status"]]
    candidates = None if complete != 8 else {
        "print_scale": _statistics(scale_values)["mean"],
        "cut_inset_mm": _statistics(inset_values)["mean"],
    }
    return {
        "calibration_complete": complete == 8,
        "completed_samples": complete,
        "total_samples": 8,
        "per_sample": per_sample,
        "print_scale": {"current": PRINT_SCALE, "observed": _statistics(scale_values), "by_variant": by_variant},
        "cut_inset_mm": {"current": CUT_INSET_MM, "observed": _statistics(inset_values)},
        "final_error_mm": _statistics(final_errors),
        "regression_printed_vs_production": regression,
        "error_pattern": _error_pattern(samples),
        "white_margin_mm": {"observed": _statistics(white_margins), "status": white_status},
        "minimums": {"meet": sum(row["variant"] == "MIN" and row["status"] == "CUMPLE" for row in per_sample),
                     "fail": sum(row["variant"] == "MIN" and row["status"] == "NO CUMPLE" for row in per_sample)},
        "maximums": {"within_limit": sum(row["variant"] == "MAX" and row["status"] == "CUMPLE" for row in per_sample),
                     "outside_limit": sum(row["variant"] == "MAX" and row["status"] == "NO CUMPLE" for row in per_sample)},
        "candidates": candidates,
    }


def write_calibration_report(input_path: str | Path, output_dir: str | Path) -> dict:
    """Lee mediciones y crea JSON, CSV y un resumen de texto sin recalibrar."""
    result = analyze_calibration_samples(load_calibration_measurements(input_path))
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "calibracion_resultado.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_path = destination / "calibracion_resultado.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(result["per_sample"][0]))
        writer.writeheader()
        writer.writerows(result["per_sample"])
    text_path = destination / "calibracion_reporte.txt"
    candidate = result["candidates"] or {}
    text_path.write_text(
        ("CALIBRACIÓN COMPLETA — RECOMENDACIONES NO APLICADAS\n"
         if result["calibration_complete"] else "CALIBRACIÓN INCOMPLETA\n")
        + f"Muestras completas: {result['completed_samples']} / 8\n"
        + f"PRINT_SCALE actual: {PRINT_SCALE}\n"
        + f"CUT_INSET actual: {CUT_INSET_MM} mm\n"
        + f"Patrón: {result['error_pattern']}\n"
        + f"Candidato PRINT_SCALE: {candidate.get('print_scale')}\n"
        + f"Candidato CUT_INSET: {candidate.get('cut_inset_mm')} mm\n",
        encoding="utf-8",
    )
    return {"result": result, "json": str(json_path), "csv": str(csv_path), "text": str(text_path)}


class CalibrationSheetGenerator:
    """Genera PNG A4, CSV y JSON para una prueba física controlada.

    La identificación está en el manifiesto/tabla complementaria para que
    texto alguno se una al contorno que ScanNCut debe detectar.
    """

    # Cuatro A4: 5-MIN/5-MAX/8-MIN; 8-MAX/10-MIN; 10-MAX/15-MIN; 15-MAX.
    PAGE_LAYOUTS = (("5-MIN", "5-MAX", "8-MIN"), ("8-MAX", "10-MIN"),
                    ("10-MAX", "15-MIN"), ("15-MAX",))

    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)

    @staticmethod
    def _source_art(sample: CalibrationSample, path: Path) -> None:
        """Fuente simple; pasa luego por el pipeline real del Creator."""
        image = Image.new("RGBA", (1200, 1200), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        if sample.variant == "MIN":
            draw.ellipse((110, 110, 1090, 1090), fill=(35, 110, 210, 255))
        else:
            draw.rounded_rectangle((110, 110, 1090, 1090), radius=165,
                                   fill=(220, 75, 55, 255))
        image.save(path, dpi=(300, 300))

    @staticmethod
    def _render_project(project: PlanchaProject):
        """Adaptador mínimo para reutilizar literalmente render_sheet existente."""
        editor = PlanchaEditor.__new__(PlanchaEditor)
        editor.project = project
        editor.current_project_index = 0
        editor.production_sticker_cache = {}
        editor.production_sticker_cache_pixels = 0
        # El caché de la ventana depende de estado Tk adicional. La plancha de
        # diagnóstico debe pasar por la misma rama de preparación de
        # ``render_sheet`` pero no necesita reutilizar entradas entre páginas.
        editor.prepared_production_sticker = lambda _item, _target, _modified: None
        return PlanchaEditor.render_sheet(editor, preview=False)

    def generate(self) -> dict[str, object]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        source_dir = self.output_dir / "creator_sources"
        source_dir.mkdir(exist_ok=True)
        samples = calibration_samples()
        processed: dict[str, Path] = {}
        for sample in samples:
            source = source_dir / f"{sample.sample}.png"
            self._source_art(sample, source)
            result = StickerProcessor(
                self.output_dir / "creator_work" / sample.sample,
                ProcessingProfile(nominal_size_cm=sample.nominal_cm),
            ).process(source)
            processed[sample.sample] = Path(result.artifacts["master"])

        by_name = {sample.sample: sample for sample in samples}
        pages: list[str] = []
        manifest_rows: list[dict] = []
        for page_number, names in enumerate(self.PAGE_LAYOUTS, start=1):
            items: list[PlanchaItem] = []
            x, y, row_height = 0.35, 0.35, 0.0
            for name in names:
                sample = by_name[name]
                if x + sample.production_cm > 20.65:
                    x, y, row_height = 0.35, y + row_height + 0.35, 0.0
                items.append(PlanchaItem(
                    path=str(processed[name]), name=name,
                    width_cm=sample.production_cm, height_cm=sample.production_cm,
                    x_cm=x, y_cm=y, nominal_size_cm=sample.nominal_cm,
                ))
                manifest_rows.append({**sample.measurement_row(), "page": page_number,
                                      "x_cm": x, "y_cm": y})
                x += sample.production_cm + 0.35
                row_height = max(row_height, sample.production_cm)
            project = PlanchaProject.from_images([])
            project.items = items
            sheet = self._render_project(project)
            page_path = self.output_dir / f"calibracion_a4_{page_number}.png"
            sheet.save(page_path, "PNG", dpi=(300, 300), compress_level=3)
            pages.append(str(page_path))

        json_path = self.output_dir / "calibracion_mediciones.json"
        json_path.write_text(json.dumps(manifest_rows, ensure_ascii=False, indent=2), encoding="utf-8")
        csv_path = self.output_dir / "calibracion_mediciones.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(manifest_rows[0]))
            writer.writeheader()
            writer.writerows(manifest_rows)
        return {"pages": pages, "json": str(json_path), "csv": str(csv_path),
                "samples": manifest_rows}
