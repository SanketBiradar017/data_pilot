"""Runs the agent graph for a user question and persists live progress."""
import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.app.agents.graph import run_workflow
from backend.app.agents.state import RunContext
from backend.app.analytics.utils import jsonable
from backend.app.db.session import SessionLocal
from backend.app.models import Analysis, Dataset, User
from backend.app.services import datasets as ds_svc

log = logging.getLogger(__name__)


def build_context(db: Session, user: User, question: str, dataset_ids: list[int]) -> tuple[RunContext, list[Dataset]]:
    ctx = RunContext(question=question)
    items = [ds_svc.get_dataset(db, user, i) for i in dataset_ids]
    for ds in items:
        if ds.kind == "table":
            ctx.tables[ds.table_name] = ds_svc.load_df(ds)
            ctx.table_labels[ds.table_name] = ds.name
        else:
            ctx.documents[ds.name] = ds_svc.load_text(ds)
    return ctx, items


def create_analysis(db: Session, user: User, question: str, dataset_ids: list[int]) -> Analysis:
    if dataset_ids:
        for i in dataset_ids:
            ds_svc.get_dataset(db, user, i)  # ownership check
    a = Analysis(owner_id=user.id, dataset_id=dataset_ids[0] if dataset_ids else None, question=question,
                 status="queued", result={"dataset_ids": dataset_ids})
    db.add(a)
    db.commit()
    return a


def execute_analysis(analysis_id: int) -> None:
    """Background-safe: opens its own DB session."""
    db = SessionLocal()
    try:
        a = db.get(Analysis, analysis_id)
        user = db.get(User, a.owner_id)
        dataset_ids = (a.result or {}).get("dataset_ids", [])
        a.status = "running"
        db.commit()
        try:
            ctx, _ = build_context(db, user, a.question, dataset_ids)
        except Exception as e:
            a.status, a.error, a.finished_at = "failed", str(e), datetime.now(UTC)
            db.commit()
            return

        def on_event(event: dict, state: dict) -> None:
            a.trace = jsonable(state.get("trace", []))
            plan = state.get("plan")
            a.result = {**(a.result or {}), **({"plan": jsonable(plan)} if plan else {})}
            db.commit()

        try:
            state = run_workflow(ctx, on_event)
            a.trace = jsonable(state.get("trace", []))
            a.result = jsonable({"dataset_ids": dataset_ids, "plan": state.get("plan"), "answer": state.get("answer"),
                                 "report": state.get("report"), "sql": {k: v for k, v in (state.get("sql") or {}).items()
                                                                       if k != "rows"},
                                 "validation": state.get("validation")})
            a.status = state["status"]
            a.error = "; ".join(state.get("errors", [])) if a.status == "failed" else ""
        except Exception as e:
            log.exception("analysis %s crashed", analysis_id)
            a.status, a.error = "failed", f"{type(e).__name__}: {e}"
        a.finished_at = datetime.now(UTC)
        db.commit()
        ds_svc.audit(db, user, "analysis.run", f"id={a.id} status={a.status}")
    finally:
        db.close()


def serialize(a: Analysis, full: bool = True) -> dict:
    d = {"id": a.id, "question": a.question, "status": a.status, "dataset_id": a.dataset_id,
         "created_at": a.created_at.isoformat(), "finished_at": a.finished_at.isoformat() if a.finished_at else None,
         "error": a.error, "trace": a.trace or [], "plan": (a.result or {}).get("plan"),
         "answer": (a.result or {}).get("answer")}
    if full:
        d["result"] = a.result
    return d
