"""阶段二测试：事件溯源数据库基座。全部使用内存数据库，不碰磁盘文件。"""
from __future__ import annotations

import pytest

from vale.core.event_log import EventLog


@pytest.fixture
def log() -> EventLog:
    return EventLog(":memory:")


def test_create_tables(log: EventLog) -> None:
    """能够成功建表。"""
    rows = log.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
    ).fetchall()
    assert len(rows) == 1


def test_insert_and_read_json(log: EventLog) -> None:
    """插入一条事件后能正确读取，且 JSON 字段解析正确。"""
    eid = log.append(
        tick=5,
        event_type="weather_changed",
        payload={"temperature_c": 22.5, "rain": False, "note": "晴"},
    )
    evt = log.get(eid)
    assert evt is not None
    assert evt["tick"] == 5
    assert evt["event_type"] == "weather_changed"
    # payload 存为 JSON 字符串，读回应解析回 dict（含中文）
    assert evt["payload"] == {"temperature_c": 22.5, "rain": False, "note": "晴"}


def test_reject_missing_tick(log: EventLog) -> None:
    """无法插入缺失 tick 的非法事件：数据库层拒绝或抛出异常。"""
    with pytest.raises((ValueError, TypeError)):
        log.append(tick=None, event_type="bad_event")  # type: ignore[arg-type]


def test_payload_default_empty_dict(log: EventLog) -> None:
    """不提供 payload 时应存为空对象，读取仍是 dict。"""
    eid = log.append(tick=1, event_type="heartbeat")
    assert log.get(eid)["payload"] == {}
