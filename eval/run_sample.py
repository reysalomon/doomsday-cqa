"""Evaluate selected DEV conversations and save raw results to eval/runs/."""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, ".")
from dotenv import load_dotenv

load_dotenv()
from app.evaluator import evaluate

tag, ids = sys.argv[1], sys.argv[2:]
checklist = json.loads(Path("config/checklist_default.json").read_text(encoding="utf-8"))
records = {r["conversation_id"]: r for r in
           json.loads(Path("data/dev.json").read_text(encoding="utf-8"))["data"]["records"]}
with ThreadPoolExecutor(4) as pool:
    results = list(pool.map(lambda i: evaluate(records[i], checklist, votes=int(os.environ.get("CQA_VOTES", "1"))), ids))
out = Path("eval/runs"); out.mkdir(parents=True, exist_ok=True)
(out / f"{tag}.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
for r in results:
    row = " ".join(f"{k[1:]}={v['answer']}" for k, v in r["criteria"].items())
    bad = [k for k, v in r["criteria"].items() if v["evidence_status"] != "verified"]
    print(r["model"], r["conversation_id"], r["score"]["total"], "GROSS" if r["score"]["gross_error"] else "-",
          row, "| evidence:", bad or "ok", f"| ${r['cost_usd']:.3f}")
