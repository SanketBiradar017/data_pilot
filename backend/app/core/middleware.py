import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

log = logging.getLogger("datapilot.http")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
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
        log.info("%s %s -> %s %.0fms rid=%s", request.method, request.url.path, response.status_code, ms, rid)
        return response
