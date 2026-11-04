
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.exceptions import NotFound
from backend.app.core.security import get_current_user, get_db
from backend.app.models import Analysis, Report, User
from backend.app.schemas.api import ReportIn
from backend.app.services import datasets as ds_svc
from backend.app.services import reports as svc

router = APIRouter()
MEDIA = {"pdf": "application/pdf", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


def _out(r: Report) -> dict:
    return {"id": r.id, "title": r.title, "format": r.format, "size_bytes": r.size_bytes, "analysis_id": r.analysis_id,
            "created_at": r.created_at.isoformat()}


def _own(db: Session, user: User, rid: int) -> Report:
    r = db.get(Report, rid)
    if not r or r.owner_id != user.id:
        raise NotFound("Report not found")
    return r


@router.post("", status_code=201)
def create(body: ReportIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    a = db.get(Analysis, body.analysis_id)
    if not a or a.owner_id != user.id:
        raise NotFound("Analysis not found")
    r = svc.create_report(db, user, a, body.format, body.title)
    ds_svc.audit(db, user, "report.create", f"id={r.id} fmt={r.format}")
    return _out(r)


@router.get("")
def list_reports(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [_out(r) for r in db.scalars(select(Report).where(Report.owner_id == user.id).order_by(Report.id.desc()))]


@router.get("/{rid}/download")
def download(rid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    r = _own(db, user, rid)
    f = ds_svc.resolve_path(r.file_path)
    if f is None:
        raise NotFound("Report file is missing")
    return FileResponse(f, media_type=MEDIA[r.format], filename=f"{r.title[:60].strip() or 'report'}.{r.format}")


@router.delete("/{rid}", status_code=204)
def delete(rid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    r = _own(db, user, rid)
    f = ds_svc.resolve_path(r.file_path)
    if f:
        f.unlink(missing_ok=True)
    db.delete(r)
    db.commit()
