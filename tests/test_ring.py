import io

from alarmclock import ring
from alarmclock.models import Alarm


def make_alarm(**kwargs):
    defaults = dict(id=1, time="07:00:00", days=[0], description="Standup")
    defaults.update(kwargs)
    return Alarm(**defaults)


def test_reads_dismiss_from_non_tty_stdin(monkeypatch, capsys):
    ringer = ring.ConsoleRinger()
    monkeypatch.setattr(ring.sys, "stdin", io.StringIO("d\n"))
    monkeypatch.setattr(ringer, "_play_sound", lambda alarm: None)
    monkeypatch.setattr(ringer, "_speak", lambda alarm: None)

    assert ringer.ring(make_alarm()) == ring.DISMISS
    assert "Standup" in capsys.readouterr().out


def test_reads_snooze_from_non_tty_stdin(monkeypatch):
    ringer = ring.ConsoleRinger()
    monkeypatch.setattr(ring.sys, "stdin", io.StringIO("s\n"))
    monkeypatch.setattr(ringer, "_play_sound", lambda alarm: None)
    monkeypatch.setattr(ringer, "_speak", lambda alarm: None)

    assert ringer.ring(make_alarm()) == ring.SNOOZE


def test_closed_stdin_times_out_rather_than_hanging(monkeypatch):
    ringer = ring.ConsoleRinger(timeout_seconds=1)
    monkeypatch.setattr(ring.sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(ringer, "_play_sound", lambda alarm: None)
    monkeypatch.setattr(ringer, "_speak", lambda alarm: None)

    assert ringer.ring(make_alarm()) == ring.TIMEOUT


def test_a_missing_player_binary_degrades_to_the_terminal_bell(monkeypatch, capsys):
    ringer = ring.ConsoleRinger()
    monkeypatch.setattr(ring.shutil, "which", lambda name: None)
    ringer._play_sound(make_alarm())
    assert "\a" in capsys.readouterr().out
