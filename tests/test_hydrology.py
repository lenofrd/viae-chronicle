"""P3a 水源库存测试：初始化、补水、取水结算、上限、拒绝、坏配置与回放。

P3c 起结算归环境域所有者 ``vale/modules/hydrology.py``（原 ``contracts/water.py``），
行为不变。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from config.schema.natural_params import WaterSupplyParams
from vale.modules.hydrology import (
    ensure_source,
    regenerate_water_sources,
    withdraw_water,
)
from vale.core.config_loader import load_config
from vale.core.event_log import EventLog
from vale.core.replay import rebuild_state
from vale.core.scheduler import run_tick
from vale.core.world import World
from vale.modules.climate import ClimateModule


def _world(*, supply: dict[str, WaterSupplyParams] | None = None, ratio: float = 0.5) -> World:
    natural = SimpleNamespace(water_supply=supply)
    config = SimpleNamespace(natural_params=natural, spatial=SimpleNamespace(nodes=[]))
    world = World("test", EventLog(":memory:"), start_tick=1, config=config)
    world.state.environment.water_level_ratio = ratio
    return world


def _params(**overrides) -> WaterSupplyParams:
    base = dict(capacity=100.0, initial_ratio=0.5,
                regeneration_per_tick=20.0, extraction_limit_per_tick=50.0)
    base.update(overrides)
    return WaterSupplyParams(**base)


# --------------------------------------------------------------------------- #
# 初始化与补水
# --------------------------------------------------------------------------- #

def test_initial_stock_uses_water_level_ratio_when_ratio_is_none():
    world = _world(supply={"well": _params(initial_ratio=None)}, ratio=0.3)
    source = ensure_source(world, "well")
    assert source is not None
    assert source.current_stock == pytest.approx(30.0)
    assert source.capacity == pytest.approx(100.0)
    events = world.event_log.by_type("water_source_initialized")
    assert len(events) == 1
    assert events[0]["payload"]["water_node"] == "well"


def test_initial_stock_uses_explicit_ratio():
    world = _world(supply={"well": _params(initial_ratio=0.8)}, ratio=0.1)
    assert ensure_source(world, "well").current_stock == pytest.approx(80.0)


def test_regeneration_scales_with_water_level_and_caps_at_capacity():
    world = _world(supply={"well": _params(initial_ratio=0.5)}, ratio=0.5)
    regenerate_water_sources(world)  # 50 + 20 × 0.5 = 60
    assert world.state.environment.water_sources["well"].current_stock == pytest.approx(60.0)

    world.state.environment.water_level_ratio = 1.0
    for _ in range(10):
        regenerate_water_sources(world)
    assert world.state.environment.water_sources["well"].current_stock == pytest.approx(100.0)

    stock_events = world.event_log.by_type("water_source_regenerated")
    assert stock_events, "补水应写事件"
    for event in stock_events:
        payload = event["payload"]
        assert payload["stock_after"] == pytest.approx(
            min(100.0, payload["stock_before"] + payload["amount"])
        )


# --------------------------------------------------------------------------- #
# 取水结算
# --------------------------------------------------------------------------- #

def test_withdraw_debits_stock_and_event_conserves_mass():
    world = _world(supply={"well": _params(initial_ratio=1.0)})
    granted = withdraw_water(world, "well", 24.0, requester_id="hh_1")
    assert granted == pytest.approx(24.0)
    assert world.state.environment.water_sources["well"].current_stock == pytest.approx(76.0)
    payload = world.event_log.by_type("water_withdrawn")[-1]["payload"]
    assert payload["amount"] == pytest.approx(24.0)
    assert payload["stock_before"] - payload["stock_after"] == pytest.approx(payload["amount"])


def test_extraction_limit_is_enforced_per_tick():
    world = _world(supply={"well": _params(initial_ratio=1.0, extraction_limit_per_tick=40.0)})
    assert withdraw_water(world, "well", 30.0) == pytest.approx(30.0)
    assert withdraw_water(world, "well", 30.0) == pytest.approx(10.0)
    assert withdraw_water(world, "well", 30.0) == pytest.approx(0.0)
    refusals = world.event_log.by_type("water_withdrawal_refused")
    assert refusals and refusals[-1]["payload"]["reason"] == "extraction_limit"

    world.current_tick = 2  # 新的一天，额度重置
    assert withdraw_water(world, "well", 30.0) == pytest.approx(30.0)


def test_withdraw_returns_zero_when_stock_is_empty():
    world = _world(supply={"well": _params(initial_ratio=0.0)})
    assert withdraw_water(world, "well", 24.0) == pytest.approx(0.0)
    refusals = world.event_log.by_type("water_withdrawal_refused")
    assert refusals[-1]["payload"]["reason"] == "insufficient_stock"
    assert not world.event_log.by_type("water_withdrawn")


def test_unconfigured_node_keeps_legacy_behaviour():
    """未登记水源的节点：取水不设上限，也不产生库存状态（保持 P3a 前行为）。"""
    world = _world(supply={})
    assert withdraw_water(world, "well", 24.0) == pytest.approx(24.0)
    assert world.state.environment.water_sources == {}


# --------------------------------------------------------------------------- #
# 配置校验与回放
# --------------------------------------------------------------------------- #

def test_bad_water_supply_config_is_rejected():
    with pytest.raises(ValidationError):
        WaterSupplyParams(capacity=0)
    with pytest.raises(ValidationError):
        WaterSupplyParams(regeneration_per_tick=-1)
    with pytest.raises(ValidationError):
        WaterSupplyParams(extraction_limit_per_tick=-1)
    with pytest.raises(ValidationError):
        WaterSupplyParams(initial_ratio=1.5)


def test_world_config_declares_well_water_source():
    cfg = load_config("brookvale-town-001")
    well = cfg.natural_params.water_supply["well"]
    assert well.capacity > 0
    assert well.extraction_limit_per_tick > 0


def test_replay_rebuilds_water_stock():
    cfg = load_config("brookvale-town-001")
    world = World(cfg.world.world_id, EventLog(":memory:"), cfg.world.start_tick, cfg)
    world.register(ClimateModule())
    run_tick(world)  # 初始化水源并补水一次
    withdraw_water(world, "well", 24.0, requester_id="hh_replay")
    live = world.state.environment.water_sources["well"]

    rebuilt = rebuild_state(world.event_log.all(), cfg).state
    assert rebuilt.environment.water_sources["well"].current_stock == pytest.approx(
        live.current_stock
    )
    assert rebuilt.environment.water_sources["well"].capacity == pytest.approx(live.capacity)
