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
