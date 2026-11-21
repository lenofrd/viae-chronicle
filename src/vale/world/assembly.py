"""统一世界组装入口（P7 — World Orchestration）。

运行入口（``scripts/run_xigu.py``、``vale/cli.py``、``viz/sim_worker.py``）不得各自
维护业务模块注册清单：清单只在这里按 profile 声明，入口只选择 profile 并调用
``build_world``。场景差异体现在「世界生成 + 初始配置 + profile」，不复制运行内核。

调度声明（``phase`` / ``depends_on``）在这里一次性校验：缺失依赖、重复模块名、
依赖环、缺少 phase 都在组装阶段失败，不等首个 tick。
"""
from __future__ import annotations

import random

from vale.core.event_log import EventLog
from vale.core.scheduler import resolve_order
from vale.core.world import Module, World
from vale.domains.environment.climate import ClimateModule
from vale.domains.environment.resources import EcologyModule
from vale.domains.society.agents import AgentModule
from vale.domains.society.economy import TenancyEconomyModule
from vale.domains.wildlife.wildlife import WildlifeModule
from vale.world.scenarios.xigu.events import XiguEventsModule


def full_modules(seed: int) -> list[Module]:
    """完整世界：自然 → 生态 → 动物 → 人文 → 场景冲击（溪谷镇长期模拟口径）。"""
    return [
        ClimateModule(),
        EcologyModule(),
        WildlifeModule(),
        AgentModule(),
        TenancyEconomyModule(),
        XiguEventsModule(seed=seed),
    ]


def base_town_modules() -> list[Module]:
    """基础聚落：气候 + 生态 + 人物（CLI 静态世界口径，行为保持不变）。"""
    return [ClimateModule(), EcologyModule(), AgentModule()]


def viz_modules(seed: int) -> list[Module]:
    """可视化轻量档案：气候 + 生态 + 人物，两条独立随机流。

    此前可视化只注册气候与人物，`agents` 声明的 `ecology` 依赖被旧调度器静默忽略；
    P7 起依赖必须满足，故补上生态模块（可视化里的资源再生/采集随之生效）。
    """
    return [
        ClimateModule(rng=random.Random(seed)),
        EcologyModule(),
        AgentModule(rng=random.Random(seed * 7 + 13)),
    ]


def build_world(config, event_log: EventLog, *, modules: list[Module]) -> World:
    """组装 World：建容器、注册模块，并在返回前校验调度声明。"""
    world = World(
        world_id=config.world.world_id,
        event_log=event_log,
        start_tick=config.world.start_tick,
        config=config,
    )
    for module in modules:
        world.register(module)
    world.strict_schedule = True
    resolve_order(world.modules)
    return world
