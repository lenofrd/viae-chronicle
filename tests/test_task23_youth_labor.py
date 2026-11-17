"""任务 23 测试：少年（8–12）轻劳作 c1。

覆盖裁决 23 §3.1 / §4.3：
- life_stages 拆分（幼年 0–8、少年 8–12）与 schema 默认同步；
- 少年候选动作白名单 = farm/harvest/weave + eat/rest，不含 fish/hunt/borrow/collect_water；
- 9 岁少年 farm 可行、fish 不在候选；
- 少年劳作触发 work_capable 增加与 household_work_nodes_changed（田块扩容）；
- 进食份额不变（0.7 / 依赖年龄 16）；
- 回放/渲染不崩；
- 关掉少年劳作（work_allowed=false）可复现任务 19 seed1 基线（2 存活 / 8 饥饿死）。
"""
from __future__ import annotations

import random

import pytest

from vale.core.config_loader import load_config
from vale.core.event_log import EventLog
from vale.core.replay import rebuild_state
from vale.core.scheduler import run_tick
from vale.core.state import AgentState
from vale.core.world import World
from vale.modules.agents import AgentModule
from vale.modules.climate import ClimateModule
from vale.observability.render import render_event

TICKS_PER_YEAR = 360


def _build(seed: int = 0) -> World:
    cfg = load_config("brookvale-town-001")
    world = World(world_id=cfg.world.world_id, event_log=EventLog(":memory:"),
                  start_tick=cfg.world.start_tick, config=cfg)
    world.register(ClimateModule(rng=random.Random(seed)))
    world.register(AgentModule(rng=random.Random(seed * 7 + 13)))
    return world


@pytest.fixture
def world():
    w = _build(0)
    run_tick(w)
    return w


def _module(world) -> AgentModule:
    return next(m for m in world.modules if m.name == "agents")  # type: ignore[return-value]


def _add_child(world, agent_id: str, age: int, household_id: str = "hh_lin_yuan") -> AgentState:
    tuning = world.config.agents.tuning
    child = AgentState(
        agent_id=agent_id, name=agent_id, sex="female",
        birth_tick=world.current_tick - age * TICKS_PER_YEAR,
        household_id=household_id, location="well",
        health=70.0, hunger=40.0, stamina=40.0, alive=True,
        life_stage=tuning.aging.stage_for(age).name,
    )
    world.state.agents[agent_id] = child
    world.state.households[household_id].member_ids.append(agent_id)
    return child


# --------------------------------------------------------------------------- #
# 分段与白名单
# --------------------------------------------------------------------------- #
def test_life_stages_split_and_defaults(world):
    tuning = world.config.agents.tuning
    stages = {s.name: s for s in tuning.aging.life_stages}
    assert {"幼年", "少年", "青年", "壮年", "老年"} <= set(stages)
    assert stages["幼年"].max_age == 8
    assert stages["幼年"].work_allowed is False
    youth = stages["少年"]
    assert youth.min_age == 8 and youth.max_age == 12
    assert youth.work_allowed is True
    assert youth.allowed_actions == ["farm", "harvest", "weave"]
    assert youth.stamina_max_mult == pytest.approx(0.60)
    assert youth.stamina_recovery_mult == pytest.approx(0.80)
    assert youth.health_max_mult == pytest.approx(0.70)
    assert youth.injury_risk_mult == pytest.approx(0.5)


def test_youth_candidate_actions_whitelist(world):
    module = _module(world)
    tuning = world.config.agents.tuning
    youth = _add_child(world, "youth8", age=8)
    actions = module._candidate_actions_for(youth, tuning)  # noqa: SLF001
    assert actions == ["eat", "rest", "farm", "harvest", "weave"]
    for forbidden in ("fish", "hunt", "borrow_grain", "collect_water"):
        assert forbidden not in actions


def test_infant_still_eat_rest(world):
    module = _module(world)
    tuning = world.config.agents.tuning
    infant = _add_child(world, "infant6", age=6)
    assert module._candidate_actions_for(infant, tuning) == ["eat", "rest"]  # noqa: SLF001


def test_youth_farm_feasible_fish_absent(world):
    module = _module(world)
    tuning = world.config.agents.tuning
    youth = _add_child(world, "youth9", age=9)
    youth.stamina = 60.0
    youth.hunger = 40.0
    work_node = world.state.households["hh_lin_yuan"].work_node
    world.state.field_growth[work_node] = 0.0
    p = module._perceive(world, youth)  # noqa: SLF001
    assert module.score_action("farm", p, tuning) != float("-inf")
    assert "fish" not in module._candidate_actions_for(youth, tuning)  # noqa: SLF001


# --------------------------------------------------------------------------- #
# 田块扩容
# --------------------------------------------------------------------------- #
def test_youth_increases_work_capacity_and_fields(world):
    module = _module(world)
    tuning = world.config.agents.tuning
    household = world.state.households["hh_lin_yuan"]
    before_capable = module._work_capable_count(world, household, tuning)  # noqa: SLF001
    before_nodes = len(household.work_nodes)
    _add_child(world, "youth10", age=10)
    run_tick(world)
    after_capable = module._work_capable_count(world, household, tuning)  # noqa: SLF001
    assert after_capable == before_capable + 1
    assert len(household.work_nodes) >= before_nodes
    events = [e for e in world.event_log.by_type("household_work_nodes_changed")
              if e["payload"].get("household_id") == "hh_lin_yuan"]
    assert events, "少年劳作应触发家庭田块扩容事件"
    payload = events[-1]["payload"]
    assert payload["work_capable_members"] == after_capable
    assert len(payload["after"]) >= len(payload["before"])


def test_minor_food_share_and_dependency_unchanged(world):
    tuning = world.config.agents.tuning
    assert tuning.consumption.minor_food_share == pytest.approx(0.7)
    assert tuning.dependency.max_age == 16


# --------------------------------------------------------------------------- #
# 回放 / 渲染
# --------------------------------------------------------------------------- #
def test_youth_actions_replay_and_render(world):
    module = _module(world)
    tuning = world.config.agents.tuning
    youth = _add_child(world, "youth11", age=11)
    youth.stamina = 60.0
    p = module._perceive(world, youth)  # noqa: SLF001
    assert module._candidate_actions_for(youth, tuning)  # noqa: SLF001
    for _ in range(8):
        run_tick(world)
    rebuild_state(world.event_log.all(), world.config)
    farm_events = [e for e in world.event_log.by_type("agent_action_taken")
                   if e["payload"]["agent_id"] == "youth11" and e["payload"]["action"] == "farm"]
    if farm_events:
        r = render_event(farm_events[-1])
        assert r.degraded is False


# --------------------------------------------------------------------------- #
# 确定性：关掉少年劳作 → 复现 seed1 基线
# --------------------------------------------------------------------------- #
def test_disabled_youth_labor_reproduces_baseline():
    world = _build(seed=1)
    for stage in world.config.agents.tuning.aging.life_stages:
        if stage.name == "少年":
            stage.work_allowed = False
            stage.allowed_actions = None
    for _ in range(3600):
        run_tick(world)
    alive = sum(1 for a in world.state.agents.values() if a.alive)
    starv = sum(1 for e in world.event_log.by_type("agent_died")
                if e["payload"].get("cause") == "starvation")
    # 004 一次切换后重定基线（旧 1 动作/日 基线作废；移动扣 TU + 任务30 用水后重测）：
    # seed=1 × 3600 → 存活 10、饿死 5
    assert alive == 10
    assert starv == 5
