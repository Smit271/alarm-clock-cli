"""Turning what the user types into typed values, or a clear error."""

import re
from datetime import time as dt_time, timedelta
from typing import List

from .models import PRESETS, WEEKDAY_NAMES


class ParseError(ValueError):
    """Raised for input the user typed wrong. The CLI turns this into exit code 2."""


_TWELVE_HOUR = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", re.IGNORECASE)
_TWENTY_FOUR_HOUR = re.compile(r"^(\d{1,2}):(\d{2})$")
_DURATION_PART = re.compile(r"(\d+)([hms])")


def parse_time(text: str) -> dt_time:
    text = (text or "").strip()
    match = _TWELVE_HOUR.match(text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        if not 1 <= hour <= 12 or minute > 59:
            raise ParseError("not a valid time: {!r}".format(text))
        if match.group(3).lower() == "am":
            hour = 0 if hour == 12 else hour
        else:
            hour = 12 if hour == 12 else hour + 12
        return dt_time(hour, minute)

    match = _TWENTY_FOUR_HOUR.match(text)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            raise ParseError("not a valid time: {!r}".format(text))
        return dt_time(hour, minute)

    raise ParseError(
        "not a valid time: {!r} (try 07:00, 19:30, 7am or 7:30pm)".format(text))


def parse_duration(text: str) -> timedelta:
    text = (text or "").strip().lower()
    parts = _DURATION_PART.findall(text)
    # Rebuilding the string from the matches rejects stray characters such as "20x".
    if not parts or "".join(n + u for n, u in parts) != text:
        raise ParseError(
            "not a valid duration: {!r} (try 45s, 20m, 2h or 1h30m)".format(text))
    units = {"h": "hours", "m": "minutes", "s": "seconds"}
    total = timedelta()
    for number, unit in parts:
        total += timedelta(**{units[unit]: int(number)})
    if total <= timedelta():
        raise ParseError("duration must be greater than zero")
    return total


def parse_recurrence(text: str) -> List[int]:
    text = (text or "").strip().lower()
    if text == "once":
        return []
    if text in PRESETS:
        return list(PRESETS[text])
    tokens = [token.strip() for token in text.split(",")]
    if not text or any(token not in WEEKDAY_NAMES for token in tokens):
        raise ParseError(
            "not a valid recurrence: {!r} (try once, daily, weekdays, weekends "
            "or a list like mon,wed,fri)".format(text))
    return sorted({WEEKDAY_NAMES.index(token) for token in tokens})


def format_countdown(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        return "now"
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days:
        return "in {}d {}h".format(days, hours)
    if hours:
        return "in {}h {}m".format(hours, minutes)
    if minutes:
        return "in {}m".format(minutes)
    return "in {}s".format(seconds)
