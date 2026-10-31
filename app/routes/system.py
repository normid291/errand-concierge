"""Health, configuration, and stats endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app import __version__
from app.schemas import AppConfig, Counts

router = APIRouter(tags=["system"])


@router.get("/health")
def health(request: Request):
    try:
        counts = request.app.state.repo.counts()
        database = "ok"
    except Exception:
        counts = None
        database = "error"
    return {
        "status": "ok" if database == "ok" else "degraded",
        "version": __version__,
        "database": database,
        "assistant": request.app.state.assistant.mode,
        "errands": counts["total"] if counts else None,
    }


@router.get("/config", response_model=AppConfig)
def config(request: Request):
    settings = request.app.state.settings
    return {
        "mode": request.app.state.assistant.mode,
        "google_configured": settings.google_configured,
        "calendar_timezone": settings.calendar_timezone,
    }


@router.get("/stats", response_model=Counts)
def stats(request: Request):
    return request.app.state.errands.stats()
