import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.router import api_router
from backend.app.config import ROOT, settings
from backend.app.core.exceptions import AppError
from backend.app.core.logging import setup_logging
from backend.app.core.middleware import RequestContextMiddleware
from backend.app.db.init_db import init_db

log = logging.getLogger("datapilot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.debug)
    if settings.app_env == "production" and settings.secret_key.startswith("development"):
        raise RuntimeError("SECRET_KEY must be set in production")
    init_db()
    from backend.app.db.session import SessionLocal
    from backend.app.services.datasets import heal_paths

    with SessionLocal() as _db:
        heal_paths(_db)
    log.info("Database: %s", settings.database_url.split("@")[-1])
    log.info("%s started (env=%s, llm=%s)", settings.app_name, settings.app_env, settings.llm_provider)
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan,
              description="Multi-agent data analytics platform")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
app.add_middleware(RequestContextMiddleware)


@app.exception_handler(AppError)
async def app_error(_: Request, exc: AppError):
    return JSONResponse({"detail": exc.message}, status_code=exc.status_code)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.exception("unhandled: %s", exc)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


app.include_router(api_router, prefix="/api/v1")


DIST = ROOT / "frontend" / "dist"
if DIST.is_dir():  # production: serve the built React app from the same origin
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(("api/", "docs", "openapi")):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        f = (DIST / path).resolve()
        return FileResponse(f if f.is_file() and DIST in f.parents else DIST / "index.html")
else:

    @app.get("/", tags=["root"])
    def root():
        return {"name": settings.app_name, "status": "running", "docs": "/docs", "api_prefix": "/api/v1"}
