import json

import pytest
from fastapi.testclient import TestClient

from app import evaluator, main

RECORD = {"conversation_id": "t1", "channel": "agent chat", "language": "RU", "audio_url": None,
          "transcript": [{"timestamp": "00:00", "speaker": "client", "text": "Где тариф?"},
                         {"timestamp": "00:05", "speaker": "operator", "text": "Здравствуйте, я Алина. В кабинете."}]}


def item(answer, quote="Здравствуйте, я Алина", turn=1):
    return {"reasoning": "r", "answer": str(answer), "explanation": "e", "evidence_turn": turn,
            "quote": quote, "checked_from": 0, "checked_to": 1}


def fake_model(system, prompt, schema):
    output = {cid: item("yes") for cid in schema["properties"]}
    for cid, spec in schema["properties"].items():
        allowed = spec["properties"]["answer"]["enum"]
        if "yes" not in allowed:
            output[cid] = item(max(int(v) for v in allowed if v != "na"))
    output["c08"] = item("no", quote="")
    output["c03"] = item("na", quote="")
    return {"output": output, "cost_usd": 0, "model": "fake"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CQA_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(main, "submit", lambda function, *args: function(*args))
    monkeypatch.setattr(evaluator, "call_model", fake_model)
    with TestClient(main.app) as test_client:
        yield test_client


def evaluate(client):
    assert client.post("/api/conversations/upload", json=[RECORD]).status_code == 200
    assert client.post("/api/evaluations", json={"conversation_ids": ["t1"]}).status_code == 200
    return client.get("/api/conversations/t1").json()["evaluation"]


def test_evaluation_marks_evidence(client):
    evaluation = evaluate(client)
    assert evaluation["status"] == "done"
    assert evaluation["final_score"]["total"] == 100
    criteria = evaluation["result"]["criteria"]
    assert criteria["c01"]["evidence_status"] == "verified"
    assert criteria["c03"]["evidence_status"] == "na_explained"
    assert criteria["c08"]["evidence_status"] == "checked_range"


def test_appeal_change_recalculates_and_keeps_original(client):
    evaluation = evaluate(client)
    appeal = client.post("/api/appeals", json={"evaluation_id": evaluation["id"], "criterion_id": "c04",
                                               "comment": "Ответ неполный"}).json()
    assert client.post("/api/appeals", json={"evaluation_id": evaluation["id"], "criterion_id": "c04",
                                             "comment": "Ещё раз"}).status_code == 409
    assert client.get("/api/appeals?status=open").json()[0]["fragment"]
    decided = client.post(f"/api/appeals/{appeal['id']}/decision",
                          json={"decision": "changed", "new_answer": "10", "reason": "Есть пробел"}).json()
    assert decided["original_score"]["total"] == 100
    assert decided["final_score"]["total"] == 87.5
    assert decided["appeals"][0]["new_answer"] == 10


def test_confirmed_appeal_keeps_score(client):
    evaluation = evaluate(client)
    appeal = client.post("/api/appeals", json={"evaluation_id": evaluation["id"], "criterion_id": "c01",
                                               "comment": "Не согласен"}).json()
    decided = client.post(f"/api/appeals/{appeal['id']}/decision",
                          json={"decision": "confirmed", "reason": "Приветствие есть"}).json()
    assert decided["final_score"]["total"] == 100


def test_invalid_appeal_answer_rejected(client):
    evaluation = evaluate(client)
    appeal = client.post("/api/appeals", json={"evaluation_id": evaluation["id"], "criterion_id": "c01",
                                               "comment": "x"}).json()
    response = client.post(f"/api/appeals/{appeal['id']}/decision",
                           json={"decision": "changed", "new_answer": "na", "reason": "y"})
    assert response.status_code == 422


def test_new_checklist_version_applies_to_new_evaluation(client):
    first = evaluate(client)
    current = client.get("/api/checklists").json()[0]
    criteria = [c for c in current["criteria"] if c["id"] != "c07"]
    criteria.append({"id": "c09", "title": "Новый", "type": "binary", "weight": 5, "rule": "Правило"})
    saved = client.post("/api/checklists", json={"name": current["name"], "criteria": criteria}).json()
    assert saved["version"] == 2
    client.post("/api/evaluations", json={"conversation_ids": ["t1"], "checklist_id": saved["id"]})
    second = client.get("/api/conversations/t1").json()["evaluation"]
    assert second["id"] != first["id"]
    assert "c09" in second["result"]["criteria"] and "c07" not in second["result"]["criteria"]


def test_bad_checklist_rejected(client):
    response = client.post("/api/checklists", json={"name": "x", "criteria": [
        {"id": "a", "title": "A", "type": "scale", "weight": 10, "rule": "r", "scale": []}]})
    assert response.status_code == 422


def test_voice_blocked_on_openrouter(client, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("CQA_ALLOW_VOICE_ON_OPENROUTER", raising=False)
    voice = {**RECORD, "conversation_id": "v1", "channel": "voice call", "audio_url": "https://x/y"}
    client.post("/api/conversations/upload", json=[voice])
    client.post("/api/evaluations", json={"conversation_ids": ["v1"]})
    evaluation = client.get("/api/conversations/v1").json()["evaluation"]
    assert evaluation["status"] == "error" and "OpenRouter" in evaluation["error"]


def test_audio_offsets_skip_pauses():
    turns = [{"timestamp": "2026-11-03T10:00:00+00:00", "speaker": "system", "text": "Запись запущена"},
             {"timestamp": "2026-11-03T10:00:10+00:00", "speaker": "system", "text": "Запись приостановлена"},
             {"timestamp": "2026-11-03T10:00:30+00:00", "speaker": "system", "text": "Запись возобновлена"},
             {"timestamp": "2026-11-03T10:00:40+00:00", "speaker": "operator", "text": "Да"}]
    assert main.audio_offsets(turns)[-1] == 20


def test_audio_stream_extracts_fresh_link(client, monkeypatch):
    voice = {**RECORD, "conversation_id": "v2", "channel": "voice call", "audio_url": "https://x/player"}
    client.post("/api/conversations/upload", json=[voice])

    class Page:
        text = '<audio><source src="https://y/a.mp3?sp=r&amp;sig=1" type="audio/mpeg"></audio>'

        def raise_for_status(self):
            pass

    monkeypatch.setattr(main.httpx, "get", lambda *a, **k: Page())
    response = client.get("/api/audio/v2/stream", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "https://y/a.mp3?sp=r&sig=1"


def split_model(monkeypatch):
    """Three passes that disagree on c05 and cite a quote that is not in the transcript for c01."""
    calls = iter(range(100))

    def model(system, prompt, schema):
        result = fake_model(system, prompt, schema)
        result["output"]["c01"] = item("yes", quote="Добрый вечер")
        if next(calls) == 0:
            result["output"]["c05"] = item("no")
        return result
    monkeypatch.setattr(evaluator, "call_model", model)
    monkeypatch.setenv("CQA_VOTES", "3")


def test_uncertain_answers_go_to_review(client, monkeypatch):
    split_model(monkeypatch)
    evaluation = evaluate(client)
    assert evaluation["review"] == {"c01": ["evidence"], "c05": ["disagreement"]}
    queue = client.get("/api/reviews").json()
    assert queue["pending"] == 2 and queue["answers"] == 8
    assert {i["criterion"]["id"] for i in queue["items"]} == {"c01", "c05"}
    assert client.get("/api/conversations").json()[0]["evaluation"]["to_review"] == 2


def test_review_decision_changes_score_and_leaves_queue(client, monkeypatch):
    split_model(monkeypatch)
    evaluation = evaluate(client)
    view = client.post("/api/reviews", json={"evaluation_id": evaluation["id"], "criterion_id": "c01",
                                             "decision": "changed", "new_answer": "no"}).json()
    assert view["final_answers"]["c01"] == "no" and view["final_score"]["total"] < 100
    assert "c01" not in view["review"]
    assert client.post("/api/reviews", json={"evaluation_id": evaluation["id"], "criterion_id": "c01",
                                             "decision": "confirmed"}).status_code == 409
    assert client.post("/api/reviews", json={"evaluation_id": evaluation["id"], "criterion_id": "c05",
                                             "decision": "confirmed"}).json()["to_review"] == 0
    assert client.get("/api/appeals").json() == []


def test_coaching_only_for_lost_points_and_cached(client, monkeypatch):
    from app import coach
    calls = []

    def model(system, prompt, schema):
        calls.append(prompt)
        return {"output": {"mistake": "m", "turn": 99, "better_reply": "b", "better_reply_ru": "b",
                           "tip": "t"}, "cost_usd": 0.01, "model": "fake"}
    monkeypatch.setattr(coach, "call_model", model)
    evaluation = evaluate(client)
    url = f"/api/evaluations/{evaluation['id']}/coach/"
    assert client.post(url + "c01").status_code == 409
    client.post("/api/appeals", json={"evaluation_id": evaluation["id"], "criterion_id": "c01", "comment": "x"})
    appeal = client.get("/api/appeals").json()[0]
    client.post(f"/api/appeals/{appeal['id']}/decision", json={"decision": "changed", "reason": "r", "new_answer": "no"})
    advice = client.post(url + "c01").json()
    assert advice["better_reply"] == "b" and advice["turn"] == 1  # out-of-range turn falls back to evidence
    assert client.post(url + "c01").json() == advice and len(calls) == 1
    assert "c01" in client.get("/api/conversations/t1").json()["evaluation"]["coaching"]


def test_export_matches_organizers_format(client):
    from app.export import build_results, check_results
    evaluate(client)
    payload = build_results("UPLOAD", "Team")
    assert payload["schema_version"] == "1.0" and check_results(payload) == []
    record = payload["results"][0]
    values = {c["criterion_id"]: c["value"] for c in record["criteria"]}
    assert values == {"contact": True, "discovery": True, "identification": None, "consultation": 20,
                      "empathy": True, "dialogue": 10, "closure": True, "critical": False}
    assert record["criteria"][0]["evidence_turns"] == [2]  # 1-based
    assert record["score"] == {"final_score": 100.0, "critical_flag": False}


def test_export_keeps_failed_conversations(client, monkeypatch):
    from app.export import build_results
    monkeypatch.setattr(evaluator, "call_model", lambda *a: (_ for _ in ()).throw(RuntimeError("limit")))
    evaluate(client)
    record = build_results("UPLOAD", "Team")["results"][0]
    assert record["status"] == "error" and record["score"] is None and record["criteria"] == []
