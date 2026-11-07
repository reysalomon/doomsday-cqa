"""SQLite persistence and result views."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.review import pending_review
from app.scoring import compute

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY, dataset TEXT NOT NULL, channel TEXT NOT NULL, language TEXT NOT NULL,
  transcript TEXT NOT NULL, audio_url TEXT, imported_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS checklists (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, version INTEGER NOT NULL,
  config TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evaluations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL REFERENCES conversations(id),
  checklist_id INTEGER NOT NULL REFERENCES checklists(id), status TEXT NOT NULL,
  result TEXT, error TEXT, created_at TEXT NOT NULL, finished_at TEXT);
CREATE TABLE IF NOT EXISTS appeals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, evaluation_id INTEGER NOT NULL REFERENCES evaluations(id),
  criterion_id TEXT NOT NULL, comment TEXT NOT NULL, status TEXT NOT NULL, decision TEXT,
  new_answer TEXT, reason TEXT, created_at TEXT NOT NULL, decided_at TEXT,
  source TEXT NOT NULL DEFAULT 'user');
CREATE TABLE IF NOT EXISTS coaching (
  evaluation_id INTEGER NOT NULL REFERENCES evaluations(id), criterion_id TEXT NOT NULL,
  result TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (evaluation_id, criterion_id));
CREATE INDEX IF NOT EXISTS idx_eval_conv ON evaluations(conversation_id, id);
CREATE INDEX IF NOT EXISTS idx_appeal_eval ON appeals(evaluation_id, id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def db():
    path = Path(os.environ.get("CQA_DB", "data/cqa.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db(default_checklist: dict) -> None:
    with db() as conn:
        conn.executescript(SCHEMA)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(appeals)")}
        if "source" not in columns:  # databases created before the review queue
            conn.execute("ALTER TABLE appeals ADD COLUMN source TEXT NOT NULL DEFAULT 'user'")
        conn.execute("UPDATE evaluations SET status='error', error='Сервер был перезапущен', "
                     "finished_at=? WHERE status IN ('pending','running')", (now(),))
        if not conn.execute("SELECT 1 FROM checklists").fetchone():
            save_checklist(conn, default_checklist)


def save_checklist(conn, checklist: dict) -> int:
    version = conn.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM checklists").fetchone()[0]
    config = {**checklist, "version": version}
    cursor = conn.execute(
        "INSERT INTO checklists (name, version, config, created_at) VALUES (?,?,?,?)",
        (checklist["name"], version, json.dumps(config, ensure_ascii=False), now()))
    return cursor.lastrowid


def checklist_view(row) -> dict:
    return {"id": row["id"], "created_at": row["created_at"], **json.loads(row["config"])}


def get_checklist(conn, checklist_id: int | None = None) -> dict | None:
    if checklist_id is None:
        row = conn.execute("SELECT * FROM checklists ORDER BY id DESC LIMIT 1").fetchone()
    else:
        row = conn.execute("SELECT * FROM checklists WHERE id=?", (checklist_id,)).fetchone()
    return checklist_view(row) if row else None


def upsert_conversation(conn, record: dict, dataset: str) -> None:
    conn.execute(
        "INSERT INTO conversations (id, dataset, channel, language, transcript, audio_url, imported_at) "
        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET dataset=excluded.dataset, "
        "channel=excluded.channel, language=excluded.language, transcript=excluded.transcript, "
        "audio_url=excluded.audio_url",
        (record["conversation_id"], dataset, record["channel"], record["language"],
         json.dumps(record["transcript"], ensure_ascii=False), record.get("audio_url"), now()))


def conversation_record(row) -> dict:
    return {"conversation_id": row["id"], "dataset": row["dataset"], "channel": row["channel"],
            "language": row["language"], "transcript": json.loads(row["transcript"]),
            "audio_url": row["audio_url"]}


def _final_answers(result: dict, appeals: list) -> dict:
    answers = {cid: item["answer"] for cid, item in result["criteria"].items()}
    for appeal in appeals:
        if appeal["status"] == "decided" and appeal["decision"] == "changed":
            answers[appeal["criterion_id"]] = json.loads(appeal["new_answer"])
    return answers


def appeal_view(row) -> dict:
    view = dict(row)
    view["new_answer"] = json.loads(row["new_answer"]) if row["new_answer"] else None
    return view


def evaluation_view(conn, row) -> dict:
    """Combine the original model result with appeal decisions into a final result."""
    view = {key: row[key] for key in ("id", "conversation_id", "checklist_id", "status", "error",
                                      "created_at", "finished_at")}
    if row["status"] != "done":
        return view
    result = json.loads(row["result"])
    checklist = get_checklist(conn, row["checklist_id"])
    appeals = conn.execute("SELECT * FROM appeals WHERE evaluation_id=? ORDER BY id",
                           (row["id"],)).fetchall()
    final_answers = _final_answers(result, appeals)
    final = compute(checklist, final_answers)
    review = pending_review(result, appeals)
    coaching = {r["criterion_id"]: json.loads(r["result"]) for r in conn.execute(
        "SELECT * FROM coaching WHERE evaluation_id=?", (row["id"],))}
    view.update(result=result, checklist=checklist, final_answers=final_answers,
                final_score=final, original_score=result["score"],
                changed=final_answers != {k: v["answer"] for k, v in result["criteria"].items()},
                appeals=[appeal_view(a) for a in appeals],
                open_appeals=sum(a["status"] == "open" for a in appeals),
                review=review, to_review=len(review), coaching=coaching)
    return view


def latest_evaluation(conn, conversation_id: str):
    return conn.execute("SELECT * FROM evaluations WHERE conversation_id=? ORDER BY id DESC LIMIT 1",
                        (conversation_id,)).fetchone()
