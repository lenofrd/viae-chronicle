"""通用事件重放引擎（ADR 009 §2.1；2026-11-21 裁决归属修正）。

core 只保留事件读取、事件顺序与通用派发骨架，不认识任何领域：

- 领域投影处理器由各领域包提供（``domains.environment.projection`` /
  ``domains.wildlife.projection`` / ``domains.society.projection``）；
- 组装与注册由世界协调层 ``vale.world.replay`` 负责，对外暴露 ``rebuild_state``。

约束：
- 只读：不修改事件、不写事件库；
- 未处理的事件计入 ``ignored_events``，不中断；
- 派发按注册顺序取第一个提供 ``_on_<event_type>`` 的投影；该方法显式
  ``return False`` 表示「该事件不归本投影」，继续找下一个投影。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from vale.core.state import WorldState


@dataclass
class ReplayResult:
    state: WorldState
    ignored_events: dict[str, int] = field(default_factory=dict)


class ProjectionBase:
    """领域投影基类：绑定引擎后共享只读上下文。"""

    _engine: "ReplayEngine"

    def bind(self, engine: "ReplayEngine") -> None:
        self._engine = engine

    @property
    def config(self):
        return self._engine.config

    @property
    def state(self):
        return self._engine.state

    @property
    def start_tick(self):
        return self._engine.start_tick

    @property
    def node_ids(self):
        return self._engine.node_ids

    @property
    def _default_home(self):
        return self._engine.default_home

    def finalize(self, state, last_tick: int, *, has_events: bool) -> None:
        """事件流结束后的一次性投影（默认无操作）。"""

    def validate(self, state) -> None:
        """重放结果校验（默认无操作）。"""


class ReplayEngine:
    def __init__(self, config, start_tick: int) -> None:
        self.config = config
        self.start_tick = start_tick
        self.state = WorldState()
        self.ignored: dict[str, int] = {}
        self.node_ids = {n.id for n in config.spatial.nodes}
        self.default_home = config.agents.agents[0].home_node if config.agents.agents else "well"
        self._projections: list[ProjectionBase] = []

    def register(self, projection: ProjectionBase) -> ProjectionBase:
        projection.bind(self)
        self._projections.append(projection)
        return projection

    def replay(self, events: list[dict]) -> ReplayResult:
        for evt in events:
            event_type = evt.get("event_type")
            payload = evt.get("payload") or {}
            tick = int(evt.get("tick", 0))
            if not self._dispatch(event_type, payload, tick):
                self.ignored[event_type] = self.ignored.get(event_type, 0) + 1
        has_events = bool(events)
        last_tick = int(events[-1].get("tick", 0)) if has_events else 0
        for projection in self._projections:
            projection.finalize(self.state, last_tick, has_events=has_events)
        for projection in self._projections:
            projection.validate(self.state)
        return ReplayResult(state=self.state, ignored_events=self.ignored)

    def _dispatch(self, event_type: str, payload: dict, tick: int) -> bool:
        for projection in self._projections:
            handler = getattr(projection, f"_on_{event_type}", None)
            if handler is None:
                continue
            if handler(payload, tick) is False:
                continue
            return True
        return False
