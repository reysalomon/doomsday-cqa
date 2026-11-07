from app.evaluator import aggregate

SCALE = {"type": "scale"}
BINARY = {"type": "binary"}


def test_binary_majority():
    assert aggregate(BINARY, ["yes", "no", "yes"]) == "yes"


def test_scale_majority():
    assert aggregate(SCALE, ["10", "10", "5"]) == "10"


def test_scale_uses_median_when_all_differ():
    assert aggregate(SCALE, ["20", "10", "5"]) == "10"


def test_scale_na_wins_only_with_majority():
    assert aggregate(SCALE, ["na", "na", "10"]) == "na"
    assert aggregate(SCALE, ["na", "15", "10"]) == "10"


def test_failed_pass_does_not_lose_evaluation(monkeypatch):
    from app import evaluator
    from tests.test_api import RECORD, fake_model
    import json
    from pathlib import Path

    checklist = json.loads(Path("config/checklist_default.json").read_text(encoding="utf-8"))
    calls = iter([RuntimeError("limit"), None, None])

    def flaky(system, prompt, schema):
        error = next(calls)
        if error:
            raise error
        return fake_model(system, prompt, schema)

    monkeypatch.setattr(evaluator, "call_model", flaky)
    result = evaluator.evaluate(RECORD, checklist, votes=3)
    assert result["votes"] == 2 and result["failed_passes"] == ["limit"]


def test_all_passes_failed_raises(monkeypatch):
    import json
    from pathlib import Path

    import pytest

    from app import evaluator
    from tests.test_api import RECORD

    checklist = json.loads(Path("config/checklist_default.json").read_text(encoding="utf-8"))

    def broken(*args):
        raise RuntimeError("down")

    monkeypatch.setattr(evaluator, "call_model", broken)
    with pytest.raises(RuntimeError, match="down"):
        evaluator.evaluate(RECORD, checklist, votes=2)
