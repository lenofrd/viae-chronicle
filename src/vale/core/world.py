"""World 运行时容器与模块协议。

World 持有事件日志、当前 tick、已注册模块、加载好的配置，以及结构化的
WorldState（不再是裸 dict）。模块实现 `name`、`depends_on` 与 `step(world)`。
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .event_log import EventLog
from .state import WorldState


@runtime_checkable
class Module(Protocol):
    name: str
    depends_on: list[str]

    def step(self, world: "World") -> None: ...


class World:
    def __init__(
        self,
        world_id: str,
        event_log: EventLog,
        start_tick: int = 0,
        config: Any = None,
    ) -> None:
        self.world_id = world_id
        self.event_log = event_log
        self.current_tick: int = start_tick
        self.modules: list[Module] = []
        # 加载好的配置聚合对象（含 .natural_params / .spatial / .world）
        self.config = config
        # 结构化共享状态，气候模块负责初始化并写入 world.state.environment.climate
        self.state: WorldState = WorldState()

    def register(self, module: Module) -> None:
        self.modules.append(module)
