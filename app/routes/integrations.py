"""Google Calendar integration endpoints (connect / callback / status)."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.schemas import IntegrationStatus
from app.services.google_oauth import GoogleAuthError

router = APIRouter(prefix="/integrations/google", tags=["integrations"])


def _redirect(request: Request, outcome: str) -> RedirectResponse:
    settings = request.app.state.settings
    base = settings.frontend_url or str(request.base_url).rstrip("/")
    query = urlencode({"google": outcome})
    return RedirectResponse(f"{base}/?{query}#/integrations")


@router.get("/status", response_model=IntegrationStatus)
def google_status(request: Request):
    return request.app.state.google_oauth.status()


@router.get("/connect")
def google_connect(request: Request):
    oauth = request.app.state.google_oauth
    if not request.app.state.settings.google_configured:
        raise HTTPException(status_code=409, detail="Google OAuth is not configured on this server.")
    state = oauth.make_state()
    return RedirectResponse(oauth.authorization_url(state))


@router.get("/callback")
def google_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    oauth = request.app.state.google_oauth
    if error or not code:
        return _redirect(request, "error")
    if not state or not oauth.verify_state(state):
        return _redirect(request, "invalid_state")
    try:
        oauth.exchange_code(code)
    except GoogleAuthError:
        return _redirect(request, "error")
    return _redirect(request, "connected")


@router.post("/disconnect", response_model=IntegrationStatus)
def google_disconnect(request: Request):
    request.app.state.google_oauth.disconnect()
    return {"connected": False, "configured": request.app.state.settings.google_configured}
