import io
import json

import pytest

from app import providers
from app.evaluator import output_schema

CHECKLIST = {"criteria": [{"id": "a", "type": "binary", "weight": 100, "na_allowed": False}]}
ITEM = {"reasoning": "r", "answer": "yes", "explanation": "e", "evidence_turn": 1, "quote": "q",
        "checked_from": 0, "checked_to": 1}


def reply(content):
    body = {"model": "m", "choices": [{"message": {"content": content}}], "usage": {"cost": 0}}
    return io.BytesIO(json.dumps(body).encode())


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setenv("OPENROUTER_MODEL", "m")
    monkeypatch.setenv("OPENROUTER_JSON_MODE", "object")


def test_openrouter_parses_fenced_json(env, monkeypatch):
    content = "```json\n" + json.dumps({"a": ITEM}) + "\n```"
    monkeypatch.setattr(providers.urllib.request, "urlopen", lambda *a, **k: reply(content))
    result = providers.call_openrouter("s", "p", output_schema(CHECKLIST))
    assert result["output"]["a"]["answer"] == "yes"


def test_openrouter_retries_invalid_answer(env, monkeypatch):
    answers = iter([{"a": {**ITEM, "answer": "maybe"}}, {"a": ITEM}])
    monkeypatch.setattr(providers.urllib.request, "urlopen",
                        lambda *a, **k: reply(json.dumps(next(answers))))
    assert providers.call_openrouter("s", "p", output_schema(CHECKLIST))["output"]["a"]["answer"] == "yes"


def test_openrouter_fails_after_repeated_invalid_output(env, monkeypatch):
    monkeypatch.setattr(providers.urllib.request, "urlopen", lambda *a, **k: reply("not json"))
    with pytest.raises(RuntimeError, match="invalid output"):
        providers.call_openrouter("s", "p", output_schema(CHECKLIST))


def test_missing_key_is_reported(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        providers.call_openrouter("s", "p", output_schema(CHECKLIST))


def test_scale_answer_number_is_normalized():
    checklist = {"criteria": [{"id": "a", "type": "scale", "weight": 100,
                               "scale": [{"value": 10, "label": "x"}, {"value": 0, "label": "y"}]}]}
    output = {"a": {**ITEM, "answer": 10}}
    providers.validate_output(output, output_schema(checklist))
    assert output["a"]["answer"] == "10"
