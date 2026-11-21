"""P3b 写入契约测试：ResourceService（采集/取水）与 EcologicalImpact（灾害/野遇）。

覆盖：额度与存量校验、同 tick 累计上限、拒绝事件、未登记资源池的旧行为、
采集守恒（池减 = 家庭增）、四类生态影响的投影与事件、回放重建、渲染不降级。
"""
from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from household_helpers import hh
from vale.contracts.impacts import EcologicalImpact
from vale.contracts.resources import ResourceService
from vale.core.config_loader import LoadedConfig, load_config
from vale.core.event_log import EventLog
from vale.core.replay import rebuild_state
from vale.core.scheduler import run_tick
from vale.core.state import ResourcePoolState
from vale.core.world import World
from vale.domains.society.agents import AgentModule
from vale.domains.environment.climate import ClimateModule
from vale.domains.environment.resources import EcologyModule
from vale.domains.wildlife.wildlife import WildlifeModule
from vale.observability.render import render_event
from vale.world.xigu import (
    XiguGenerationConfig,
    build_xigu_agents_config,
    generate_xigu_town,
)


def _pool(**overrides) -> ResourcePoolState:
    pool = ResourcePoolState(
        resource_type="fish",
        current_stock=100.0,
        max_stock=100.0,
        regeneration_per_tick=0.0,
        extraction_limit_per_tick=10.0,
    )
    return pool.model_copy(update=overrides)


def _world(pool: ResourcePoolState | None = None) -> World:
    world = World("p3b", EventLog(":memory:"), start_tick=1, config=SimpleNamespace())
    if pool is not None:
        world.state.environment.ecological_resources["river_town"] = pool
    return world


def _sim(seed: int = 0) -> World:
    base = load_config("brookvale-town-001")
    generated = generate_xigu_town(
        XiguGenerationConfig(seed=seed), base_spatial=base.spatial
    )
    cfg = LoadedConfig(
        world=base.world,
        natural_params=base.natural_params,
        spatial=generated.spatial,
        agents=build_xigu_agents_config(generated, base.agents.tuning, base.agents),
        terrain=generated.terrain,
        resources=generated.resources,
    )
    world = World(cfg.world.world_id, EventLog(":memory:"), cfg.world.start_tick, cfg)
    world.register(ClimateModule(rng=random.Random(seed)))
    world.register(EcologyModule())
    world.register(WildlifeModule())
    world.register(AgentModule(rng=random.Random(seed * 7 + 13)))
    run_tick(world)  # 初始化资源池、家庭与人物
    return world


def _module(world: World) -> AgentModule:
    return next(m for m in world.modules if m.name == "agents")  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# ResourceService：额度、拒绝、旧行为
# --------------------------------------------------------------------------- #
def test_harvest_granted_and_event_pairs_stock():
    world = _world(_pool(current_stock=50.0, extraction_limit_per_tick=10.0))
    granted = ResourceService.harvest(
        world, "river_town", 4.0, agent_id="a1", household_id="hh1", action="fish",
    )
    assert granted == pytest.approx(4.0)
    pool = world.state.environment.ecological_resources["river_town"]
    assert pool.current_stock == pytest.approx(46.0)
    assert pool.harvested_this_tick == pytest.approx(4.0)
    event = world.event_log.by_type("resource_harvested")[-1]["payload"]
    assert event["stock_before"] == pytest.approx(50.0)
    assert event["stock_after"] == pytest.approx(46.0)
    assert event["amount"] == pytest.approx(4.0)
    # 守恒：事件前后差 == 实际给付
    assert round(event["stock_before"] - event["stock_after"], 6) == pytest.approx(granted)


def test_harvest_respects_same_tick_extraction_limit():
    world = _world(_pool(current_stock=100.0, extraction_limit_per_tick=10.0))
    assert ResourceService.harvest(world, "river_town", 6.0) == pytest.approx(6.0)
    assert ResourceService.harvest(world, "river_town", 6.0) == pytest.approx(4.0)
    assert ResourceService.harvest(world, "river_town", 1.0) == pytest.approx(0.0)
    refused = world.event_log.by_type("resource_harvest_refused")[-1]["payload"]
    assert refused["reason"] == "extraction_limit"
    assert refused["granted"] == 0.0

    # 跨 tick 重置额度
    world.current_tick += 1
    assert ResourceService.harvest(world, "river_town", 3.0) == pytest.approx(3.0)


def test_harvest_refuses_empty_stock_without_writing_state():
    world = _world(_pool(current_stock=0.0))
    granted = ResourceService.harvest(
        world, "river_town", 2.0, agent_id="a1", action="fish",
    )
    assert granted == 0.0
    pool = world.state.environment.ecological_resources["river_town"]
    assert pool.current_stock == 0.0
    assert not world.event_log.by_type("resource_harvested")
    refused = world.event_log.by_type("resource_harvest_refused")[-1]["payload"]
    assert refused["reason"] == "stock_depleted"


def test_harvest_without_registered_pool_is_refused():
    """2026-11-21 裁决：无池目录不等资源无限，未登记池一律拒绝（不再原额给付）。"""
    world = _world()
    assert ResourceService.is_resource_node(world, "well") is False
    with pytest.raises(ValueError, match="unregistered"):
        ResourceService.harvest(world, "well", 3.0)
    assert not world.event_log.by_type("resource_harvested")


# --------------------------------------------------------------------------- #
# 采集结算：池 → 家庭的配对守恒
# --------------------------------------------------------------------------- #
def test_gather_through_service_conserves_pool_and_household():
    world = _sim()
    module = _module(world)
    agent = world.state.human.agents["lin_yuan"]
    agent.location = "low_mountain"
    agent.stamina = 100.0
    cfg = world.config.agents.tuning.gathering.actions["hunt"]
    cfg.base_success_rate = 1.0
    cfg.season_modifier = {}
    cfg.injury_risk = 0.0

    pool = world.state.environment.ecological_resources["low_mountain"]
    stock_before = float(pool.current_stock)
    meat_before = hh(world, agent).meat

    module._execute_gather(world, agent, "hunt", module._perceive(world, agent),  # noqa: SLF001
                           world.config.agents.tuning)

    harvested = world.event_log.by_type("resource_harvested")[-1]["payload"]
    success = world.event_log.by_type("gather_success")[-1]["payload"]
    granted = float(harvested["amount"])
    assert granted > 0
    assert float(pool.current_stock) == pytest.approx(stock_before - granted, abs=1e-6)
    assert hh(world, agent).meat == pytest.approx(meat_before + granted, abs=0.01)
    assert success["output_field"] == "meat"
    assert success["amount"] == pytest.approx(round(granted, 2))


# --------------------------------------------------------------------------- #
# EcologicalImpact：四类影响的投影与事件
# --------------------------------------------------------------------------- #
def test_flood_and_drought_clamp_field_growth():
    world = _world()
    world.state.environment.field_growth["f1"] = 10.0
    assert EcologicalImpact.flood_damage(world, "f1", 4.0, precipitation_mm=25.0) == pytest.approx(4.0)
    assert world.state.environment.field_growth["f1"] == pytest.approx(6.0)
    flood = world.event_log.by_type("field_flood_damage")[-1]["payload"]
    assert flood["before"] == pytest.approx(10.0)
    assert flood["after"] == pytest.approx(6.0)

    assert EcologicalImpact.drought_damage(world, "f1", 100.0, drought_state="crisis") == pytest.approx(6.0)
    assert world.state.environment.field_growth["f1"] == pytest.approx(0.0)
    drought = world.event_log.by_type("field_drought_damage")[-1]["payload"]
    assert drought["damage"] == pytest.approx(6.0)


def test_landslide_floors_fertility_and_emits_event():
    world = _world()
    world.state.environment.fertility_factor["f1"] = 0.12
    EcologicalImpact.landslide(
        world, "f1", amount=.08, source_node="low_mountain", resource_stock_ratio=.1,
    )
    assert world.state.environment.fertility_factor["f1"] == pytest.approx(0.1)
    payload = world.event_log.by_type("landslide_damage")[-1]["payload"]
    assert payload["fertility_before"] == pytest.approx(0.12)
    assert payload["fertility_after"] == pytest.approx(0.1)


def test_wildlife_attack_settles_health_and_ignores_dead_target():
    world = _sim()
    agent = world.state.human.agents["lin_yuan"]
    before = agent.health
    assert EcologicalImpact.wildlife_attack(world, agent.agent_id, 8.0, location="low_mountain")
    assert agent.health == pytest.approx(max(0.0, before - 8.0))
    assert agent.last_injury_tick == world.current_tick
    payload = world.event_log.by_type("wildlife_attack")[-1]["payload"]
    assert payload["health_after"] == pytest.approx(agent.health)

    agent.alive = False
    count = len(world.event_log.by_type("wildlife_attack"))
    assert not EcologicalImpact.wildlife_attack(world, agent.agent_id, 8.0)
    assert len(world.event_log.by_type("wildlife_attack")) == count


def test_replay_rebuilds_impact_projection():
    world = _sim()
    field = next(
        node.id for node in world.config.spatial.nodes
        if getattr(node.type, "value", node.type) == "field"
        and not node.attributes.get("abstract_zone")
    )
    world.state.environment.field_growth[field] = 40.0
    world.state.environment.fertility_factor[field] = 1.0
    EcologicalImpact.flood_damage(world, field, 5.0, precipitation_mm=25.0)
    EcologicalImpact.drought_damage(world, field, 1.0, drought_state="warning")
    EcologicalImpact.landslide(
        world, field, amount=.08, source_node="low_mountain", resource_stock_ratio=.1,
    )
    agent = world.state.human.agents["lin_yuan"]
    EcologicalImpact.wildlife_attack(world, agent.agent_id, 8.0, location="low_mountain")

    rebuilt = rebuild_state(world.event_log.all(), world.config).state
    assert rebuilt.environment.field_growth[field] == pytest.approx(
        world.state.environment.field_growth[field]
    )
    assert rebuilt.environment.fertility_factor[field] == pytest.approx(
        world.state.environment.fertility_factor[field]
    )
    assert rebuilt.human.agents[agent.agent_id].health == pytest.approx(agent.health)
    assert rebuilt.human.agents[agent.agent_id].last_injury_tick == agent.last_injury_tick


# --------------------------------------------------------------------------- #
# 观察层：新拒绝事件不降级
# --------------------------------------------------------------------------- #
def test_render_harvest_refused():
    evt = {"event_type": "resource_harvest_refused", "payload": {
        "resource_node": "river_town", "action": "fish", "agent_id": "ag-1",
        "requested": 5, "granted": 0, "reason": "extraction_limit",
    }}
    result = render_event(evt)
    assert not result.degraded
    assert "被拒" in result.text
