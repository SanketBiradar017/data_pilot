from fastapi import APIRouter, Depends

from backend.app.api.v1 import (
    advanced,
    analyses,
    auth,
    chat,
    dashboard,
    datasets,
    duplicates,
    health,
    intelligence,
    reports,
    settings,
    sql,
)
from backend.app.core.security import get_current_user

api_router = APIRouter()
protected = [Depends(get_current_user)]

api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(datasets.router, prefix="/datasets", tags=["Datasets"])
api_router.include_router(duplicates.router, prefix="/datasets", tags=["Duplicates"])
api_router.include_router(advanced.router, prefix="/advanced", tags=["Advanced analytics"])
api_router.include_router(intelligence.router, prefix="/intelligence", tags=["AI intelligence"])
api_router.include_router(sql.router, prefix="/sql", tags=["SQL"])
api_router.include_router(analyses.router, prefix="/analyses", tags=["Analyses"])
api_router.include_router(chat.router, prefix="/chat", tags=["Chat"])
api_router.include_router(reports.router, prefix="/reports", tags=["Reports"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
api_router.include_router(settings.router, prefix="/settings", tags=["Settings"])
