from __future__ import annotations

import hashlib

from vale.core.event_log import EventLog
from viz.data import EventSource


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_open_and_refresh_never_change_database(tmp_path):
    path = tmp_path / "events.db"
    log = EventLog(str(path))
    log.append(0, "weather_changed", {"weather": "sunny", "temperature_c": 20})
    log.append(1, "agent_action_taken", {"agent_id": "a", "agent_name": "阿远", "action": "rest"})
    log.close()
    before = digest(path)

    source = EventSource.database(path)
    first = source.load()
    second = source.load()

    assert len(first) == len(second) == 2
    assert first[1]["payload"]["agent_name"] == "阿远"
    assert digest(path) == before
