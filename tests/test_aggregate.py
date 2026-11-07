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
