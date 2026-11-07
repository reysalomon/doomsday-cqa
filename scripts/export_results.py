"""Write results/<dev|prod>/results.json in the organizers' format.

Usage: .venv/bin/python -m scripts.export_results DEV dev
       .venv/bin/python -m scripts.export_results <group_id> prod
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from app.export import build_results, check_results

ROOT = Path(__file__).resolve().parent.parent


def main(dataset: str, target: str) -> int:
    load_dotenv(ROOT / ".env")
    team = os.environ.get("CQA_TEAM_NAME", "").strip()
    if not team:
        print("Укажите название команды: CQA_TEAM_NAME=... в файле .env")
        return 1
    payload = build_results(dataset, team)
    problems = check_results(payload)
    out = ROOT / "results" / target / "results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ok = sum(r["status"] == "ok" for r in payload["results"])
    print(f"{out.relative_to(ROOT)}: записей {len(payload['results'])}, ok {ok}, ошибок {len(payload['results']) - ok}")
    for problem in problems:
        print("ПРОБЛЕМА:", problem)
    if not payload["results"]:
        print(f"В наборе {dataset!r} нет диалогов. Проверьте group_id.")
        return 1
    if target == "prod" and len(payload["results"]) != 10:
        print("ВНИМАНИЕ: в prod должно быть ровно 10 записей.")
    return 1 if problems else 0


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[2] not in ("dev", "prod"):
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
