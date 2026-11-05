"""Stress determinista para comparar las dos heurísticas productivas A4."""

from __future__ import annotations

import os
import random

from app.planchas.model import (
    pack_all_pages,
    validate_no_overlaps,
    validate_package_geometry,
)


SEED = 20260808
LOT_COUNT = 200
STRATEGIES = ("area_desc", "longest_side_desc")


def make_lot(rng: random.Random) -> list[dict]:
    items = []
    for _ in range(rng.randint(5, 50)):
        kind = rng.choice(("square", "wide", "tall", "small", "medium", "large"))
        if kind == "square":
            side = rng.randint(2, 19)
            width = height = side
        elif kind == "wide":
            width, height = rng.randint(7, 19), rng.randint(2, 8)
        elif kind == "tall":
            width, height = rng.randint(2, 8), rng.randint(7, 19)
        elif kind == "small":
            width, height = rng.randint(2, 5), rng.randint(2, 5)
        elif kind == "medium":
            width, height = rng.randint(5, 11), rng.randint(5, 11)
        else:
            width, height = rng.randint(11, 19), rng.randint(5, 12)
        items.append({"cut_width_cm": float(width), "cut_height_cm": float(height)})
    return items


def score(result):
    return (
        len(result.impossible),
        len(result.pages),
        -result.last_page_largest_free_rect_area,
        result.rotations,
    )


def snapshot(results):
    return {
        strategy: (
            len(result.pages), len(result.impossible), result.total_placed,
            result.last_page_largest_free_rect_area, result.rotations,
        )
        for strategy, result in results.items()
    }


def run_stress(seed: int = SEED, lot_count: int = LOT_COUNT) -> dict:
    rng = random.Random(seed)
    wins = {strategy: 0 for strategy in STRATEGIES}
    totals = {strategy: 0 for strategy in STRATEGIES}
    ties = 0
    max_sheet_difference = 0
    valid_geometry = True
    deterministic = True

    for _ in range(lot_count):
        lot = make_lot(rng)
        results = {strategy: pack_all_pages(lot, strategy=strategy) for strategy in STRATEGIES}
        rerun = {strategy: pack_all_pages(lot, strategy=strategy) for strategy in STRATEGIES}
        deterministic &= snapshot(results) == snapshot(rerun)
        for strategy, result in results.items():
            totals[strategy] += len(result.pages)
            for page in result.pages:
                valid_geometry &= validate_no_overlaps(page.placed) and validate_package_geometry(page.placed)

        area_score, long_score = score(results["area_desc"]), score(results["longest_side_desc"])
        if area_score < long_score:
            wins["area_desc"] += 1
        elif long_score < area_score:
            wins["longest_side_desc"] += 1
        else:
            ties += 1
        max_sheet_difference = max(max_sheet_difference, abs(len(results["area_desc"].pages) - len(results["longest_side_desc"].pages)))

    return {
        "lots": lot_count,
        "wins": wins,
        "ties": ties,
        "total_sheets": totals,
        "max_sheet_difference": max_sheet_difference,
        "zero_overlaps": valid_geometry,
        "zero_out_of_bounds": valid_geometry,
        "deterministic": deterministic,
    }


if __name__ == "__main__":
    report = run_stress()
    text = "\n".join((
        "MULTIPAGE STRESS REPORT",
        f"seed: {SEED}",
        f"lots: {report['lots']}",
        f"area_desc wins: {report['wins']['area_desc']}",
        f"longest_side_desc wins: {report['wins']['longest_side_desc']}",
        f"ties: {report['ties']}",
        f"total sheets area_desc: {report['total_sheets']['area_desc']}",
        f"total sheets longest_side_desc: {report['total_sheets']['longest_side_desc']}",
        f"max sheet difference: {report['max_sheet_difference']}",
        f"zero overlaps: {report['zero_overlaps']}",
        f"zero out-of-bounds: {report['zero_out_of_bounds']}",
        f"deterministic: {report['deterministic']}",
    ))
    artifacts = os.path.join(os.getcwd(), "artifacts")
    os.makedirs(artifacts, exist_ok=True)
    report_path = os.path.join(artifacts, "multipage_stress_report.txt")
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write(text + "\n")
    print(text)
    print("report:", report_path)
