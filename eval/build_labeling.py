"""Build a self-contained local labeling page. It embeds transcripts, so it stays out of Git."""
import json
from pathlib import Path

IDS = ["p1-ru-002", "p1-ru-005", "p1-ru-009", "p1-ru-012", "p1-ru-014", "p1-ru-016", "p1-ru-022",
       "p1-ru-025", "p1-ru-026", "p1-ru-029", "p1-kz-003", "p1-kz-006", "p1-kz-009", "p1-kz-012",
       "p1-kz-015", "p1-en-002", "p1-en-006", "p1-en-011", "p4-ru-001", "p4-ru-002"]

checklist = json.loads(Path("config/checklist_default.json").read_text(encoding="utf-8"))
records = {r["conversation_id"]: r for r in
           json.loads(Path("data/dev.json").read_text(encoding="utf-8"))["data"]["records"]}
dialogs = [{k: records[i][k] for k in ("conversation_id", "channel", "language", "transcript")} for i in IDS]
data = json.dumps({"checklist": checklist, "dialogs": dialogs}, ensure_ascii=False).replace("</", "<\\/")
template = Path("eval/labeling_template.html").read_text(encoding="utf-8")
Path("eval/labeling.html").write_text(template.replace("__DATA__", data), encoding="utf-8")
print("dialogs", len(dialogs))
