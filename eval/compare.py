"""Compare saved runs with each other and with a small reviewed reference set."""
import json
import sys
from pathlib import Path

REVIEWED = {("p1-ru-012", "c04"): 20, ("p1-ru-012", "c07"): "na", ("p1-ru-016", "c04"): 20,
            ("p1-ru-016", "c06"): 4, ("p1-ru-014", "c02"): "no", ("p1-en-006", "c04"): 20,
            ("p1-en-006", "c06"): 10, ("p1-kz-015", "c07"): "yes", ("p1-ru-026", "c02"): "no",
            ("p1-ru-026", "c04"): 5}


def load(tag):
    rows = json.loads(Path(f"eval/runs/{tag}.json").read_text(encoding="utf-8"))
    return {r["conversation_id"]: r for r in rows}


runs = {tag: load(tag) for tag in sys.argv[1:]}
for tag, run in runs.items():
    hits = sum(run[i]["criteria"][k]["answer"] == v for (i, k), v in REVIEWED.items())
    cost = sum(r["cost_usd"] for r in run.values())
    items = [c for r in run.values() for c in r["criteria"].values()]
    split = sum(len(set(c.get("votes", []))) > 1 for c in items)
    print(f"{tag}: reviewed {hits}/{len(REVIEWED)}, ${cost:.2f}, split votes {split}/{len(items)}")
tags = list(runs)
for a, b in zip(tags, tags[1:]):
    same = total = 0
    gaps = []
    for i, row in runs[a].items():
        gaps.append(abs(row["score"]["total"] - runs[b][i]["score"]["total"]))
        for k, item in row["criteria"].items():
            total += 1
            same += item["answer"] == runs[b][i]["criteria"][k]["answer"]
    print(f"{a} vs {b}: {same}/{total}, mean total gap {sum(gaps) / len(gaps):.2f}")
