import pytest

from alarmclock.cli import main
from alarmclock.store import Store


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("ALARM_CLOCK_HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return tmp_path


def alarms(home):
    return Store(home).read().alarms


def test_add_creates_a_recurring_alarm(home, capsys):
    assert main(["add", "07:00", "-d", "Standup", "-r", "weekdays"]) == 0
    alarm = alarms(home)[0]
    assert alarm.id == 1
    assert alarm.time == "07:00:00"
    assert alarm.days == [0, 1, 2, 3, 4]
    assert alarm.description == "Standup"
    assert "Standup" in capsys.readouterr().out


def test_add_defaults_to_a_one_off_with_a_concrete_date(home):
    assert main(["add", "7am"]) == 0
    alarm = alarms(home)[0]
    assert alarm.days == []
    assert alarm.date is not None
    assert alarm.one_off_datetime() is not None


def test_add_accepts_sound_and_snooze_overrides(home):
    main(["add", "07:00", "--sound", "Glass", "--snooze", "5"])
    alarm = alarms(home)[0]
    assert alarm.sound == "Glass"
    assert alarm.snooze_minutes == 5


def test_add_rejects_a_bad_time_with_exit_code_2(home, capsys):
    assert main(["add", "25:00"]) == 2
    assert "not a valid time" in capsys.readouterr().err
    assert alarms(home) == []


def test_add_rejects_a_bad_recurrence_with_exit_code_2(home, capsys):
    assert main(["add", "07:00", "-r", "monday"]) == 2
    assert "not a valid recurrence" in capsys.readouterr().err


def test_in_creates_a_one_off_at_now_plus_duration(home):
    from datetime import datetime
    before = datetime.now()
    assert main(["in", "20m", "-d", "Tea"]) == 0
    alarm = alarms(home)[0]
    delta = alarm.one_off_datetime() - before
    assert 19 * 60 <= delta.total_seconds() <= 21 * 60
    assert alarm.description == "Tea"


def test_list_shows_alarms_with_a_countdown(home, capsys):
    main(["add", "07:00", "-d", "Standup", "-r", "daily"])
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "Standup" in out
    assert "daily" in out
    assert "in " in out


def test_list_hides_disabled_alarms_unless_all_is_given(home, capsys):
    main(["add", "07:00", "-d", "Standup", "-r", "daily"])
    main(["disable", "1"])
    capsys.readouterr()

    main(["list"])
    assert "Standup" not in capsys.readouterr().out

    main(["list", "--all"])
    out = capsys.readouterr().out
    assert "Standup" in out
    assert "off" in out


def test_list_is_friendly_when_empty(home, capsys):
    assert main(["list"]) == 0
    assert "no alarms" in capsys.readouterr().out.lower()


def test_disable_and_enable_toggle_without_deleting(home):
    main(["add", "07:00", "-r", "daily"])
    main(["disable", "1"])
    assert alarms(home)[0].enabled is False
    main(["enable", "1"])
    assert alarms(home)[0].enabled is True


def test_enable_clears_a_previous_outcome(home):
    main(["add", "07:00", "-r", "daily"])
    store = Store(home)
    with store.transaction() as data:
        data.alarms[0].enabled = False
        data.alarms[0].outcome = "dismissed"
    main(["enable", "1"])
    assert alarms(home)[0].outcome is None


def test_rm_deletes_the_named_alarms(home):
    main(["add", "07:00", "-r", "daily"])
    main(["add", "08:00", "-r", "daily"])
    assert main(["rm", "1"]) == 0
    assert [a.id for a in alarms(home)] == [2]


def test_rm_reports_an_unknown_id_with_exit_code_2(home, capsys):
    assert main(["rm", "99"]) == 2
    assert "99" in capsys.readouterr().err


def test_clean_removes_finished_one_offs_but_keeps_hand_disabled_alarms(home):
    main(["add", "07:00"])                 # one-off, id 1
    main(["add", "08:00", "-r", "daily"])  # recurring, id 2
    store = Store(home)
    with store.transaction() as data:
        data.alarms[0].enabled = False
        data.alarms[0].outcome = "dismissed"
        data.alarms[1].enabled = False     # disabled by hand, no outcome
    assert main(["clean"]) == 0
    assert [a.id for a in alarms(home)] == [2]


def test_run_once_exits_without_hanging(home):
    assert main(["run", "--once"]) == 0


def test_ids_survive_a_reload(home):
    main(["add", "07:00", "-r", "daily"])
    main(["rm", "1"])
    main(["add", "08:00", "-r", "daily"])
    assert alarms(home)[0].id == 2
