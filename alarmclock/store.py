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
