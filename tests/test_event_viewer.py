"""观察层（任务 07）单元测试：筛选 / 渲染 / 导出 / 只读性 / 错误隔离。

不依赖真实终端、不依赖固定 events.db；用临时库构造事件。保持确定性。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

from config.schema.natural_params import Season
from vale.core.event_log import EventLog
from vale.observability.export import EXPORT_FORMATS, export_csv, export_jsonl, export_markdown
from vale.observability.query import EventFilter, apply_filter
from vale.observability.render import render_event
from vale.observability.viewer import (
    ReadonlyEventStore,
    date_str,
    expr_to_tick,
    parse_date,
    tick_from_date,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI_PATH = os.path.join(REPO_ROOT, "src", "vale", "cli.py")


def _cfg():
    """最小 mock cfg：开局立春（start_doy=1），start_tick=0。"""
    return SimpleNamespace(
        world=SimpleNamespace(start_tick=0, start_year=1, world_id="test"),
        natural_params=SimpleNamespace(
            climate_initial=SimpleNamespace(season=Season.SPRING, season_progress=0.0)
        ),
    )


def _write_events(path, rows):
    """rows: list of (tick, event_type, payload_dict_or_str)。直接写 sqlite，可控。"""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, tick INTEGER NOT NULL, "
        "event_type TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)"
    )
    for tick, et, payload in rows:
        raw = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        conn.execute(
            "INSERT INTO events (tick, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            (tick, et, raw, "2026-01-01T00:00:00"),
        )
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# 渲染：正常路径
# --------------------------------------------------------------------------
def test_render_weather_ok():
    evt = {"id": 1, "tick": 0, "event_type": "weather_changed",
           "payload": {"weather": "sunny", "temperature_c": 24, "drought_state": "none"}}
    r = render_event(evt)
    assert not r.degraded
    assert "晴" in r.text and "24" in r.text


def test_render_season_ok():
    evt = {"id": 2, "tick": 90, "event_type": "season_changed",
           "payload": {"from": "spring", "to": "summer", "year": 1, "month": 4, "day": 1}}
    r = render_event(evt)
    assert not r.degraded
    assert "spring" in r.text and "summer" in r.text


@pytest.mark.parametrize("action", ["eat", "rest", "farm", "collect_water", "harvest", "borrow_grain"])
def test_render_known_actions_not_degraded(action):
    payload = {"agent_name": "林远", "action": action, "target_node": "field_west",
               "grain_before": 10, "grain_after": 8, "debt_before": 0, "debt_after": 0,
               "field_growth_before": 0, "field_growth_after": 5,
               "hunger_before": 50, "hunger_after": 45, "stamina_after": 70, "weather": "sunny"}
    r = render_event({"id": 3, "tick": 1, "event_type": "agent_action_taken", "payload": payload},
                     names={"field_west": "西片田"})
    assert not r.degraded, f"{action} 不应降级：{r.reason}"
    assert "林远" in r.text


# --------------------------------------------------------------------------
# 渲染：B2 eat 文案修正（吃非粮按实际食物类型显示，不得误导为“存粮”）
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "food,before,after,label",
    [
        ("meat", 13, 12, "肉"),
        ("fish", 7, 6, "鱼"),
        ("vegetable", 5, 4, "菜"),
    ],
)
def test_render_eat_non_grain_shows_actual_food(food, before, after, label):
    """grain_before=0 且实际吃非粮：渲染含该食物类型，不含“存粮”，不降级。"""
    payload = {
        "agent_name": "林远", "action": "eat",
        "grain_before": 0, "grain_after": 0,
        "meat_before": 0, "meat_after": 0,
        "fish_before": 0, "fish_after": 0,
        "vegetable_before": 0, "vegetable_after": 0,
    }
    payload[f"{food}_before"] = before
    payload[f"{food}_after"] = after
    r = render_event({"id": 10, "tick": 1, "event_type": "agent_action_taken", "payload": payload})
    assert not r.degraded
    assert label in r.text
    assert "存粮" not in r.text


def test_render_eat_grain_text_unchanged():
    """吃粮：文案与旧行为逐字一致（grain 10→8 → 「吃了些存粮（存粮剩 8 石）」）。"""
    payload = {
        "agent_name": "林远", "action": "eat",
        "grain_before": 10, "grain_after": 8,
        "meat_before": 0, "meat_after": 0,
        "fish_before": 0, "fish_after": 0,
        "vegetable_before": 0, "vegetable_after": 0,
    }
    r = render_event({"id": 11, "tick": 1, "event_type": "agent_action_taken", "payload": payload})
    assert not r.degraded
    assert r.text == "[林远] 吃了些存粮（存粮剩 8 石）"


def test_render_eat_missing_before_fields_no_crash():
    """旧事件缺 before 字段：按 0 兜底，不抛异常；无匹配非粮时回退吃粮文案。"""
    payload = {"agent_name": "林远", "action": "eat", "grain_after": 3}
    r = render_event({"id": 12, "tick": 1, "event_type": "agent_action_taken", "payload": payload})
    assert not r.degraded
    assert r.text == "[林远] 吃了些存粮（存粮剩 3 石）"


def test_render_agent_error_ok():
    evt = {"id": 4, "tick": 2, "event_type": "agent_error",
           "payload": {"agent_name": "林远", "error": "ValueError('boom')", "traceback": "..."}}
    r = render_event(evt)
    assert not r.degraded
    assert "林远" in r.text and "boom" in r.text


# --------------------------------------------------------------------------
# 渲染：兜底与降级（不崩）
# --------------------------------------------------------------------------
def test_render_unknown_action_is_degraded():
    payload = {"agent_name": "林远", "action": "steal_cow", "target_node": "barn"}
    r = render_event({"id": 5, "tick": 1, "event_type": "agent_action_taken", "payload": payload})
    assert r.degraded
    assert r.reason is not None


def test_render_unknown_event_type_is_degraded():
    r = render_event({"id": 6, "tick": 1, "event_type": "trust_changed",
                      "payload": {"from": "a", "to": "b"}})
    assert r.degraded
    assert r.reason == "unknown_event_type"


def test_render_missing_weather_field_is_degraded():
    r = render_event({"id": 7, "tick": 0, "event_type": "weather_changed", "payload": {}})
    assert r.degraded  # 缺 weather 字段


def test_render_broken_payload_is_degraded():
    r = render_event({"id": 8, "tick": 0, "event_type": "weather_changed",
                      "payload": {}, "_payload_broken": True})
    assert r.degraded
    assert r.reason == "payload_broken_json"


# --------------------------------------------------------------------------
# 筛选
# --------------------------------------------------------------------------
def _sample_events():
    return [
        {"id": 1, "tick": 0, "event_type": "weather_changed", "payload": {"weather": "sunny"}},
        {"id": 2, "tick": 0, "event_type": "agent_action_taken",
         "payload": {"agent_name": "林远", "action": "eat"}},
        {"id": 3, "tick": 1, "event_type": "agent_action_taken",
         "payload": {"agent_name": "李全", "action": "farm"}},
        {"id": 4, "tick": 5, "event_type": "season_changed", "payload": {"from": "x", "to": "y"}},
    ]


def test_filter_by_agent():
    out = apply_filter(_sample_events(), EventFilter(agent="林远"))
    assert [e["id"] for e in out] == [2]


def test_filter_by_type_multi():
    out = apply_filter(_sample_events(), EventFilter(event_types=["weather_changed", "season_changed"]))
    assert [e["id"] for e in out] == [1, 4]


def test_filter_by_tick_range_inclusive():
    out = apply_filter(_sample_events(), EventFilter(tick_from=1, tick_to=5))
    assert [e["id"] for e in out] == [3, 4]


def test_filter_limit_and_reverse():
    out = apply_filter(_sample_events(), EventFilter(limit=2, reverse=True))
    assert [e["id"] for e in out] == [4, 3]  # 倒序取前 2


def test_filter_agent_excludes_weather():
    # 天气事件无 agent_name，按人筛选时被排除
    out = apply_filter(_sample_events(), EventFilter(agent="不存在的人"))
    assert out == []


# --------------------------------------------------------------------------
# 日期换算（走 calendar.py）
# --------------------------------------------------------------------------
def test_date_str_start_is_lichun():
    assert date_str(0, _cfg()) == "1年1月1日 立春"


def test_tick_from_date_roundtrip():
    cfg = _cfg()
    for (y, m, d) in [(1, 1, 1), (1, 7, 1), (1, 12, 30), (2, 1, 1)]:
        t = tick_from_date(cfg, y, m, d)
        assert date_str(t, cfg).startswith(f"{y}年{m}月{d}日")


def test_parse_date_and_expr():
    assert parse_date("1年7月1日") == (1, 7, 1)
    assert parse_date("not a date") is None
    assert expr_to_tick("5", _cfg()) == 5
    assert expr_to_tick("1年7月1日", _cfg()) == tick_from_date(_cfg(), 1, 7, 1)


def test_tick_from_date_rejects_out_of_range():
    with pytest.raises(ValueError):
        tick_from_date(_cfg(), 1, 13, 1)
    with pytest.raises(ValueError):
        tick_from_date(_cfg(), 1, 1, 31)


# --------------------------------------------------------------------------
# 只读存储：坏载荷解析 + 不崩
# --------------------------------------------------------------------------
def test_broken_payload_parsed_and_flagged(tmp_path):
    db = tmp_path / "bad.db"
    _write_events(db, [
        (0, "weather_changed", "这不是合法的 JSON {"),
        (0, "agent_action_taken", {"agent_name": "林远", "action": "eat"}),
    ])
    store = ReadonlyEventStore(str(db))
    try:
        events = store.all()
    finally:
        store.close()
    assert len(events) == 2
    assert events[0]["_payload_broken"] is True
    assert events[1]["_payload_broken"] is False
    # 坏事件不拖垮整体渲染
    results = [render_event(e) for e in events]
    assert results[0].degraded and not results[1].degraded


def test_broken_event_does_not_break_batch(tmp_path):
    db = tmp_path / "batch.db"
    rows = [(i, "weather_changed", "坏载荷" if i == 3 else {"weather": "sunny"}) for i in range(5)]
    _write_events(db, rows)
    store = ReadonlyEventStore(str(db))
    try:
        events = store.all()
    finally:
        store.close()
    degraded = sum(1 for e in events if render_event(e).degraded)
    assert degraded == 1  # 只有 1 条坏，其余正常渲染
    assert len(events) == 5  # 没丢数据


# --------------------------------------------------------------------------
# 只读性：运行前后 DB 不变 + 写操作被拒
# --------------------------------------------------------------------------
def test_db_unchanged_after_readonly_query(tmp_path):
    db = tmp_path / "ro.db"
    _write_events(db, [(0, "weather_changed", {"weather": "sunny"})])
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    store = ReadonlyEventStore(str(db))
    try:
        _ = store.all()
        _ = store.get(1)
    finally:
        store.close()
    after = hashlib.sha256(db.read_bytes()).hexdigest()
    assert before == after, "只读查询不应修改数据库文件"


def test_readonly_store_rejects_write(tmp_path):
    db = tmp_path / "nowrite.db"
    _write_events(db, [(0, "weather_changed", {"weather": "sunny"})])
    store = ReadonlyEventStore(str(db))
    try:
        with pytest.raises(sqlite3.OperationalError):
            store.conn.execute("INSERT INTO events (tick, event_type, payload, created_at) "
                               "VALUES (9, 'x', '{}', 'now')")
            store.conn.commit()
    finally:
        store.close()


def test_missing_db_raises_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        ReadonlyEventStore(str(tmp_path / "nope.db"))


def test_schema_mismatch_raises_clear_error(tmp_path):
    db = tmp_path / "weird.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE other (x INT)")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError):
        ReadonlyEventStore(str(db))


# --------------------------------------------------------------------------
# 导出：条数与查看一致
# --------------------------------------------------------------------------
def test_export_counts_match_filter():
    cfg = _cfg()
    events = [
        {"id": 1, "tick": 0, "event_type": "weather_changed", "payload": {"weather": "sunny"}},
        {"id": 2, "tick": 1, "event_type": "agent_action_taken",
         "payload": {"agent_name": "林远", "action": "eat"}},
        {"id": 3, "tick": 2, "event_type": "agent_action_taken",
         "payload": {"agent_name": "李全", "action": "farm", "target_node": "f"}},
    ]
    filt = EventFilter(agent="林远")
    view = apply_filter(events, filt)
    date_of = lambda t: date_str(t, cfg)
    md = export_markdown(view, names={}, date_of=date_of, filter_desc="agent=林远")
    csv_ = export_csv(view, names={}, date_of=date_of, filter_desc="agent=林远")
    jsonl = export_jsonl(view, names={}, date_of=date_of, filter_desc="agent=林远")
    # 三种格式的数据行数都应 == 查看条数（导出条数与查看一致）
    md_rows = len(re.findall(r"^\| \d+ \|", md, re.M))  # 以「| 数字 |」开头的行=数据行
    csv_rows = len(re.findall(r"^\d+,", csv_, re.M))    # 以数字开头的行=数据行
    jsonl_rows = len([ln for ln in jsonl.strip().splitlines() if '"_meta"' not in ln])
    assert md_rows == len(view) == csv_rows == jsonl_rows
    assert "total=1" in md and "total=1" in csv_


# --------------------------------------------------------------------------
# CLI 集成：错误信息 + 非零退出 + --debug 堆栈
# --------------------------------------------------------------------------
def _run_cli(*args):
    # stdin=DEVNULL + close_fds：避免在 pytest 捕获 stdio 的 Windows 环境下
    # 子进程继承无效句柄导致 WinError 6。
    return subprocess.run(
        [sys.executable, CLI_PATH, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
        stdin=subprocess.DEVNULL, close_fds=True,
    )


def test_cli_missing_db_exit_nonzero_and_readable(tmp_path):
    r = _run_cli("events", "list", "--db", str(tmp_path / "missing.db"))
    assert r.returncode != 0
    assert "事件库不存在" in r.stderr
    assert "Traceback" not in r.stderr  # 默认不暴露堆栈给老板


def test_cli_debug_shows_traceback(tmp_path):
    # 构造一个 schema 不符的 db，触发 RuntimeError → --debug 应打印堆栈
    db = tmp_path / "weird.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE other (x INT)")
    conn.commit()
    conn.close()
    r = _run_cli("events", "--debug", "list", "--db", str(db))
    assert r.returncode != 0
    assert "Traceback" in r.stderr


def test_cli_schema_mismatch_readable_without_debug(tmp_path):
    db = tmp_path / "weird2.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE other (x INT)")
    conn.commit()
    conn.close()
    r = _run_cli("events", "list", "--db", str(db))
    assert r.returncode != 0
    assert "错误：" in r.stderr
    assert "Traceback" not in r.stderr
