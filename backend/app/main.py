"""FastAPI application: routers, security headers, static frontend, lifecycle."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import ROOT_DIR, get_settings
from .database import session_scope
from .routers import ai, auth, executions, integrations, templates, workflows, workspaces
from .seed import ensure_demo_account, seed_templates
from .worker import BackgroundRunner

log = logging.getLogger("flowforge")
settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    with session_scope() as db:
        seed_templates(db)
        if settings.demo_mode_enabled:
            ensure_demo_account(db)
    runner = None
    if settings.worker_enabled:
        runner = BackgroundRunner()
        runner.start()
    yield
    if runner:
        runner.stop()


app = FastAPI(title="FlowForge AI API", version=__version__, lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Workspace-Id"],
)

_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
    "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
)
_DOCS_CSP = "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; frame-ancestors 'none'"


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = _DOCS_CSP if request.url.path == "/api/docs" else _CSP
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(_request: Request, exc: RequestValidationError):
    # Echoing `input` could reflect passwords back, so return only location and message.
    issues = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
    first = issues[0] if issues else {"field": "", "message": "Invalid request"}
    return JSONResponse({"detail": f"{first['field']}: {first['message']}".strip(": "), "issues": issues}, status_code=422)


@app.exception_handler(Exception)
async def unexpected_handler(_request: Request, exc: Exception):
    log.exception("Unhandled error", exc_info=exc)
    return JSONResponse({"detail": "Something went wrong on the server"}, status_code=500)


for router in (
    auth.router,
    workspaces.router,
    workspaces.audit_router,
    workflows.router,
    workflows.meta_router,
    executions.router,
    executions.analytics_router,
    integrations.credentials_router,
    integrations.integrations_router,
    integrations.webhooks_router,
    integrations.hooks_router,
    integrations.data_router,
    templates.router,
    ai.router,
):
    app.include_router(router)


@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok", "version": __version__, "environment": settings.app_env}


_DIST = ROOT_DIR / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        candidate = (_DIST / path).resolve()
        if path and candidate.is_file() and Path(_DIST.resolve()) in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")
