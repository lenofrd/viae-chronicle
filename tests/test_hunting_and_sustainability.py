"""任务 09 测试：经济可持续性平衡 + 打猎生计 + 扩展点。

覆盖：候选动作配置驱动、hunt 目标节点与户外属性、打猎产出肉与守恒、
eat 多食物优先级、受伤不致死、季节/天气修正、无负不变量、借粮守恒、
1080 tick 不全员灭绝、扩展点（新增第二采集动作不改核心结算）、观察层渲染。
全部用临时 db（:memory:）。
"""
from __future__ import annotations

from household_helpers import hh
from vale.core.household import home_node_of, work_node_of

import random

import pytest

from config.schema.agents import GatheringActionTuning
from config.schema.natural_params import Season, WeatherType
from vale.core.config_loader import load_config
from vale.core.event_log import EventLog
from vale.core.scheduler import run_tick
from vale.core.world import World
from vale.modules.agents import IMPOSSIBLE, AgentModule, _candidate_actions, _target_node
from vale.modules.climate import ClimateModule
from vale.observability.render import render_event


def _build(seed: int = 0) -> World:
    cfg = load_config("brookvale-town-001")
    log = EventLog(":memory:")
    w = World(world_id=cfg.world.world_id, event_log=log,
              start_tick=cfg.world.start_tick, config=cfg)
    w.register(ClimateModule(rng=random.Random(seed)))
    w.register(AgentModule(rng=random.Random(seed * 7 + 13)))
    return w


@pytest.fixture
def world():
    w = _build(0)
    # 任务12：采集/进食单元测试隔离婚配合并（家庭机制由 task12 专项覆盖）
    for m in w.modules:
        if m.name == "agents":
            m._settle_marriage = lambda *a, **k: None  # noqa: SLF001
    run_tick(w)  # 初始化 agents / climate
    return w


def _module(world) -> AgentModule:
    return next(m for m in world.modules if m.name == "agents")  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# 机制：候选动作 / 目标节点 / 户外属性（配置驱动，不写死 hunt）
# --------------------------------------------------------------------------- #
def test_hunt_in_candidate_actions(world):
    assert "hunt" in _candidate_actions(world.config.agents.tuning)


def test_hunt_target_node_is_low_mountain(world):
    agent = next(iter(world.state.agents.values()))
    assert _target_node("hunt", agent, world) == "low_mountain"


def test_hunt_is_outdoor_action(world):
    assert "hunt" in world.config.agents.tuning.action.outdoor


def test_no_hardcoded_hunt_branch_in_candidates():
    """候选动作来自配置 gathering.actions，而非硬编码列表。"""
    cfg = load_config("brookvale-town-001")
    # 清空采集动作后 hunt 不应出现在候选（证明是配置驱动）
    cfg.agents.tuning.gathering.actions.clear()
    assert "hunt" not in _candidate_actions(cfg.agents.tuning)


# --------------------------------------------------------------------------- #
# 打猎产出与守恒
# --------------------------------------------------------------------------- #
def test_hunt_action_occurs(world):
    """田封顶 + 饱腹的农闲窗口应出猎（任务10：打猎为远征型经济动作，
    仅在 farm 不可行（封顶）且 hunger 低（eat 不迫切）时胜出）。"""
    cap = world.config.agents.tuning.agriculture.max_field_growth
    for a in world.state.agents.values():
        world.state.field_growth[work_node_of(world, a)] = cap
    for _ in range(120):
        run_tick(world)
    actions = [e["payload"].get("action") for e in world.event_log.by_type("agent_action_taken")]
    assert "hunt" in actions


def test_gather_success_produces_meat(world):
    cap = world.config.agents.tuning.agriculture.max_field_growth
    for a in world.state.agents.values():
        world.state.field_growth[work_node_of(world, a)] = cap
    for _ in range(120):
        run_tick(world)
    succ = [e for e in world.event_log.by_type("gather_success")
            if e["payload"]["action"] == "hunt"]
    assert succ, "120 天内应至少打猎成功一次"
    # 产出守恒：单事件 output_after - output_before == amount
    e = succ[0]["payload"]
    assert round(e["output_after"] - e["output_before"], 4) == round(e["amount"], 4)
    assert e["output_field"] == "meat"


def test_meat_is_non_negative(world):
    for _ in range(120):
        run_tick(world)
    assert all(hh(world, a).meat >= 0 for a in world.state.agents.values())


# --------------------------------------------------------------------------- #
# eat 多食物守恒消耗
# --------------------------------------------------------------------------- #
def test_eat_prefers_grain_over_meat(world):
    agent = next(iter(world.state.agents.values()))
    hh(world, agent).grain = 5.0
    hh(world, agent).meat = 5.0
    agent.hunger = 90.0
    p = _module(world)._perceive(world, agent)
    _module(world)._execute(world, agent, "eat", p, world.config.agents.tuning)
    assert hh(world, agent).grain == 4.0
    assert hh(world, agent).meat == 5.0  # 粮够时不动肉


def test_eat_consumes_meat_when_grain_insufficient(world):
    agent = next(iter(world.state.agents.values()))
    hh(world, agent).grain = 0.0
    hh(world, agent).meat = 5.0
    agent.hunger = 90.0
    p = _module(world)._perceive(world, agent)
    _module(world)._execute(world, agent, "eat", p, world.config.agents.tuning)
    assert hh(world, agent).grain == 0.0
    assert hh(world, agent).meat == 4.0


def test_eat_drains_largest_food_when_none_sufficient(world):
    """所有食物字段都 < cost 时，吃尽存量最多的字段，不产生负值。"""
    agent = world.state.agents["lin_yuan"]
    hh(world, agent).grain = 0.3
    hh(world, agent).meat = 0.0
    hh(world, agent).fish = 0.0
    hh(world, agent).vegetable = 0.0
    agent.hunger = 90.0
    p = _module(world)._perceive(world, agent)
    _module(world)._execute(world, agent, "eat", p, world.config.agents.tuning)
    assert hh(world, agent).grain == 0.0
    assert hh(world, agent).meat == 0.0


def test_eat_impossible_when_no_food(world):
    agent = world.state.agents["lin_yuan"]
    hh(world, agent).grain = 0.0
    hh(world, agent).meat = 0.0
    hh(world, agent).fish = 0.0
    hh(world, agent).vegetable = 0.0
    agent.hunger = 90.0
    p = _module(world)._perceive(world, agent)
    score = _module(world).score_action("eat", p, world.config.agents.tuning)
    assert score == IMPOSSIBLE


# --------------------------------------------------------------------------- #
# 受伤不致死
# --------------------------------------------------------------------------- #
def test_gather_injury_does_not_kill(world):
    """强制受伤触发时，健康不会降到 0 以下（max(0, ...)）。"""
    mod = _module(world)
    agent = next(iter(world.state.agents.values()))
    agent.health = 10.0
    p = mod._perceive(world, agent)
    tuning = world.config.agents.tuning
    cfg = tuning.gathering.actions["hunt"]
    # 把受伤概率拉满，rng 固定返回 0 必触发
    cfg.injury_risk = 1.0
    cfg.injury_health_loss = 15.0
    mod.rng = random.Random(0)  # 前两个 random()：success、injury 都 < 1.0
    mod._execute_gather(world, agent, "hunt", p, tuning)
    assert agent.health == 0.0  # 10-15 被 clamp 到 0，不为负
    assert world.event_log.by_type("gather_injury")


def test_gather_success_when_rate_full(world):
    """base_success_rate=1 且无季节/天气惩罚时必成功。"""
    mod = _module(world)
    agent = next(iter(world.state.agents.values()))
    p = mod._perceive(world, agent)
    tuning = world.config.agents.tuning
    cfg = tuning.gathering.actions["hunt"]
    cfg.base_success_rate = 1.0
    cfg.season_modifier = {}
    cfg.injury_risk = 0.0
    meat_before = hh(world, agent).meat
    mod._execute_gather(world, agent, "hunt", p, tuning)
    assert hh(world, agent).meat == meat_before + cfg.output_amount
    assert world.event_log.by_type("gather_success")


def test_gather_fail_when_season_zeroes_rate(world):
    """季节修正把成功率乘到 0 时必失败。"""
    mod = _module(world)
    agent = next(iter(world.state.agents.values()))
    p = mod._perceive(world, agent)
    tuning = world.config.agents.tuning
    cfg = tuning.gathering.actions["hunt"]
    cfg.base_success_rate = 1.0
    cfg.season_modifier = {p.season.value: 0.0}
    cfg.injury_risk = 0.0
    meat_before = hh(world, agent).meat
    mod._execute_gather(world, agent, "hunt", p, tuning)
    assert hh(world, agent).meat == meat_before  # 失败不产出
    assert world.event_log.by_type("gather_fail")


# --------------------------------------------------------------------------- #
# 不变量：无负值 / 借粮守恒
# --------------------------------------------------------------------------- #
def test_no_negative_grain_meat_debt_over_200_ticks(world):
    for _ in range(200):
        run_tick(world)
    for a in world.state.agents.values():
        assert hh(world, a).grain >= 0
        assert hh(world, a).meat >= 0
        assert hh(world, a).debt >= 0
    assert not world.event_log.by_type("agent_error")


def test_borrow_conserves_grain_over_200_ticks(world):
    for _ in range(200):
        run_tick(world)
    formed = sum(e["payload"]["amount"] for e in world.event_log.by_type("debt_formed"))
    repaid = sum(e["payload"].get("amount", 0) for e in world.event_log.by_type("debt_repaid"))
    collected = sum(e["payload"].get("amount_paid", 0) for e in world.event_log.by_type("debt_collected"))
    # 任务11：第 4 NPC 无田可耕，可能借粮后亡故，债务被核销（debt_forgiven），须计入守恒
    forgiven = sum(e["payload"].get("amount", 0) for e in world.event_log.by_type("debt_forgiven"))
    outstanding = sum(hh(world, a).debt for a in world.state.agents.values())
    assert abs(formed - repaid - collected - forgiven - outstanding) < 1e-6


# --------------------------------------------------------------------------- #
# 1080 tick 不全员灭绝（验收核心）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("seed", [0, 1, 7, 42, 123])
def test_1080_ticks_not_all_extinct(seed):
    """1080 tick 不全员灭绝（阶段三验收：技术债断言已恢复）。"""
    w = _build(seed)
    curve: list[int] = []
    for tick in range(1, 1081):
        run_tick(w)
        if tick % 200 == 0:
            curve.append(sum(1 for a in w.state.agents.values() if a.alive))
    survivors = [a for a in w.state.agents.values() if a.alive]
    assert survivors, f"seed={seed} 全员灭绝，违反可持续性下限"
    assert len(curve) == 5  # 每 200 tick 采样一次
    assert all(count >= 0 for count in curve)
    # 不变量（任务10：fish 加入守恒集合）
    assert all(hh(w, a).grain >= 0 and hh(w, a).meat >= 0 and hh(w, a).fish >= 0 and hh(w, a).debt >= 0
               for a in w.state.agents.values())
    assert not w.event_log.by_type("agent_error")
    # 失能/死亡事件幂等：每人至多一次
    for evt_type in ("agent_incapacitated", "agent_died"):
        ids = [e["payload"]["agent_id"] for e in w.event_log.by_type(evt_type)]
        assert len(ids) == len(set(ids)), f"{evt_type} 事件重复"


# --------------------------------------------------------------------------- #
# 扩展点：新增第二采集动作（fish）不改核心结算
# --------------------------------------------------------------------------- #
def test_candidate_actions_include_newly_configured_gather(world):
    """在 gathering.actions 加 fish，候选动作自动包含，无需改核心代码。"""
    tuning = world.config.agents.tuning
    tuning.gathering.actions["fish"] = GatheringActionTuning(
        target_node="well", output_field="meat", base_success_rate=1.0,
        output_amount=3, injury_risk=0.0, bad_weather_success_mult=1.0,
        bad_weather_injury_mult=1.0,
    )
    assert "fish" in _candidate_actions(tuning)
    agent = next(iter(world.state.agents.values()))
    assert _target_node("fish", agent, world) == "well"


def test_execute_gather_works_for_arbitrary_action_name(world):
    """_execute_gather 通用分支对任意配置动作（fish）生效，不写死 hunt。"""
    mod = _module(world)
    agent = next(iter(world.state.agents.values()))
    tuning = world.config.agents.tuning
    tuning.gathering.actions["fish"] = GatheringActionTuning(
        target_node="well", output_field="meat", base_success_rate=1.0,
        output_amount=3, injury_risk=0.0, bad_weather_success_mult=1.0,
        bad_weather_injury_mult=1.0,
    )
    p = mod._perceive(world, agent)
    meat_before = hh(world, agent).meat
    mod._execute_gather(world, agent, "fish", p, tuning)
    assert hh(world, agent).meat == meat_before + 3
    fish_evts = [e for e in world.event_log.by_type("gather_success")
                 if e["payload"]["action"] == "fish"]
    assert fish_evts


def test_core_settlement_still_runs_after_adding_action(world):
    """新增 fish 动作后，_settle（催收/回血）照常执行，未被绕过。"""
    tuning = world.config.agents.tuning
    tuning.gathering.actions["fish"] = GatheringActionTuning(
        target_node="well", output_field="meat", base_success_rate=1.0,
        output_amount=3, injury_risk=0.0, bad_weather_success_mult=1.0,
        bad_weather_injury_mult=1.0,
    )
    for _ in range(120):
        run_tick(world)
    # 核心结算事件仍出现（健康回血 / 债务事件）
    assert world.event_log.by_type("health_recovered")
    # 无结算错误
    assert not world.event_log.by_type("agent_error")


# --------------------------------------------------------------------------- #
# 观察层渲染（任务 §6.6）
# --------------------------------------------------------------------------- #
def test_render_gather_success():
    evt = {"event_type": "gather_success", "payload": {
        "agent_id": "lin_yuan", "agent_name": "林远", "action": "hunt",
        "resource_node": "low_mountain", "output_field": "meat",
        "output_before": 0, "output_after": 5, "amount": 5, "success_rate": 0.5}}
    r = render_event(evt)
    assert not r.degraded
    assert "打猎" in r.text and "肉" in r.text


def test_render_gather_fail_and_injury():
    f = {"event_type": "gather_fail", "payload": {
        "agent_id": "lin_yuan", "agent_name": "林远", "action": "hunt",
        "resource_node": "low_mountain", "reason": "未获猎物", "success_rate": 0.1}}
    assert not render_event(f).degraded and "打猎" in render_event(f).text
    i = {"event_type": "gather_injury", "payload": {
        "agent_id": "lin_yuan", "agent_name": "林远", "action": "hunt",
        "resource_node": "low_mountain", "health_before": 80, "health_after": 65, "loss": 15}}
    r = render_event(i)
    assert not r.degraded and "受伤" in r.text


def test_render_hunt_action_line():
    evt = {"event_type": "agent_action_taken", "payload": {
        "agent_name": "林远", "action": "hunt", "target_node": "low_mountain",
        "meat_after": 5}}
    r = render_event(evt, names={"low_mountain": "浅山"})
    assert not r.degraded and "打猎" in r.text


def test_render_unknown_event_still_falls_back():
    evt = {"event_type": "future_event", "payload": {"a": 1}}
    r = render_event(evt)
    assert r.degraded and r.reason == "unknown_event_type"
