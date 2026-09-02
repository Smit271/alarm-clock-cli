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
