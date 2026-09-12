"""
integrations_routes.py — FastAPI routes for the Integrations tab.

HOW TO WIRE IN: in backend.py, add:

    from integrations_routes import router as integrations_router
    app.include_router(integrations_router)

(Requires: pip install requests google_auth.py and calendar_tools.py present
in the same directory as backend.py)
"""

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

import google_auth

router = APIRouter(prefix="/api/integrations/google", tags=["integrations"])


@router.get("/status")
def google_status():
    """Used by the Integrations tab to show Connected/Not connected + email."""
    return google_auth.get_connection_status()


@router.get("/connect")
def google_connect():
    """Redirects the browser to Google's consent screen."""
    return RedirectResponse(google_auth.get_authorization_url())


@router.get("/callback")
def google_callback(code: str = None, error: str = None):
    """
    Google redirects here after consent. Exchanges the code for tokens,
    then redirects back to the frontend's Integrations tab.
    """
    if error or not code:
        return RedirectResponse("/#/integrations?google=error")

    google_auth.exchange_code_for_tokens(code)
    return RedirectResponse("/#/integrations?google=connected")


@router.post("/disconnect")
def google_disconnect():
    """Revokes and clears the stored Google tokens."""
    google_auth.disconnect()
    return {"connected": False}
