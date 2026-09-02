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
