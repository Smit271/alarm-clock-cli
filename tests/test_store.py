import json

import pytest

from alarmclock.models import Alarm
from alarmclock.store import SCHEMA_VERSION, Store, default_store_dir


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path)


def test_reading_a_missing_file_gives_an_empty_store(store):
    data = store.read()
    assert data.alarms == []
    assert data.next_id == 1


def test_transaction_writes_and_round_trips(store):
    with store.transaction() as data:
        data.alarms.append(Alarm(id=data.next_id, time="07:00:00", days=[0, 1, 2, 3, 4]))
        data.next_id += 1

    reloaded = store.read()
    assert len(reloaded.alarms) == 1
    assert reloaded.alarms[0].time == "07:00:00"
    assert reloaded.next_id == 2


def test_transaction_does_not_write_when_the_body_raises(store):
    with pytest.raises(RuntimeError):
        with store.transaction() as data:
            data.alarms.append(Alarm(id=1, time="07:00:00", days=[0]))
            raise RuntimeError("boom")
    assert store.read().alarms == []


def test_ids_are_not_reused_after_deletion(store):
    with store.transaction() as data:
        for _ in range(2):
            data.alarms.append(Alarm(id=data.next_id, time="07:00:00", days=[0]))
            data.next_id += 1
    with store.transaction() as data:
        data.alarms.clear()
    with store.transaction() as data:
        data.alarms.append(Alarm(id=data.next_id, time="08:00:00", days=[0]))
        data.next_id += 1
    assert store.read().alarms[0].id == 3


def test_written_file_carries_a_schema_version(store, tmp_path):
    with store.transaction() as data:
        data.alarms.append(Alarm(id=1, time="07:00:00", days=[0]))
        data.next_id = 2
    raw = json.loads((tmp_path / "alarms.json").read_text())
    assert raw["version"] == SCHEMA_VERSION


def test_a_corrupt_file_is_quarantined_and_the_store_stays_usable(store, tmp_path, capsys):
    store.path.write_text("{ this is not json")
    data = store.read()
    assert data.alarms == []
    quarantined = list(tmp_path.glob("alarms.json.corrupt-*"))
    assert len(quarantined) == 1
    assert "corrupt" in capsys.readouterr().err.lower()


def test_default_store_dir_honours_the_override(monkeypatch, tmp_path):
    monkeypatch.setenv("ALARM_CLOCK_HOME", str(tmp_path / "custom"))
    assert default_store_dir() == tmp_path / "custom"


def test_default_store_dir_falls_back_to_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("ALARM_CLOCK_HOME", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert default_store_dir() == tmp_path / "xdg" / "alarmclock"
