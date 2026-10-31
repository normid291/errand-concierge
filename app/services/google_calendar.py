"""Google Calendar sync.

Every method is best-effort: calendar problems never block managing errands.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import requests

from app.services.google_oauth import GoogleOAuth

logger = logging.getLogger(__name__)

API_BASE = "https://www.googleapis.com/calendar/v3"
EVENT_DURATION = timedelta(hours=1)


class GoogleCalendar:
    def __init__(self, oauth: GoogleOAuth, timezone: str):
        self.oauth = oauth
        self.timezone = timezone

    def is_connected(self) -> bool:
        return self.oauth.access_token() is not None

    def _headers(self) -> dict | None:
        token = self.oauth.access_token()
        if not token:
            return None
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _body(self, title: str, start: datetime, notes: str | None) -> dict:
        end = start + EVENT_DURATION
        return {
            "summary": title,
            "description": notes or "Added via Errand Concierge",
            "start": {"dateTime": start.isoformat(), "timeZone": self.timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": self.timezone},
        }

    def create(self, title: str, start: datetime, notes: str | None = None) -> str | None:
        headers = self._headers()
        if not headers:
            return None
        try:
            response = requests.post(
                f"{API_BASE}/calendars/primary/events",
                headers=headers,
                json=self._body(title, start, notes),
                timeout=12,
            )
            if response.ok:
                return response.json().get("id")
            logger.warning("Calendar create failed: %s %s", response.status_code, response.text[:200])
        except requests.RequestException as exc:
            logger.warning("Calendar create error: %s", exc)
        return None

    def update(
        self,
        event_id: str,
        title: str | None = None,
        start: datetime | None = None,
        notes: str | None = None,
    ) -> bool:
        headers = self._headers()
        if not headers or not event_id:
            return False
        body = {}
        if start is not None:
            body["start"] = {"dateTime": start.isoformat(), "timeZone": self.timezone}
            body["end"] = {"dateTime": (start + EVENT_DURATION).isoformat(), "timeZone": self.timezone}
        if title:
            body["summary"] = title
        if notes is not None:
            body["description"] = notes
        try:
            response = requests.patch(
                f"{API_BASE}/calendars/primary/events/{event_id}",
                headers=headers,
                json=body,
                timeout=12,
            )
            return response.ok
        except requests.RequestException as exc:
            logger.warning("Calendar update error: %s", exc)
            return False

    def delete(self, event_id: str) -> bool:
        headers = self._headers()
        if not headers or not event_id:
            return False
        try:
            response = requests.delete(
                f"{API_BASE}/calendars/primary/events/{event_id}",
                headers=headers,
                timeout=12,
            )
            return response.ok or response.status_code == 404
        except requests.RequestException as exc:
            logger.warning("Calendar delete error: %s", exc)
            return False
