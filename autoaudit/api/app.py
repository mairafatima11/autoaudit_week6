"""FastAPI application factory.

Run locally with:
    uvicorn autoaudit.api.app:app --reload --port 8000

Interactive docs are then at /docs (Swagger) and /redoc.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth import ApiKeyAuthMiddleware
from .routers import audits, explorer, memory, models, repository


def create_app() -> FastAPI:
    app = FastAPI(
        title="AutoAudit AI API",
        description="HTTP API for the AutoAudit AI multi-agent code review pipeline.",
        version="0.8.0",
    )

    # Auth placeholder — no-op unless AUTOAUDIT_API_KEY is set. See api/auth.py.
    # Added before CORS so CORS ends up as the outermost layer (Starlette
    # wraps middleware in reverse add-order) and still attaches headers to
    # auth's own 401 responses — otherwise a browser client would see an
    # opaque CORS failure instead of a readable 401 when a key is missing.
    app.add_middleware(ApiKeyAuthMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # dashboard is a separate dev-server origin; tighten for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(audits.router)
    app.include_router(explorer.router)
    app.include_router(memory.router)
    app.include_router(models.router)
    app.include_router(repository.router)

    @app.get("/api/health", tags=["meta"])
    def health():
        return {"status": "ok"}

    return app


app = create_app()
