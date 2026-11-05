import logging
from datetime import UTC

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.agents.graph import run_workflow
from backend.app.analytics.question import resolve_followup
from backend.app.analytics.utils import jsonable
from backend.app.core.exceptions import NotFound
from backend.app.core.security import get_current_user, get_db
from backend.app.models import Conversation, Message, User
from backend.app.schemas.api import ConversationIn, MessageIn
from backend.app.services import analysis as an_svc
from backend.app.services import datasets as ds_svc
from backend.app.services import entitlements as ent

router = APIRouter()
log = logging.getLogger(__name__)


def _previous_question(c: Conversation, ids: list[int]) -> str | None:
    """The self-contained wording of the last answered question, if it was about the same datasets."""
    for m in reversed(c.messages):
        p = m.payload or {}
        if m.role == "assistant" and p.get("resolved_question"):
            return p["resolved_question"] if p.get("dataset_ids") == ids and not p.get("clarification") else None
    return None


def _own(db: Session, user: User, cid: int) -> Conversation:
    c = db.get(Conversation, cid)
    if not c or c.owner_id != user.id:
        raise NotFound("Conversation not found")
    return c


def _msg(m: Message) -> dict:
    return {"id": m.id, "role": m.role, "content": m.content, "payload": m.payload or {}, "created_at": m.created_at.isoformat()}


def _conv(c: Conversation) -> dict:
    return {"id": c.id, "title": c.title, "dataset_id": c.dataset_id, "created_at": c.created_at.isoformat()}


@router.get("/conversations")
def list_conversations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(Conversation).where(Conversation.owner_id == user.id).order_by(Conversation.id.desc())).all()
    return [_conv(c) for c in rows]


@router.post("/conversations", status_code=201)
def create_conversation(body: ConversationIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ids = body.dataset_ids
    for i in ids:
        ds_svc.get_dataset(db, user, i)
    c = Conversation(owner_id=user.id, dataset_id=ids[0] if ids else None, title=body.title)
    db.add(c)
    db.commit()
    return _conv(c)


@router.get("/conversations/{cid}")
def get_conversation(cid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = _own(db, user, cid)
    return {**_conv(c), "messages": [_msg(m) for m in c.messages]}


@router.delete("/conversations/{cid}", status_code=204)
def delete_conversation(cid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.delete(_own(db, user, cid))
    db.commit()


@router.post("/conversations/{cid}/messages")
def send(cid: int, body: MessageIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = _own(db, user, cid)
    ent.check_limit(db, user, "chat_messages_per_month")
    ids = body.dataset_ids or ([c.dataset_id] if c.dataset_id else [])
    user_msg = Message(conversation_id=c.id, role="user", content=body.content, payload={})
    db.add(user_msg)
    if c.title == "New conversation":
        c.title = body.content[:60]
    if body.dataset_ids:
        c.dataset_id = body.dataset_ids[0]
    db.flush()

    if not ids:
        reply = Message(conversation_id=c.id, role="assistant", content="Select a dataset first so I can answer from real data.", payload={})
    else:
        analysis = an_svc.create_analysis(db, user, body.content, ids)
        ctx, _ = an_svc.build_context(db, user, body.content, ids)
        follow = {"question": body.content, "followup": False, "note": None}
        prev = _previous_question(c, ids)
        if prev and ctx.primary:
            try:  # follow-ups ("what about South?") are rewritten into a complete question using the previous one
                follow = resolve_followup(body.content, ctx.tables[ctx.primary], prev)
            except Exception:
                log.exception("follow-up resolution failed; using the question as typed")
        ctx.question = follow["question"]
        state = run_workflow(ctx)
        analysis.trace = jsonable(state["trace"])
        analysis.result = jsonable({"dataset_ids": ids, "plan": state.get("plan"), "answer": state.get("answer"),
                                    "report": state.get("report"), "validation": state.get("validation")})
        analysis.status = state["status"]
        analysis.error = "; ".join(state.get("errors", []))
        from datetime import datetime

        analysis.finished_at = datetime.now(UTC)
        rep = state.get("report") or {}
        reply = Message(conversation_id=c.id, role="assistant", content=state.get("answer") or "No answer produced.",
                        payload=jsonable({"analysis_id": analysis.id, "sql": rep.get("sql"), "charts": rep.get("charts", [])[:2] if ent.feature_state(db, user)["data_visualization"] else [],
                                          "evidence": rep.get("evidence", []), "citations": rep.get("citations", []),
                                          "trace": state["trace"], "validation": state.get("validation"),
                                          "result_columns": rep.get("result_columns"), "result_rows": (rep.get("result_rows") or [])[:20],
                                          "resolved_question": follow["question"], "followup_note": follow["note"], "dataset_ids": ids,
                                          "interpretation": rep.get("interpretation"), "notes": rep.get("notes") or [],
                                          "clarification": rep.get("clarification"), "recommendations": (rep.get("recommendations") or [])[:5],
                                          "intents": (state.get("plan") or {}).get("steps", [])}))
    db.add(reply)
    db.commit()
    return {"user": _msg(user_msg), "assistant": _msg(reply)}
