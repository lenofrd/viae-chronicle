"""World 运行时容器与模块协议。

World 持有事件日志、当前 tick、已注册模块、加载好的配置，以及结构化的
WorldState（不再是裸 dict）。模块实现 `name`、`phase`、`depends_on` 与
`step(world)`；调度顺序由 `core.scheduler.resolve_order` 依据显式声明计算。
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .event_log import EventLog
from .state import WorldState

# 调度阶段（P7）：同一 tick 内的因果关系按阶段推进，模块不得跨阶段隐式插队。
PHASE_NATURAL = 1      # 基础自然条件演化（气候、天气）
PHASE_ECOLOGY = 2      # 环境生态演化（资源再生、田块生态）
PHASE_WILDLIFE = 3     # 动物演化（鱼/猎物存量）
PHASE_SOCIETY = 4      # 人类社会活动（人物、家庭、经济）
PHASE_IMPACT = 5       # 跨领域影响结算（场景灾害等对领域的冲击）
PHASE_PROJECTION = 6   # 状态投影与观察


@runtime_checkable
class Module(Protocol):
    name: str
    phase: int
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
        # 是否要求模块声明的 depends_on 必须全部注册（统一组装入口置 True）；
        # 手工搭建的局部世界（测试夹具）保持 False，只校验重名/依赖环/phase。
        self.strict_schedule: bool = False
        # 加载好的配置聚合对象（含 .natural_params / .spatial / .world）
        self.config = config
        # 结构化共享状态，气候模块负责初始化并写入 world.state.environment.climate
        self.state: WorldState = WorldState()

    def register(self, module: Module) -> None:
        duplicate = next(
            (m.name for m in self.modules if m.name == getattr(module, "name", None)),
            None,
        )
        if duplicate is not None:
            raise ValueError(f"模块名重复：'{duplicate}' 已注册")
        self.modules.append(module)
