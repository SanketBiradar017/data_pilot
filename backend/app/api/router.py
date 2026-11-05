from fastapi import APIRouter, Depends

from backend.app.api.v1 import (
    admin,
    admin_billing,
    advanced,
    analyses,
    auth,
    billing,
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
from backend.app.services.entitlements import require_feature

api_router = APIRouter()
protected = [Depends(get_current_user)]

api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(datasets.router, prefix="/datasets", tags=["Datasets"])
api_router.include_router(duplicates.router, prefix="/datasets", tags=["Duplicates"], dependencies=[Depends(require_feature("data_cleaning"))])
api_router.include_router(advanced.router, prefix="/advanced", tags=["Advanced analytics"], dependencies=[Depends(require_feature("eda"))])
api_router.include_router(intelligence.router, prefix="/intelligence", tags=["AI intelligence"], dependencies=[Depends(require_feature("ai_agents"))])
api_router.include_router(sql.router, prefix="/sql", tags=["SQL"], dependencies=[Depends(require_feature("sql_analysis"))])
api_router.include_router(analyses.router, prefix="/analyses", tags=["Analyses"])
api_router.include_router(chat.router, prefix="/chat", tags=["Chat"], dependencies=[Depends(require_feature("ai_chat"))])
api_router.include_router(reports.router, prefix="/reports", tags=["Reports"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
api_router.include_router(settings.router, prefix="/settings", tags=["Settings"])
api_router.include_router(admin.router, prefix="/admin", tags=["Super admin"])  # router-level require_super_admin
api_router.include_router(billing.public_router, tags=["Platform"])
api_router.include_router(billing.router, prefix="/billing", tags=["Billing"], dependencies=protected)
api_router.include_router(admin_billing.router, prefix="/admin", tags=["Super admin"])
