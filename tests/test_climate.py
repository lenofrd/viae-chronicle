"""阶段四测试：气候演化模块。全部使用内存数据库。"""
from __future__ import annotations

import pytest

from vale.core.config_loader import load_config
from vale.core.event_log import EventLog
from vale.core.scheduler import run_tick
from vale.core.world import World
from vale.domains.environment.climate import ClimateModule


class _DryRng:
    """始终无雨、扰动取中值的伪随机源。"""

    def random(self) -> float:
        return 1.0

    def uniform(self, a: float, b: float) -> float:
        return (a + b) / 2.0


class _WetRng:
    """始终降雨。"""

    def random(self) -> float:
        return 0.0

    def uniform(self, a: float, b: float) -> float:
        return (a + b) / 2.0


@pytest.fixture
def world():
    cfg = load_config("brookvale-town-001")
    log = EventLog(":memory:")
    return World(
        world_id=cfg.world.world_id,
        event_log=log,
        start_tick=cfg.world.start_tick,
        config=cfg,
    )


def test_drought_accumulates_without_rain(world):
    """连续 10 天无雨，旱情累积值应增加（且单调递增）。"""
    world.register(ClimateModule(rng=_DryRng()))
    run_tick(world)  # 初始化
    initial_acc = world.state.environment.climate.drought_accumulation

    accs = [initial_acc]
    for _ in range(9):
        run_tick(world)
        accs.append(world.state.environment.climate.drought_accumulation)

    assert accs[-1] > accs[0]
    assert all(accs[i + 1] >= accs[i] for i in range(len(accs) - 1))
    # 无雨阈值 10，初始已连旱 15 天，每天 +1
    assert accs[-1] == pytest.approx(initial_acc + 9)


def test_rain_reduces_drought(world):
    """连续降雨应按 recovery_rate 降低旱情累积。"""
    world.register(ClimateModule(rng=_WetRng()))
    run_tick(world)
    initial_acc = world.state.environment.climate.drought_accumulation
    for _ in range(3):
        run_tick(world)
    assert world.state.environment.climate.drought_accumulation < initial_acc


def test_season_changes_spring_to_summer(world):
    """开局立春（progress=0.0，90 天/季），跑过整个春季后应切换到夏季。"""
    import random

    world.register(ClimateModule(rng=random.Random(42)))
    seasons_seen = set()
    # 春季 90 天：tick 1..90 为春，tick 91 起入夏，故需 91 次 run_tick
    for _ in range(92):
        run_tick(world)
        seasons_seen.add(world.state.environment.climate.season.value)
    assert "summer" in seasons_seen
    # 应有 season_changed 事件
    season_events = world.event_log.by_type("season_changed")
    assert len(season_events) >= 1
    assert season_events[0]["payload"]["from"] == "spring"
    assert season_events[0]["payload"]["to"] == "summer"


def test_temperature_delta_within_limit(world):
    """温度单日变化不得超过 max_temp_delta_per_tick（=2.0）。"""
    import random

    world.register(ClimateModule(rng=random.Random(7)))
    temps = []
    for _ in range(12):
        run_tick(world)
        temps.append(world.state.environment.climate.temperature_c)
    deltas = [abs(temps[i + 1] - temps[i]) for i in range(len(temps) - 1)]
    assert deltas, "should have run multiple ticks"
    assert all(d <= 2.0 + 1e-9 for d in deltas), f"temperature jumped: {deltas}"


def test_weather_changed_event_every_tick(world):
    """每个 Tick 都应生成一条 weather_changed 事件。"""
    world.register(ClimateModule(rng=_DryRng()))
    for _ in range(3):
        run_tick(world)
    assert len(world.event_log.by_type("weather_changed")) == 3
