from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.analytics.discovery import discover
from backend.app.analytics.executive import run_executive_summary
from backend.app.analytics.roles import detect_roles
from backend.app.analytics.root_cause import parse_question, run_root_cause
from backend.app.analytics.scenario import run_scenarios
from backend.app.analytics.story import root_cause_story
from backend.app.core.exceptions import AppError
from backend.app.core.security import get_current_user, get_db
from backend.app.models import User
from backend.app.schemas.api import ExecExportIn, ModeIn, RootCauseIn, ScenarioIn
from backend.app.services import datasets as ds_svc
from backend.app.services import reports as rep_svc

router = APIRouter()
_cache: dict[tuple, dict] = {}


def _frame(db: Session, user: User, dataset_id: int):
    ds = ds_svc.get_dataset(db, user, dataset_id)
    if ds.kind != "table":
        raise AppError("This tool needs a tabular dataset")
    return ds, ds_svc.load_df(ds)


@router.get("/roles/{dataset_id}")
def roles(dataset_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _, df = _frame(db, user, dataset_id)
    r = detect_roles(df)
    return {k: v for k, v in r.items() if k != "measures"} | {"measures": r["measures"]}


@router.post("/root-cause")
def root_cause(body: RootCauseIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ds, df = _frame(db, user, body.dataset_id)
    month = year = None
    metric, grain = body.metric, body.grain
    if body.question:  # free-text hints fill whatever the form left empty
        hint = parse_question(body.question, df, detect_roles(df))
        if hint["unsupported"] and not (metric or hint["metric"]):
            raise AppError(f"I can't explain changes in “{hint['unsupported']}” because it is not an additive measure. Choose revenue, cost, quantity or profit.")
        metric = metric or hint["metric"]
        month, year = (hint["month"], hint["year"]) if not body.current else (None, None)
        grain = hint["grain"] if body.grain == "month" and hint["grain"] != "month" else grain
    res = run_root_cause(df, ds.table_name, metric, body.date_column, grain, body.current, body.previous, body.dimensions, body.question, body.number_mode, month, year)
    ds_svc.audit(db, user, "intelligence.root_cause", f"dataset={body.dataset_id} metric={res['metric']}")
    return {**res, "story": root_cause_story(res)}


@router.get("/discover/{dataset_id}")
def discover_insights(dataset_id: int, number_mode: str = "standard", refresh: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ds, df = _frame(db, user, dataset_id)
    key = (ds.id, ds.updated_at.isoformat(), number_mode)
    if refresh or key not in _cache:
        if len(_cache) > 50:
            _cache.clear()
        _cache[key] = discover(df, ds.table_name, number_mode)
        ds_svc.audit(db, user, "intelligence.discover", f"dataset={dataset_id}")
    return _cache[key]


@router.post("/executive-summary")
def executive(body: ModeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ds, df = _frame(db, user, body.dataset_id)
    res = run_executive_summary(df, ds.table_name, ds.name, body.number_mode, (ds.quality or {}).get("score"))
    ds_svc.audit(db, user, "intelligence.executive", f"dataset={body.dataset_id}")
    return res


@router.post("/executive-summary/export", status_code=201)
def executive_export(body: ExecExportIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ds, df = _frame(db, user, body.dataset_id)
    res = run_executive_summary(df, ds.table_name, ds.name, body.number_mode, (ds.quality or {}).get("score"))
    rec = rep_svc.create_report_from_payload(db, user, rep_svc.executive_to_report(res, ds.name), body.format)
    ds_svc.audit(db, user, "report.create", f"id={rec.id} executive fmt={body.format}")
    return {"id": rec.id, "title": rec.title, "format": rec.format, "size_bytes": rec.size_bytes, "analysis_id": None, "created_at": rec.created_at.isoformat()}


@router.post("/scenario")
def scenario(body: ScenarioIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ds, df = _frame(db, user, body.dataset_id)
    res = run_scenarios(df, ds.table_name, [s.model_dump() for s in body.scenarios], body.revenue, body.cost, body.quantity, body.date_column,
                        body.baseline_scope, body.grain, body.group_by, body.number_mode)
    ds_svc.audit(db, user, "intelligence.scenario", f"dataset={body.dataset_id} n={len(body.scenarios)}")
    return res
