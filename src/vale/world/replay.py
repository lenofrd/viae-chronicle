"""事件流只读重放的组装入口（ADR 009 §2.1；2026-11-21 裁决归属修正）。

世界协调层只负责把三个领域的事件投影注册到通用引擎
（``core.replay.ReplayEngine``）并对外暴露 ``rebuild_state``：

- 环境域：``domains.environment.projection.EnvironmentProjection``
- 动物域：``domains.wildlife.projection.WildlifeProjection``
- 人文域：``domains.society.projection.SocietyProjection``

``rebuild_state`` 的签名与返回类型保持不变（旧库 → 单人家庭；新库 → 按
household_id 重放），调用方无需感知投影拆分。
"""
from __future__ import annotations

from vale.core.replay import ReplayEngine, ReplayResult
from vale.domains.environment.projection import EnvironmentProjection
from vale.domains.society.projection import SocietyProjection
from vale.domains.wildlife.projection import WildlifeProjection


def rebuild_state(events: list[dict], config) -> ReplayResult:
    """只读重放事件流为家庭状态（旧库 → 单人家庭；新库 → 按 household_id）。"""
    engine = ReplayEngine(config, start_tick=config.world.start_tick)
    for projection in (EnvironmentProjection(), WildlifeProjection(), SocietyProjection()):
        engine.register(projection)
    return engine.replay(events)
