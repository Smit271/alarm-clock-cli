"""The run loop: decide what is due, ring it, record the result."""

from datetime import datetime, timedelta
from typing import List, Optional

from . import ring as ring_module
from .models import OUTCOME_DISMISSED, OUTCOME_MISSED, Alarm, from_iso, to_iso
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
