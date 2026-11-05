"""Runtime-editable configuration stored in the DB (JSON per key) with a short in-process cache.
Secrets (API keys, SMTP password, gateway secrets) are NOT here - they come from the environment."""
import copy
import time

from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.db.session import SessionLocal
from backend.app.ingestion.loaders import ALLOWED_EXT
from backend.app.models import AppSetting

FEATURES = {
    "ai_chat": "AI Chat", "data_cleaning": "Data Cleaning", "eda": "EDA", "ai_agents": "AI Agents",
    "sql_analysis": "SQL Analysis", "data_visualization": "Data Visualization", "pdf_reports": "PDF Reports",
    "excel_reports": "Excel Reports", "document_research": "Document Research",
}
LIMITS = {
    "max_datasets": "Datasets", "max_file_mb": "Max file size (MB)", "storage_mb": "Storage (MB)",
    "ai_analyses_per_month": "AI analyses / month", "reports_per_month": "Reports / month", "chat_messages_per_month": "Chat messages / month",
}

DEFAULTS: dict[str, dict] = {
    "platform": {
        "app_name": settings.app_name, "tagline": "", "primary_color": "#6366f1", "logo_url": "", "support_email": "",
        "public_url": "http://localhost:5173",
        "maintenance_mode": False, "maintenance_message": "DataPilot AI is undergoing scheduled maintenance. Please check back shortly.",
        "registration_open": True, "email_verification": False,
        "announcement": "", "announcement_tone": "info",
    },
    "smtp": {"host": "", "port": 587, "username": "", "from_email": "", "from_name": "DataPilot AI", "use_tls": True},
    "notifications": {
        "verification_subject": "Verify your email", "verification_body": "Hi {name},\n\nConfirm your email to activate your account:\n{link}\n\nThis link expires in 48 hours.",
        "welcome_subject": "Welcome to {app}", "welcome_body": "Hi {name},\n\nYour account is ready. Sign in at {url}.",
        "suspended_subject": "Your account has been suspended", "suspended_body": "Hi {name},\n\nYour account was suspended by an administrator. Contact {support} if you think this is a mistake.",
    },
    "features": {k: True for k in FEATURES},
    "uploads": {"max_upload_mb": settings.max_upload_mb, "allowed_formats": sorted(ALLOWED_EXT), "storage_limit_gb": None},
    "ai": {
        "provider": "", "model": "", "temperature": None, "max_output_tokens": None, "system_prompt": "",
        "fallback_provider": "", "fallback_model": "", "monthly_token_cap": None, "daily_call_cap": None,
        "prices": {},  # {"model-name": {"input_per_m": 3.0, "output_per_m": 15.0}}  (USD per 1M tokens)
    },
    "payments": {"gateway": "manual", "mode": "test", "currency": "INR", "enabled": False, "webhook_url": "", "statement_descriptor": ""},
}

_cache: dict[str, tuple[float, dict]] = {}
_TTL = 5.0


def get(key: str, db: Session | None = None) -> dict:
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    own = db is None
    db = db or SessionLocal()
    try:
        row = db.get(AppSetting, key)
        val = {**copy.deepcopy(DEFAULTS[key]), **(row.value if row else {})}
    except Exception:  # table missing (fresh DB / before init) -> defaults, don't cache
        return copy.deepcopy(DEFAULTS[key])
    finally:
        if own:
            db.close()
    _cache[key] = (time.monotonic(), val)
    return val


def put(db: Session, key: str, patch: dict) -> dict:
    unknown = set(patch) - set(DEFAULTS[key])
    if unknown:
        raise ValueError(f"Unknown setting(s): {', '.join(sorted(unknown))}")
    row = db.get(AppSetting, key)
    cur = dict(row.value) if row else {}
    cur.update(patch)
    if row:
        row.value = cur
    else:
        db.add(AppSetting(key=key, value=cur))
    db.commit()
    _cache.pop(key, None)
    return get(key, db)


def smtp_configured() -> bool:
    c = get("smtp")
    return bool(c["host"] and c["from_email"])
