"""Date parsing behaviour."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.dates import parse_due

TZ = "Africa/Lagos"
REF = datetime(2026, 10, 31, 12, 0, tzinfo=ZoneInfo(TZ))  # a Saturday


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("today", "2026-10-31T09:00:00+01:00"),
        ("tomorrow", "2026-11-01T09:00:00+01:00"),
        ("tonight", "2026-10-31T19:00:00+01:00"),
        ("friday", "2026-11-06T09:00:00+01:00"),
        ("this friday", "2026-11-06T09:00:00+01:00"),
        ("next week", "2026-11-07T09:00:00+01:00"),
        ("in 3 days", "2026-11-03T09:00:00+01:00"),
        ("in 2 weeks", "2026-11-14T09:00:00+01:00"),
        ("Nov 3", "2026-11-03T09:00:00+01:00"),
        ("2026-11-03", "2026-11-03T09:00:00+01:00"),
        ("tomorrow at 3pm", "2026-11-01T15:00:00+01:00"),
        ("3pm tomorrow", "2026-11-01T15:00:00+01:00"),
        ("next tuesday at 3pm", "2026-11-03T15:00:00+01:00"),
        ("friday 3pm", "2026-11-06T15:00:00+01:00"),
        ("this weekend", "2026-10-31T09:00:00+01:00"),
        ("next weekend", "2026-11-07T09:00:00+01:00"),
    ],
)
def test_parse_common_phrases(phrase: str, expected: str):
    parsed = parse_due(phrase, TZ, REF)
    assert parsed is not None
    assert parsed.isoformat() == expected


@pytest.mark.parametrize("phrase", [None, "", "   ", "whenever", "sometime soon"])
def test_parse_unclear_phrases(phrase):
    assert parse_due(phrase, TZ, REF) is None


def test_end_of_week_and_month():
    assert parse_due("end of week", TZ, REF).isoformat() == "2026-11-06T09:00:00+01:00"
    assert parse_due("end of month", TZ, REF).isoformat() == "2026-10-31T09:00:00+01:00"


def test_weekday_is_always_in_the_future():
    # REF is a Saturday; "saturday" should mean next Saturday, not today.
    assert parse_due("saturday", TZ, REF).isoformat() == "2026-11-07T09:00:00+01:00"
    assert parse_due("this saturday", TZ, REF).isoformat() == "2026-10-31T09:00:00+01:00"
