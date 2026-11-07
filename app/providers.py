"""Model providers. Each returns {"output": dict, "cost_usd": float, "model": str}."""
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
ATTEMPTS = 2


def validate_output(output: dict, schema: dict) -> None:
    """Reject answers the provider did not constrain, such as an invalid enum value."""
    if "answer" not in next(iter(schema["properties"].values())).get("properties", {}):
        missing = [field for field in schema["required"] if field not in output]
        if missing:  # a plain schema such as coaching: only check the fields exist
            raise ValueError(f"missing fields {missing}")
        return
    for name, spec in schema["properties"].items():
        item = output.get(name)
        if not isinstance(item, dict):
            raise ValueError(f"{name}: missing criterion")
        missing = [field for field in spec["required"] if field not in item]
        if missing:
            raise ValueError(f"{name}: missing fields {missing}")
        allowed = spec["properties"]["answer"]["enum"]
        item["answer"] = str(item["answer"])
        if item["answer"] not in allowed:
            raise ValueError(f"{name}: answer {item['answer']!r} not in {allowed}")
        for field in ("evidence_turn", "checked_from", "checked_to"):
            item[field] = int(item[field])


def parse_json(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return json.loads(cleaned)


def call_claude_cli(system: str, prompt: str, schema: dict) -> dict:
    """Call Claude through the logged-in CLI with tools and local settings disabled."""
    model = os.environ.get("LLM_MODEL", "sonnet")
    command = ["claude", "-p", "--model", model, "--output-format", "json",
               "--no-session-persistence", "--system-prompt", system,
               "--tools", "", "--setting-sources", "", "--strict-mcp-config",
               "--json-schema", json.dumps(schema)]
    for attempt in range(ATTEMPTS):
        try:
            done = subprocess.run(command, input=prompt, capture_output=True, text=True, timeout=240)
        except subprocess.TimeoutExpired:
            if attempt + 1 == ATTEMPTS:
                raise RuntimeError("claude не ответил за 240 секунд") from None
            continue
        if done.returncode == 0 or attempt + 1 == ATTEMPTS:
            break
        time.sleep(5)
    if done.returncode != 0:
        raise RuntimeError(f"claude exited {done.returncode}: {done.stderr[:300] or done.stdout[:300]}")
    payload = json.loads(done.stdout)
    if payload.get("is_error") or not payload.get("structured_output"):
        raise RuntimeError(f"claude returned no result: {str(payload.get('result'))[:300]}")
    validate_output(payload["structured_output"], schema)
    return {"output": payload["structured_output"], "cost_usd": payload.get("total_cost_usd", 0),
            "model": model}


def _openrouter_request(body: dict, key: str) -> dict:
    request = urllib.request.Request(
        OPENROUTER_URL, data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "X-Title": "CQA Hackathon Prototype"})
    try:
        with urllib.request.urlopen(request, timeout=240) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:300]
        raise RuntimeError(f"OpenRouter HTTP {error.code}: {detail}") from error


def call_openrouter(system: str, prompt: str, schema: dict) -> dict:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set in .env")
    model = os.environ.get("OPENROUTER_MODEL", "google/gemma-4-31b-it:free")
    if os.environ.get("OPENROUTER_JSON_MODE", "object") == "schema":
        response_format = {"type": "json_schema",
                           "json_schema": {"name": "evaluation", "strict": True, "schema": schema}}
        user = prompt
    else:
        response_format = {"type": "json_object"}
        user = f"{prompt}\n\nВерни только JSON по этой JSON Schema:\n{json.dumps(schema, ensure_ascii=False)}"
    body = {"model": model, "temperature": 0, "response_format": response_format,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}

    failure = None
    for _ in range(ATTEMPTS):
        payload = _openrouter_request(body, key)
        if payload.get("error"):
            raise RuntimeError(f"OpenRouter error: {str(payload['error'])[:300]}")
        try:
            output = parse_json(payload["choices"][0]["message"]["content"])
            validate_output(output, schema)
        except (KeyError, IndexError, TypeError, ValueError) as error:
            failure = error
            continue
        return {"output": output, "cost_usd": payload.get("usage", {}).get("cost", 0) or 0,
                "model": payload.get("model", model)}
    raise RuntimeError(f"{model} returned invalid output: {failure}")


PROVIDERS = {"claude_cli": call_claude_cli, "openrouter": call_openrouter}


def call_model(system: str, prompt: str, schema: dict) -> dict:
    name = os.environ.get("LLM_PROVIDER", "claude_cli")
    if name not in PROVIDERS:
        raise RuntimeError(f"Unknown LLM_PROVIDER {name!r}")
    return PROVIDERS[name](system, prompt, schema)
