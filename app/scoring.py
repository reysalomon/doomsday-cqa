"""Deterministic score calculation. The LLM never computes totals."""
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

NA = "na"


def _round2(value: Fraction) -> float:
    exact = Decimal(value.numerator) / Decimal(value.denominator)
    return float(exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _share(criterion: dict, answer) -> Fraction:
    """Fraction of the criterion's weight earned by an answer."""
    if criterion["type"] == "binary":
        if answer not in ("yes", "no"):
            raise ValueError(f"{criterion['id']}: invalid answer {answer!r}")
        return Fraction(1 if answer == "yes" else 0)
    steps = [step["value"] for step in criterion["scale"]]
    if answer not in steps:
        raise ValueError(f"{criterion['id']}: {answer!r} is not a scale step")
    return Fraction(answer, max(steps))


def compute(checklist: dict, answers: dict) -> dict:
    """Return per-criterion points, section results, total and gross-error flag.

    `answers` maps criterion id to "yes", "no", "na" or a scale step.
    `total` is None when no weighted criterion is applicable.
    """
    scored = [c for c in checklist["criteria"] if c["type"] != "flag"]
    for criterion in checklist["criteria"]:
        if criterion["id"] not in answers:
            raise ValueError(f"{criterion['id']}: missing answer")
        if answers[criterion["id"]] == NA and not criterion.get("na_allowed"):
            raise ValueError(f"{criterion['id']}: N/A is not allowed")

    applicable = [c for c in scored if answers[c["id"]] != NA and c["weight"] > 0]
    applicable_weight = sum(Fraction(c["weight"]) for c in applicable)

    rows, sections, total = {}, {}, Fraction(0)
    for criterion in scored:
        answer = answers[criterion["id"]]
        section = sections.setdefault(
            criterion.get("section") or "", {"earned": Fraction(0), "max": Fraction(0)}
        )
        if answer == NA or criterion["weight"] <= 0 or not applicable_weight:
            rows[criterion["id"]] = {"applied_weight": None, "points": None}
            continue
        applied = Fraction(criterion["weight"]) * 100 / applicable_weight
        points = applied * _share(criterion, answer)
        total += points
        section["earned"] += points
        section["max"] += applied
        rows[criterion["id"]] = {"applied_weight": _round2(applied), "points": _round2(points)}

    gross = any(
        answers[c["id"]] == "yes" for c in checklist["criteria"] if c["type"] == "flag"
    )
    return {
        "criteria": rows,
        "sections": {
            name: {"earned": _round2(s["earned"]), "max": _round2(s["max"])}
            for name, s in sections.items()
        },
        "total": _round2(total) if applicable_weight else None,
        "gross_error": gross,
    }
