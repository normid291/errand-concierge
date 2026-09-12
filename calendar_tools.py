"""
calendar_tools.py — Google Calendar sync helpers.

These are plain functions (not @tool-decorated) meant to be called INSIDE
your existing tools.py functions (add_errand, reschedule_errand, etc.),
not exposed directly to the agent as separate tools — the agent shouldn't
need to think about Calendar explicitly; it should just happen.

All functions no-op quietly if Google Calendar isn't connected, so the app
behaves identically whether or not the user has connected their calendar.
"""

import requests
from datetime import datetime, timedelta
from dateutil import parser as date_parser

from google_auth import get_valid_access_token

CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"


def parse_due_to_iso(due: str) -> str | None:
    """
    Best-effort conversion of a plain-language due string (e.g. "Friday",
    "next week", "2026-09-20") into an ISO 8601 datetime. Returns None if it
    can't be parsed — callers should skip calendar sync in that case rather
    than fail the whole errand-adding flow.
    """
    if not due:
        return None
    try:
        dt = date_parser.parse(due, fuzzy=True, default=datetime.now().replace(
            hour=9, minute=0, second=0, microsecond=0
        ))
        return dt.isoformat()
    except (ValueError, OverflowError):
        return None


def _headers() -> dict | None:
    token = get_valid_access_token()
    if not token:
        return None
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def create_calendar_event(title: str, due_iso: str, notes: str = "") -> str | None:
    """
    Creates a Calendar event for an errand. due_iso should be an ISO 8601
    datetime string (e.g. "2026-09-14T15:00:00"). Returns the Google event ID
    on success, or None if not connected / on failure.
    """
    headers = _headers()
    if not headers:
        return None

    start_dt = date_parser.parse(due_iso)
    end_dt = start_dt + timedelta(hours=1)

    body = {
        "summary": title,
        "description": notes or "Added via Errand Concierge",
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "Africa/Lagos"},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": "Africa/Lagos"},
    }
    try:
        resp = requests.post(
            f"{CALENDAR_API_BASE}/calendars/primary/events",
            headers=headers,
            json=body,
            timeout=10,
        )
        if resp.ok:
            return resp.json().get("id")
    except requests.RequestException:
        pass
    return None


def update_calendar_event(event_id: str, title: str = None, due_iso: str = None, notes: str = None) -> bool:
    """Updates an existing Calendar event (e.g. on reschedule). Returns success bool."""
    headers = _headers()
    if not headers or not event_id:
        return False

    body = {}
    if title:
        body["summary"] = title
    if notes is not None:
        body["description"] = notes
    if due_iso:
        start_dt = date_parser.parse(due_iso)
        end_dt = start_dt + timedelta(hours=1)
        body["start"] = {"dateTime": start_dt.isoformat(), "timeZone": "Africa/Lagos"}
        body["end"] = {"dateTime": end_dt.isoformat(), "timeZone": "Africa/Lagos"}

    try:
        resp = requests.patch(
            f"{CALENDAR_API_BASE}/calendars/primary/events/{event_id}",
            headers=headers,
            json=body,
            timeout=10,
        )
        return resp.ok
    except requests.RequestException:
        return False


def delete_calendar_event(event_id: str) -> bool:
    """Deletes a Calendar event (e.g. when an errand is deleted/cancelled)."""
    headers = _headers()
    if not headers or not event_id:
        return False
    try:
        resp = requests.delete(
            f"{CALENDAR_API_BASE}/calendars/primary/events/{event_id}",
            headers=headers,
            timeout=10,
        )
        return resp.ok or resp.status_code == 404  # already gone counts as success
    except requests.RequestException:
        return False
