from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.analytics.charts import chart_from_result
from backend.app.analytics.nl2sql import generate_sql
from backend.app.analytics.sql_engine import run_query
from backend.app.config import settings
from backend.app.core.exceptions import AppError, NotFound
from backend.app.core.security import get_current_user, get_db
from backend.app.models import Dataset, SavedQuery, User
from backend.app.schemas.api import SavedQueryIn, SqlGenerateIn, SqlQueryIn
from backend.app.services import datasets as svc

router = APIRouter()


def _tables(db: Session, user: User, ids: list[int] | None):
    q = select(Dataset).where(Dataset.owner_id == user.id, Dataset.kind == "table")
    if ids:
        q = q.where(Dataset.id.in_(ids))
    return {d.table_name: d for d in db.scalars(q).all()}


@router.get("/schema")
def schema(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [{"dataset_id": d.id, "table": t, "name": d.name, "rows": d.row_count,
             "columns": [{"name": c["name"], "type": c["type"], "dtype": c["dtype"]}
                         for c in (d.profile or {}).get("column_profiles", [])]}
            for t, d in _tables(db, user, None).items()]


@router.post("/query")
def query(body: SqlQueryIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ds = _tables(db, user, body.dataset_ids)
    if not ds:
        raise AppError("No tabular datasets available to query. Upload a dataset first.", 404)
    frames = {t: svc.load_df(d) for t, d in ds.items()}
    res = run_query(frames, body.sql, min(body.max_rows, settings.max_query_rows), settings.query_timeout_seconds)
    df = res.pop("dataframe")
    svc.audit(db, user, "sql.query", body.sql[:500])
    return {**res, "chart": chart_from_result(df, "Query result")}


@router.post("/generate")
def generate(body: SqlGenerateIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ds = svc.get_dataset(db, user, body.dataset_id)
    if ds.kind != "table":
        raise AppError("Dataset is not tabular")
    return generate_sql(body.question, ds.table_name, svc.load_df(ds))


@router.get("/saved")
def saved(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(SavedQuery).where(SavedQuery.owner_id == user.id).order_by(SavedQuery.id.desc())).all()
    return [{"id": r.id, "name": r.name, "sql": r.sql, "created_at": r.created_at.isoformat()} for r in rows]


@router.post("/saved", status_code=201)
def save(body: SavedQueryIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from backend.app.analytics.sql_engine import validate_read_query

    validate_read_query(body.sql)
    r = SavedQuery(owner_id=user.id, name=body.name, sql=body.sql)
    db.add(r)
    db.commit()
    return {"id": r.id, "name": r.name, "sql": r.sql, "created_at": r.created_at.isoformat()}


@router.delete("/saved/{qid}", status_code=204)
def delete_saved(qid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    r = db.get(SavedQuery, qid)
    if not r or r.owner_id != user.id:
        raise NotFound("Saved query not found")
    db.delete(r)
    db.commit()
