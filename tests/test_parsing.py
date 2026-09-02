from datetime import time, timedelta

import pytest

from alarmclock.parsing import (ParseError, format_countdown, parse_duration,
                                parse_recurrence, parse_time)


@pytest.mark.parametrize("text,expected", [
    ("07:00", time(7, 0)),
    ("7:00", time(7, 0)),
    ("19:30", time(19, 30)),
    ("00:00", time(0, 0)),
    ("7am", time(7, 0)),
    ("7AM", time(7, 0)),
    ("7:30pm", time(19, 30)),
    ("12am", time(0, 0)),
    ("12pm", time(12, 0)),
])
def test_parse_time_accepts_supported_forms(text, expected):
    assert parse_time(text) == expected


@pytest.mark.parametrize("text", ["25:00", "07:60", "7pmm", "", "abc", "13pm"])
def test_parse_time_rejects_bad_input(text):
    with pytest.raises(ParseError):
        parse_time(text)


@pytest.mark.parametrize("text,expected", [
    ("45s", timedelta(seconds=45)),
    ("20m", timedelta(minutes=20)),
    ("2h", timedelta(hours=2)),
    ("1h30m", timedelta(hours=1, minutes=30)),
    ("1h30m15s", timedelta(hours=1, minutes=30, seconds=15)),
])
def test_parse_duration_accepts_supported_forms(text, expected):
    assert parse_duration(text) == expected


@pytest.mark.parametrize("text", ["20x", "", "h", "-5m", "0m", "20"])
def test_parse_duration_rejects_bad_input(text):
    with pytest.raises(ParseError):
        parse_duration(text)


@pytest.mark.parametrize("text,expected", [
    ("once", []),
    ("daily", [0, 1, 2, 3, 4, 5, 6]),
    ("weekdays", [0, 1, 2, 3, 4]),
    ("weekends", [5, 6]),
    ("mon,wed,fri", [0, 2, 4]),
    ("Sun, Mon", [0, 6]),
])
def test_parse_recurrence_accepts_supported_forms(text, expected):
    assert parse_recurrence(text) == expected


@pytest.mark.parametrize("text", ["monday", "", "mon,,fri", "xyz", "mon,xyz"])
def test_parse_recurrence_rejects_bad_input(text):
    with pytest.raises(ParseError):
        parse_recurrence(text)


@pytest.mark.parametrize("delta,expected", [
    (timedelta(seconds=30), "in 30s"),
    (timedelta(minutes=9), "in 9m"),
    (timedelta(hours=8, minutes=12), "in 8h 12m"),
    (timedelta(days=2, hours=3), "in 2d 3h"),
    (timedelta(seconds=-5), "now"),
])
def test_format_countdown(delta, expected):
    assert format_countdown(delta) == expected
