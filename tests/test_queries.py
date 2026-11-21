"""P2 只读查询契约测试：EnvironmentQuery / SpatialQuery / WildlifeQuery。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from vale.config.schema.natural_params import Season, WeatherType
from vale.config.schema.spatial_units import DistanceEdge, NodeType, SpatialConfig, SpatialNode
from vale.contracts.queries import EnvironmentQuery, SpatialQuery, WildlifeQuery
from vale.core.snapshots import ClimateSnapshot
from vale.core.state import WorldState


def _world(*, climate=None, gear: str = "low", spatial: SpatialConfig | None = None):
    """最小只读世界桩：查询只依赖 state/config，不启动模块。"""
    if spatial is None:
        spatial = SpatialConfig(nodes=[SpatialNode(id="well", name="井", type=NodeType.RESOURCE)])
    state = WorldState()
    state.environment.climate = climate
    state.environment.irrigation_gear = gear
    config = SimpleNamespace(
        spatial=spatial,
        natural_params=SimpleNamespace(
            hydrology_evolution=SimpleNamespace(
                moisture_by_gear={"low": 1.1, "abundant": 1.2, "dry": 0.7}
            )
        ),
    )
    return SimpleNamespace(state=state, config=config)


def _climate() -> ClimateSnapshot:
    return ClimateSnapshot(
        season=Season.SUMMER,
        season_progress=0.5,
        year=3,
        month=7,
        day=15,
        solar_term="小暑",
        current_weather=WeatherType.MODERATE_RAIN,
        temperature_c=26.5,
        humidity_pct=70.0,
    )


# --------------------------------------------------------------------------- #
# EnvironmentQuery
# --------------------------------------------------------------------------- #

def test_environment_query_defaults_when_climate_is_absent():
    world = _world()
    assert EnvironmentQuery.climate(world) is None
    assert EnvironmentQuery.season(world) is Season.SPRING
    assert EnvironmentQuery.weather(world) is WeatherType.SUNNY
    assert EnvironmentQuery.temperature_c(world) == 0.0
    assert EnvironmentQuery.year(world) == 1
    assert EnvironmentQuery.season_name(world) == ""
    assert EnvironmentQuery.weather_name(world) == ""


def test_environment_query_reads_snapshot_fields():
    world = _world(climate=_climate())
    assert EnvironmentQuery.season(world) is Season.SUMMER
    assert EnvironmentQuery.weather(world) is WeatherType.MODERATE_RAIN
    assert EnvironmentQuery.temperature_c(world) == pytest.approx(26.5)
    assert EnvironmentQuery.year(world) == 3
    assert EnvironmentQuery.season_name(world) == "summer"
    assert EnvironmentQuery.weather_name(world) == "moderate_rain"


def test_environment_query_moisture_follows_gear_table():
    assert EnvironmentQuery.moisture_factor(_world(gear="low")) == pytest.approx(1.1)
    assert EnvironmentQuery.moisture_factor(_world(gear="abundant")) == pytest.approx(1.2)
    # 未知/空档位按 1.0 降级，不改变旧行为。
    assert EnvironmentQuery.moisture_factor(_world(gear="unknown")) == pytest.approx(1.0)
    assert EnvironmentQuery.moisture_factor(_world(gear="")) == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# SpatialQuery
# --------------------------------------------------------------------------- #

@pytest.fixture
def spatial() -> SpatialConfig:
    return SpatialConfig(
        nodes=[
            SpatialNode(id="north_field", name="北田", type=NodeType.FIELD, area=1.5),
            SpatialNode(id="abstract_field", name="抽象田", type=NodeType.FIELD,
                        attributes={"abstract_zone": True}),
            SpatialNode(id="market", name="集市", type=NodeType.SOCIAL),
        ],
        distance_edges=[
            DistanceEdge(from_id="north_field", to_id="market", one_way_tu=4.0),
        ],
    )


def test_spatial_query_lists_only_real_fields(spatial):
    world = _world(spatial=spatial)
    assert SpatialQuery.field_ids(world) == ("north_field",)
    assert tuple(n.id for n in SpatialQuery.field_nodes(world)) == ("north_field",)
    assert SpatialQuery.is_field(world, "north_field") is True
    assert SpatialQuery.is_field(world, "abstract_field") is False
    assert SpatialQuery.is_field(world, "market") is False
    assert SpatialQuery.is_field(world, "missing") is False


def test_spatial_query_node_and_area_fallbacks(spatial):
    world = _world(spatial=spatial)
    assert SpatialQuery.node(world, "market").name == "集市"
    assert SpatialQuery.node(world, "missing") is None
    assert SpatialQuery.area(world, "north_field") == pytest.approx(1.5)
    # 非田/未知节点按 1.0，保持既有产量口径。
    assert SpatialQuery.area(world, "market") == pytest.approx(1.0)
    assert SpatialQuery.area(world, "missing") == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# WildlifeQuery
# --------------------------------------------------------------------------- #

def test_wildlife_query_exposes_read_only_pools_view():
    """P4：鱼/猎物池迁动物域后，查询暴露只读池视图（空世界视图为空）。"""
    world = _world()
    assert WildlifeQuery.populations(world)["pools"] == {}

    from vale.core.pools import ResourcePoolState
    world.state.wildlife.pools["river_town"] = ResourcePoolState(
        resource_type="fish", current_stock=90.0, max_stock=140.0)
    view = WildlifeQuery.populations(world)
    assert view["pools"]["river_town"]["current_stock"] == 90.0
    with pytest.raises(TypeError):
        view["deer"] = 1  # type: ignore[index]
    # 快照隔离：改返回值不影响状态本体（内层是深拷贝 dict）。
    view["pools"]["river_town"]["current_stock"] = 1.0
    assert world.state.wildlife.pools["river_town"].current_stock == 90.0
