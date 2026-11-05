from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.analytics.llm import ai_runtime  # noqa: E402
from backend.app.api.v1.auth import user_out
from backend.app.config import settings
from backend.app.core.security import get_current_user, get_db
from backend.app.models import User
from backend.app.schemas.api import PreferencesIn

router = APIRouter()


@router.get("")
def get_settings(user: User = Depends(get_current_user)):
    return {"user": user_out(user), "system": {
        "app_env": settings.app_env, "database": settings.database_url.split(":")[0].split("+")[0],
        "database_location": settings.database_url.split("///")[-1] if settings.database_url.startswith("sqlite") else settings.database_url.split("@")[-1],
        "llm_provider": settings.llm_provider, "llm_enabled": ai_runtime()["enabled"],
        "llm_model": settings.llm_model or None, "max_upload_mb": settings.max_upload_mb,
        "max_query_rows": settings.max_query_rows, "query_timeout_seconds": settings.query_timeout_seconds,
        "supported_formats": ["csv", "tsv", "xlsx", "xls", "json", "jsonl", "parquet", "sqlite", "db", "pdf", "docx", "txt", "md"]}}


@router.put("")
def update(body: PreferencesIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    prefs = dict(user.preferences or {})
    for k in ("theme", "default_row_limit"):
        v = getattr(body, k)
        if v is not None:
            prefs[k] = v
    user.preferences = prefs
    if body.name is not None:
        user.name = body.name
    db.commit()
    return user_out(user)
