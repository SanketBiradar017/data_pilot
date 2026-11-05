import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.app.db.session import SessionLocal
from backend.app.models import ApiRequestLog

log = logging.getLogger("datapilot.http")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        if (blocked := _maintenance(request)) is not None:
            blocked.headers["x-request-id"] = rid
            return blocked
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error rid=%s %s %s", rid, request.method, request.url.path)
            raise
        ms = (time.perf_counter() - start) * 1000
        response.headers["x-request-id"] = rid
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["x-frame-options"] = "DENY"
        _record(request, response.status_code, ms)
        log.info("%s %s -> %s %.0fms rid=%s", request.method, request.url.path, response.status_code, ms, rid)
        return response


def _record(request, status_code: int, ms: float) -> None:
    """Persist one usage row per API call. Failures here must never break the request."""
    path = request.url.path
    if not path.startswith("/api/") or request.method == "OPTIONS" or path.startswith("/api/v1/health"):
        return
    route = path  # template-ize: /datasets/42 -> /datasets/{dataset_id} (never store raw ids/params)
    for k, v in request.path_params.items():
        route = route.replace(f"/{v}", f"/{{{k}}}")
    if request.scope.get("route") is None:
        route = "(unmatched)"
    try:
        with SessionLocal() as db:
            db.add(ApiRequestLog(user_id=getattr(request.state, "user_id", None), method=request.method,
                                 route=route[:200], status_code=status_code, duration_ms=round(ms, 1)))
            db.commit()
    except Exception:
        log.warning("api usage log failed", exc_info=True)


_OPEN_DURING_MAINTENANCE = ("/api/v1/platform", "/api/v1/health", "/api/v1/auth/login", "/api/v1/auth/me", "/api/v1/admin")


def _maintenance(request):
    """503 for the app API while maintenance mode is on. Admin routes stay reachable (they enforce super_admin themselves)."""
    path = request.url.path
    if not path.startswith("/api/") or path.startswith(_OPEN_DURING_MAINTENANCE):
        return None
    try:
        from backend.app.services import appconfig

        p = appconfig.get("platform")
        if p["maintenance_mode"]:
            return JSONResponse({"detail": p["maintenance_message"], "maintenance": True}, status_code=503, headers={"retry-after": "300"})
    except Exception:
        log.warning("maintenance check failed", exc_info=True)
    return None
