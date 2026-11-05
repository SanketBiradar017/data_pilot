from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.analytics.suggestions import build_suggestions
from backend.app.core.exceptions import NotFound
from backend.app.core.security import get_current_user, get_db
from backend.app.models import Analysis, User
from backend.app.schemas.api import AnalysisIn
from backend.app.services import analysis as svc
from backend.app.services import entitlements as ent

router = APIRouter()


def _own(db: Session, user: User, aid: int) -> Analysis:
    a = db.get(Analysis, aid)
    if not a or a.owner_id != user.id:
        raise NotFound("Analysis not found")
    return a


_sug_cache: dict[tuple, list] = {}


@router.get("/suggestions")
def suggestions(dataset_ids: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Questions tailored to the selected data sources (real columns, values and latest period)."""
    from backend.app.services import datasets as ds_svc

    try:
        ids = [int(x) for x in dataset_ids.split(",") if x.strip()][:6]
    except ValueError:
        return []
    items = [ds_svc.get_dataset(db, user, i) for i in ids]
    key = (user.id, tuple((d.id, d.updated_at.isoformat()) for d in items))
    if key not in _sug_cache:
        if len(_sug_cache) > 100:
            _sug_cache.clear()
        tables = [(d.name, ds_svc.load_df(d), (d.quality or {}).get("score")) for d in items if d.kind == "table"]
        docs = [(d.name, ds_svc.load_text(d)) for d in items if d.kind == "document"]
        _sug_cache[key] = build_suggestions(tables, docs)
    return _sug_cache[key]


@router.post("", status_code=202)
def start(body: AnalysisIn, bg: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ent.check_feature(db, user, "ai_agents")
    ent.check_limit(db, user, "ai_analyses_per_month")
    a = svc.create_analysis(db, user, body.question, body.dataset_ids)
    bg.add_task(svc.execute_analysis, a.id)
    return svc.serialize(a, full=False)


@router.get("")
def history(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(Analysis).where(Analysis.owner_id == user.id).order_by(Analysis.id.desc()).limit(200)).all()
    return [svc.serialize(a, full=False) for a in rows]


@router.get("/{aid}")
def get_one(aid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    out = svc.serialize(_own(db, user, aid))
    return out if ent.feature_state(db, user)["data_visualization"] else ent.strip_charts(out)


@router.delete("/{aid}", status_code=204)
def delete(aid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.delete(_own(db, user, aid))
    db.commit()
