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
