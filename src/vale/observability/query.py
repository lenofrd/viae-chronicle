"""事件筛选纯函数（任务 07）。

不碰数据库、不碰日历：只接收已解析的事件列表与筛选条件，返回过滤后的列表。
事件结构（viewer 层解析后）：
  {"id": int, "tick": int, "event_type": str, "payload": dict, "created_at": str}
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class EventFilter:
    agent: Optional[str] = None
    event_types: Optional[list[str]] = None
    tick_from: Optional[int] = None  # 包含
    tick_to: Optional[int] = None    # 包含
    limit: Optional[int] = None      # None = 不限
    reverse: bool = False


def _matches_agent(evt: dict, agent: str) -> bool:
    """人物筛选：payload.agent_name 命中；无该字段的事件（天气/换季）不匹配。"""
    payload = evt.get("payload")
    if not isinstance(payload, dict):
        return False
    return payload.get("agent_name") == agent


def apply_filter(events: list[dict], f: EventFilter) -> list[dict]:
    """按筛选条件过滤并排序。返回新列表，不修改入参。"""
    out: list[dict] = []
    for evt in events:
        if f.event_types and evt.get("event_type") not in f.event_types:
            continue
        if f.agent and not _matches_agent(evt, f.agent):
            continue
        tick = evt.get("tick")
        if f.tick_from is not None and (tick is None or tick < f.tick_from):
            continue
        if f.tick_to is not None and (tick is None or tick > f.tick_to):
            continue
        out.append(evt)

    # 默认按 id 升序（= 写入顺序 = tick 升序 + 同 tick 写入序）
    out.sort(key=lambda e: e.get("id", 0))
    if f.reverse:
        out.reverse()
    if f.limit is not None and f.limit >= 0:
        out = out[: f.limit]
    return out
