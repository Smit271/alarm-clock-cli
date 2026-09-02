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
