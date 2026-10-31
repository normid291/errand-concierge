"""Application factory."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import Settings
from app.db import init_db, migrate_json_files
from app.repository import ErrandRepository
from app.routes import chat, errands, integrations, system
from app.services.assistant import build_assistant
from app.services.errands import ErrandService
from app.services.google_calendar import GoogleCalendar
from app.services.google_oauth import GoogleOAuth, TokenStore

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()

    init_db(settings.database_path)
    imported = migrate_json_files(settings.database_path, settings.base_dir, settings.calendar_timezone)
    if imported:
        logger.info("Imported %s errands from the legacy JSON store.", imported)

    repository = ErrandRepository(settings.database_path)
    token_store = TokenStore(settings.database_path)
    google_oauth = GoogleOAuth(settings, token_store)
    calendar = GoogleCalendar(google_oauth, settings.calendar_timezone)
    errands_service = ErrandService(repository, calendar, settings.calendar_timezone)
    assistant = build_assistant(settings, errands_service)

    app = FastAPI(
        title="Errand Concierge API",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.repo = repository
    app.state.errands = errands_service
    app.state.assistant = assistant
    app.state.google_oauth = google_oauth

    if settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.allowed_origins,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type"],
            allow_credentials=False,
        )

    app.add_middleware(GZipMiddleware, minimum_size=800)

    app.include_router(system.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(errands.router, prefix="/api")
    app.include_router(integrations.router, prefix="/api")

    frontend_dir: Path = settings.base_dir / "frontend"
    if frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

    return app
