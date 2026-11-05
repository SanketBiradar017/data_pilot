"""Central AI configuration: which API key and model every LLM request uses.

Resolution order for a provider: active admin-managed key (encrypted in the DB) -> environment variable (initial fallback).
Nothing is cached for long: each instance re-reads the DB at most every _TTL seconds, so a key change made on one
instance reaches all the others within that window, and the instance that handled the change applies it immediately."""
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.core import secrets
from backend.app.core.exceptions import AppError, NotFound
from backend.app.db.session import SessionLocal
from backend.app.models import ApiKey, ApiKeyEvent, AuditLog, LlmUsage, User

log = logging.getLogger(__name__)

PROVIDERS = ("google", "anthropic")
_TTL = 5.0
_KEY_RE = re.compile(r"^[A-Za-z0-9_\-.]{20,256}$")
# real model ids are short and lowercase; this also keeps a pasted API key (mixed case, long) from ever being accepted as a model name
_MODEL_RE = re.compile(r"^[a-z][a-z0-9._\-]{0,63}$")
GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash", "gemini-1.5-pro"]


@dataclass(frozen=True)
class ResolvedKey:
    key: str
    source: str            # "admin" | "env" | "none"
    key_id: int | None = None


_NONE = ResolvedKey("", "none")
_cache: dict[str, tuple[float, ResolvedKey]] = {}


def _env_key(provider: str) -> str:
    return {"anthropic": settings.anthropic_api_key, "google": settings.google_api_key}.get(provider, "")


def invalidate() -> None:
    _cache.clear()


def resolve(provider: str) -> ResolvedKey:
    """The key to use right now. Never raises: any problem with the admin key falls back to the environment key."""
    hit = _cache.get(provider)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    out = _NONE
    try:
        with SessionLocal() as db:
            row = db.scalar(select(ApiKey).where(ApiKey.provider == provider, ApiKey.is_active.is_(True)))
            if row is not None:
                try:
                    out = ResolvedKey(secrets.decrypt(row.ciphertext), "admin", row.id)
                except AppError as e:
                    log.error("Active %s API key (id=%s) unusable, using environment key: %s", provider, row.id, e.message)
    except Exception:  # table missing / DB hiccup -> environment fallback, do not cache the failure
        log.warning("API key lookup failed; using environment key", exc_info=False)
        env = _env_key(provider)
        return ResolvedKey(env, "env") if env else _NONE
    if out is _NONE and (env := _env_key(provider)):
        out = ResolvedKey(env, "env")
    _cache[provider] = (time.monotonic(), out)
    return out


def has_key(provider: str) -> bool:
    return bool(resolve(provider).key)


# ------------------------------------------------------------------ validation / testing
def validate_key_format(key: str) -> str:
    key = (key or "").strip()
    if not _KEY_RE.match(key):  # deliberately generic: never echo the value
        raise AppError("That does not look like a valid API key (20–256 letters, digits, '-', '_' or '.', no spaces).", 422)
    return key


def validate_model(model: str) -> str:
    model = (model or "").strip().removeprefix("models/")
    if not _MODEL_RE.match(model):
        raise AppError("Model name must be lowercase letters, digits, '.', '-' or '_' (max 64 characters), e.g. gemini-2.5-flash.", 422)
    return model


def usable_model(name: str) -> bool:
    return bool(_MODEL_RE.match((name or "").removeprefix("models/")))


def current_model(provider: str = "google") -> str:
    from backend.app.analytics.llm import ai_runtime

    rt = ai_runtime()
    return rt["model"] if rt["provider"] == provider else ""


def test_key(provider: str, key: str, model: str | None = None) -> tuple[bool, str]:
    """Live check that costs no tokens (model metadata lookup). Returns (ok, safe message)."""
    model = model or current_model(provider) or "gemini-2.0-flash"
    try:
        if provider == "google":
            r = httpx.get(f"https://generativelanguage.googleapis.com/v1beta/models/{model}", headers={"x-goog-api-key": key}, timeout=15)
        elif provider == "anthropic":
            r = httpx.get("https://api.anthropic.com/v1/models", headers={"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout=15)
        else:
            return False, "Unsupported provider"
    except httpx.TimeoutException:
        return False, "The provider did not respond in time. Try again."
    except httpx.HTTPError:
        return False, "Could not reach the provider (network error)."
    if r.status_code == 200:
        return True, f"Connected. Model “{model}” is available." if provider == "google" else "Connected."
    if r.status_code in (400, 401, 403):
        return False, "The provider rejected this key (invalid, revoked, or the API is not enabled for it)."
    if r.status_code == 404:
        return False, f"Key accepted, but model “{model}” was not found."
    if r.status_code == 429:
        return False, "The provider is rate-limiting or the key's quota is exhausted."
    return False, f"Unexpected response from the provider (HTTP {r.status_code})."


# ------------------------------------------------------------------ management
def _event(db: Session, admin: User, action: str, row: ApiKey | None = None, detail: str = "", provider: str = "") -> None:
    db.add(ApiKeyEvent(api_key_id=row.id if row else None, provider=row.provider if row else provider, action=action,
                       actor_id=admin.id, actor_email=admin.email, detail=detail[:300]))
    ref = f"id={row.id} " if row else ""
    # added to the caller's transaction (committed together with the change itself), unlike services.datasets.audit which commits immediately
    db.add(AuditLog(user_id=admin.id, action=f"admin.apikey.{action}", detail=f"{ref}provider={row.provider if row else provider} {detail}"[:480]))


def get_key(db: Session, key_id: int) -> ApiKey:
    row = db.get(ApiKey, key_id)
    if row is None:
        raise NotFound("API key not found")
    return row


def _check_provider(p: str) -> str:
    if p not in PROVIDERS:
        raise AppError("Unsupported provider", 422)
    return p


def create(db: Session, admin: User, provider: str, label: str, api_key: str, activate: bool) -> ApiKey:
    provider = _check_provider(provider)
    key = validate_key_format(api_key)
    row = ApiKey(provider=provider, label=(label or "").strip()[:80] or "API key", ciphertext=secrets.encrypt(key), last4=key[-4:], created_by=admin.id)
    db.add(row)
    db.flush()
    _event(db, admin, "create", row, f"label={row.label} last4={row.last4}")
    db.commit()
    if activate:
        activate_key(db, admin, row.id)
    return row


def update(db: Session, admin: User, key_id: int, label: str | None, api_key: str | None) -> ApiKey:
    row = get_key(db, key_id)
    changes = []
    if api_key:
        key = validate_key_format(api_key)
        ok, msg = test_key(row.provider, key)
        if row.is_active and not ok:  # never swap the live key for a broken one
            raise AppError(f"The new key was not applied: {msg}", 422)
        row.ciphertext, row.last4 = secrets.encrypt(key), key[-4:]
        row.status, row.status_message, row.last_tested_at = ("valid" if ok else "invalid"), msg, datetime.now(UTC)
        changes.append(f"key replaced last4={row.last4}")
    if label is not None and label.strip() and label.strip() != row.label:
        row.label = label.strip()[:80]
        changes.append("label changed")
    if not changes:
        raise AppError("Nothing to update", 422)
    _event(db, admin, "update", row, "; ".join(changes))
    db.commit()
    invalidate()
    return row


def test_stored(db: Session, admin: User, key_id: int) -> ApiKey:
    row = get_key(db, key_id)
    ok, msg = test_key(row.provider, secrets.decrypt(row.ciphertext))
    row.status, row.status_message, row.last_tested_at = ("valid" if ok else "invalid"), msg, datetime.now(UTC)
    _event(db, admin, "test", row, f"result={row.status}")
    db.commit()
    return row


def activate_key(db: Session, admin: User, key_id: int) -> ApiKey:
    row = get_key(db, key_id)
    ok, msg = test_key(row.provider, secrets.decrypt(row.ciphertext))
    row.status, row.status_message, row.last_tested_at = ("valid" if ok else "invalid"), msg, datetime.now(UTC)
    if not ok:
        _event(db, admin, "activate_failed", row, f"validation failed: {msg}")
        db.commit()
        raise AppError(f"Not activated: {msg}", 422)
    for other in db.scalars(select(ApiKey).where(ApiKey.provider == row.provider, ApiKey.is_active.is_(True), ApiKey.id != row.id)):
        other.is_active = False
        _event(db, admin, "deactivate", other, "replaced by newly activated key")
    db.flush()  # clear the old active flag before setting the new one (partial unique index)
    row.is_active, row.activated_at = True, datetime.now(UTC)
    _event(db, admin, "activate", row, f"last4={row.last4}")
    db.commit()
    invalidate()
    return row


def deactivate_key(db: Session, admin: User, key_id: int) -> tuple[ApiKey, str]:
    row = get_key(db, key_id)
    row.is_active = False
    _event(db, admin, "deactivate", row)
    db.commit()
    invalidate()
    fallback = "the environment key" if _env_key(row.provider) else "deterministic mode (no AI key configured)"
    return row, f"Deactivated. The app now uses {fallback}."


def delete_key(db: Session, admin: User, key_id: int) -> None:
    row = get_key(db, key_id)
    if row.is_active:
        raise AppError("Deactivate this key before deleting it.", 409)
    _event(db, admin, "delete", row, f"label={row.label} last4={row.last4}")
    db.delete(row)
    db.commit()


def set_model(db: Session, admin: User, provider: str, model: str, verify: bool) -> dict:
    from backend.app.services import appconfig

    provider, model = _check_provider(provider), validate_model(model)
    r = resolve(provider)
    if verify and r.key:
        ok, msg = test_key(provider, r.key, model)
        if not ok:
            raise AppError(f"Model not changed: {msg}", 422)
    old = current_model(provider)
    appconfig.put(db, "ai", {"provider": provider, "model": model})
    _event(db, admin, "model_changed", None, f"{old or '(default)'} -> {model}", provider)
    db.commit()
    return {"provider": provider, "model": model}


# ------------------------------------------------------------------ read models (masked; no secret ever leaves here)
def usage_by_key(db: Session) -> dict[int | None, dict]:
    rows = db.execute(select(LlmUsage.api_key_id, func.count(), func.coalesce(func.sum(LlmUsage.input_tokens), 0),
                             func.coalesce(func.sum(LlmUsage.output_tokens), 0), func.coalesce(func.sum(case((LlmUsage.ok.is_(False), 1), else_=0)), 0),
                             func.max(LlmUsage.created_at)).group_by(LlmUsage.api_key_id)).all()
    return {k: {"calls": c, "input_tokens": int(i), "output_tokens": int(o), "failures": int(f), "last_used_at": t.isoformat() if t else None}
            for k, c, i, o, f, t in rows}


def serialize(row: ApiKey, usage: dict | None = None) -> dict:
    return {"id": row.id, "provider": row.provider, "label": row.label, "masked": secrets.mask(row.last4), "is_active": row.is_active,
            "status": row.status, "status_message": row.status_message,
            "last_tested_at": row.last_tested_at.isoformat() if row.last_tested_at else None,
            "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
            "activated_at": row.activated_at.isoformat() if row.activated_at else None,
            "usage": usage or {"calls": 0, "input_tokens": 0, "output_tokens": 0, "failures": 0, "last_used_at": None}}
