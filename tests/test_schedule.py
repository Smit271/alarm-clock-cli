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
