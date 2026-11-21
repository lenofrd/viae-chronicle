"""任务 29 测试：M5 日内 TU 循环 / 体力分级 / 位置语义 / 事件日内字段（004 落地）。

覆盖任务书 §3.4：
- 工作窗按季节取值；TU 预算耗尽终止；slot 连续；
- 重活 4 TU 归零、rest/闲时 1 TU 回满、无可行动作转闲时恢复；
- 位置链（家→田→…→家）与计距基点改为当前位置；
- 贪心可复现（同种子同事件流）；坏配置（重活缺 tu_cost）启动即报错；集市在场免赶路。
全部内存事件库。
"""
from __future__ import annotations

from vale.domains.society.households import home_node_of, work_node_of

import random

import pytest
from pydantic import ValidationError

from household_helpers import attach_test_resource_pools
from vale.config.schema.agents import ActionTuning
from vale.config.schema.natural_params import Season
from vale.core.config_loader import load_config
from vale.core.event_log import EventLog
from vale.core.scheduler import run_tick
from vale.core.world import World
from vale.domains.society.agents import AgentModule, SpatialIndex
from vale.domains.environment.climate import ClimateModule

WORK_WINDOW = {"spring": 10.0, "summer": 9.0, "autumn": 10.0, "winter": 6.0}


def _build(seed: int = 0) -> World:
    cfg = load_config("brookvale-town-001")
    w = World(world_id=cfg.world.world_id, event_log=EventLog(":memory:"),
              start_tick=cfg.world.start_tick, config=cfg)
    attach_test_resource_pools(w)
    w.register(ClimateModule(rng=random.Random(seed)))
    w.register(AgentModule(rng=random.Random(seed * 7 + 13)))
    return w


@pytest.fixture
def world():
    w = _build(0)
    run_tick(w)  # 初始化 agents / climate / 空间索引
    return w


def _module(world) -> AgentModule:
    mod = next(m for m in world.modules if m.name == "agents")
    if mod._spatial is None:  # noqa: SLF001
        mod._spatial = SpatialIndex(world.config.spatial)  # noqa: SLF001
    return mod


# =========================================================================== #
# 工作窗与日内预算
# =========================================================================== #
def test_work_window_follows_season(world):
    """工作窗取 natural-params.seasons.*.work_window_tu（春10/夏9/秋10/冬6）。"""
    mod = _module(world)
    for name, tu in WORK_WINDOW.items():
        world.state.environment.climate.season = Season(name)
        assert mod._work_window_tu(world) == pytest.approx(tu)  # noqa: SLF001


def test_daily_tu_budget_exhausted_with_contiguous_slots(world):
    """当日 TU 预算恰好耗尽（含闲时余量），slot 从 1 起连续。"""
    mod = _module(world)
    window = mod._work_window_tu(world)  # noqa: SLF001
    executed_tick = world.current_tick
    run_tick(world)
    events = [
        e for e in world.event_log.by_type("agent_action_taken")
        if e["tick"] == executed_tick
    ]
    for agent_id in world.state.human.agents:
        acts = [e["payload"] for e in events if e["payload"]["agent_id"] == agent_id]
        if not acts:
            continue
        assert [p["slot"] for p in acts] == list(range(1, len(acts) + 1))
        assert sum(p["tu_spent"] for p in acts) == pytest.approx(window)


# =========================================================================== #
# 体力分级：重活 Δ100 / 轻活 0 / rest 1 TU 回满
# =========================================================================== #
def test_heavy_action_drains_full_stamina(world):
    """farm 4 TU 重活 = 25×4 = 100 劳动体力，满体力执行后归零。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.human.agents["lin_yuan"]
    lin.stamina = 100.0
    world.state.environment.field_growth[work_node_of(world, lin)] = 0.0
    p = mod._perceive(world, lin)  # noqa: SLF001

    mod._execute(world, lin, "farm", p, tuning)  # noqa: SLF001

    ev = world.event_log.by_type("agent_action_taken")[-1]["payload"]
    assert ev["labor_stamina"] == pytest.approx(100.0)
    assert ev["move_stamina"] > 0
    assert lin.stamina == pytest.approx(0.0)


def test_light_action_has_zero_labor_stamina(world):
    """轻活（weave）只占 TU，劳动体力为 0，仅扣移动。"""
    mod = _module(world)
    act = world.config.agents.tuning.action
    assert mod._labor_stamina("weave", act) == 0.0  # noqa: SLF001
    assert mod._labor_stamina("hunt", act) == pytest.approx(act.heavy_stamina_per_tu * act.tu_cost["hunt"])  # noqa: SLF001


def test_rest_refills_to_cap_in_one_tu(world):
    """rest 为 1 TU 回满（004），不再是线性 +40。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.human.agents["lin_yuan"]
    lin.stamina = 5.0
    p = mod._perceive(world, lin)  # noqa: SLF001

    mod._execute(world, lin, "rest", p, tuning)  # noqa: SLF001

    assert lin.stamina == pytest.approx(mod._stamina_cap(lin, tuning))  # noqa: SLF001
    ev = world.event_log.by_type("agent_action_taken")[-1]["payload"]
    assert ev["tu_spent"] == pytest.approx(1.0)
    assert ev["labor_stamina"] == 0.0


def test_idle_rest_consumes_remaining_tu_once(world, monkeypatch):
    """无可行动作 → 剩余 TU 一次性转闲时休整（单事件，不逐 TU 刷屏）。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.human.agents["lin_yuan"]
    monkeypatch.setattr(AgentModule, "_decide", lambda *a, **k: None)
    before = len(world.event_log.by_type("agent_action_taken"))

    mod._run_intraday(world, lin, tuning)  # noqa: SLF001

    new = world.event_log.by_type("agent_action_taken")[before:]
    assert len(new) == 1
    payload = new[0]["payload"]
    assert payload["action"] == "rest"
    assert payload["idle"] is True
    assert payload["tu_spent"] == pytest.approx(mod._work_window_tu(world))  # noqa: SLF001
    assert payload["tu_remaining"] == pytest.approx(0.0)
    assert lin.stamina == pytest.approx(mod._stamina_cap(lin, tuning))  # noqa: SLF001


# =========================================================================== #
# 位置语义
# =========================================================================== #
def test_location_follows_action_then_returns_home(world):
    """日内 location 停在动作目标；日末结算后统一回家。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.human.agents["lin_yuan"]
    lin.stamina = 100.0
    world.state.environment.field_growth[work_node_of(world, lin)] = 0.0
    p = mod._perceive(world, lin)  # noqa: SLF001

    mod._execute(world, lin, "farm", p, tuning)  # noqa: SLF001
    assert lin.location == work_node_of(world, lin)

    run_tick(world)
    for agent in world.state.human.agents.values():
        if agent.alive:
            assert agent.location == home_node_of(world, agent)


def test_perceive_distance_starts_from_current_location(world):
    """计距基点 = 人物当前位置（不再固定从家起算）。"""
    mod = _module(world)
    lin = world.state.human.agents["lin_yuan"]
    lin.location = "well"
    p = mod._perceive(world, lin)  # noqa: SLF001
    work = work_node_of(world, lin)
    assert p.distance_from_location[work] == pytest.approx(
        mod._spatial.travel_tu("well", work)  # noqa: SLF001
    )


def test_travel_tu_counts_against_work_window(world):
    """移动与动作同时占工作窗（老板裁决）：tu_spent = 动作 TU + 往返 TU。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.human.agents["lin_yuan"]
    lin.stamina = 100.0
    lin.location = "well"
    world.state.environment.field_growth[work_node_of(world, lin)] = 0.0
    p = mod._perceive(world, lin)  # noqa: SLF001
    travel = 2.0 * mod._spatial.travel_tu("well", work_node_of(world, lin))  # noqa: SLF001
    assert mod._tu_total("farm", p, tuning) == pytest.approx(4.0 + travel)  # noqa: SLF001

    mod._execute(world, lin, "farm", p, tuning)  # noqa: SLF001
    ev = world.event_log.by_type("agent_action_taken")[-1]["payload"]
    assert ev["round_trip_tu"] == pytest.approx(travel)
    assert ev["tu_spent"] == pytest.approx(4.0 + travel)


def test_decide_never_picks_action_exceeding_remaining_tu(world):
    """TU 不够往返的远途动作被过滤（距离因此成为时间约束）。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    p = mod._perceive(world, world.state.human.agents["lin_yuan"])  # noqa: SLF001
    for remaining in (1.0, 3.0, 5.0, 10.0):
        action = mod._decide(p, tuning, tu_remaining=remaining)  # noqa: SLF001
        if action is not None:
            assert mod._tu_total(action, p, tuning) <= remaining + 1e-9  # noqa: SLF001


# =========================================================================== #
# 可复现与配置校验
# =========================================================================== #
def test_intraday_greedy_reproducible_with_same_seed():
    """同种子两次运行产生完全相同的事件流（类型/tick/载荷）。"""

    def stream(seed: int) -> list[tuple[int, str, dict]]:
        w = _build(seed)
        for _ in range(60):
            run_tick(w)
        return [(e["tick"], e["event_type"], e["payload"]) for e in w.event_log.all()]

    assert stream(7) == stream(7)


def test_heavy_action_without_tu_cost_rejected():
    """重活必须在 tu_cost 中声明时长，坏配置直接报错。"""
    with pytest.raises(ValidationError):
        ActionTuning(tu_cost={"eat": 1}, heavy_actions=["farm"])


# =========================================================================== #
# 集市：当日已在集市免往返
# =========================================================================== #
def test_market_presence_waives_travel_stamina(world):
    """执行者当日已在 market（location==market）→ 赶路体力为 0。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    for agent in world.state.human.agents.values():
        agent.stamina = 100.0
        agent.location = tuning.market.market_node

    mod._settle_market(world, tuning)  # noqa: SLF001

    summary = world.event_log.by_type("market_day_summary")[-1]["payload"]
    assert summary["participants"]
    assert all(p["travel_stamina_cost"] == 0.0 for p in summary["participants"])
