"""Super-admin panel API. Every route requires role == super_admin (checked against the DB per request)."""
import csv
import io
import logging
import platform
import shutil
import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, case, delete, func, or_, select, text
from sqlalchemy.orm import Session

from backend.app.analytics.llm import ai_runtime
from backend.app.config import settings
from backend.app.core.security import SUPER_ADMIN, get_db, require_super_admin
from backend.app.db.session import engine
from backend.app.models import (
    Analysis,
    ApiRequestLog,
    AuditLog,
    Dataset,
    LlmUsage,
    Plan,
    Report,
    Subscription,
    User,
)
from backend.app.services import datasets as ds_svc
from backend.app.services.datasets import audit

log = logging.getLogger("datapilot.admin")
router = APIRouter(dependencies=[Depends(require_super_admin)])
_STARTED = time.time()


# ---------------------------------------------------------------- helpers
def _utc(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=UTC)


def _iso(dt: datetime | None) -> str | None:
    return _utc(dt).isoformat() if dt else None


def _since(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def _like(q: str) -> str:
    return "%" + q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _series(db: Session, col, days: int, *extra) -> list[dict]:
    """Per-day counts (zero-filled). `extra` = additional (label, expression) aggregates."""
    day = func.date(col)
    cols = [day, func.count()] + [e for _, e in extra]
    rows = {str(r[0]): r for r in db.execute(select(*cols).where(col >= _since(days)).group_by(day))}
    out = []
    for i in range(days - 1, -1, -1):
        d = (datetime.now(UTC) - timedelta(days=i)).date().isoformat()
        r = rows.get(d)
        out.append({"date": d, "count": r[1] if r else 0,
                    **{lbl: int((r[2 + j] or 0) if r else 0) for j, (lbl, _) in enumerate(extra)}})
    return out


def _page(total: int, page: int, size: int) -> dict:
    return {"total": total, "page": page, "page_size": size, "pages": max(1, -(-total // size))}


def _csv_cell(v) -> str:
    """Neutralise spreadsheet formula injection (=, +, -, @, tab, CR) in user-controlled text."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def bootstrap_super_admins(db: Session) -> int:
    emails = [e.strip().lower() for e in settings.super_admin_emails if e.strip()]
    if not emails:
        return 0
    n = 0
    for u in db.scalars(select(User).where(func.lower(User.email).in_(emails), User.role != SUPER_ADMIN)):
        u.role = SUPER_ADMIN
        n += 1
        log.warning("promoted %s to super_admin (SUPER_ADMIN_EMAILS)", u.email)
    db.commit()
    return n


def prune_usage_logs(db: Session) -> None:
    cutoff = _since(settings.usage_log_retention_days)
    db.execute(delete(ApiRequestLog).where(ApiRequestLog.created_at < cutoff))
    db.execute(delete(LlmUsage).where(LlmUsage.created_at < cutoff))
    db.commit()


# ---------------------------------------------------------------- overview
@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    since30, since7 = _since(30), _since(7)
    api_users = select(ApiRequestLog.user_id).where(ApiRequestLog.created_at >= since30, ApiRequestLog.user_id.is_not(None))
    one = lambda stmt: db.scalar(stmt) or 0  # noqa: E731
    return {
        "total_users": one(select(func.count(User.id))),
        "active_users": one(select(func.count(User.id)).where(
            User.status == "active", or_(User.last_login_at >= since30, User.id.in_(api_users)))),
        "suspended_users": one(select(func.count(User.id)).where(User.status == "suspended")),
        "new_users_7d": one(select(func.count(User.id)).where(User.created_at >= since7)),
        "new_users_30d": one(select(func.count(User.id)).where(User.created_at >= since30)),
        "datasets": one(select(func.count(Dataset.id))),
        "storage_bytes": one(select(func.sum(Dataset.size_bytes))),
        "analyses": one(select(func.count(Analysis.id))),
        "analyses_7d": one(select(func.count(Analysis.id)).where(Analysis.created_at >= since7)),
        "failed_analyses_7d": one(select(func.count(Analysis.id)).where(Analysis.created_at >= since7, Analysis.status == "failed")),
        "signups_by_day": _series(db, User.created_at, 30),
        "analyses_by_day": _series(db, Analysis.created_at, 30),
    }


# ---------------------------------------------------------------- users
def _user_query(q: str | None, status_: str | None, role: str | None, sort: str, order: str):
    n_ds = select(func.count(Dataset.id)).where(Dataset.owner_id == User.id).correlate(User).scalar_subquery()
    n_an = select(func.count(Analysis.id)).where(Analysis.owner_id == User.id).correlate(User).scalar_subquery()
    stmt = select(User, n_ds.label("datasets"), n_an.label("analyses"))
    if q and q.strip():
        pat = _like(q)
        stmt = stmt.where(or_(func.lower(User.email).like(pat, escape="\\"), func.lower(User.name).like(pat, escape="\\")))
    if status_ in ("active", "suspended"):
        stmt = stmt.where(User.status == status_)
    if role in ("analyst", "admin", SUPER_ADMIN):
        stmt = stmt.where(User.role == role)
    col = {"email": User.email, "name": User.name, "last_login_at": User.last_login_at, "created_at": User.created_at}.get(sort, User.created_at)
    return stmt.order_by(col.asc().nulls_last() if order == "asc" else col.desc().nulls_last(), User.id.desc())


def _user_row(u: User, datasets: int = 0, analyses: int = 0) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "status": u.status,
            "created_at": _iso(u.created_at), "last_login_at": _iso(u.last_login_at),
            "datasets": datasets, "analyses": analyses}


@router.get("/users")
def list_users(q: str | None = None, status: str | None = None, role: str | None = None,
               sort: str = "created_at", order: str = "desc",
               page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    stmt = _user_query(q, status, role, sort, order)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.execute(stmt.limit(page_size).offset((page - 1) * page_size)).all()
    plans = {uid: name for uid, name in db.execute(select(Subscription.user_id, Plan.name).join(Plan, Plan.id == Subscription.plan_id)
                                                   .where(Subscription.user_id.in_([u.id for u, _, _ in rows]), Subscription.status != "canceled"))}
    return {"items": [{**_user_row(u, d, a), "plan": plans.get(u.id, "Free")} for u, d, a in rows], **_page(total, page, page_size)}


@router.get("/users/export.csv")
def export_users(q: str | None = None, status: str | None = None, role: str | None = None,
                 sort: str = "created_at", order: str = "desc",
                 db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    rows = db.execute(_user_query(q, status, role, sort, order)).all()
    audit(db, admin, "admin.users.export", f"rows={len(rows)} q={q or ''} status={status or ''} role={role or ''}")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "email", "name", "role", "status", "registered_at", "last_login_at", "datasets", "analyses"])
    for u, d, a in rows:
        w.writerow([u.id, _csv_cell(u.email), _csv_cell(u.name), u.role, u.status, _iso(u.created_at), _iso(u.last_login_at) or "", d, a])
    name = f"users-{datetime.now(UTC):%Y%m%d-%H%M}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _get_user(db: Session, uid: int) -> User:
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "User not found")
    return u


@router.get("/users/{uid}")
def user_detail(uid: int, db: Session = Depends(get_db)):
    u = _get_user(db, uid)
    one = lambda stmt: db.scalar(stmt) or 0  # noqa: E731
    tokens = db.execute(select(func.count(), func.coalesce(func.sum(LlmUsage.input_tokens), 0),
                               func.coalesce(func.sum(LlmUsage.output_tokens), 0)).where(LlmUsage.user_id == uid)).one()
    ds = db.scalars(select(Dataset).where(Dataset.owner_id == uid).order_by(Dataset.id.desc()).limit(10)).all()
    acts = db.scalars(select(AuditLog).where(AuditLog.user_id == uid).order_by(AuditLog.id.desc()).limit(15)).all()
    return {
        **_user_row(u, one(select(func.count(Dataset.id)).where(Dataset.owner_id == uid)),
                    one(select(func.count(Analysis.id)).where(Analysis.owner_id == uid))),
        "reports": one(select(func.count(Report.id)).where(Report.owner_id == uid)),
        "storage_bytes": one(select(func.sum(Dataset.size_bytes)).where(Dataset.owner_id == uid)),
        "api_requests_30d": one(select(func.count(ApiRequestLog.id)).where(ApiRequestLog.user_id == uid, ApiRequestLog.created_at >= _since(30))),
        "llm_calls": tokens[0], "input_tokens": int(tokens[1]), "output_tokens": int(tokens[2]),
        "recent_datasets": [{"id": d.id, "name": d.name, "source_type": d.source_type, "row_count": d.row_count,
                             "size_bytes": d.size_bytes, "created_at": _iso(d.created_at)} for d in ds],
        "recent_activity": [{"id": a.id, "action": a.action, "detail": a.detail, "created_at": _iso(a.created_at)} for a in acts],
    }


def _guard_target(admin: User, target: User, verb: str) -> None:
    if target.id == admin.id:
        raise HTTPException(400, f"You cannot {verb} your own account")
    if target.role == SUPER_ADMIN:
        raise HTTPException(403, f"Super admin accounts cannot be {verb}d here")


@router.post("/users/{uid}/suspend")
def suspend_user(uid: int, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    u = _get_user(db, uid)
    _guard_target(admin, u, "suspend")
    u.status = "suspended"
    db.commit()
    audit(db, admin, "admin.user.suspend", f"user_id={u.id} email={u.email}")
    from backend.app.api.v1.auth import _notify

    _notify("suspended", u)
    return _user_row(u)


@router.post("/users/{uid}/reactivate")
def reactivate_user(uid: int, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    u = _get_user(db, uid)
    u.status = "active"
    db.commit()
    audit(db, admin, "admin.user.reactivate", f"user_id={u.id} email={u.email}")
    return _user_row(u)


class DeleteUserIn(BaseModel):
    confirm_email: str


@router.post("/users/{uid}/delete")
def delete_user(uid: int, body: DeleteUserIn, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    """POST (not DELETE) so the typed-email confirmation travels in a body. Irreversible."""
    u = _get_user(db, uid)
    _guard_target(admin, u, "delete")
    if body.confirm_email.strip().lower() != u.email.lower():
        raise HTTPException(400, "Confirmation email does not match")
    for d in db.scalars(select(Dataset).where(Dataset.owner_id == uid)):
        if (f := ds_svc.resolve_path(d.data_path)):
            f.unlink(missing_ok=True)
    from pathlib import Path
    for r in db.scalars(select(Report).where(Report.owner_id == uid)):
        Path(r.file_path).unlink(missing_ok=True)
    email = u.email
    db.delete(u)  # datasets/analyses/conversations/reports/saved queries cascade at the DB level
    db.commit()
    audit(db, admin, "admin.user.delete", f"user_id={uid} email={email}")
    return {"deleted": uid}


# ---------------------------------------------------------------- datasets
@router.get("/datasets")
def list_datasets(q: str | None = None, kind: str | None = None, owner_id: int | None = None,
                  page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    stmt = select(Dataset, User.email).join(User, User.id == Dataset.owner_id)
    if q and q.strip():
        pat = _like(q)
        stmt = stmt.where(or_(func.lower(Dataset.name).like(pat, escape="\\"), func.lower(User.email).like(pat, escape="\\")))
    if kind in ("table", "document"):
        stmt = stmt.where(Dataset.kind == kind)
    if owner_id:
        stmt = stmt.where(Dataset.owner_id == owner_id)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.execute(stmt.order_by(Dataset.id.desc()).limit(page_size).offset((page - 1) * page_size)).all()
    by_type = db.execute(select(Dataset.source_type, func.count()).group_by(Dataset.source_type).order_by(func.count().desc())).all()
    return {
        "items": [{"id": d.id, "name": d.name, "kind": d.kind, "source_type": d.source_type, "owner_id": d.owner_id,
                   "owner_email": email, "status": d.status, "row_count": d.row_count, "column_count": d.column_count,
                   "size_bytes": d.size_bytes, "quality_score": (d.quality or {}).get("score"),
                   "created_at": _iso(d.created_at)} for d, email in rows],
        "totals": {"datasets": db.scalar(select(func.count(Dataset.id))) or 0,
                   "size_bytes": db.scalar(select(func.sum(Dataset.size_bytes))) or 0,
                   "rows": db.scalar(select(func.sum(Dataset.row_count))) or 0},
        "by_source_type": [{"source_type": s, "count": c} for s, c in by_type],
        **_page(total, page, page_size),
    }


@router.delete("/datasets/{did}", status_code=204)
def delete_dataset(did: int, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    d = db.get(Dataset, did)
    if not d:
        raise HTTPException(404, "Dataset not found")
    info = f"id={d.id} name={d.name} owner_id={d.owner_id}"
    if (f := ds_svc.resolve_path(d.data_path)):
        f.unlink(missing_ok=True)
    db.delete(d)
    db.commit()
    audit(db, admin, "admin.dataset.delete", info)


# ---------------------------------------------------------------- activity log
@router.get("/activity")
def activity(q: str | None = None, user_id: int | None = None, days: int = Query(30, ge=1, le=365),
             page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    stmt = select(AuditLog, User.email).join(User, User.id == AuditLog.user_id, isouter=True).where(AuditLog.created_at >= _since(days))
    if q and q.strip():
        pat = _like(q)
        stmt = stmt.where(or_(func.lower(AuditLog.action).like(pat, escape="\\"), func.lower(AuditLog.detail).like(pat, escape="\\"),
                              func.lower(User.email).like(pat, escape="\\")))
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.execute(stmt.order_by(AuditLog.id.desc()).limit(page_size).offset((page - 1) * page_size)).all()
    return {"items": [{"id": a.id, "user_id": a.user_id, "user_email": email, "action": a.action, "detail": a.detail,
                       "created_at": _iso(a.created_at)} for a, email in rows], **_page(total, page, page_size)}


# ---------------------------------------------------------------- AI token usage
@router.get("/usage/tokens")
def token_usage(days: int = Query(30, ge=1, le=90), db: Session = Depends(get_db)):
    w = LlmUsage.created_at >= _since(days)
    tin, tout = func.coalesce(func.sum(LlmUsage.input_tokens), 0), func.coalesce(func.sum(LlmUsage.output_tokens), 0)
    tot = db.execute(select(func.count(), tin, tout, func.coalesce(func.sum(case((LlmUsage.ok.is_(False), 1), else_=0)), 0)).where(w)).one()
    by_model = db.execute(select(LlmUsage.provider, LlmUsage.model, func.count(), tin, tout).where(w)
                          .group_by(LlmUsage.provider, LlmUsage.model).order_by((tin + tout).desc())).all()
    top = db.execute(select(User.id, User.email, func.count(), tin, tout).select_from(LlmUsage).join(User, User.id == LlmUsage.user_id)
                     .where(w).group_by(User.id, User.email).order_by((tin + tout).desc()).limit(10)).all()
    return {
        "days": days, "llm_enabled": ai_runtime()["enabled"], "provider": ai_runtime()["provider"],
        "totals": {"calls": tot[0], "input_tokens": int(tot[1]), "output_tokens": int(tot[2]), "failed_calls": int(tot[3])},
        "by_day": _series(db, LlmUsage.created_at, days, ("input_tokens", func.sum(LlmUsage.input_tokens)),
                          ("output_tokens", func.sum(LlmUsage.output_tokens))),
        "by_model": [{"provider": p, "model": m, "calls": c, "input_tokens": int(i), "output_tokens": int(o)} for p, m, c, i, o in by_model],
        "top_users": [{"user_id": i, "email": e, "calls": c, "input_tokens": int(a), "output_tokens": int(b)} for i, e, c, a, b in top],
    }


# ---------------------------------------------------------------- API usage
@router.get("/usage/api")
def api_usage(days: int = Query(14, ge=1, le=60), db: Session = Depends(get_db)):
    R = ApiRequestLog
    w = R.created_at >= _since(days)
    err5 = func.sum(case((R.status_code >= 500, 1), else_=0))
    err4 = func.sum(case((and_(R.status_code >= 400, R.status_code < 500), 1), else_=0))
    tot = db.execute(select(func.count(), func.coalesce(err4, 0), func.coalesce(err5, 0), func.coalesce(func.avg(R.duration_ms), 0)).where(w)).one()
    routes = db.execute(select(R.method, R.route, func.count(), func.avg(R.duration_ms), func.max(R.duration_ms), func.coalesce(err5, 0))
                        .where(w).group_by(R.method, R.route).order_by(func.count().desc()).limit(15)).all()
    top = db.execute(select(User.id, User.email, func.count()).select_from(R).join(User, User.id == R.user_id).where(w)
                     .group_by(User.id, User.email).order_by(func.count().desc()).limit(10)).all()
    return {
        "days": days,
        "totals": {"requests": tot[0], "client_errors": int(tot[1]), "server_errors": int(tot[2]), "avg_ms": round(float(tot[3]), 1)},
        "by_day": _series(db, R.created_at, days, ("errors", err5)),
        "top_routes": [{"method": m, "route": r, "requests": c, "avg_ms": round(float(a or 0), 1), "max_ms": round(float(x or 0), 1), "server_errors": int(e)}
                       for m, r, c, a, x, e in routes],
        "top_users": [{"user_id": i, "email": e, "requests": c} for i, e, c in top],
    }


# ---------------------------------------------------------------- system health
def _dir_free(path) -> dict | None:
    try:
        u = shutil.disk_usage(path)
        return {"total": u.total, "used": u.used, "free": u.free, "used_pct": round(u.used / u.total * 100, 1)}
    except OSError:
        return None


@router.get("/system")
def system_health(db: Session = Depends(get_db)):
    checks = []

    t0 = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        db_ms, db_ok = round((time.perf_counter() - t0) * 1000, 1), True
    except Exception as e:  # noqa: BLE001
        db_ms, db_ok = None, False
        log.warning("health: db check failed: %s", e)
    checks.append({"name": "Database", "status": "ok" if db_ok else "down",
                   "detail": f"{engine.dialect.name}, {db_ms} ms" if db_ok else "unreachable"})

    disk = _dir_free(settings.upload_directory) or _dir_free(settings.upload_directory.parent)
    if disk:
        checks.append({"name": "Disk", "status": "ok" if disk["used_pct"] < 85 else "warn" if disk["used_pct"] < 95 else "down",
                       "detail": f"{disk['used_pct']}% used"})

    hour = _since(0) - timedelta(hours=1)
    h = db.execute(select(func.count(), func.coalesce(func.sum(case((ApiRequestLog.status_code >= 500, 1), else_=0)), 0),
                          func.coalesce(func.avg(ApiRequestLog.duration_ms), 0)).where(ApiRequestLog.created_at >= hour)).one()
    err_rate = (h[1] / h[0] * 100) if h[0] else 0.0
    checks.append({"name": "API (last hour)", "status": "ok" if err_rate < 2 else "warn" if err_rate < 10 else "down",
                   "detail": f"{h[0]} requests, {err_rate:.1f}% 5xx, avg {float(h[2]):.0f} ms"})

    stuck_cut = datetime.now(UTC) - timedelta(minutes=30)
    stuck = db.scalar(select(func.count(Analysis.id)).where(Analysis.status.in_(("queued", "running")), Analysis.created_at < stuck_cut)) or 0
    running = db.scalar(select(func.count(Analysis.id)).where(Analysis.status.in_(("queued", "running")))) or 0
    failed_24h = db.scalar(select(func.count(Analysis.id)).where(Analysis.status == "failed", Analysis.created_at >= _since(1))) or 0
    checks.append({"name": "Analysis workers", "status": "warn" if stuck else "ok",
                   "detail": f"{running} in flight, {stuck} stuck >30 min, {failed_24h} failed in 24h"})

    llm_24h = db.execute(select(func.count(), func.coalesce(func.sum(case((LlmUsage.ok.is_(False), 1), else_=0)), 0))
                         .where(LlmUsage.created_at >= _since(1))).one()
    if not ai_runtime()["enabled"]:
        checks.append({"name": "LLM provider", "status": "off", "detail": "not configured (deterministic mode)"})
    else:
        bad = llm_24h[1] / llm_24h[0] * 100 if llm_24h[0] else 0
        checks.append({"name": "LLM provider", "status": "ok" if bad < 20 else "warn",
                       "detail": f"{ai_runtime()['provider']}, {llm_24h[0]} calls/24h, {bad:.0f}% failed"})

    rank = {"down": 3, "warn": 2, "ok": 0, "off": 0}
    worst = max((rank[c["status"]] for c in checks), default=0)
    return {
        "status": {3: "down", 2: "degraded", 0: "ok"}[worst],
        "checks": checks,
        "uptime_seconds": int(time.time() - _STARTED),
        "environment": settings.app_env, "python": platform.python_version(), "database": engine.dialect.name,
        "disk": disk, "db_latency_ms": db_ms, "checked_at": datetime.now(UTC).isoformat(),
    }
