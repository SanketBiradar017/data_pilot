"""Super-admin API key management. Responses never contain key material: only masked values (last 4 characters)."""
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.analytics.llm import ai_runtime
from backend.app.config import settings
from backend.app.core import secrets
from backend.app.core.exceptions import AppError
from backend.app.core.security import get_db, require_super_admin
from backend.app.models import ApiKey, ApiKeyEvent, User
from backend.app.services import ai_config

router = APIRouter(dependencies=[Depends(require_super_admin)])

# Plain `str` fields without validators on purpose: a failed pydantic constraint would echo the submitted secret in the 422 body.
class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, repr=False)


class KeyCreateIn(_In):
    provider: str = "google"
    label: str = ""
    api_key: str
    activate: bool = False


class KeyUpdateIn(_In):
    label: str | None = None
    api_key: str | None = None


class ModelIn(_In):
    provider: str = "google"
    model: str
    verify: bool = True


_hits: dict[int, deque] = defaultdict(deque)


def _throttle(admin: User, limit: int = 20, window: float = 60.0) -> None:
    """Live provider checks are rate-limited per admin so the endpoint cannot be used to hammer the provider."""
    q, now = _hits[admin.id], time.monotonic()
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        raise AppError("Too many connection tests. Wait a minute and try again.", 429)
    q.append(now)


def _env_info(provider: str) -> dict:
    env = ai_config._env_key(provider)
    return {"configured": bool(env), "masked": secrets.mask(env[-4:]) if env else ""}


@router.get("")
def overview(db: Session = Depends(get_db)):
    usage = ai_config.usage_by_key(db)
    keys = [ai_config.serialize(k, usage.get(k.id)) for k in db.scalars(select(ApiKey).order_by(ApiKey.provider, ApiKey.created_at.desc()))]
    rt = ai_runtime()
    src = ai_config.resolve(rt["provider"]) if rt["provider"] in ai_config.PROVIDERS else ai_config._NONE
    try:
        secrets._fernet()
        enc_ok, enc_msg = True, ("derived from SECRET_KEY (development only)" if not settings.api_key_encryption_key else "configured")
    except AppError as e:
        enc_ok, enc_msg = False, e.message
    return {
        "keys": keys,
        "env": {p: _env_info(p) for p in ai_config.PROVIDERS},
        "effective": {"provider": rt["provider"], "model": rt["model"], "enabled": rt["enabled"], "key_source": src.source,
                      "key_id": src.key_id, "masked": secrets.mask(src.key[-4:]) if src.key else ""},
        "env_usage": usage.get(None),
        "model_suggestions": {"google": ai_config.GEMINI_MODELS, "anthropic": ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"]},
        "encryption": {"ok": enc_ok, "detail": enc_msg},
        "sync_note": f"Changes are stored in the database; every backend instance picks them up within {int(ai_config._TTL)} seconds, with no restart.",
    }


@router.post("", status_code=201)
def create(body: KeyCreateIn, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    row = ai_config.create(db, admin, body.provider, body.label, body.api_key, body.activate)
    db.refresh(row)
    return ai_config.serialize(row)


@router.put("/model")
def change_model(body: ModelIn, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    _throttle(admin)
    return ai_config.set_model(db, admin, body.provider, body.model, body.verify)


@router.get("/history")
def history(key_id: int | None = None, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    q = select(ApiKeyEvent).order_by(ApiKeyEvent.id.desc()).limit(limit)
    if key_id is not None:
        q = q.where(ApiKeyEvent.api_key_id == key_id)
    return [{"id": e.id, "api_key_id": e.api_key_id, "provider": e.provider, "action": e.action, "actor": e.actor_email, "detail": e.detail,
             "created_at": e.created_at.isoformat()} for e in db.scalars(q)]


@router.put("/{key_id}")
def update(key_id: int, body: KeyUpdateIn, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    if body.api_key:
        _throttle(admin)
    return ai_config.serialize(ai_config.update(db, admin, key_id, body.label, body.api_key))


@router.post("/{key_id}/test")
def test(key_id: int, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    _throttle(admin)
    row = ai_config.test_stored(db, admin, key_id)
    return {"ok": row.status == "valid", "message": row.status_message, "key": ai_config.serialize(row)}


@router.post("/{key_id}/activate")
def activate(key_id: int, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    _throttle(admin)
    return ai_config.serialize(ai_config.activate_key(db, admin, key_id))


@router.post("/{key_id}/deactivate")
def deactivate(key_id: int, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    row, msg = ai_config.deactivate_key(db, admin, key_id)
    return {"key": ai_config.serialize(row), "message": msg}


@router.delete("/{key_id}", status_code=204)
def delete(key_id: int, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    ai_config.delete_key(db, admin, key_id)
