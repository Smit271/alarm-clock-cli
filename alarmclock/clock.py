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
