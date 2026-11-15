"""阶段三第 2 轮：未成年人 food_share（消费端系数）专项。

覆盖：未成年扣减 ×0.7、成年不变、food_share=1.0 回退到第 1 轮行为、消费守恒。
"""
from __future__ import annotations

import random

import pytest
from config.schema.agents import AgentSex
from household_helpers import hh
from vale.core.config_loader import load_config
from vale.core.event_log import EventLog
from vale.core.scheduler import run_tick
from vale.core.state import AgentState
from vale.core.world import World
from vale.modules.agents import AgentModule, SpatialIndex, age_years
from vale.modules.climate import ClimateModule


def _build(seed: int = 0) -> World:
    cfg = load_config("brookvale-town-001")
    w = World(world_id=cfg.world.world_id, event_log=EventLog(":memory:"),
              start_tick=cfg.world.start_tick, config=cfg)
    w.register(ClimateModule(rng=random.Random(seed)))
    w.register(AgentModule(rng=random.Random(seed * 7 + 13)))
    run_tick(w)
    return w


def _module(world) -> AgentModule:
    mod = AgentModule(rng=random.Random(99))
    mod._spatial = SpatialIndex(world.config.spatial)  # noqa: SLF001
    return mod


def _add_minor(world, host_id: str = "zhao_cuilan", agent_id: str = "child_88") -> AgentState:
    """把一个 0 岁未成年加入 host_id 所在家庭（随户消费）。"""
    host = world.state.agents[host_id]
    household = hh(world, host)
    household.member_ids.append(agent_id)
    child = AgentState(
        agent_id=agent_id, name="林阿宁", surname="林", sex=AgentSex.FEMALE,
        birth_tick=world.current_tick, life_stage="幼年",
        household_id=household.household_id, location=household.home_node,
        work_node=None, health=60.0, hunger=80.0, stamina=50.0,
        mother_id=host_id if host.sex == AgentSex.FEMALE else None,
        father_id=host_id if host.sex == AgentSex.MALE else None,
    )
    world.state.agents[agent_id] = child
    return child


def _eat(world, mod, agent) -> dict:
    before = len(world.event_log.all())
    mod._execute(world, agent, "eat", mod._perceive(world, agent),  # noqa: SLF001
                 world.config.agents.tuning)
    events = world.event_log.all()[before:]
    return [e["payload"] for e in events if e["event_type"] == "agent_action_taken"][-1]


def test_minor_eats_share_of_adult_ration():
    w = _build()
    mod = _module(w)
    tuning = w.config.agents.tuning
    child = _add_minor(w)
    assert age_years(child.birth_tick, w.current_tick) < tuning.dependency.max_age
    household = hh(w, child)
    household.grain = 10.0
    child.hunger = 80.0

    payload = _eat(w, mod, child)

    expected = 10.0 - tuning.physiology.eat_grain_cost * tuning.consumption.minor_food_share
    assert household.grain == pytest.approx(expected)
    assert payload["grain_before"] == pytest.approx(10.0)
    assert payload["grain_after"] == pytest.approx(expected)
    # 饥饿降低量与成年一致（只有库存扣减打折）
    assert payload["hunger_after"] == pytest.approx(
        80.0 - tuning.physiology.eat_hunger_reduction
    )


def test_adult_ration_unchanged():
    w = _build()
    mod = _module(w)
    tuning = w.config.agents.tuning
    lin = w.state.agents["lin_yuan"]
    household = hh(w, lin)
    household.grain = 10.0
    lin.hunger = 80.0

    _eat(w, mod, lin)

    assert household.grain == pytest.approx(10.0 - tuning.physiology.eat_grain_cost)


def test_share_one_matches_previous_behavior():
    w = _build()
    mod = _module(w)
    tuning = w.config.agents.tuning
    tuning.consumption.minor_food_share = 1.0
    child = _add_minor(w)
    household = hh(w, child)
    household.grain = 10.0
    child.hunger = 80.0

    _eat(w, mod, child)

    assert household.grain == pytest.approx(10.0 - tuning.physiology.eat_grain_cost)


def test_consumption_conserves_household_stock():
    """同户成年 + 未成年各吃一次：库存减少 = 两次实际扣减之和，且非负。"""
    w = _build()
    mod = _module(w)
    tuning = w.config.agents.tuning
    lin = w.state.agents["lin_yuan"]
    child = _add_minor(w, host_id="lin_yuan")
    household = hh(w, lin)
    household.grain = 10.0
    lin.hunger = 80.0
    child.hunger = 80.0

    p_adult = _eat(w, mod, lin)
    p_minor = _eat(w, mod, child)

    adult_used = p_adult["grain_before"] - p_adult["grain_after"]
    minor_used = p_minor["grain_before"] - p_minor["grain_after"]
    assert adult_used == pytest.approx(tuning.physiology.eat_grain_cost)
    assert minor_used == pytest.approx(
        tuning.physiology.eat_grain_cost * tuning.consumption.minor_food_share
    )
    assert household.grain == pytest.approx(10.0 - adult_used - minor_used)
    assert household.grain >= 0.0
