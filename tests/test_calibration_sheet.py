import pytest

from app.planchas.calibration import (
    CalibrationValidationError,
    analyze_calibration_samples,
    calibration_samples,
    measurement_error_mm,
    observed_cut_inset_mm,
    observed_print_scale,
)


def test_calibration_has_min_and_max_for_each_commercial_nominal():
    samples = calibration_samples()
    assert [sample.sample for sample in samples] == [
        "5-MIN", "5-MAX", "8-MIN", "8-MAX", "10-MIN", "10-MAX", "15-MIN", "15-MAX",
    ]
    for sample in samples:
        target = sample.nominal_cm + (0.5 if sample.variant == "MAX" else 0.0)
        assert sample.expected_final_cm == pytest.approx(target)
        assert sample.measured_printed_cm is None
        assert sample.measured_cut_cm is None


def test_observed_calibration_uses_only_physical_measurements():
    rows = [sample.measurement_row() for sample in calibration_samples()[:2]]
    assert observed_print_scale(rows)["mean"] is None
    assert observed_cut_inset_mm(rows)["mean"] is None
    rows[0]["measured_printed_cm"] = rows[0]["production_cm"] * 0.97
    rows[0]["measured_cut_cm"] = rows[0]["measured_printed_cm"] - 0.3
    assert observed_print_scale(rows)["mean"] == pytest.approx(0.97)
    assert observed_cut_inset_mm(rows)["mean"] == pytest.approx(1.5)
    assert measurement_error_mm(rows[0]) is not None


def _perfect_rows():
    rows = [sample.measurement_row() for sample in calibration_samples()]
    for row in rows:
        row["measured_printed_cm"] = row["expected_printed_cm"]
        row["measured_cut_cm"] = row["expected_final_cm"]
    return rows


def test_complete_perfect_measurements_recommend_but_do_not_apply_policy():
    result = analyze_calibration_samples(_perfect_rows())
    assert result["calibration_complete"]
    assert result["candidates"]["print_scale"] == pytest.approx(0.9727)
    assert result["candidates"]["cut_inset_mm"] == pytest.approx(1.5)
    assert result["print_scale"]["current"] == pytest.approx(0.9727)


def test_incomplete_data_has_no_candidates_and_rejects_cut_larger_than_printed():
    rows = _perfect_rows()
    rows[2]["measured_printed_cm"] = None
    rows[2]["measured_cut_cm"] = None
    assert analyze_calibration_samples(rows)["candidates"] is None
    rows[0]["measured_cut_cm"] = rows[0]["measured_printed_cm"] + 0.01
    with pytest.raises(CalibrationValidationError, match="cortada"):
        analyze_calibration_samples(rows)


def test_error_patterns_distinguish_scale_from_constant_offset():
    proportional = _perfect_rows()
    constant = _perfect_rows()
    for row in proportional:
        row["measured_printed_cm"] = row["expected_printed_cm"] * 0.99
    for row in constant:
        row["measured_printed_cm"] = row["expected_printed_cm"] - 0.025
    assert "escala" in analyze_calibration_samples(proportional)["error_pattern"].lower()
    assert "constante" in analyze_calibration_samples(constant)["error_pattern"].lower()
