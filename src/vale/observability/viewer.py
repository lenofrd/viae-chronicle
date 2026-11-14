"""只读事件存储 + 日期换算 + 高层组合（任务 07）。

只读保证：用 SQLite URI mode=ro 打开，绝不复用 EventLog（其 _create_tables 会写库）。
日期换算：tick↔日期 全部走 vale.core.calendar 的常量与函数，不硬编码世界数值。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from typing import Any, Optional

from vale.core.calendar import (
    DAYS_PER_MONTH,
    DAYS_PER_YEAR,
    calendar_from_tick,
    start_day_of_year,
)

_DATE_RE = re.compile(r"^\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日\s*$")


class ReadonlyEventStore:
    """以只读模式打开 events.db。不建表、不写库、不迁移。"""

    def __init__(self, db_path: str) -> None:
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"事件库不存在：{db_path}（请先执行 cli.py run N）")
        # mode=ro：任何写操作都会被 SQLite 引擎拒绝
        self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row
        # 轻量校验表存在（schema 不符时给明确提示，不静默）
        try:
            self.conn.execute("SELECT id, tick, event_type, payload FROM events LIMIT 1")
        except sqlite3.OperationalError as exc:
            self.conn.close()
            raise RuntimeError(f"事件库 schema 不符（缺 events 表）：{exc}") from exc

    def _row_to_event(self, row: sqlite3.Row) -> dict[str, Any]:
        evt = dict(row)
        raw = evt.get("payload")
        try:
            evt["payload"] = json.loads(raw) if raw else {}
            evt["_payload_broken"] = False
            evt["_raw_payload"] = None
        except (json.JSONDecodeError, TypeError):
            evt["payload"] = {}
            evt["_payload_broken"] = True
            evt["_raw_payload"] = raw
        return evt

    def all(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM events ORDER BY id").fetchall()
        return [self._row_to_event(r) for r in rows]

    def get(self, event_id: int) -> Optional[dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return self._row_to_event(row) if row else None

    def close(self) -> None:
        self.conn.close()


# ----------------------------------------------------------------------
# 日期换算（全部走 calendar.py，不重复定义常量）
# ----------------------------------------------------------------------
def _start_doy(cfg) -> int:
    init = cfg.natural_params.climate_initial
    return start_day_of_year(init.season, init.season_progress or 0.0)


def date_str(tick: int, cfg) -> str:
    """tick →「X年M月D日 节气」，与气候模块同源。"""
    year, month, day, solar_term, _ = calendar_from_tick(
        tick, cfg.world.start_tick, _start_doy(cfg), cfg.world.start_year
    )
    return f"{year}年{month}月{day}日 {solar_term}"


def tick_from_date(cfg, year: int, month: int, day: int) -> int:
    """(year, month, day) → tick。用于日期筛选。用 calendar.py 常量反推。"""
    if not (1 <= month <= 12):
        raise ValueError(f"月份越界：{month}（应为 1-12）")
    if not (1 <= day <= DAYS_PER_MONTH):
        raise ValueError(f"日期越界：{day}（应为 1-{DAYS_PER_MONTH}）")
    if year < cfg.world.start_year:
        raise ValueError(f"年份 {year} 早于开局年份 {cfg.world.start_year}")
    start_doy = _start_doy(cfg)
    target_doy = (month - 1) * DAYS_PER_MONTH + day  # 1-based
    total_0based = (year - cfg.world.start_year) * DAYS_PER_YEAR + (target_doy - 1)
    return cfg.world.start_tick + (total_0based - (start_doy - 1))


def parse_date(s: str) -> Optional[tuple[int, int, int]]:
    """解析「X年M月D日」；不匹配返回 None。"""
    m = _DATE_RE.match(s)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def expr_to_tick(s: str, cfg) -> int:
    """把 --from/--to/--day 的表达式转成 tick：纯数字→tick；年月日→日期换算。"""
    s = s.strip()
    if s.isdigit():
        return int(s)
    parsed = parse_date(s)
    if parsed is None:
        raise ValueError(f"无法解析为日期或 tick：{s!r}（用「1年7月1日」或纯数字）")
    return tick_from_date(cfg, *parsed)


def day_tick_range(cfg, expr: str) -> tuple[int, int]:
    """某一天的 tick 范围 [start, end]（含）。日期→当天 tick；纯数字→该 tick 当天。"""
    s = expr.strip()
    if s.isdigit():
        t = int(s)
        return t, t
    parsed = parse_date(s)
    if parsed is None:
        raise ValueError(f"无法解析为日期或 tick：{s!r}")
    t = tick_from_date(cfg, *parsed)
    return t, t
