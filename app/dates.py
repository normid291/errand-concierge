"""Natural-language date parsing for errand due dates.

The language model is deliberately *not* asked to do date arithmetic. It passes
the user's phrase through untouched and this module resolves it against the
current date in the configured timezone.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil import parser as date_parser

DEFAULT_HOUR = 9

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

RELATIVE_DAYS = {
    "today": 0,
    "tonight": 0,
    "tomorrow": 1,
    "tmrw": 1,
    "tmr": 1,
    "day after tomorrow": 2,
}

_NUMBER_WORDS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def get_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def now_in(tz: ZoneInfo | None = None) -> datetime:
    return datetime.now(tz or ZoneInfo("UTC"))


def _at_default_hour(day: date, tz: ZoneInfo, hour: int = DEFAULT_HOUR) -> datetime:
    return datetime.combine(day, time(hour=hour), tzinfo=tz)


def _extract_time(text: str) -> tuple[int, int] | None:
    """Picks up a time like `3pm`, `15:30`, or `at 9` when one is present."""
    match = re.search(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text, re.IGNORECASE)
    if match:
        hour = int(match.group(1)) % 12
        if match.group(3).lower() == "pm":
            hour += 12
        minute = int(match.group(2) or 0)
        return hour, minute
    match = re.search(r"\b(?:at\s+)(\d{1,2}):(\d{2})\b", text, re.IGNORECASE)
    if match:
        return int(match.group(1)) % 24, int(match.group(2))
    match = re.search(r"\bT(\d{2}):(\d{2})\b", text)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def parse_due(
    text: str | None,
    timezone: str = "Africa/Lagos",
    reference: datetime | None = None,
) -> datetime | None:
    """Resolve a plain-language due phrase to an aware datetime.

    Returns ``None`` when the phrase is empty or cannot be understood. The
    parser never raises: invalid input simply means "no due date".
    """
    if not text or not str(text).strip():
        return None

    tz = get_timezone(timezone)
    ref = reference.astimezone(tz) if reference else now_in(tz)
    raw = str(text).strip()
    lowered = re.sub(r"\s+", " ", raw.lower()).strip(" .,!?")

    # A date-only ISO value such as 2026-11-03.
    iso_date = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", lowered)
    if iso_date:
        try:
            return _at_default_hour(date(*map(int, iso_date.groups())), tz)
        except ValueError:
            return None

    if lowered in {"now", "right now"}:
        return ref
    if lowered in RELATIVE_DAYS:
        days = RELATIVE_DAYS[lowered]
        target = _at_default_hour(ref.date() + timedelta(days=days), tz)
        if lowered == "tonight":
            target = target.replace(hour=19)
        return target

    match = re.fullmatch(
        r"in\s+(a|an|one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
        r"(day|days|week|weeks|month|months)",
        lowered,
    )
    if match:
        amount = _NUMBER_WORDS.get(match.group(1)) or int(match.group(1))
        unit = match.group(2)
        if unit.startswith("day"):
            return _at_default_hour(ref.date() + timedelta(days=amount), tz)
        if unit.startswith("week"):
            return _at_default_hour(ref.date() + timedelta(weeks=amount), tz)
        return _at_default_hour(_add_months(ref.date(), amount), tz)

    if lowered in {"next week", "in a week"}:
        return _at_default_hour(ref.date() + timedelta(weeks=1), tz)
    if lowered in {"next month", "in a month"}:
        return _at_default_hour(_add_months(ref.date(), 1), tz)
    if lowered == "end of week":
        days_ahead = (4 - ref.weekday()) % 7
        return _at_default_hour(ref.date() + timedelta(days=days_ahead), tz)
    if lowered == "end of month":
        last_day = calendar.monthrange(ref.year, ref.month)[1]
        return _at_default_hour(ref.date().replace(day=last_day), tz)

    if lowered in {"weekend", "this weekend"}:
        days_ahead = (5 - ref.weekday()) % 7
        return _at_default_hour(ref.date() + timedelta(days=days_ahead), tz)
    if lowered == "next weekend":
        days_ahead = (5 - ref.weekday()) % 7 + 7
        return _at_default_hour(ref.date() + timedelta(days=days_ahead), tz)

    # "tomorrow at 3pm" / "3pm tomorrow" — dateutil does not combine these.
    relative = re.search(r"\b(day after tomorrow|today|tonight|tomorrow|tmrw|tmr)\b", lowered)
    if relative and relative.group(1) in RELATIVE_DAYS:
        word = relative.group(1)
        target_day = ref.date() + timedelta(days=RELATIVE_DAYS[word])
        parts = _extract_time(raw)
        if parts:
            return datetime.combine(target_day, time(hour=parts[0], minute=parts[1]), tzinfo=tz)
        hour = 19 if word == "tonight" else DEFAULT_HOUR
        return _at_default_hour(target_day, tz, hour)

    weekday_match = re.fullmatch(
        r"(next|this|coming)?\s*"
        r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
        lowered,
    )
    if weekday_match:
        qualifier = weekday_match.group(1)
        target = WEEKDAYS[weekday_match.group(2)]
        days_ahead = (target - ref.weekday()) % 7
        # "this friday" may mean today; a bare weekday or "next friday" always
        # points at a future date.
        if days_ahead == 0 and qualifier != "this":
            days_ahead = 7
        return _at_default_hour(ref.date() + timedelta(days=days_ahead), tz)

    # Fall back to dateutil for explicit dates like "Nov 3" or "3/11/2026".
    try:
        default = ref.replace(hour=DEFAULT_HOUR, minute=0, second=0, microsecond=0)
        parsed = date_parser.parse(raw, fuzzy=True, default=default)
    except (ValueError, OverflowError, TypeError):
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    else:
        parsed = parsed.astimezone(tz)

    # dateutil fills in "today" when only a time was supplied; that is fine.
    time_parts = _extract_time(raw)
    if time_parts is not None:
        parsed = parsed.replace(hour=time_parts[0], minute=time_parts[1])
    return parsed


def _add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))
