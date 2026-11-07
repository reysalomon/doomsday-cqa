"""Results file in the organizers' format 1.0 (results/<dev|prod>/results.json)."""
import json
import os

from app import store

# Organizers' criterion codes for the default checklist ids.
CODES = {"c01": "contact", "c02": "discovery", "c03": "identification", "c04": "consultation",
         "c05": "empathy", "c06": "dialogue", "c07": "closure", "c08": "critical"}
MODEL_NAMES = {"sonnet": "Claude Sonnet 5.5", "opus": "Claude Opus 5.5", "haiku": "Claude Haiku 5.5"}


def _value(answer):
    if answer == "na":
        return None
    if answer in ("yes", "no"):
        return answer == "yes"
    return int(answer)


def _turns(item: dict, size: int) -> list:
    """1-based turn numbers over the full transcript, as the format requires."""
    turns = {item["evidence_turn"]}
    if item.get("evidence_status") == "checked_range":
        turns |= {item["checked_from"], item["checked_to"]}
    return sorted(t + 1 for t in turns if 0 <= t < size)


def _error(conversation_id: str, reason: str) -> dict:
    return {"conversation_id": conversation_id, "status": "error", "criteria": [], "score": None,
            "error": reason}


def _model() -> dict:
    if os.environ.get("LLM_PROVIDER", "claude_cli") == "openrouter":
        name = os.environ.get("OPENROUTER_MODEL", "openrouter")
    else:
        alias = os.environ.get("LLM_MODEL", "sonnet")
        name = MODEL_NAMES.get(alias, alias)
    return {"mode": "external_api", "name": name}


def build_results(dataset: str, team_name: str, final: bool = False) -> dict:
    """One record per conversation of the dataset; failures stay visible as status=error.

    By default the model's own answers are exported. `final` applies human review and appeals.
    """
    results = []
    with store.db() as conn:
        rows = conn.execute("SELECT * FROM conversations WHERE dataset=? ORDER BY id", (dataset,)).fetchall()
        for row in rows:
            latest = conn.execute("SELECT * FROM evaluations WHERE conversation_id=? AND status='done' "
                                  "ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
            if not latest:
                failed = store.latest_evaluation(conn, row["id"])
                reason = failed["error"] if failed and failed["error"] else "Диалог не оценён."
                results.append(_error(row["id"], reason))
                continue
            view = store.evaluation_view(conn, latest)
            ids = [c["id"] for c in view["checklist"]["criteria"]]
            if sorted(ids) != sorted(CODES):
                results.append(_error(row["id"], "Оценка сделана по чек-листу, отличному от действующего."))
                continue
            answers = view["final_answers"] if final else {k: v["answer"] for k, v in view["result"]["criteria"].items()}
            score = view["final_score"] if final else view["original_score"]
            size = len(json.loads(row["transcript"]))
            criteria = [{"criterion_id": CODES[cid], "value": _value(answers[cid]),
                         "rationale": view["result"]["criteria"][cid]["explanation"],
                         "evidence_turns": _turns(view["result"]["criteria"][cid], size)}
                        for cid in CODES]
            results.append({"conversation_id": row["id"], "status": "ok", "criteria": criteria,
                            "score": {"final_score": score["total"] if score["total"] is not None else 0.0,
                                      "critical_flag": score["gross_error"]}})
    return {"schema_version": "1.0", "team_name": team_name, "model": _model(), "results": results}


def check_results(payload: dict) -> list:
    """Problems that would make the file invalid for the organizers."""
    problems, seen = [], set()
    for record in payload["results"]:
        cid = record["conversation_id"]
        if cid in seen:
            problems.append(f"{cid}: повторяющийся ID")
        seen.add(cid)
        if record["status"] == "ok":
            codes = [c["criterion_id"] for c in record["criteria"]]
            if sorted(codes) != sorted(CODES.values()):
                problems.append(f"{cid}: нужны все 8 критериев ровно один раз")
    return problems
