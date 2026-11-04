from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.security import get_current_user, get_db
from backend.app.models import Analysis, Dataset, Report, User
from backend.app.services import analysis as an_svc
from backend.app.services import datasets as ds_svc

router = APIRouter()


@router.get("/overview")
def overview(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ds = db.scalars(select(Dataset).where(Dataset.owner_id == user.id).order_by(Dataset.created_at.desc())).all()
    tables = [d for d in ds if d.kind == "table"]
    scores = [d.quality["score"] for d in tables if d.quality and "score" in d.quality]
    analyses = db.scalars(select(Analysis).where(Analysis.owner_id == user.id).order_by(Analysis.id.desc())).all()
    n_reports = db.scalar(select(func.count(Report.id)).where(Report.owner_id == user.id))
    done = [a for a in analyses if a.status == "completed"]
    issues = sorted(((d.name, i) for d in tables for i in (d.quality or {}).get("issues", [])),
                    key=lambda t: {"high": 0, "medium": 1, "low": 2}[t[1]["severity"]])[:6]
    return {
        "kpis": {"datasets": len(ds), "total_rows": sum(d.row_count for d in tables), "analyses": len(analyses),
                 "completed_analyses": len(done), "reports": n_reports or 0,
                 "avg_quality": round(sum(scores) / len(scores), 1) if scores else None},
        "recent_datasets": [ds_svc.serialize(d) for d in ds[:5]],
        "recent_analyses": [an_svc.serialize(a, full=False) for a in analyses[:6]],
        "top_issues": [{"dataset": n, **i} for n, i in issues],
        "quality_by_dataset": [{"name": d.name, "score": d.quality.get("score")} for d in tables if d.quality],
    }
