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


def test_tick_window_queries_are_exact_and_ordered(log: EventLog) -> None:
    log.append(1, "agent_action_taken", {"agent_id": "a"})
    log.append(2, "agent_action_taken", {"agent_id": "b"})
    log.append(2, "weather_changed", {"rain": True})
    log.append(3, "agent_action_taken", {"agent_id": "c"})
    assert [e["payload"]["agent_id"] for e in log.by_type_at_tick("agent_action_taken", 2)] == ["b"]
    assert [e["payload"]["agent_id"] for e in log.by_type_between_ticks("agent_action_taken", 1, 3)] == ["b", "c"]
    assert [e["tick"] for e in log.between_ticks(1, 2)] == [2, 2]



def test_marriage_events_have_readable_rendering() -> None:
    from vale.observability.render import render_event

    moved = render_event({
        "event_type": "household_member_transferred",
        "payload": {
            "agent_id": "wife", "agent_name": "林娘子",
            "source_household_id": "hh_wife", "target_household_id": "hh_husband",
        },
    })
    assert not moved.degraded
    assert "迁入家庭" in moved.text and "林娘子" in moved.text

    bride_price = render_event({
        "event_type": "marriage_assets_transferred",
        "payload": {
            "transfer_type": "bride_price",
            "from_household_id": "hh_husband",
            "to_household_id": "hh_wife",
            "resources": {"grain": 2.5, "coin": 10},
        },
    })
    assert not bride_price.degraded
    assert "彩礼" in bride_price.text and "粮" in bride_price.text and "铜钱" in bride_price.text

    dowry = render_event({
        "event_type": "marriage_assets_transferred",
        "payload": {
            "transfer_type": "dowry",
            "from_household_id": "hh_wife",
            "to_household_id": "hh_husband",
            "resources": {"cloth": 1},
        },
    })
    assert not dowry.degraded and "陪嫁" in dowry.text
