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
