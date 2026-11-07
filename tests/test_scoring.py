import json
from pathlib import Path

import pytest

from app.scoring import compute

CHECKLIST = json.loads(Path("config/checklist_default.json").read_text(encoding="utf-8"))
PERFECT = {"c01": "yes", "c02": "yes", "c03": "yes", "c04": 20, "c05": "yes",
           "c06": 10, "c07": "yes", "c08": "no"}


def test_weights_sum_to_100():
    assert sum(c["weight"] for c in CHECKLIST["criteria"]) == 100


def test_perfect_score():
    assert compute(CHECKLIST, PERFECT)["total"] == 100


def test_scale_is_proportional_to_weight():
    result = compute(CHECKLIST, {**PERFECT, "c06": 7})
    assert result["criteria"]["c06"]["points"] == 10.5
    assert result["total"] == 95.5


def test_na_redistributes_weight():
    result = compute(CHECKLIST, {**PERFECT, "c03": "na", "c04": 15})
    assert result["criteria"]["c04"]["applied_weight"] == 25
    assert result["criteria"]["c04"]["points"] == 18.75
    assert result["criteria"]["c03"]["points"] is None
    assert result["total"] == 93.75


def test_total_rounds_once_at_the_end():
    answers = {**PERFECT, "c02": "na", "c07": "na", "c01": "no"}
    assert compute(CHECKLIST, answers)["total"] == 87.5


def test_gross_error_does_not_change_total():
    result = compute(CHECKLIST, {**PERFECT, "c08": "yes"})
    assert result["gross_error"] is True
    assert result["total"] == 100


def test_no_applicable_criteria_gives_no_total():
    checklist = {"criteria": [{"id": "a", "type": "binary", "weight": 10, "na_allowed": True}]}
    assert compute(checklist, {"a": "na"})["total"] is None


def test_na_rejected_when_not_allowed():
    with pytest.raises(ValueError):
        compute(CHECKLIST, {**PERFECT, "c01": "na"})


def test_invalid_scale_step_rejected():
    with pytest.raises(ValueError):
        compute(CHECKLIST, {**PERFECT, "c04": 12})
