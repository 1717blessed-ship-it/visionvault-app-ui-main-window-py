"""Adapter between order jobs and the existing productive A4 calculator.

Keeping this translation out of Tk widgets makes the commercial/productive
boundary testable and prevents product-name checks from spreading through UI.
"""
from __future__ import annotations

from typing import Any
import json


PLANCHA_A4_PRODUCT_CODE = "plancha_a4"


def supports_productive_plancha_a4(job: dict[str, Any]) -> bool:
    """Whether a job belongs to the sole product currently supported by Fase 3.

    New catalogued jobs use ``product_id``/``product_code``.  The size/material
    fallback is deliberately centralized for legacy jobs until their catalog
    reference is available.
    """
    code = str(job.get("product_code") or job.get("product_catalog_code") or "").strip().lower()
    if code:
        return code == PLANCHA_A4_PRODUCT_CODE
    size = str(job.get("size") or job.get("size_snapshot") or "").strip().lower()
    material = str(job.get("material") or job.get("product_name_snapshot") or "").strip().lower()
    title = str(job.get("title") or "").strip().lower()
    return size == "a4" and ("plancha" in material or "plancha" in title)


def analysis_context(job: dict[str, Any], *, applied_price: float | None = None) -> dict[str, Any]:
    """Build the calculator input without duplicating any pricing formula."""
    estimate = dict(job.get("production_estimate") or {})
    design_minutes = estimate.get("design_minutes_list") or job.get("design_minutes_list") or []
    if not design_minutes and estimate.get("design_minutes_json"):
        try:
            design_minutes = json.loads(estimate["design_minutes_json"])
        except (TypeError, ValueError):
            design_minutes = []
    if not isinstance(design_minutes, list):
        design_minutes = []
    context = {
        "quantity": job.get("quantity", 1),
        "unique_designs": estimate.get("unique_designs", job.get("unique_designs", len(design_minutes) or 1)),
        "design_minutes": design_minutes,
        "print_minutes": estimate.get("print_minutes", job.get("estimated_print_minutes")),
        "cut_minutes": estimate.get("cut_minutes", job.get("estimated_cut_minutes")),
        "production_mode": estimate.get("production_mode", job.get("production_mode", "individual")),
        "productive_surcharge": estimate.get("productive_surcharge", 0),
        "additional_services": estimate.get("additional_services", job.get("extra_services", 0)),
        "authorized_discount": estimate.get("authorized_discount", 0),
        "customer_kind": job.get("customer_kind", "first_purchase"),
    }
    if applied_price is not None:
        context["applied_price"] = applied_price
    return context


def snapshot_job(job: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    """Return a job enriched with immutable values ready for order persistence."""
    result = dict(job)
    result.update({
        "subtotal": analysis.get("applied_price") if analysis.get("applied_price") is not None else job.get("subtotal", 0),
        "base_price_snapshot": analysis["base_price"],
        "suggested_price_snapshot": analysis["suggested_price"],
        "applied_price_snapshot": analysis.get("applied_price"),
        "manual_price_snapshot": analysis.get("manual_price"),
        "price_source": analysis.get("price_source", "suggested"),
        "productive_cost": analysis["productive_cost"],
        "final_cost": analysis["final_cost"],
        "productive_margin": analysis["applied_productive_margin_percentage"] if analysis.get("applied_price") is not None else analysis["productive_margin_percentage"],
        "final_margin": analysis["applied_final_margin_percentage"] if analysis.get("applied_price") is not None else analysis["final_margin_percentage"],
        "productive_classification": analysis["classification"],
        "production_mode": analysis["production_mode"],
        "cost_mp": analysis.get("raw_material_cost", 0),
        "cost_mo": analysis.get("labor_cost", 0),
        "cost_cf": analysis.get("overhead_cost", 0),
        "cost_total": analysis["productive_cost"],
        "production_estimate": {
            **dict(job.get("production_estimate") or {}),
            "unique_designs": analysis["unique_designs"], "production_mode": analysis["production_mode"],
            "design_minutes": analysis["estimated_design_minutes"], "print_minutes": analysis["estimated_print_minutes"],
            "cut_minutes": analysis["estimated_cut_minutes"],
            "design_minutes_list": analysis.get("design_minutes_list", job.get("production_estimate", {}).get("design_minutes_list", [])),
            "productive_surcharge": analysis["productive_surcharge"],
            "additional_services": analysis["additional_services"],
            "authorized_discount": analysis["authorized_discount"],
        },
    })
    return result
