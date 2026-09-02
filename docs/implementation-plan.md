# alarmclock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A command-line alarm clock that stores multiple described, optionally recurring alarms and rings them from a foreground watcher with snooze and dismiss.

**Architecture:** A stdlib-only Python package. All calendar math lives in one pure function, `schedule.next_occurrence`, which never reads the clock. The watcher loop depends on two injected seams — a `Clock` and a `Ringer` — so every scheduling behaviour is tested instantly with a fake clock rather than by waiting. Persistence is a JSON file mutated only inside a locked read-modify-write transaction.

**Tech Stack:** Python 3.9, argparse, dataclasses, json, fcntl, termios, subprocess. pytest is the only development dependency.

**Spec:** `docs/design.md`

## Global Constraints

- Target Python 3.9. No `X | Y` annotations evaluated at runtime, no `match` statements, no builtin generics in annotations — use `typing.Optional`, `typing.List`, `typing.Dict`.
- Zero third-party runtime dependencies. pytest is dev-only.
- All datetimes are naive local time. Never call `datetime.utcnow()` or attach a tzinfo.
- Times are stored as `"HH:MM:SS"` and dates as `"YYYY-MM-DD"`. ISO datetimes are written with `to_iso` (microseconds stripped) and read with `from_iso`.
- Weekdays are ints with Monday = 0, matching `datetime.weekday()`.
- No module outside `store.py` opens the JSON file. No module outside `ring.py` and `watcher.py` writes to stdout, except `cli.py`.
- The grace window is 5 minutes and the watcher tick ceiling is 30 seconds.
- User errors exit 2 with a message on stderr. Never let a traceback reach the user for bad input.
- Commit after every task.

---

### Task 1: Project scaffold and the Alarm model

**Files:**
- Create: `pyproject.toml`
- Create: `alarmclock/__init__.py`
- Create: `alarmclock/models.py`
- Create: `tests/__init__.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Alarm` dataclass with fields `id: int`, `time: str`, `days: List[int]`, `date: Optional[str]`, `description: str`, `enabled: bool`, `sound: Optional[str]`, `snooze_minutes: int`, `snoozed_until: Optional[str]`, `last_fired: Optional[str]`, `outcome: Optional[str]`, `created_at: str`; property `is_one_off: bool`; methods `to_dict() -> Dict`, `from_dict(data: Dict) -> Alarm` (classmethod), `recurrence_label() -> str`, `clock_time() -> datetime.time`, `one_off_datetime() -> Optional[datetime]`. Module constants `WEEKDAY_NAMES: List[str]`, `PRESETS: Dict[str, List[int]]`, `OUTCOME_DISMISSED = "dismissed"`, `OUTCOME_MISSED = "missed"`. Module functions `to_iso(dt) -> str`, `from_iso(s) -> datetime`.

- [ ] **Step 1: Create the project scaffold**

`pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "alarmclock"
version = "0.1.0"
description = "A command-line alarm clock"
requires-python = ">=3.9"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=7"]

[project.scripts]
alarm = "alarmclock.cli:main"

[tool.setuptools]
packages = ["alarmclock"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Then create the empty files `alarmclock/__init__.py` and `tests/__init__.py`.

- [ ] **Step 2: Write the failing test**

`tests/test_models.py`:

```python
from datetime import datetime

from alarmclock.models import Alarm, from_iso, to_iso


def make(**kwargs):
    defaults = dict(id=1, time="07:00:00", days=[0, 1, 2, 3, 4], date=None,
                    description="Standup", created_at="2026-09-02T20:00:00")
    defaults.update(kwargs)
    return Alarm(**defaults)


def test_round_trips_through_dict():
    alarm = make(sound="Glass", snooze_minutes=5)
    assert Alarm.from_dict(alarm.to_dict()) == alarm


def test_from_dict_fills_defaults_for_absent_optional_fields():
    alarm = Alarm.from_dict({"id": 3, "time": "08:30:00", "days": [], "date": "2026-09-03"})
    assert alarm.enabled is True
    assert alarm.description == ""
    assert alarm.snooze_minutes == 9
    assert alarm.snoozed_until is None
    assert alarm.last_fired is None
    assert alarm.outcome is None


def test_one_off_is_identified_by_empty_days():
    assert make(days=[], date="2026-09-03").is_one_off is True
    assert make().is_one_off is False


def test_recurrence_label_names_presets_and_lists_other_days():
    assert make(days=[], date="2026-09-03").recurrence_label() == "once"
    assert make(days=[0, 1, 2, 3, 4, 5, 6]).recurrence_label() == "daily"
    assert make(days=[0, 1, 2, 3, 4]).recurrence_label() == "weekdays"
    assert make(days=[5, 6]).recurrence_label() == "weekends"
    assert make(days=[0, 2, 4]).recurrence_label() == "mon,wed,fri"


def test_one_off_datetime_combines_date_and_time():
    alarm = make(days=[], date="2026-09-03", time="07:15:00")
    assert alarm.one_off_datetime() == datetime(2026, 9, 3, 7, 15)
    assert make().one_off_datetime() is None


def test_iso_helpers_drop_microseconds_and_round_trip():
    dt = datetime(2026, 9, 2, 20, 30, 15, 123456)
    assert to_iso(dt) == "2026-09-02T20:30:15"
    assert from_iso(to_iso(dt)) == datetime(2026, 9, 2, 20, 30, 15)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'alarmclock.models'`

- [ ] **Step 4: Write the implementation**

`alarmclock/models.py`:

```python
"""The Alarm record and its serialisation."""

from dataclasses import dataclass, field
from datetime import datetime, time as dt_time
from typing import Dict, List, Optional

WEEKDAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

PRESETS = {
    "daily": [0, 1, 2, 3, 4, 5, 6],
    "weekdays": [0, 1, 2, 3, 4],
    "weekends": [5, 6],
}

OUTCOME_DISMISSED = "dismissed"
OUTCOME_MISSED = "missed"

TIME_FORMAT = "%H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"


def to_iso(dt: datetime) -> str:
    """Serialise a datetime without microseconds, so stored values compare cleanly."""
    return dt.replace(microsecond=0).isoformat()


def from_iso(text: str) -> datetime:
    return datetime.fromisoformat(text)


@dataclass
class Alarm:
    id: int
    time: str
    days: List[int] = field(default_factory=list)
    date: Optional[str] = None
    description: str = ""
    enabled: bool = True
    sound: Optional[str] = None
    snooze_minutes: int = 9
    snoozed_until: Optional[str] = None
    last_fired: Optional[str] = None
    outcome: Optional[str] = None
    created_at: str = ""

    @property
    def is_one_off(self) -> bool:
        return not self.days

    def clock_time(self) -> dt_time:
        return datetime.strptime(self.time, TIME_FORMAT).time()

    def one_off_datetime(self) -> Optional[datetime]:
        """The single moment a one-off alarm is scheduled for, or None if recurring."""
        if not self.is_one_off or self.date is None:
            return None
        day = datetime.strptime(self.date, DATE_FORMAT).date()
        return datetime.combine(day, self.clock_time())

    def recurrence_label(self) -> str:
        if self.is_one_off:
            return "once"
        for name, days in PRESETS.items():
            if sorted(self.days) == days:
                return name
        return ",".join(WEEKDAY_NAMES[d] for d in sorted(self.days))

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "time": self.time,
            "days": list(self.days),
            "date": self.date,
            "description": self.description,
            "enabled": self.enabled,
            "sound": self.sound,
            "snooze_minutes": self.snooze_minutes,
            "snoozed_until": self.snoozed_until,
            "last_fired": self.last_fired,
            "outcome": self.outcome,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Alarm":
        return cls(
            id=data["id"],
            time=data["time"],
            days=list(data.get("days") or []),
            date=data.get("date"),
            description=data.get("description", ""),
            enabled=data.get("enabled", True),
            sound=data.get("sound"),
            snooze_minutes=data.get("snooze_minutes", 9),
            snoozed_until=data.get("snoozed_until"),
            last_fired=data.get("last_fired"),
            outcome=data.get("outcome"),
            created_at=data.get("created_at", ""),
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_models.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml alarmclock tests
git commit -m "Add project scaffold and Alarm model"
```

---

### Task 2: Input parsing

**Files:**
- Create: `alarmclock/parsing.py`
- Test: `tests/test_parsing.py`

**Interfaces:**
- Consumes: `alarmclock.models.PRESETS`, `alarmclock.models.WEEKDAY_NAMES`.
- Produces: `ParseError(ValueError)`; `parse_time(text: str) -> datetime.time`; `parse_duration(text: str) -> datetime.timedelta`; `parse_recurrence(text: str) -> List[int]`; `format_countdown(delta: timedelta) -> str`.

- [ ] **Step 1: Write the failing test**

`tests/test_parsing.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_parsing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'alarmclock.parsing'`

- [ ] **Step 3: Write the implementation**

`alarmclock/parsing.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_parsing.py -v`
Expected: PASS, 32 tests.

- [ ] **Step 5: Commit**

```bash
git add alarmclock/parsing.py tests/test_parsing.py
git commit -m "Add time, duration and recurrence parsing"
```

---

### Task 3: The scheduling function

**Files:**
- Create: `alarmclock/schedule.py`
- Test: `tests/test_schedule.py`

**Interfaces:**
- Consumes: `alarmclock.models.Alarm`.
- Produces: `next_occurrence(alarm: Alarm, after: datetime) -> Optional[datetime]`; constant `SCAN_DAYS = 8`.

This is the heart of the tool. It reads no clock and touches no disk — the caller supplies `after`, which is what lets the watcher ask "what have I not handled yet" and the listing ask "what is coming up" using the same function.

- [ ] **Step 1: Write the failing test**

`tests/test_schedule.py`:

```python
from datetime import datetime

from alarmclock.models import Alarm
from alarmclock.schedule import next_occurrence

# 2026-09-02 is a Wednesday.
WED_NOON = datetime(2026, 9, 2, 12, 0)


def recurring(days, time="07:00:00", **kwargs):
    return Alarm(id=1, time=time, days=days, **kwargs)


def one_off(date, time="07:00:00", **kwargs):
    return Alarm(id=1, time=time, days=[], date=date, **kwargs)


def test_disabled_alarm_never_occurs():
    assert next_occurrence(recurring([0, 1, 2, 3, 4], enabled=False), WED_NOON) is None


def test_one_off_ahead_returns_its_moment():
    alarm = one_off("2026-09-03")
    assert next_occurrence(alarm, WED_NOON) == datetime(2026, 9, 3, 7, 0)


def test_one_off_behind_returns_none():
    alarm = one_off("2026-09-01")
    assert next_occurrence(alarm, WED_NOON) is None


def test_recurring_returns_today_when_time_is_still_ahead():
    alarm = recurring([0, 1, 2, 3, 4], time="18:00:00")
    assert next_occurrence(alarm, WED_NOON) == datetime(2026, 9, 2, 18, 0)


def test_recurring_rolls_to_tomorrow_when_todays_time_has_passed():
    alarm = recurring([0, 1, 2, 3, 4], time="07:00:00")
    assert next_occurrence(alarm, WED_NOON) == datetime(2026, 9, 3, 7, 0)


def test_weekdays_alarm_skips_the_weekend():
    friday_evening = datetime(2026, 9, 4, 20, 0)
    alarm = recurring([0, 1, 2, 3, 4])
    assert next_occurrence(alarm, friday_evening) == datetime(2026, 9, 7, 7, 0)


def test_sunday_wraps_around_to_monday():
    sunday_evening = datetime(2026, 9, 6, 20, 0)
    alarm = recurring([0])
    assert next_occurrence(alarm, sunday_evening) == datetime(2026, 9, 7, 7, 0)


def test_weekly_alarm_returns_the_same_weekday_next_week():
    alarm = recurring([2], time="07:00:00")  # Wednesdays
    assert next_occurrence(alarm, WED_NOON) == datetime(2026, 9, 9, 7, 0)


def test_exact_boundary_returns_the_following_occurrence_not_the_same_one():
    alarm = recurring([0, 1, 2, 3, 4, 5, 6], time="07:00:00")
    exactly_on_it = datetime(2026, 9, 2, 7, 0)
    assert next_occurrence(alarm, exactly_on_it) == datetime(2026, 9, 3, 7, 0)


def test_watcher_style_call_with_an_old_after_returns_a_past_occurrence():
    """Passing last_fired as `after` surfaces occurrences the watcher has not handled."""
    alarm = recurring([0, 1, 2, 3, 4, 5, 6], time="07:00:00")
    assert next_occurrence(alarm, datetime(2026, 9, 1, 12, 0)) == datetime(2026, 9, 2, 7, 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_schedule.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'alarmclock.schedule'`

- [ ] **Step 3: Write the implementation**

`alarmclock/schedule.py`:

```python
"""Pure calendar arithmetic. No clock, no disk."""

from datetime import datetime, timedelta
from typing import Optional

from .models import Alarm

# Seven would suffice to find any weekday, but scanning from `after`'s own date
# means today may already be spent, so an eighth day is needed to wrap around.
SCAN_DAYS = 8


def next_occurrence(alarm: Alarm, after: datetime) -> Optional[datetime]:
    """The first moment this alarm is scheduled for, strictly after `after`.

    Returns None when the alarm is disabled, or when a one-off's single moment
    is already behind `after`.
    """
    if not alarm.enabled:
        return None

    if alarm.is_one_off:
        moment = alarm.one_off_datetime()
        if moment is None or moment <= after:
            return None
        return moment

    wanted = set(alarm.days)
    clock_time = alarm.clock_time()
    for offset in range(SCAN_DAYS):
        day = after.date() + timedelta(days=offset)
        if day.weekday() not in wanted:
            continue
        moment = datetime.combine(day, clock_time)
        if moment > after:
            return moment
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_schedule.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add alarmclock/schedule.py tests/test_schedule.py
git commit -m "Add next_occurrence scheduling function"
```

---

### Task 4: Persistence

**Files:**
- Create: `alarmclock/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `alarmclock.models.Alarm`.
- Produces: `default_store_dir() -> Path`; `StoreData` dataclass with `alarms: List[Alarm]` and `next_id: int`; `Store` class with `__init__(self, directory)`, attributes `path` and `lock_path`, methods `read() -> StoreData` and `transaction()` (a context manager yielding a `StoreData` that is written back on clean exit); constant `SCHEMA_VERSION = 1`.

Ringing must never happen inside a transaction — the lock would block `alarm add` from another terminal for as long as the alarm rings. The watcher reads outside the lock, rings, then opens a short transaction to record the result.

- [ ] **Step 1: Write the failing test**

`tests/test_store.py`:

```python
import json

import pytest

from alarmclock.models import Alarm
from alarmclock.store import SCHEMA_VERSION, Store, default_store_dir


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path)


def test_reading_a_missing_file_gives_an_empty_store(store):
    data = store.read()
    assert data.alarms == []
    assert data.next_id == 1


def test_transaction_writes_and_round_trips(store):
    with store.transaction() as data:
        data.alarms.append(Alarm(id=data.next_id, time="07:00:00", days=[0, 1, 2, 3, 4]))
        data.next_id += 1

    reloaded = store.read()
    assert len(reloaded.alarms) == 1
    assert reloaded.alarms[0].time == "07:00:00"
    assert reloaded.next_id == 2


def test_transaction_does_not_write_when_the_body_raises(store):
    with pytest.raises(RuntimeError):
        with store.transaction() as data:
            data.alarms.append(Alarm(id=1, time="07:00:00", days=[0]))
            raise RuntimeError("boom")
    assert store.read().alarms == []


def test_ids_are_not_reused_after_deletion(store):
    with store.transaction() as data:
        for _ in range(2):
            data.alarms.append(Alarm(id=data.next_id, time="07:00:00", days=[0]))
            data.next_id += 1
    with store.transaction() as data:
        data.alarms.clear()
    with store.transaction() as data:
        data.alarms.append(Alarm(id=data.next_id, time="08:00:00", days=[0]))
        data.next_id += 1
    assert store.read().alarms[0].id == 3


def test_written_file_carries_a_schema_version(store, tmp_path):
    with store.transaction() as data:
        data.alarms.append(Alarm(id=1, time="07:00:00", days=[0]))
        data.next_id = 2
    raw = json.loads((tmp_path / "alarms.json").read_text())
    assert raw["version"] == SCHEMA_VERSION


def test_a_corrupt_file_is_quarantined_and_the_store_stays_usable(store, tmp_path, capsys):
    store.path.write_text("{ this is not json")
    data = store.read()
    assert data.alarms == []
    quarantined = list(tmp_path.glob("alarms.json.corrupt-*"))
    assert len(quarantined) == 1
    assert "corrupt" in capsys.readouterr().err.lower()


def test_default_store_dir_honours_the_override(monkeypatch, tmp_path):
    monkeypatch.setenv("ALARM_CLOCK_HOME", str(tmp_path / "custom"))
    assert default_store_dir() == tmp_path / "custom"


def test_default_store_dir_falls_back_to_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("ALARM_CLOCK_HOME", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert default_store_dir() == tmp_path / "xdg" / "alarmclock"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'alarmclock.store'`

- [ ] **Step 3: Write the implementation**

`alarmclock/store.py`:

```python
"""The JSON store. The only module that touches the alarms file."""

import fcntl
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator, List

from .models import Alarm

SCHEMA_VERSION = 1
FILENAME = "alarms.json"
LOCK_FILENAME = ".alarms.lock"


def default_store_dir() -> Path:
    override = os.environ.get("ALARM_CLOCK_HOME")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "alarmclock"
    return Path.home() / ".config" / "alarmclock"


@dataclass
class StoreData:
    alarms: List[Alarm] = field(default_factory=list)
    next_id: int = 1


class Store:
    def __init__(self, directory) -> None:
        self.directory = Path(directory)
        self.path = self.directory / FILENAME
        self.lock_path = self.directory / LOCK_FILENAME

    def read(self) -> StoreData:
        """Load the store, tolerating a missing or damaged file."""
        if not self.path.exists():
            return StoreData()
        try:
            raw = json.loads(self.path.read_text())
            alarms = [Alarm.from_dict(item) for item in raw.get("alarms", [])]
            return StoreData(alarms=alarms, next_id=raw.get("next_id", 1))
        except (ValueError, KeyError, TypeError) as error:
            self._quarantine(error)
            return StoreData()

    @contextmanager
    def transaction(self) -> Iterator[StoreData]:
        """Read-modify-write under an exclusive lock.

        Keep the body short: the lock blocks other commands. Never ring inside one.
        """
        self.directory.mkdir(parents=True, exist_ok=True)
        with open(str(self.lock_path), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                data = self.read()
                yield data
                self._write(data)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _write(self, data: StoreData) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": SCHEMA_VERSION,
            "next_id": data.next_id,
            "alarms": [alarm.to_dict() for alarm in data.alarms],
        }
        # Write to a sibling temp file then rename, so a reader never sees a
        # half-written store.
        handle, temp_name = tempfile.mkstemp(dir=str(self.directory), suffix=".tmp")
        try:
            with os.fdopen(handle, "w") as out:
                json.dump(payload, out, indent=2)
                out.write("\n")
            os.replace(temp_name, str(self.path))
        except BaseException:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
            raise

    def _quarantine(self, error) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.directory / "{}.corrupt-{}".format(FILENAME, stamp)
        os.replace(str(self.path), str(target))
        print(
            "warning: alarms file was corrupt ({}); moved to {} and started "
            "fresh".format(error, target),
            file=sys.stderr,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_store.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add alarmclock/store.py tests/test_store.py
git commit -m "Add locked, atomic JSON store"
```

---

### Task 5: The clock and ringer seams

**Files:**
- Create: `alarmclock/clock.py`
- Create: `alarmclock/ring.py`
- Create: `tests/conftest.py`
- Test: `tests/test_ring.py`

**Interfaces:**
- Consumes: `alarmclock.models.Alarm`.
- Produces: `clock.Clock` (base with `now() -> datetime` and `sleep(seconds: float) -> None`), `clock.RealClock`; `ring.SNOOZE = "snooze"`, `ring.DISMISS = "dismiss"`, `ring.TIMEOUT = "timeout"`, `ring.Ringer` (base with `ring(alarm: Alarm) -> str`), `ring.ConsoleRinger(sound_dir=None, timeout_seconds=300)`; test fixtures `FakeClock` and `FakeRinger` in `tests/conftest.py`.

- [ ] **Step 1: Write the failing test**

`tests/conftest.py`:

```python
from datetime import datetime, timedelta

from alarmclock import ring


class FakeClock:
    """A clock that jumps forward instead of waiting, so tests run instantly."""

    def __init__(self, start: datetime):
        self._now = start

    def now(self) -> datetime:
        return self._now

    def sleep(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)

    def advance(self, **kwargs) -> None:
        self._now += timedelta(**kwargs)


class FakeRinger:
    """Records what was rung and replays scripted answers."""

    def __init__(self, answers=None):
        self.rung = []
        self.answers = list(answers or [])

    def ring(self, alarm):
        self.rung.append(alarm.id)
        if self.answers:
            return self.answers.pop(0)
        return ring.DISMISS
```

`tests/test_ring.py`:

```python
import io

from alarmclock import ring
from alarmclock.models import Alarm


def make_alarm(**kwargs):
    defaults = dict(id=1, time="07:00:00", days=[0], description="Standup")
    defaults.update(kwargs)
    return Alarm(**defaults)


def test_reads_dismiss_from_non_tty_stdin(monkeypatch, capsys):
    ringer = ring.ConsoleRinger()
    monkeypatch.setattr(ring.sys, "stdin", io.StringIO("d\n"))
    monkeypatch.setattr(ringer, "_play_sound", lambda alarm: None)
    monkeypatch.setattr(ringer, "_speak", lambda alarm: None)

    assert ringer.ring(make_alarm()) == ring.DISMISS
    assert "Standup" in capsys.readouterr().out


def test_reads_snooze_from_non_tty_stdin(monkeypatch):
    ringer = ring.ConsoleRinger()
    monkeypatch.setattr(ring.sys, "stdin", io.StringIO("s\n"))
    monkeypatch.setattr(ringer, "_play_sound", lambda alarm: None)
    monkeypatch.setattr(ringer, "_speak", lambda alarm: None)

    assert ringer.ring(make_alarm()) == ring.SNOOZE


def test_closed_stdin_times_out_rather_than_hanging(monkeypatch):
    ringer = ring.ConsoleRinger(timeout_seconds=1)
    monkeypatch.setattr(ring.sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(ringer, "_play_sound", lambda alarm: None)
    monkeypatch.setattr(ringer, "_speak", lambda alarm: None)

    assert ringer.ring(make_alarm()) == ring.TIMEOUT


def test_a_missing_player_binary_degrades_to_the_terminal_bell(monkeypatch, capsys):
    ringer = ring.ConsoleRinger()
    monkeypatch.setattr(ring.shutil, "which", lambda name: None)
    ringer._play_sound(make_alarm())
    assert "\a" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_ring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'alarmclock.ring'`

- [ ] **Step 3: Write the implementation**

`alarmclock/clock.py`:

```python
"""The time seam. Injected everywhere so tests never wait."""

import time as time_module
from datetime import datetime


class Clock:
    def now(self) -> datetime:
        raise NotImplementedError

    def sleep(self, seconds: float) -> None:
        raise NotImplementedError


class RealClock(Clock):
    def now(self) -> datetime:
        return datetime.now()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time_module.sleep(seconds)
```

`alarmclock/ring.py`:

```python
"""Making noise and asking the user what to do about it."""

import os
import select
import shutil
import subprocess
import sys
import termios
import time as time_module
import tty
from typing import Optional

from .models import Alarm

SNOOZE = "snooze"
DISMISS = "dismiss"
TIMEOUT = "timeout"

MACOS_SOUND_DIR = "/System/Library/Sounds"
DEFAULT_SOUND = "Submarine"
DEFAULT_TIMEOUT_SECONDS = 300


class Ringer:
    def ring(self, alarm: Alarm) -> str:
        """Ring, then return SNOOZE, DISMISS or TIMEOUT."""
        raise NotImplementedError


class ConsoleRinger(Ringer):
    def __init__(self, sound_dir: Optional[str] = None,
                 timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.sound_dir = sound_dir or MACOS_SOUND_DIR
        self.timeout_seconds = timeout_seconds

    def ring(self, alarm: Alarm) -> str:
        self._banner(alarm)
        self._speak(alarm)
        deadline = time_module.monotonic() + self.timeout_seconds
        while time_module.monotonic() < deadline:
            self._play_sound(alarm)
            answer = self._read_key(timeout=1.0)
            if answer in (SNOOZE, DISMISS):
                print("  snoozing for {} minutes".format(alarm.snooze_minutes)
                      if answer == SNOOZE else "  dismissed")
                return answer
        print("  no answer; marked as missed")
        return TIMEOUT

    def _banner(self, alarm: Alarm) -> None:
        print("")
        print("=" * 48)
        print("  ALARM  {}".format(alarm.time[:5]))
        if alarm.description:
            print("  {}".format(alarm.description))
        print("=" * 48)
        print("  [s] snooze {}m    [d] dismiss".format(alarm.snooze_minutes))

    def _speak(self, alarm: Alarm) -> None:
        if not alarm.description:
            return
        for binary in ("say", "spd-say"):
            if shutil.which(binary):
                self._spawn([binary, alarm.description])
                return

    def _play_sound(self, alarm: Alarm) -> None:
        name = alarm.sound or DEFAULT_SOUND
        path = os.path.join(self.sound_dir, name + ".aiff")
        if shutil.which("afplay") and os.path.exists(path):
            self._spawn(["afplay", path])
            return
        for binary in ("paplay", "aplay"):
            if shutil.which(binary) and os.path.exists(path):
                self._spawn([binary, path])
                return
        # Nothing to play with: the terminal bell is better than silence.
        sys.stdout.write("\a")
        sys.stdout.flush()

    def _spawn(self, command) -> None:
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except OSError:
            pass

    def _read_key(self, timeout: float) -> Optional[str]:
        stdin = sys.stdin
        try:
            is_tty = stdin.isatty()
        except (AttributeError, ValueError):
            is_tty = False

        if not is_tty:
            line = stdin.readline()
            if not line:
                # Closed or exhausted stdin: burn the remaining time rather than
                # spinning, so the timeout path is reached.
                time_module.sleep(timeout)
                return None
            return self._interpret(line.strip()[:1])

        settings = termios.tcgetattr(stdin)
        try:
            tty.setcbreak(stdin.fileno())
            ready, _, _ = select.select([stdin], [], [], timeout)
            if not ready:
                return None
            return self._interpret(stdin.read(1))
        finally:
            termios.tcsetattr(stdin, termios.TCSADRAIN, settings)

    def _interpret(self, key: str) -> Optional[str]:
        key = (key or "").lower()
        if key == "s":
            return SNOOZE
        if key == "d":
            return DISMISS
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_ring.py -v`
Expected: PASS, 4 tests, in about a second. The timeout test constructs the ringer with `timeout_seconds=1` so the exhausted-stdin path reaches its deadline after a single one-second slice.

- [ ] **Step 5: Commit**

```bash
git add alarmclock/clock.py alarmclock/ring.py tests/conftest.py tests/test_ring.py
git commit -m "Add clock and ringer seams"
```

---

### Task 6: The watcher loop

**Files:**
- Create: `alarmclock/watcher.py`
- Test: `tests/test_watcher.py`

**Interfaces:**
- Consumes: `store.Store`, `store.StoreData`, `clock.Clock`, `ring.Ringer` and the `ring.SNOOZE`/`DISMISS`/`TIMEOUT` constants, `schedule.next_occurrence`, `models.Alarm`, `models.to_iso`, `models.from_iso`, `models.OUTCOME_DISMISSED`, `models.OUTCOME_MISSED`.
- Produces: `GRACE = timedelta(minutes=5)`; `MAX_TICK_SECONDS = 30.0`; `Watcher(store, clock, ringer, grace=GRACE, max_tick=MAX_TICK_SECONDS)` with `target_for(alarm, now) -> Optional[datetime]`, `tick() -> List[int]` (ids rung), and `run(once=False) -> None`.

An alarm that has never fired has no `last_fired` to scan forward from. The floor is the alarm's `created_at`: occurrences from before the alarm existed were never missed, so they must not be reported. Using `datetime.min` here would make `next_occurrence` scan from the year 1 and return an occurrence two millennia overdue, which the watcher would classify as missed and the alarm would never ring at all.

- [ ] **Step 1: Write the failing test**

`tests/test_watcher.py`:

```python
from datetime import datetime, timedelta

import pytest

from alarmclock import ring
from alarmclock.models import OUTCOME_DISMISSED, OUTCOME_MISSED, Alarm, to_iso
from alarmclock.store import Store
from alarmclock.watcher import Watcher
from tests.conftest import FakeClock, FakeRinger

WED = datetime(2026, 9, 2, 6, 59, 0)  # a Wednesday, one minute before 07:00
CREATED = datetime(2026, 9, 1, 12, 0)  # the day before, so nothing is pre-missed


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path)


def add(store, **kwargs):
    defaults = dict(time="07:00:00", days=[0, 1, 2, 3, 4, 5, 6], description="Standup",
                    created_at=to_iso(CREATED))
    defaults.update(kwargs)
    with store.transaction() as data:
        alarm = Alarm(id=data.next_id, **defaults)
        data.alarms.append(alarm)
        data.next_id += 1
    return alarm.id


def only(store):
    return store.read().alarms[0]


def test_does_not_ring_before_the_alarm_time(store):
    add(store)
    clock, ringer = FakeClock(WED), FakeRinger()
    Watcher(store, clock, ringer).tick()
    assert ringer.rung == []


def test_rings_exactly_once_and_not_again_inside_the_grace_window(store):
    alarm_id = add(store)
    clock = FakeClock(datetime(2026, 9, 2, 7, 0, 0))
    ringer = FakeRinger(answers=[ring.DISMISS])
    watcher = Watcher(store, clock, ringer)

    assert watcher.tick() == [alarm_id]

    # Still inside the 5-minute grace window: it must not ring again.
    clock.advance(seconds=5)
    assert watcher.tick() == []
    clock.advance(minutes=2)
    assert watcher.tick() == []
    assert ringer.rung == [alarm_id]


def test_rings_again_at_the_next_days_occurrence(store):
    alarm_id = add(store)
    clock = FakeClock(datetime(2026, 9, 2, 7, 0, 0))
    ringer = FakeRinger(answers=[ring.DISMISS, ring.DISMISS])
    watcher = Watcher(store, clock, ringer)

    watcher.tick()
    clock.advance(days=1)
    assert watcher.tick() == [alarm_id]
    assert ringer.rung == [alarm_id, alarm_id]


def test_snooze_refires_after_the_interval_and_can_be_repeated(store):
    alarm_id = add(store, snooze_minutes=9)
    clock = FakeClock(datetime(2026, 9, 2, 7, 0, 0))
    ringer = FakeRinger(answers=[ring.SNOOZE, ring.SNOOZE, ring.DISMISS])
    watcher = Watcher(store, clock, ringer)

    watcher.tick()
    assert only(store).snoozed_until == to_iso(datetime(2026, 9, 2, 7, 9))
    assert only(store).last_fired is None  # the occurrence is still open

    clock.advance(minutes=9)
    assert watcher.tick() == [alarm_id]
    clock.advance(minutes=9)
    assert watcher.tick() == [alarm_id]

    assert ringer.rung == [alarm_id] * 3
    assert only(store).snoozed_until is None
    # The answered snooze target is what was handled, not the original 07:00.
    # It is still a scheduled time, never the wall-clock instant of the keypress.
    assert only(store).last_fired == to_iso(datetime(2026, 9, 2, 7, 18))

    # What actually matters: the recurrence is undisturbed and resumes tomorrow.
    clock.advance(minutes=1)  # 07:19, nothing left today
    assert watcher.tick() == []
    clock.advance(days=1, minutes=-19)  # 2026-09-03 07:00:00 exactly
    assert clock.now() == datetime(2026, 9, 3, 7, 0)
    assert watcher.tick() == [alarm_id]


def test_dismissing_a_one_off_disables_it_and_records_the_outcome(store):
    alarm_id = add(store, days=[], date="2026-09-02", description="Tea")
    clock = FakeClock(datetime(2026, 9, 2, 7, 0, 0))
    ringer = FakeRinger(answers=[ring.DISMISS])
    watcher = Watcher(store, clock, ringer)

    assert watcher.tick() == [alarm_id]
    alarm = only(store)
    assert alarm.enabled is False
    assert alarm.outcome == OUTCOME_DISMISSED

    clock.advance(minutes=1)
    assert watcher.tick() == []


def test_an_alarm_missed_beyond_the_grace_window_is_not_rung_but_is_marked_handled(store):
    add(store)
    # The machine was asleep: we wake 20 minutes after the alarm was due.
    clock = FakeClock(datetime(2026, 9, 2, 7, 20, 0))
    ringer = FakeRinger()
    watcher = Watcher(store, clock, ringer)

    assert watcher.tick() == []
    assert ringer.rung == []
    assert only(store).last_fired == to_iso(datetime(2026, 9, 2, 7, 0))
    # Marked handled, so it does not re-trigger on the next tick either.
    assert watcher.tick() == []


def test_a_missed_one_off_records_the_missed_outcome(store):
    add(store, days=[], date="2026-09-02")
    clock = FakeClock(datetime(2026, 9, 2, 7, 20, 0))
    watcher = Watcher(store, clock, FakeRinger())

    watcher.tick()
    alarm = only(store)
    assert alarm.enabled is False
    assert alarm.outcome == OUTCOME_MISSED


def test_a_timed_out_ring_counts_as_missed(store):
    add(store, days=[], date="2026-09-02")
    clock = FakeClock(datetime(2026, 9, 2, 7, 0, 0))
    ringer = FakeRinger(answers=[ring.TIMEOUT])
    Watcher(store, clock, ringer).tick()
    assert only(store).outcome == OUTCOME_MISSED


def test_a_disabled_alarm_never_rings(store):
    add(store, enabled=False)
    clock = FakeClock(datetime(2026, 9, 2, 7, 0, 0))
    ringer = FakeRinger()
    Watcher(store, clock, ringer).tick()
    assert ringer.rung == []


def test_an_alarm_created_after_its_time_today_is_not_reported_as_missed(store):
    """created_at is the floor: an alarm cannot have missed a time it predates."""
    now = datetime(2026, 9, 2, 7, 20, 0)
    add(store, created_at=to_iso(now))
    watcher = Watcher(store, FakeClock(now), FakeRinger())

    assert watcher.tick() == []
    assert only(store).last_fired is None


def test_an_alarm_added_mid_run_is_picked_up_on_the_next_tick(store):
    clock = FakeClock(datetime(2026, 9, 2, 6, 59, 0))
    ringer = FakeRinger(answers=[ring.DISMISS])
    watcher = Watcher(store, clock, ringer)
    assert watcher.tick() == []

    alarm_id = add(store)  # as if typed in another terminal

    clock.advance(minutes=1)
    assert watcher.tick() == [alarm_id]


def test_run_once_performs_a_single_pass_and_returns(store):
    alarm_id = add(store)
    clock = FakeClock(datetime(2026, 9, 2, 7, 0, 0))
    ringer = FakeRinger(answers=[ring.DISMISS])
    Watcher(store, clock, ringer).run(once=True)
    assert ringer.rung == [alarm_id]


def test_sleep_is_capped_at_the_tick_ceiling(store):
    add(store, time="23:00:00")
    start = datetime(2026, 9, 2, 7, 0, 0)
    clock = FakeClock(start)
    watcher = Watcher(store, clock, FakeRinger())
    watcher.sleep_until_next()
    assert clock.now() - start == timedelta(seconds=30)


def test_sleep_stops_short_at_the_next_alarm(store):
    add(store, time="07:00:10")
    start = datetime(2026, 9, 2, 7, 0, 0)
    clock = FakeClock(start)
    watcher = Watcher(store, clock, FakeRinger())
    watcher.sleep_until_next()
    assert clock.now() - start == timedelta(seconds=10)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_watcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'alarmclock.watcher'`

- [ ] **Step 3: Write the implementation**

`alarmclock/watcher.py`:

```python
"""The run loop: decide what is due, ring it, record the result."""

from datetime import datetime, timedelta
from typing import List, Optional

from . import ring as ring_module
from .models import (OUTCOME_DISMISSED, OUTCOME_MISSED, Alarm, from_iso,
                     to_iso)
from .schedule import next_occurrence

GRACE = timedelta(minutes=5)
MAX_TICK_SECONDS = 30.0


class Watcher:
    def __init__(self, store, clock, ringer, grace: timedelta = GRACE,
                 max_tick: float = MAX_TICK_SECONDS) -> None:
        self.store = store
        self.clock = clock
        self.ringer = ringer
        self.grace = grace
        self.max_tick = max_tick

    def target_for(self, alarm: Alarm, now: datetime) -> Optional[datetime]:
        """The moment this alarm is waiting on, or None if it is waiting on nothing.

        A snooze overrides the schedule without disturbing it. Otherwise the
        target is the earliest occurrence not yet marked handled -- scanned
        forward from last_fired, or from created_at for an alarm that has never
        fired, so that occurrences predating the alarm are never reported.
        """
        if not alarm.enabled:
            return None
        if alarm.snoozed_until:
            return from_iso(alarm.snoozed_until)
        floor = alarm.last_fired or alarm.created_at
        # A record with no created_at (hand-edited) still must not scan from
        # the year 1, so fall back to the edge of the grace window.
        after = from_iso(floor) if floor else now - self.grace
        return next_occurrence(alarm, after)

    def tick(self) -> List[int]:
        """One pass. Returns the ids of alarms that actually rang."""
        now = self.clock.now()
        data = self.store.read()

        due = []
        missed = []
        for alarm in data.alarms:
            target = self.target_for(alarm, now)
            if target is None or target > now:
                continue
            if now - target <= self.grace:
                due.append((target, alarm))
            else:
                missed.append((target, alarm))

        for target, alarm in missed:
            self._settle(alarm.id, target, OUTCOME_MISSED)

        rung = []
        # Ringing happens outside any transaction: it can take minutes, and the
        # store lock must not be held while another terminal wants to add.
        for target, alarm in sorted(due, key=lambda pair: pair[0]):
            answer = self.ringer.ring(alarm)
            if answer == ring_module.SNOOZE:
                self._snooze(alarm.id, now)
            elif answer == ring_module.DISMISS:
                self._settle(alarm.id, target, OUTCOME_DISMISSED)
            else:
                self._settle(alarm.id, target, OUTCOME_MISSED)
            rung.append(alarm.id)
        return rung

    def sleep_until_next(self) -> None:
        now = self.clock.now()
        targets = [t for t in (self.target_for(a, now) for a in self.store.read().alarms)
                   if t is not None and t > now]
        seconds = self.max_tick
        if targets:
            seconds = min(seconds, max(0.0, (min(targets) - now).total_seconds()))
        self.clock.sleep(seconds)

    def run(self, once: bool = False) -> None:
        while True:
            self.tick()
            if once:
                return
            self.sleep_until_next()

    def _snooze(self, alarm_id: int, now: datetime) -> None:
        with self.store.transaction() as data:
            alarm = self._find(data, alarm_id)
            if alarm is None:
                return
            alarm.snoozed_until = to_iso(now + timedelta(minutes=alarm.snooze_minutes))

    def _settle(self, alarm_id: int, target: datetime, outcome: str) -> None:
        """Mark an occurrence handled so it can never ring twice."""
        with self.store.transaction() as data:
            alarm = self._find(data, alarm_id)
            if alarm is None:
                return
            alarm.snoozed_until = None
            alarm.last_fired = to_iso(target)
            if alarm.is_one_off:
                alarm.enabled = False
                alarm.outcome = outcome

    @staticmethod
    def _find(data, alarm_id: int) -> Optional[Alarm]:
        for alarm in data.alarms:
            if alarm.id == alarm_id:
                return alarm
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_watcher.py -v`
Expected: PASS, 14 tests.

- [ ] **Step 5: Run the whole suite**

Run: `python3 -m pytest -v`
Expected: PASS, all tests from tasks 1-6.

- [ ] **Step 6: Commit**

```bash
git add alarmclock/watcher.py tests/test_watcher.py
git commit -m "Add watcher loop with grace window and snooze"
```

---

### Task 7: The command-line interface

**Files:**
- Create: `alarmclock/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything from tasks 1-6.
- Produces: `UserError(Exception)`; `build_parser() -> argparse.ArgumentParser`; `main(argv=None) -> int`; `state_of(alarm) -> str`.

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:

```python
import json

import pytest

from alarmclock.cli import main
from alarmclock.store import Store


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("ALARM_CLOCK_HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return tmp_path


def alarms(home):
    return Store(home).read().alarms


def test_add_creates_a_recurring_alarm(home, capsys):
    assert main(["add", "07:00", "-d", "Standup", "-r", "weekdays"]) == 0
    alarm = alarms(home)[0]
    assert alarm.id == 1
    assert alarm.time == "07:00:00"
    assert alarm.days == [0, 1, 2, 3, 4]
    assert alarm.description == "Standup"
    assert "Standup" in capsys.readouterr().out


def test_add_defaults_to_a_one_off_with_a_concrete_date(home):
    assert main(["add", "7am"]) == 0
    alarm = alarms(home)[0]
    assert alarm.days == []
    assert alarm.date is not None
    assert alarm.one_off_datetime() is not None


def test_add_accepts_sound_and_snooze_overrides(home):
    main(["add", "07:00", "--sound", "Glass", "--snooze", "5"])
    alarm = alarms(home)[0]
    assert alarm.sound == "Glass"
    assert alarm.snooze_minutes == 5


def test_add_rejects_a_bad_time_with_exit_code_2(home, capsys):
    assert main(["add", "25:00"]) == 2
    assert "not a valid time" in capsys.readouterr().err
    assert alarms(home) == []


def test_add_rejects_a_bad_recurrence_with_exit_code_2(home, capsys):
    assert main(["add", "07:00", "-r", "monday"]) == 2
    assert "not a valid recurrence" in capsys.readouterr().err


def test_in_creates_a_one_off_at_now_plus_duration(home):
    from datetime import datetime
    before = datetime.now()
    assert main(["in", "20m", "-d", "Tea"]) == 0
    alarm = alarms(home)[0]
    delta = alarm.one_off_datetime() - before
    assert 19 * 60 <= delta.total_seconds() <= 21 * 60
    assert alarm.description == "Tea"


def test_list_shows_alarms_with_a_countdown(home, capsys):
    main(["add", "07:00", "-d", "Standup", "-r", "daily"])
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "Standup" in out
    assert "daily" in out
    assert "in " in out


def test_list_hides_disabled_alarms_unless_all_is_given(home, capsys):
    main(["add", "07:00", "-d", "Standup", "-r", "daily"])
    main(["disable", "1"])
    capsys.readouterr()

    main(["list"])
    assert "Standup" not in capsys.readouterr().out

    main(["list", "--all"])
    out = capsys.readouterr().out
    assert "Standup" in out
    assert "off" in out


def test_list_is_friendly_when_empty(home, capsys):
    assert main(["list"]) == 0
    assert "no alarms" in capsys.readouterr().out.lower()


def test_disable_and_enable_toggle_without_deleting(home):
    main(["add", "07:00", "-r", "daily"])
    main(["disable", "1"])
    assert alarms(home)[0].enabled is False
    main(["enable", "1"])
    assert alarms(home)[0].enabled is True


def test_enable_clears_a_previous_outcome(home):
    main(["add", "07:00", "-r", "daily"])
    store = Store(home)
    with store.transaction() as data:
        data.alarms[0].enabled = False
        data.alarms[0].outcome = "dismissed"
    main(["enable", "1"])
    assert alarms(home)[0].outcome is None


def test_rm_deletes_the_named_alarms(home):
    main(["add", "07:00", "-r", "daily"])
    main(["add", "08:00", "-r", "daily"])
    assert main(["rm", "1"]) == 0
    assert [a.id for a in alarms(home)] == [2]


def test_rm_reports_an_unknown_id_with_exit_code_2(home, capsys):
    assert main(["rm", "99"]) == 2
    assert "99" in capsys.readouterr().err


def test_clean_removes_finished_one_offs_but_keeps_hand_disabled_alarms(home):
    main(["add", "07:00"])              # one-off, id 1
    main(["add", "08:00", "-r", "daily"])  # recurring, id 2
    store = Store(home)
    with store.transaction() as data:
        data.alarms[0].enabled = False
        data.alarms[0].outcome = "dismissed"
        data.alarms[1].enabled = False   # disabled by hand, no outcome
    assert main(["clean"]) == 0
    assert [a.id for a in alarms(home)] == [2]


def test_run_once_exits_without_hanging(home):
    assert main(["run", "--once"]) == 0


def test_ids_survive_a_reload(home):
    main(["add", "07:00", "-r", "daily"])
    main(["rm", "1"])
    main(["add", "08:00", "-r", "daily"])
    assert alarms(home)[0].id == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'alarmclock.cli'`

- [ ] **Step 3: Write the implementation**

`alarmclock/cli.py`:

```python
"""The argparse front end."""

import argparse
import sys
from datetime import datetime, timedelta
from typing import List, Optional

from . import parsing
from .clock import RealClock
from .models import OUTCOME_DISMISSED, OUTCOME_MISSED, Alarm, from_iso, to_iso
from .ring import ConsoleRinger
from .schedule import next_occurrence
from .store import Store, default_store_dir
from .watcher import Watcher


class UserError(Exception):
    """Something the user got wrong. Reported on stderr with exit code 2."""


def state_of(alarm: Alarm) -> str:
    if alarm.enabled:
        return "on"
    if alarm.outcome == OUTCOME_DISMISSED:
        return "done"
    if alarm.outcome == OUTCOME_MISSED:
        return "missed"
    return "off"


def _resolve_one_off_date(clock_time, now: datetime) -> str:
    """Pin a one-off to a real date: today if the time is still ahead, else tomorrow."""
    moment = datetime.combine(now.date(), clock_time)
    if moment <= now:
        moment += timedelta(days=1)
    return moment.date().isoformat()


def _append(store, **fields) -> Alarm:
    with store.transaction() as data:
        alarm = Alarm(id=data.next_id, created_at=to_iso(datetime.now()), **fields)
        data.alarms.append(alarm)
        data.next_id += 1
    return alarm


def _describe(alarm: Alarm) -> str:
    parts = ["alarm {}".format(alarm.id), alarm.time[:5], alarm.recurrence_label()]
    if alarm.description:
        parts.append("- {}".format(alarm.description))
    return " ".join(parts)


def cmd_add(args, store) -> int:
    clock_time = parsing.parse_time(args.time)
    days = parsing.parse_recurrence(args.recurrence)
    date = None if days else _resolve_one_off_date(clock_time, datetime.now())
    alarm = _append(store, time=clock_time.strftime("%H:%M:%S"), days=days, date=date,
                    description=args.description, sound=args.sound,
                    snooze_minutes=args.snooze)
    print("Added {}".format(_describe(alarm)))
    return 0


def cmd_in(args, store) -> int:
    moment = (datetime.now() + parsing.parse_duration(args.duration)).replace(microsecond=0)
    alarm = _append(store, time=moment.strftime("%H:%M:%S"), days=[],
                    date=moment.date().isoformat(), description=args.description,
                    sound=args.sound, snooze_minutes=args.snooze)
    print("Added {} ({})".format(
        _describe(alarm), parsing.format_countdown(moment - datetime.now())))
    return 0


def cmd_list(args, store) -> int:
    now = datetime.now()
    rows = []
    for alarm in sorted(store.read().alarms, key=lambda a: (a.time, a.id)):
        if not alarm.enabled and not args.all:
            continue
        after = now
        if alarm.last_fired:
            after = max(after, from_iso(alarm.last_fired))
        upcoming = next_occurrence(alarm, after)
        when = "-"
        if upcoming is not None:
            when = "{} ({})".format(upcoming.strftime("%a %H:%M"),
                                    parsing.format_countdown(upcoming - now))
        rows.append((str(alarm.id), alarm.time[:5], alarm.recurrence_label(),
                     state_of(alarm), when, alarm.description))

    if not rows:
        print("No alarms. Add one with: alarm add 07:00 -d \"Wake up\" -r weekdays")
        return 0

    headers = ("ID", "TIME", "REPEATS", "STATE", "NEXT", "DESCRIPTION")
    widths = [max(len(row[i]) for row in ((headers,) + tuple(rows)))
              for i in range(len(headers))]
    template = "  ".join("{:<" + str(width) + "}" for width in widths)
    print(template.format(*headers).rstrip())
    for row in rows:
        print(template.format(*row).rstrip())
    return 0


def _apply_to_ids(store, ids: List[int], action) -> None:
    with store.transaction() as data:
        known = {alarm.id: alarm for alarm in data.alarms}
        unknown = [str(i) for i in ids if i not in known]
        if unknown:
            raise UserError("no alarm with id {}".format(", ".join(unknown)))
        action(data, [known[i] for i in ids])


def cmd_rm(args, store) -> int:
    def action(data, targets):
        doomed = {alarm.id for alarm in targets}
        data.alarms[:] = [a for a in data.alarms if a.id not in doomed]

    _apply_to_ids(store, args.ids, action)
    print("Removed {} alarm(s)".format(len(args.ids)))
    return 0


def cmd_enable(args, store) -> int:
    def action(data, targets):
        for alarm in targets:
            alarm.enabled = True
            # A re-enabled alarm is live again, so its terminal state must go.
            alarm.outcome = None
            alarm.snoozed_until = None

    _apply_to_ids(store, args.ids, action)
    print("Enabled {} alarm(s)".format(len(args.ids)))
    return 0


def cmd_disable(args, store) -> int:
    def action(data, targets):
        for alarm in targets:
            alarm.enabled = False
            alarm.snoozed_until = None

    _apply_to_ids(store, args.ids, action)
    print("Disabled {} alarm(s)".format(len(args.ids)))
    return 0


def cmd_clean(args, store) -> int:
    removed = 0
    with store.transaction() as data:
        keep = [a for a in data.alarms if not (a.is_one_off and a.outcome)]
        removed = len(data.alarms) - len(keep)
        data.alarms[:] = keep
    print("Removed {} finished alarm(s)".format(removed))
    return 0


def cmd_run(args, store) -> int:
    watcher = Watcher(store, RealClock(), ConsoleRinger())
    if not args.once:
        print("Watching for alarms. Press Ctrl-C to stop.")
    try:
        watcher.run(once=args.once)
    except KeyboardInterrupt:
        print("\nStopped watching.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alarm", description="A command-line alarm clock.")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True  # Python 3.9 argparse needs this set explicitly.

    def add_alarm_options(sub):
        sub.add_argument("-d", "--description", default="",
                         help="text shown and spoken when the alarm rings")
        sub.add_argument("--sound", default=None,
                         help="sound name, e.g. Glass (default: Submarine)")
        sub.add_argument("--snooze", type=int, default=9,
                         help="minutes added per snooze (default: 9)")

    add_parser = subparsers.add_parser("add", help="add an alarm at a clock time")
    add_parser.add_argument("time", help="07:00, 19:30, 7am or 7:30pm")
    add_parser.add_argument("-r", "--recurrence", default="once",
                            help="once, daily, weekdays, weekends or mon,wed,fri")
    add_alarm_options(add_parser)
    add_parser.set_defaults(func=cmd_add)

    in_parser = subparsers.add_parser("in", help="add a one-off alarm a duration from now")
    in_parser.add_argument("duration", help="45s, 20m, 2h or 1h30m")
    add_alarm_options(in_parser)
    in_parser.set_defaults(func=cmd_in)

    list_parser = subparsers.add_parser("list", help="list alarms and when they next fire")
    list_parser.add_argument("--all", action="store_true", help="include disabled alarms")
    list_parser.set_defaults(func=cmd_list)

    for name, handler, help_text in (
        ("rm", cmd_rm, "delete alarms"),
        ("enable", cmd_enable, "re-enable alarms"),
        ("disable", cmd_disable, "turn alarms off without deleting them"),
    ):
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("ids", nargs="+", type=int, metavar="ID")
        sub.set_defaults(func=handler)

    clean_parser = subparsers.add_parser("clean", help="delete one-off alarms that have finished")
    clean_parser.set_defaults(func=cmd_clean)

    run_parser = subparsers.add_parser("run", help="watch for alarms and ring them")
    run_parser.add_argument("--once", action="store_true",
                            help="make a single pass and exit")
    run_parser.set_defaults(func=cmd_run)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    store = Store(default_store_dir())
    try:
        return args.func(args, store)
    except (parsing.ParseError, UserError) as error:
        print("error: {}".format(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: PASS, 16 tests.

- [ ] **Step 5: Run the whole suite**

Run: `python3 -m pytest -q`
Expected: PASS, everything green.

- [ ] **Step 6: Commit**

```bash
git add alarmclock/cli.py tests/test_cli.py
git commit -m "Add command-line interface"
```

---

### Task 8: Install, verify against a real clock, and document

The suite proves the logic with a fake clock. This task proves the tool actually rings on the real one.

**Files:**
- Create: `README.md`
- Create: `.gitignore`

**Interfaces:**
- Consumes: the `alarm` console script from `pyproject.toml`.
- Produces: nothing further.

- [ ] **Step 1: Install the package in editable mode**

Run: `python3 -m pip install -e ".[dev]"`
Expected: succeeds, and `alarm --help` prints the subcommand list.

- [ ] **Step 2: Verify a real alarm rings**

Run these in one terminal, using a scratch store so your real alarms are untouched:

```bash
export ALARM_CLOCK_HOME=/tmp/alarmclock-smoke
alarm in 20s -d "Smoke test"
alarm list
alarm run
```

Expected: `list` shows the alarm with a countdown under 20 seconds. `run` prints its watching message, then about 20 seconds later prints the banner, plays a sound, speaks "Smoke test", and waits. Press `s`, confirm it re-rings after the snooze interval, then press `d` and confirm it stops. Ctrl-C exits cleanly.

- [ ] **Step 3: Verify cross-terminal pickup**

With `alarm run` still going in the first terminal, in a second terminal run
`ALARM_CLOCK_HOME=/tmp/alarmclock-smoke alarm in 40s -d "Second terminal"`.
Expected: the running watcher rings it without being restarted.

- [ ] **Step 4: Write the .gitignore**

```
__pycache__/
*.pyc
*.egg-info/
.pytest_cache/
build/
dist/
```

- [ ] **Step 5: Write the README**

`README.md` must contain: a one-paragraph description; an install section
(`python3 -m pip install -e "."`); a quick-start showing `alarm add 07:00 -d "Wake up" -r weekdays`, `alarm in 20m -d "Tea"`, `alarm list` and `alarm run`; a
table of all eight commands with one line each; a section stating plainly that
`alarm run` must be left open in a terminal for alarms to ring; the accepted
time, duration and recurrence formats; the store location and the
`ALARM_CLOCK_HOME` override; and a development section showing
`python3 -m pip install -e ".[dev]"` and `python3 -m pytest`.

- [ ] **Step 6: Commit**

```bash
git add README.md .gitignore
git commit -m "Add README and gitignore"
```

---

## Verification checklist

Run at the end. Every line must hold before the work is called done.

- [ ] `python3 -m pytest -q` — all tests pass.
- [ ] `alarm add 07:00 -d "Standup" -r weekdays` then `alarm list` shows the next Monday-to-Friday 07:00 with a countdown.
- [ ] `alarm in 20s` rings within a second of its time under `alarm run`.
- [ ] Snooze re-rings; dismiss stops it; both survive a watcher restart.
- [ ] An alarm added in a second terminal is picked up by a running watcher.
- [ ] `alarm add 25:00` exits 2 with a readable message and no traceback.
- [ ] `python3 -c "import alarmclock.cli"` works on Python 3.9 with no syntax errors.
