"""Human review queue: answers the model is not sure about go to a person.

A criterion needs review when the independent passes disagreed or the cited evidence
was not found in the transcript. Everything else is accepted automatically.
"""
BAD_EVIDENCE = {"quote_mismatch", "invalid_turn", "no_evidence", "no_quote"}
REASONS = {"disagreement": "Прогоны модели разошлись",
           "evidence": "Доказательство не найдено в транскрипте"}


def review_reasons(item: dict, votes: int) -> list:
    reasons = []
    if votes > 1 and item.get("agreement", 1) < 1:
        reasons.append("disagreement")
    if item.get("evidence_status") in BAD_EVIDENCE:
        reasons.append("evidence")
    return reasons


def pending_review(result: dict, appeals: list) -> dict:
    """Criteria still waiting for a person. Any appeal means a person already looks at it."""
    handled = {appeal["criterion_id"] for appeal in appeals}
    pending = {}
    for cid, item in result["criteria"].items():
        reasons = review_reasons(item, result.get("votes", 1))
        if reasons and cid not in handled:
            pending[cid] = reasons
    return pending
