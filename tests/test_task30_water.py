"""任务 30 测试：水模型最小切片（004 §2.7）。

覆盖：初始水文、日演化（雨升/旱降/夹紧）、灌溉档四档与变更事件、
collect_water 产水与守恒、日耗按成员数扣减、moisture 接入产量、坏配置报错、回放。
全部内存事件库，种子固定。
"""
from __future__ import annotations

from household_helpers import hh
from vale.core.household import work_node_of

import random

import pytest
from pydantic import ValidationError

from household_helpers import attach_test_resource_pools
from vale.config.schema.natural_params import HydrologyEvolutionParams, Season
from vale.core.config_loader import load_config
from vale.core.event_log import EventLog
from vale.core.replay import rebuild_state
from vale.core.scheduler import run_tick
from vale.core.world import World
from vale.domains.society.agents import AgentModule, SpatialIndex, expected_yield
from vale.domains.environment.climate import ClimateModule


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
    run_tick(w)  # 初始化 climate / hydrology / agents
    return w


def _module(world) -> AgentModule:
    mod = next(m for m in world.modules if m.name == "agents")
    if mod._spatial is None:  # noqa: SLF001
        mod._spatial = SpatialIndex(world.config.spatial)  # noqa: SLF001
    return mod


def _climate(world) -> ClimateModule:
    return next(m for m in world.modules if m.name == "climate")


# =========================================================================== #
# 初始与演化
# =========================================================================== #
def test_hydrology_initialized_from_config():
    """开局水文取 natural-params.hydrology_initial：0.60 / low（首次 step 前初始化）。"""
    w = _build(0)
    _climate(w)._ensure_initialized(w)  # noqa: SLF001
    assert w.state.environment.water_level_ratio == pytest.approx(0.60)
    assert w.state.environment.irrigation_gear == "low"


def test_rain_raises_and_dry_lowers_water(world):
    mod = _climate(world)
    cfg = world.config.natural_params
    recharge = cfg.hydrology_evolution.recharge_per_mm
    world.state.environment.water_level_ratio = 0.50

    mod._evolve_hydrology(world, cfg, 20.0)  # 按剩余空间补水：0.5 + k×20×(1−0.5)
    assert world.state.environment.water_level_ratio == pytest.approx(0.50 + recharge * 20.0 * 0.5)

    mid = world.state.environment.water_level_ratio
    mod._evolve_hydrology(world, cfg, 0.0)  # 无雨：−dry_loss_per_day
    assert world.state.environment.water_level_ratio == pytest.approx(
        mid - cfg.hydrology_evolution.dry_loss_per_day
    )


def test_water_level_stays_in_unit_interval(world):
    mod = _climate(world)
    cfg = world.config.natural_params
    world.state.environment.water_level_ratio = 0.90
    for _ in range(200):  # 持续暴雨：渐近 1.0，但绝不越界
        mod._evolve_hydrology(world, cfg, 100.0)
        assert 0.0 <= world.state.environment.water_level_ratio <= 1.0
    assert world.state.environment.water_level_ratio > 0.99

    world.state.environment.water_level_ratio = 0.001
    mod._evolve_hydrology(world, cfg, 0.0)
    assert world.state.environment.water_level_ratio == pytest.approx(0.0)


def test_gear_maps_to_four_levels(world):
    mod = _climate(world)
    thr = world.config.natural_params.hydrology_evolution.gear_thresholds
    assert mod._classify_irrigation(0.90, thr) == "abundant"
    assert mod._classify_irrigation(0.60, thr) == "low"
    assert mod._classify_irrigation(0.35, thr) == "scarce"
    assert mod._classify_irrigation(0.10, thr) == "dry"


def test_gear_event_only_when_level_crosses_threshold(world):
    """水位每变必写 water_level_changed；灌溉档仅在跨档时写事件。"""
    mod = _climate(world)
    cfg = world.config.natural_params
    world.state.environment.water_level_ratio = 0.54
    world.state.environment.irrigation_gear = "scarce"
    before = len(world.event_log.by_type("irrigation_gear_changed"))

    mod._evolve_hydrology(world, cfg, 20.0)  # 0.54 + 0.20 = 0.74 → low
    after = world.event_log.by_type("irrigation_gear_changed")
    assert len(after) == before + 1
    assert after[-1]["payload"]["from"] == "scarce"
    assert after[-1]["payload"]["to"] == "low"

    mod._evolve_hydrology(world, cfg, 0.0)  # 0.736 仍在 low
    assert len(world.event_log.by_type("irrigation_gear_changed")) == before + 1


# =========================================================================== #
# collect_water 产出与日耗
# =========================================================================== #
def test_collect_water_produces_configured_amount(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.human.agents["lin_yuan"]
    lin.stamina = 100.0
    household = hh(world, lin)
    household.water = 0.0
    world.state.environment.water_level_ratio = 0.0  # 河流水位不是地下水位；不改变井水取水量
    p = mod._perceive(world, lin)  # noqa: SLF001

    mod._execute(world, lin, "collect_water", p, tuning)  # noqa: SLF001

    assert household.water == pytest.approx(tuning.water.collect_amount)
    ev = world.event_log.by_type("agent_action_taken")[-1]["payload"]
    assert ev["action"] == "collect_water"
    assert ev["target_node"] == "well"
    assert ev["water_before"] == pytest.approx(0.0)
    assert ev["water_after"] == pytest.approx(tuning.water.collect_amount)


def test_collect_water_returns_carrier_home_after_fetch(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.human.agents["lin_yuan"]
    household = hh(world, lin)
    lin.location = household.home_node
    p = mod._perceive(world, lin)  # noqa: SLF001

    mod._execute(world, lin, "collect_water", p, tuning)  # noqa: SLF001

    assert lin.location == household.home_node
    next_perception = mod._perceive(world, lin)  # noqa: SLF001
    assert next_perception.distance_from_location["well"] == pytest.approx(
        p.distance_from_location["well"]
    )


def test_seasonal_water_reserve_targets_cover_unreachable_periods(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.human.agents["lin_yuan"]
    p = mod._perceive(world, lin)  # noqa: SLF001
    daily_need = p.household_daily_water_need

    p.well_distance_from_home = 4.2
    p.season = Season.SPRING
    p.season_progress = 0.5
    assert mod._water_reserve_target(p, tuning) == pytest.approx(daily_need * 90)
    p.season_progress = 1.0
    assert mod._water_reserve_target(p, tuning) == pytest.approx(daily_need * 180)

    p.well_distance_from_home = 3.0
    p.season = Season.AUTUMN
    p.season_progress = 1.0
    assert mod._water_reserve_target(p, tuning) == pytest.approx(daily_need * 90)

    p.well_distance_from_home = 2.0
    p.season = Season.WINTER
    assert mod._water_reserve_target(p, tuning) == pytest.approx(daily_need)


def test_water_shortage_is_recorded_without_health_penalty(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.human.agents["lin_yuan"]
    household = hh(world, lin)
    household.water = 0.0
    health_before = lin.health

    mod._settle_water(world, tuning)  # noqa: SLF001

    shortage = [
        event["payload"] for event in world.event_log.by_type("water_shortage")
        if event["payload"]["household_id"] == household.household_id
    ]
    assert shortage
    assert shortage[-1]["shortage"] > 0
    assert shortage[-1]["health_penalty_applied"] is False
    assert lin.health == pytest.approx(health_before)


def test_daily_water_consumption_per_member(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.human.agents["lin_yuan"]
    household = hh(world, lin)
    household.water = 10.0
    living = [m for m in household.member_ids
              if world.state.human.agents.get(m) and world.state.human.agents[m].alive]

    mod._settle_water(world, tuning)  # noqa: SLF001

    need = tuning.water.daily_consumption_per_member * len(living)
    assert household.water == pytest.approx(10.0 - need)
    ev = [
        e["payload"] for e in world.event_log.by_type("water_consumed")
        if e["payload"]["household_id"] == household.household_id
        and e["tick"] == world.current_tick
    ][-1]
    assert ev["amount"] == pytest.approx(need)


def test_daily_consumption_floors_at_zero(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    household = hh(world, world.state.human.agents["lin_yuan"])
    household.water = 0.5
    before_events = len(world.event_log.by_type("water_consumed"))

    mod._settle_water(world, tuning)  # noqa: SLF001

    assert household.water == pytest.approx(0.0)
    new = [
        e["payload"] for e in world.event_log.by_type("water_consumed")[before_events:]
        if e["payload"]["household_id"] == household.household_id
    ]
    assert new and new[-1]["amount"] <= 0.5
    assert new[-1]["after"] == pytest.approx(0.0)


def test_water_conservation_production_minus_consumption_equals_stock(world):
    """产出 − 日耗 = 存量增量（逐事件可对账）。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.human.agents["lin_yuan"]
    household = hh(world, lin)
    household.water = 0.0
    lin.stamina = 100.0
    p = mod._perceive(world, lin)  # noqa: SLF001
    mod._execute(world, lin, "collect_water", p, tuning)  # noqa: SLF001
    ev = world.event_log.by_type("agent_action_taken")[-1]["payload"]
    produced = ev["water_after"] - ev["water_before"]

    before_consumption_events = len(world.event_log.by_type("water_consumed"))
    mod._settle_water(world, tuning)  # noqa: SLF001
    consumed = sum(
        e["payload"]["amount"] for e in world.event_log.by_type("water_consumed")[before_consumption_events:]
        if e["payload"]["household_id"] == household.household_id
        and e["tick"] == world.current_tick
    )
    assert produced - consumed == pytest.approx(household.water)


# =========================================================================== #
# moisture 接入产量
# =========================================================================== #
def test_moisture_scales_expected_yield(world):
    tuning = world.config.agents.tuning
    table = world.config.natural_params.hydrology_evolution.moisture_by_gear
    world.state.environment.fertility_factor["east_field"] = 1.0

    world.state.environment.irrigation_gear = "abundant"
    assert expected_yield(world, "east_field", "grain", tuning) == pytest.approx(
        tuning.agriculture.base_yield["grain"] * table["abundant"]
    )
    world.state.environment.irrigation_gear = "dry"
    assert expected_yield(world, "east_field", "grain", tuning) == pytest.approx(
        tuning.agriculture.base_yield["grain"] * table["dry"]
    )


def test_harvest_payload_carries_moisture(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    zhao = world.state.human.agents["zhao_cuilan"]
    zhao.stamina = 100.0
    world.state.environment.climate.season = Season.AUTUMN
    world.state.environment.field_growth[work_node_of(world, zhao)] = 90.0
    world.state.environment.irrigation_gear = "scarce"
    p = mod._perceive(world, zhao)  # noqa: SLF001

    mod._execute(world, zhao, "harvest", p, tuning)  # noqa: SLF001

    ev = world.event_log.by_type("agent_action_taken")[-1]["payload"]
    assert ev["moisture"] == pytest.approx(
        world.config.natural_params.hydrology_evolution.moisture_by_gear["scarce"]
    )


# =========================================================================== #
# 水的用途（老板裁决「选 b」）：烹饪需水 + 缺水驱动打水
# =========================================================================== #
def test_eat_infeasible_without_cooking_water(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.human.agents["lin_yuan"]
    household = hh(world, lin)
    household.grain = 5.0
    for f in tuning.physiology.food_fields:
        if f != "grain":
            setattr(household, f, 0.0)
    household.water = 0.0
    p = mod._perceive(world, lin)  # noqa: SLF001
    assert mod.score_action("eat", p, tuning) == float("-inf")

    household.water = tuning.water.water_per_meal
    lin.hunger = (
        tuning.physiology.hunger_health_damage_threshold
        - tuning.physiology.hunger_gain_per_tick
    )
    p = mod._perceive(world, lin)  # noqa: SLF001
    assert mod.score_action("eat", p, tuning) > float("-inf")


def test_survival_gate_fetches_water_before_eating(world):
    """有粮无水且饥饿将跨阈值 → 门控直接去打水（而非饿着）。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    phys = tuning.physiology
    lin = world.state.human.agents["lin_yuan"]
    household = hh(world, lin)
    household.grain = 5.0
    for f in phys.food_fields:
        if f != "grain":
            setattr(household, f, 0.0)
    household.water = 0.0
    lin.hunger = phys.hunger_health_damage_threshold - 1.0
    lin.stamina = 100.0
    p = mod._perceive(world, lin)  # noqa: SLF001
    assert mod._decide(p, tuning, tu_remaining=10.0) == "collect_water"  # noqa: SLF001


def test_eat_consumes_cooking_water(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.human.agents["lin_yuan"]
    household = hh(world, lin)
    household.water = 2.0
    lin.hunger = 70.0
    p = mod._perceive(world, lin)  # noqa: SLF001

    mod._execute(world, lin, "eat", p, tuning)  # noqa: SLF001

    assert household.water == pytest.approx(2.0 - tuning.water.water_per_meal)
    ev = world.event_log.by_type("agent_action_taken")[-1]["payload"]
    assert ev["water_before"] - ev["water_after"] == pytest.approx(
        tuning.water.water_per_meal
    )


def test_collect_water_scarcity_bonus(world):
    """家庭存水低于目标时，打水得分随缺水程度上升。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.human.agents["lin_yuan"]
    household = hh(world, lin)
    lin.stamina = 100.0
    household.water = 0.0
    p0 = mod._perceive(world, lin)  # noqa: SLF001
    dry_score = mod.score_action("collect_water", p0, tuning)

    household.water = tuning.water.household_stock_target
    p1 = mod._perceive(world, lin)  # noqa: SLF001
    full_score = mod.score_action("collect_water", p1, tuning)
    assert dry_score - full_score == pytest.approx(tuning.water.scarcity_weight)


# =========================================================================== #
# 坏配置
# =========================================================================== #
def test_bad_gear_thresholds_rejected():
    with pytest.raises(ValidationError):
        HydrologyEvolutionParams(gear_thresholds={"abundant": 0.5, "low": 0.8, "scarce": 0.3})


def test_missing_moisture_gear_rejected():
    with pytest.raises(ValidationError):
        HydrologyEvolutionParams(moisture_by_gear={"abundant": 1.0, "low": 0.8})


# =========================================================================== #
# 回放
# =========================================================================== #
def test_replay_restores_hydrology_and_household_water():
    cfg = load_config("brookvale-town-001")
    w = _build(0)
    for _ in range(20):
        run_tick(w)
    events = w.event_log.all()

    state = rebuild_state(events, cfg).state
    assert state.environment.water_level_ratio == pytest.approx(w.state.environment.water_level_ratio)
    assert state.environment.irrigation_gear == w.state.environment.irrigation_gear
    for hid, household in w.state.human.households.items():
        if hid in state.human.households:
            water_events = [
                event for event in events
                if event.get("payload", {}).get("household_id") == hid
                and ("water" in event.get("event_type", "") or "water_" in event.get("event_type", ""))
            ]
            assert state.human.households[hid].water == pytest.approx(household.water), (
                f"water replay mismatch for {hid}: runtime={household.water}, "
                f"replay={state.human.households[hid].water}; events={water_events}"
            )
