"""HTTP API and static UI for Conversation Quality Analytics."""
import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import store
from app.checklist import allowed_answers, validate_checklist
from app.coach import coach, lost_points
from app.evaluator import evaluate
from app.review import REASONS

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
SPEAKERS = {"client", "operator", "bot", "system"}
executor = ThreadPoolExecutor(int(os.environ.get("CQA_WORKERS", "3")))


def submit(function, *args):
    executor.submit(function, *args)


@asynccontextmanager
async def lifespan(_app):
    default = json.loads((ROOT / "config/checklist_default.json").read_text(encoding="utf-8"))
    store.init_db(validate_checklist(default))
    yield


app = FastAPI(title="CQA", lifespan=lifespan)


class ImportRequest(BaseModel):
    group_id: str


class ChecklistRequest(BaseModel):
    name: str
    criteria: list[dict]


class EvaluateRequest(BaseModel):
    conversation_ids: list[str]
    checklist_id: int | None = None


class AppealRequest(BaseModel):
    evaluation_id: int
    criterion_id: str
    comment: str


class ReviewRequest(BaseModel):
    evaluation_id: int
    criterion_id: str
    decision: str
    new_answer: str | int | None = None
    reason: str = ""


class DecisionRequest(BaseModel):
    decision: str
    reason: str
    new_answer: str | int | None = None


def normalize_records(payload) -> list:
    """Accept the organizers' API response, a list of records or one record."""
    if isinstance(payload, dict) and "data" in payload:
        if payload.get("isSuccess") is False:
            raise ValueError(payload.get("error") or "Источник вернул ошибку.")
        payload = payload["data"].get("records")
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list) or not payload:
        raise ValueError("В данных нет записей.")
    for record in payload:
        if not isinstance(record, dict) or not record.get("conversation_id"):
            raise ValueError("У записи нет conversation_id.")
        turns = record.get("transcript")
        if not isinstance(turns, list) or not turns:
            raise ValueError(f"{record['conversation_id']}: пустой транскрипт.")
        if any(t.get("speaker") not in SPEAKERS or "text" not in t for t in turns):
            raise ValueError(f"{record['conversation_id']}: неверный формат реплики.")
        if record.get("channel") not in ("agent chat", "voice call"):
            raise ValueError(f"{record['conversation_id']}: неизвестный канал.")
        if record.get("language") not in ("RU", "KZ", "EN"):
            raise ValueError(f"{record['conversation_id']}: неизвестный язык.")
    return payload


def _save_records(records: list, dataset: str) -> dict:
    with store.db() as conn:
        for record in records:
            store.upsert_conversation(conn, record, dataset)
    return {"imported": len(records), "dataset": dataset}


def _dataset_url(group_id: str) -> str:
    base = os.environ.get("CQA_API_URL")
    if not base:
        raise HTTPException(500, "CQA_API_URL не задан в .env")
    parts = urlsplit(base)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["group_id"] = group_id
    return urlunsplit(parts._replace(query=urlencode(query)))


@app.post("/api/import")
def import_dataset(request: ImportRequest):
    group_id = request.group_id.strip()
    if not group_id:
        raise HTTPException(422, "Укажите group_id.")
    try:
        response = httpx.get(_dataset_url(group_id), timeout=120)
        response.raise_for_status()
        records = normalize_records(response.json())
    except httpx.HTTPError as error:  # the message would otherwise contain the signed URL
        raise HTTPException(502, f"API организаторов недоступен ({type(error).__name__}).") from None
    except ValueError as error:
        raise HTTPException(502, f"API организаторов: {error}") from None
    return _save_records(records, group_id)


@app.post("/api/conversations/upload")
def upload_conversations(payload: dict | list = Body(...)):
    try:
        return _save_records(normalize_records(payload), "UPLOAD")
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@app.get("/api/conversations")
def list_conversations():
    with store.db() as conn:
        items = []
        for row in conn.execute("SELECT * FROM conversations ORDER BY dataset, id").fetchall():
            latest = store.latest_evaluation(conn, row["id"])
            item = {"id": row["id"], "dataset": row["dataset"], "channel": row["channel"],
                    "language": row["language"], "turns": len(json.loads(row["transcript"])),
                    "evaluation": None}
            if latest:
                view = store.evaluation_view(conn, latest)
                item["evaluation"] = {
                    "id": view["id"], "status": view["status"], "error": view["error"],
                    "total": view["final_score"]["total"] if view["status"] == "done" else None,
                    "gross_error": view["final_score"]["gross_error"] if view["status"] == "done" else False,
                    "open_appeals": view.get("open_appeals", 0), "changed": view.get("changed", False),
                    "to_review": view.get("to_review", 0)}
            items.append(item)
    return items


def audio_offsets(transcript: list) -> list:
    """Seconds from the recording start, with paused intervals removed. Chats return None."""
    def parse(value):
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    stamps = [parse(turn.get("timestamp")) for turn in transcript]
    if not stamps or stamps[0] is None:
        return [None] * len(transcript)
    offsets, paused, paused_at = [], 0.0, None
    for turn, stamp in zip(transcript, stamps):
        text = turn["text"].lower()
        if stamp is None:
            offsets.append(None)
            continue
        if turn["speaker"] == "system" and "приостановлен" in text:
            paused_at = stamp
        elif turn["speaker"] == "system" and "возобновлен" in text and paused_at:
            paused += (stamp - paused_at).total_seconds()
            paused_at = None
        offsets.append(round((stamp - stamps[0]).total_seconds() - paused, 1))
    return offsets


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str):
    with store.db() as conn:
        row = conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Диалог не найден.")
        record = store.conversation_record(row)
        latest = store.latest_evaluation(conn, conversation_id)
        evaluation = store.evaluation_view(conn, latest) if latest else None
    has_audio = bool(record.pop("audio_url"))
    return {**record, "has_audio": has_audio, "evaluation": evaluation,
            "audio_offsets": audio_offsets(record["transcript"]) if has_audio else None}


@app.get("/api/audio/{conversation_id}")
def open_audio(conversation_id: str):
    with store.db() as conn:
        row = conn.execute("SELECT audio_url FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    if not row or not row["audio_url"]:
        raise HTTPException(404, "Для диалога нет записи.")
    return RedirectResponse(row["audio_url"])


@app.get("/api/audio/{conversation_id}/stream")
def stream_audio(conversation_id: str):
    """Redirect to a fresh short-lived MP3 link taken from the organizers' player page."""
    with store.db() as conn:
        row = conn.execute("SELECT audio_url FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    if not row or not row["audio_url"]:
        raise HTTPException(404, "Для диалога нет записи.")
    try:
        page = httpx.get(row["audio_url"], timeout=60)
        page.raise_for_status()
    except httpx.HTTPError as error:  # the message would otherwise contain the signed URL
        raise HTTPException(502, f"Плеер недоступен ({type(error).__name__}).") from None
    found = re.search(r'<source[^>]+src="([^"]+)"', page.text)
    if not found:
        raise HTTPException(502, "На странице плеера нет ссылки на запись.")
    return RedirectResponse(html.unescape(found.group(1)))


@app.get("/api/checklists")
def list_checklists():
    with store.db() as conn:
        rows = conn.execute("SELECT * FROM checklists ORDER BY id DESC").fetchall()
    return [store.checklist_view(row) for row in rows]


@app.post("/api/checklists")
def create_checklist(request: ChecklistRequest):
    try:
        checklist = validate_checklist(request.model_dump())
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    with store.db() as conn:
        new_id = store.save_checklist(conn, checklist)
        return store.get_checklist(conn, new_id)


def check_provider(record: dict) -> None:
    if (record["channel"] == "voice call" and os.environ.get("LLM_PROVIDER") == "openrouter"
            and os.environ.get("CQA_ALLOW_VOICE_ON_OPENROUTER") != "1"):
        raise RuntimeError("Реальные звонки не отправляются на OpenRouter без разрешения организаторов.")


def run_evaluation(evaluation_id: int) -> None:
    """Background job: always performs a fresh model evaluation."""
    with store.db() as conn:
        row = conn.execute("SELECT * FROM evaluations WHERE id=?", (evaluation_id,)).fetchone()
        conn.execute("UPDATE evaluations SET status='running' WHERE id=?", (evaluation_id,))
        record = store.conversation_record(
            conn.execute("SELECT * FROM conversations WHERE id=?", (row["conversation_id"],)).fetchone())
        checklist = store.get_checklist(conn, row["checklist_id"])
    try:
        check_provider(record)
        result = evaluate(record, checklist, votes=int(os.environ.get("CQA_VOTES", "1")))
        update = ("done", json.dumps(result, ensure_ascii=False), None)
    except Exception as error:  # the job must record every failure for the UI
        update = ("error", None, str(error)[:500])
    with store.db() as conn:
        conn.execute("UPDATE evaluations SET status=?, result=?, error=?, finished_at=? WHERE id=?",
                     (*update, store.now(), evaluation_id))


@app.post("/api/evaluations")
def start_evaluations(request: EvaluateRequest):
    if not request.conversation_ids:
        raise HTTPException(422, "Выберите диалоги.")
    created = []
    with store.db() as conn:
        checklist = store.get_checklist(conn, request.checklist_id)
        if not checklist:
            raise HTTPException(404, "Чек-лист не найден.")
        for conversation_id in request.conversation_ids:
            if not conn.execute("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)).fetchone():
                raise HTTPException(404, f"Диалог {conversation_id} не найден.")
            cursor = conn.execute(
                "INSERT INTO evaluations (conversation_id, checklist_id, status, created_at) VALUES (?,?,?,?)",
                (conversation_id, checklist["id"], "pending", store.now()))
            created.append(cursor.lastrowid)
    for evaluation_id in created:
        submit(run_evaluation, evaluation_id)
    return {"evaluation_ids": created}


def _done_evaluation(conn, evaluation_id: int):
    row = conn.execute("SELECT * FROM evaluations WHERE id=?", (evaluation_id,)).fetchone()
    if not row or row["status"] != "done":
        raise HTTPException(404, "Завершённая оценка не найдена.")
    return row


def _criterion(checklist: dict, criterion_id: str) -> dict:
    found = next((c for c in checklist["criteria"] if c["id"] == criterion_id), None)
    if not found:
        raise HTTPException(404, "Критерий не найден в этой оценке.")
    return found


@app.post("/api/appeals")
def create_appeal(request: AppealRequest):
    comment = request.comment.strip()
    if not comment:
        raise HTTPException(422, "Добавьте комментарий к апелляции.")
    with store.db() as conn:
        row = _done_evaluation(conn, request.evaluation_id)
        _criterion(store.get_checklist(conn, row["checklist_id"]), request.criterion_id)
        if conn.execute("SELECT 1 FROM appeals WHERE evaluation_id=? AND criterion_id=? AND status='open'",
                        (request.evaluation_id, request.criterion_id)).fetchone():
            raise HTTPException(409, "По этому критерию уже есть открытая апелляция.")
        cursor = conn.execute(
            "INSERT INTO appeals (evaluation_id, criterion_id, comment, status, created_at) VALUES (?,?,?,?,?)",
            (request.evaluation_id, request.criterion_id, comment, "open", store.now()))
        return store.appeal_view(conn.execute("SELECT * FROM appeals WHERE id=?", (cursor.lastrowid,)).fetchone())


@app.get("/api/appeals")
def list_appeals(status: str | None = None):
    with store.db() as conn:
        query = ("SELECT a.*, e.conversation_id FROM appeals a JOIN evaluations e ON e.id=a.evaluation_id "
                 "WHERE a.source='user'")
        rows = conn.execute(query + (" AND a.status=?" if status else "") + " ORDER BY a.id DESC",
                            (status,) if status else ()).fetchall()
        items = []
        for row in rows:
            evaluation = store.evaluation_view(
                conn, conn.execute("SELECT * FROM evaluations WHERE id=?", (row["evaluation_id"],)).fetchone())
            conversation = store.conversation_record(conn.execute(
                "SELECT * FROM conversations WHERE id=?", (row["conversation_id"],)).fetchone())
            item = evaluation["result"]["criteria"][row["criterion_id"]]
            turn = item["evidence_turn"]
            items.append({**store.appeal_view(row), "conversation_id": row["conversation_id"],
                          "criterion": _criterion(evaluation["checklist"], row["criterion_id"]),
                          "original": item, "current_total": evaluation["final_score"]["total"],
                          "fragment": _fragment(conversation["transcript"], turn)})
    return items


def _fragment(transcript: list, turn: int) -> list:
    return [{**t, "index": i} for i, t in enumerate(transcript) if turn - 2 <= i <= turn + 2]


def _new_answer(criterion: dict, value):
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if value not in allowed_answers(criterion):
        raise HTTPException(422, "Такой ответ недоступен для этого критерия.")
    return value


@app.post("/api/appeals/{appeal_id}/decision")
def decide_appeal(appeal_id: int, request: DecisionRequest):
    reason = request.reason.strip()
    if request.decision not in ("confirmed", "changed"):
        raise HTTPException(422, "Решение должно быть confirmed или changed.")
    if not reason:
        raise HTTPException(422, "Укажите причину решения.")
    with store.db() as conn:
        appeal = conn.execute("SELECT * FROM appeals WHERE id=?", (appeal_id,)).fetchone()
        if not appeal:
            raise HTTPException(404, "Апелляция не найдена.")
        if appeal["status"] != "open":
            raise HTTPException(409, "По апелляции уже принято решение.")
        row = _done_evaluation(conn, appeal["evaluation_id"])
        new_answer = None
        if request.decision == "changed":
            criterion = _criterion(store.get_checklist(conn, row["checklist_id"]), appeal["criterion_id"])
            new_answer = _new_answer(criterion, request.new_answer)
        conn.execute("UPDATE appeals SET status='decided', decision=?, new_answer=?, reason=?, decided_at=? "
                     "WHERE id=?", (request.decision, json.dumps(new_answer) if new_answer is not None else None,
                                    reason, store.now(), appeal_id))
        return store.evaluation_view(conn, row)


@app.get("/api/reviews")
def list_reviews():
    """Answers the model is unsure about, from the latest evaluation of every conversation."""
    items, answers, reviewed = [], 0, 0
    with store.db() as conn:
        rows = conn.execute("SELECT e.* FROM evaluations e WHERE e.status='done' AND e.id = "
                            "(SELECT MAX(id) FROM evaluations WHERE conversation_id=e.conversation_id) "
                            "ORDER BY e.conversation_id").fetchall()
        for row in rows:
            view = store.evaluation_view(conn, row)
            answers += len(view["result"]["criteria"])
            reviewed += sum(a["source"] == "review" for a in view["appeals"])
            transcript = None
            for cid, reasons in view["review"].items():
                if transcript is None:
                    transcript = store.conversation_record(conn.execute(
                        "SELECT * FROM conversations WHERE id=?", (row["conversation_id"],)).fetchone())["transcript"]
                item = view["result"]["criteria"][cid]
                items.append({"evaluation_id": row["id"], "conversation_id": row["conversation_id"],
                              "criterion": _criterion(view["checklist"], cid), "original": item,
                              "reasons": [REASONS[r] for r in reasons], "votes": view["result"]["votes"],
                              "fragment": _fragment(transcript, item["evidence_turn"])})
    return {"items": items, "answers": answers, "pending": len(items), "reviewed": reviewed,
            "evaluations": len(rows)}


@app.post("/api/reviews")
def decide_review(request: ReviewRequest):
    """A person confirms or corrects an answer from the review queue."""
    if request.decision not in ("confirmed", "changed"):
        raise HTTPException(422, "Решение должно быть confirmed или changed.")
    with store.db() as conn:
        row = _done_evaluation(conn, request.evaluation_id)
        view = store.evaluation_view(conn, row)
        if request.criterion_id not in view["review"]:
            raise HTTPException(409, "Этот ответ не ждёт проверки.")
        new_answer = None
        if request.decision == "changed":
            new_answer = _new_answer(_criterion(view["checklist"], request.criterion_id), request.new_answer)
        stamp = store.now()
        conn.execute(
            "INSERT INTO appeals (evaluation_id, criterion_id, comment, status, decision, new_answer, reason, "
            "created_at, decided_at, source) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (row["id"], request.criterion_id, "Ответ модели отправлен на проверку автоматически", "decided",
             request.decision, json.dumps(new_answer) if new_answer is not None else None,
             request.reason.strip() or "Проверено человеком", stamp, stamp, "review"))
        return store.evaluation_view(conn, row)


@app.post("/api/evaluations/{evaluation_id}/coach/{criterion_id}")
def coach_operator(evaluation_id: int, criterion_id: str):
    """How the operator should have answered. Generated once per criterion and kept."""
    with store.db() as conn:
        row = _done_evaluation(conn, evaluation_id)
        view = store.evaluation_view(conn, row)
        criterion = _criterion(view["checklist"], criterion_id)
        if criterion_id in view["coaching"]:
            return view["coaching"][criterion_id]
        answer = view["final_answers"][criterion_id]
        if not lost_points(criterion, answer):
            raise HTTPException(409, "По этому критерию оператор не потерял баллы.")
        record = store.conversation_record(conn.execute(
            "SELECT * FROM conversations WHERE id=?", (row["conversation_id"],)).fetchone())
    try:
        check_provider(record)
        advice = coach(record, criterion, answer, view["result"]["criteria"][criterion_id])
    except Exception as error:  # show the model failure in the UI instead of a bare 500
        raise HTTPException(502, f"Не удалось подготовить совет: {str(error)[:300]}") from None
    with store.db() as conn:
        conn.execute("INSERT OR REPLACE INTO coaching (evaluation_id, criterion_id, result, created_at) "
                     "VALUES (?,?,?,?)", (evaluation_id, criterion_id, json.dumps(advice, ensure_ascii=False),
                                          store.now()))
    return advice


@app.get("/api/health")
def health():
    return {"provider": os.environ.get("LLM_PROVIDER", "claude_cli"),
            "model": (os.environ.get("OPENROUTER_MODEL") if os.environ.get("LLM_PROVIDER") == "openrouter"
                      else os.environ.get("LLM_MODEL", "sonnet"))}


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
