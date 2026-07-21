"""Script de diagnóstico para reglas de precio y modelos de costos.

Uso:
  python diagnose_cost_model.py [--db PATH] [--price-rule-id ID]

El script abre la DB en modo solo lectura y no modifica nada.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any
import sys

from costos.models.cost_component import CostComponent
from costos.models.cost_rule import CostRule
from costos.services.cost_calculator import CostCalculator


def open_readonly(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def normalize_cost_mode(value: Any) -> str:
    if value is None:
        return "percent"
    s = str(value).strip().casefold()
    if s in {"fijo", "fixed"} or "fix" in s:
        return "fixed"
    if s in {"percent", "percentage", "porcentaje", "%", "percento"} or "por" in s:
        return "percent"
    return s


def build_cost_rule_from_model_row(row: dict) -> CostRule | None:
    if not row:
        return None
    if not row.get("id"):
        return None
    rule = CostRule(
        id=int(row.get("id") or 0),
        name=str(row.get("name") or ""),
        product_type=str(row.get("material") or ""),
        minimum_margin=float(row.get("cost_mp_percent") or 0),
        active=bool(row.get("id") is not None),
    )

    # Track component sources separately for diagnostics
    legacy_components: list[CostComponent] = []
    json_components: list[CostComponent] = []

    # Add legacy MP/MO/CF components from top-level columns
    for label, code, mode_key, value_key in (
        ("Materia Prima", "mp", "cost_mp_mode", "cost_mp_percent"),
        ("Mano de Obra", "mo", "cost_mo_mode", "cost_mo_percent"),
        ("Carga Fabril", "cf", "cost_cf_mode", "cost_cf_percent"),
    ):
        mode = normalize_cost_mode(row.get(mode_key))
        if mode == "percent":
            value_type = "percentage"
        elif mode == "fixed":
            value_type = "fixed"
        else:
            value_type = mode
        try:
            value = float(row.get(value_key) or 0)
        except Exception:
            value = 0.0
        comp = CostComponent(name=label, code=code, value_type=value_type, value=value)
        legacy_components.append(comp)
        rule.add_component(comp)

    components_payload = row.get("components_json") or row.get("components") or []
    invalid_json = False
    if isinstance(components_payload, str):
        try:
            components_payload = json.loads(components_payload)
        except Exception:
            components_payload = []
            invalid_json = True
    if isinstance(components_payload, list):
        for component in components_payload:
            if not isinstance(component, dict):
                continue
            try:
                comp = CostComponent(
                    name=str(component.get("name") or component.get("code") or "Componente"),
                    code=str(component.get("code") or component.get("name") or "component"),
                    value_type=str(component.get("value_type") or "percentage"),
                    value=float(component.get("value") or 0),
                    enabled=bool(component.get("enabled", True)),
                    order=int(component.get("order") or 0),
                )
            except Exception:
                continue
            json_components.append(comp)
            rule.add_component(comp)

    # attach meta for diagnostics
    setattr(rule, "_legacy_components", legacy_components)
    setattr(rule, "_json_components", json_components)
    setattr(rule, "_invalid_components_json", invalid_json)
    return rule


def fetch_row(conn: sqlite3.Connection, table: str, pk: int) -> dict | None:
    cur = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (int(pk),))
    row = cur.fetchone()
    if not row:
        return None
    return {k: row[idx] for idx, k in enumerate([d[0] for d in cur.description])}


def fetch_first_active_price_rule(conn: sqlite3.Connection) -> dict | None:
    cur = conn.execute("SELECT * FROM price_rules WHERE active = 1 ORDER BY material COLLATE NOCASE, size COLLATE NOCASE, min_quantity DESC, id DESC LIMIT 1")
    row = cur.fetchone()
    if not row:
        return None
    return {k: row[idx] for idx, k in enumerate([d[0] for d in cur.description])}


def diag(db_path: Path, price_rule_id: int | None = None, verbose: bool = False, export: str | None = None) -> None:
    conn = open_readonly(db_path)
    conn.row_factory = sqlite3.Row
    # select price rule
    if price_rule_id:
        pr = fetch_row(conn, "price_rules", price_rule_id)
    else:
        pr = fetch_first_active_price_rule(conn)

    if not pr:
        # collect available price_rule ids
        cur = conn.execute("SELECT id FROM price_rules ORDER BY id")
        available = [r[0] for r in cur.fetchall()]
        msg = "No se encontró ninguna regla de precio activa ni con ese ID."
        print(msg)
        diagnostics = {
            "price_rule_row": None,
            "cost_rule_row": None,
            "available_price_rule_ids": available,
            "db_path": str(db_path.resolve()),
        }
        # always write export if requested
        if export:
            try:
                with open(export, "w", encoding="utf-8") as fh:
                    json.dump(diagnostics, fh, ensure_ascii=False, indent=2)
                print(f"\nExportado informe a: {export}")
            except Exception as e:
                print(f"No se pudo escribir export file: {e}")
        # return warning exit code
        print("\n=== Final Status ===")
        print("⚠ WARN (exit code 1)")
        sys.exit(1)

    print("\n=== Price Rule (db row) ===")
    print(json.dumps(pr, indent=2, ensure_ascii=False))

    cost_model_id = pr.get("cost_model_id")
    print(f"\ncost_model_id: {cost_model_id}")

    model_row = None
    if cost_model_id not in (None, "", 0):
        cur = conn.execute("SELECT * FROM cost_rules WHERE id = ?", (int(cost_model_id),))
        r = cur.fetchone()
        if r:
            model_row = {k: r[idx] for idx, k in enumerate([d[0] for d in cur.description])}

    print("\n=== Cost Rule (db row) ===")
    if model_row:
        print(json.dumps(model_row, indent=2, ensure_ascii=False))
    else:
        print("<no model found>")

    # build cost rule like _build_cost_rule_from_model
    built_rule = build_cost_rule_from_model_row(model_row) if model_row else None
    print("\n=== components_json raw ===")
    if model_row:
        print(model_row.get("components_json") or "[]")
    else:
        print("[]")

    # Print components by source
    print("\n=== LEGACY components (from top-level columns) ===")
    legacy_list = []
    json_list = []
    final_list = []
    if built_rule:
        legacy_list = [asdict(c) for c in getattr(built_rule, "_legacy_components", [])]
        json_list = [asdict(c) for c in getattr(built_rule, "_json_components", [])]
        final_list = [asdict(c) for c in built_rule.components]
    print(json.dumps(legacy_list, indent=2, ensure_ascii=False))

    print("\n=== COMPONENTES JSON (parsed) ===")
    print(json.dumps(json_list, indent=2, ensure_ascii=False))

    print("\n=== COMPONENTES FINALES (final list passed to CostCalculator) ===")
    if final_list:
        print(json.dumps(final_list, indent=2, ensure_ascii=False))
    else:
        print("<no components>")

    # Run calculator
    sale_price = float(pr.get("price") or 0)
    quantity = max(1, int(pr.get("min_quantity") or 1))
    analysis = None
    if built_rule:
        analysis = CostCalculator.calculate(
            built_rule,
            sale_price=sale_price,
            quantity=quantity,
            hours=0.0,
            surface=0.0,
            suggested_price=sale_price,
        )

    print("\n=== CostAnalysisResult ===")
    if analysis:
        # convert to dict-ish
        out = {
            "rule_name": analysis.rule_name,
            "rule_id": analysis.rule_id,
            "product_type": analysis.product_type,
            "suggested_price": analysis.suggested_price,
            "cost_total": analysis.cost_total,
            "gross_profit": analysis.gross_profit,
            "margin_percentage": analysis.margin_percentage,
            "markup_percentage": analysis.markup_percentage,
            "profitability_status": analysis.profitability_status,
            "warnings": analysis.warnings,
            "components": [asdict(c) for c in analysis.components],
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        analysis_out = out
    else:
        print("<no analysis — no model>")
        analysis_out = None

    # Build the presentation row like price_rule_presentations()
    print("\n=== Presentation (UI) row ===")
    resolved_rule = built_rule
    legacy_rule = not bool(pr.get("cost_model_id"))
    if resolved_rule is None:
        presentation = {
            **pr,
            "model_name": "—",
            "cost_total": 0.0,
            "margin": round(sale_price - 0.0, 2),
            "margin_pct": 0.0,
            "status": "Modelo no disponible",
            "detail": "Modelo no disponible",
        }
    else:
        presentation = {**pr}
        presentation.update({
            "model_name": str(resolved_rule.name or "Modelo"),
            "cost_total": round(float(analysis.cost_total or 0), 2) if analysis else 0.0,
            "margin": round(float(analysis.gross_profit or 0), 2) if analysis else 0.0,
            "margin_pct": round(float(analysis.margin_percentage or 0), 1) if analysis else 0.0,
            "status": (
                "Regla antigua" if legacy_rule else (
                    "Rentable" if analysis and analysis.profitability_status == "profitable" else (
                        "Margen bajo" if analysis and analysis.profitability_status == "margin_low" else (
                            "Pérdida" if analysis and analysis.profitability_status == "loss" else (
                                "Sin costos" if analysis and analysis.profitability_status == "no_costs" else "Sin datos"
                            )
                        )
                    )
                )
            ),
            "detail": (
                " | ".join(
                    [f"{c.name}: {('%g' % c.value) + ('%' if c.value_type=='percentage' else '')} → ${c.amount:,.2f}" for c in analysis.components]
                ) if analysis and analysis.components else "Sin componentes configurados"
            ),
        })

    print(json.dumps(presentation, indent=2, ensure_ascii=False))

    # Auto-detections
    print("\n=== Auto-detections ===")
    issues = []
    if not model_row and cost_model_id not in (None, "", 0):
        issues.append(("error", "Modelo inexistente"))
    if cost_model_id in (None, "", 0):
        issues.append(("info", "Price rule sin cost_model_id — usa campos legacy"))
    if built_rule:
        # invalid JSON detection
        if getattr(built_rule, "_invalid_components_json", False):
            issues.append(("error", "components_json inválido (parsing failure)"))
        codes = [c.code for c in built_rule.components]
        names = [c.name for c in built_rule.components]
        dup_codes = sorted({c for c in codes if codes.count(c) > 1})
        dup_names = sorted({n for n in names if names.count(n) > 1})
        if dup_codes:
            issues.append(("warning", f"Componentes duplicados por code: {', '.join(dup_codes)}"))
        if dup_names:
            issues.append(("warning", f"Componentes duplicados por name: {', '.join(dup_names)}"))
        # differences between legacy columns and components_json
        legacy_triplet = {"mp": float(model_row.get("cost_mp_percent") or 0) if model_row else 0,
                          "mo": float(model_row.get("cost_mo_percent") or 0) if model_row else 0,
                          "cf": float(model_row.get("cost_cf_percent") or 0) if model_row else 0}
        json_map = {c.code: c.value for c in built_rule.components}
        diffs = []
        for k, v in legacy_triplet.items():
            jv = json_map.get(k)
            if jv is not None and abs(jv - v) > 1e-6:
                diffs.append(f"{k}: legacy={v} vs components_json={jv}")
        if diffs:
            issues.append(("warning", "Diferencias legacy vs components_json: " + "; ".join(diffs)))
        # disabled components
        disabled = [c.code for c in built_rule.components if not c.enabled]
        if disabled:
            issues.append(("info", "Componentes deshabilitados: " + ", ".join(disabled)))
        # invalid values and negative values
        invalid = []
        negative = []
        missing_code_or_type = []
        for c in built_rule.components:
            if not getattr(c, "code", None) or not getattr(c, "value_type", None):
                missing_code_or_type.append(getattr(c, "name", "<sin nombre>"))
            try:
                if isinstance(c.value, (int, float)) and c.value < 0:
                    negative.append(c.code)
            except Exception:
                invalid.append(c.code)
        if missing_code_or_type:
            issues.append(("error", "Componentes con código o value_type faltante: " + ", ".join(missing_code_or_type)))
        if invalid:
            issues.append(("warning", "Componentes con valores inválidos: " + ", ".join(invalid)))
        if negative:
            issues.append(("warning", "Componentes con valores negativos: " + ", ".join(negative)))
        # empty components
        if len(built_rule.components) == 0:
            issues.append(("warning", "Modelo sin componentes configurados"))

    # Print summary and final status
    print("\n=== Summary ===")
    ok = True
    has_warn = False
    has_err = False
    if model_row:
        print("✓ Modelo encontrado")
    else:
        print("✗ Modelo inexistente")
        ok = False
    if built_rule:
        print("✓ Regla resuelta")
    else:
        print("✗ Regla no resuelta")
        ok = False
    for level, msg in issues:
        if level == "warning":
            has_warn = True
        if level == "error":
            has_err = True
        prefix = "⚠" if level == "warning" else ("✗" if level == "error" else "i")
        print(f"{prefix} {msg}")

    # Build diagnostics payload for export or verbose
    diagnostics = {
        "price_rule_row": pr,
        "cost_rule_row": model_row,
        "components_json_raw": model_row.get("components_json") if model_row else None,
        "legacy_components": legacy_list,
        "json_components": json_list,
        "final_components": final_list,
        "analysis": analysis_out,
        "presentation": presentation,
        "issues": issues,
    }

    if verbose:
        print("\n=== Verbose diagnostics (full JSON) ===")
        print(json.dumps(diagnostics, indent=2, ensure_ascii=False))

    if export:
        try:
            with open(export, "w", encoding="utf-8") as fh:
                json.dump(diagnostics, fh, ensure_ascii=False, indent=2)
            print(f"\nExportado informe a: {export}")
        except Exception as e:
            print(f"No se pudo escribir export file: {e}")

    # decide exit code: 0=OK,1=Warnings,2=Errors
    exit_code = 0
    if has_err:
        exit_code = 2
    elif has_warn:
        exit_code = 1
    # final status line
    status = "OK" if exit_code == 0 else ("WARN" if exit_code == 1 else "ERROR")
    symbol = "✓" if exit_code == 0 else ("⚠" if exit_code == 1 else "✗")
    print("\n=== Final Status ===")
    print(f"{symbol} {status} (exit code {exit_code})")
    sys.exit(exit_code)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="visionvault.db", help="Ruta a la DB SQLite")
    p.add_argument("--price-rule-id", type=int, help="ID de price_rule a diagnosticar (opcional)")
    p.add_argument("--verbose", action="store_true", help="Mostrar diagnóstico completo (JSON)")
    p.add_argument("--export", help="Ruta de salida JSON para exportar el informe")
    args = p.parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"DB no encontrada: {db_path}")
        return
    diag(db_path, args.price_rule_id, verbose=args.verbose, export=args.export)


if __name__ == "__main__":
    main()
