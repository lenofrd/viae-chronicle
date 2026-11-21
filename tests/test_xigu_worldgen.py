from config.schema.spatial_units import NodeType
from vale.worldgen.nature import harvest_resource, regenerate_resource
from vale.worldgen.xigu import (
    XiguGenerationConfig, build_xigu_agents_config, generate_xigu_town, validate_xigu_town,
)


def test_default_generation_has_requested_population_and_land_use():
    result = generate_xigu_town()
    assert validate_xigu_town(result) == []
    homes = [n for n in result.spatial.nodes if n.attributes.get("residence")]
    assert len(homes) == 40
    assert sum(n.district == "poor_district" for n in homes) == 21
    assert sum(n.district == "common_district" for n in homes) == 14
    assert sum(n.district == "wealthy_district" for n in homes) == 5
    assert sum(n.attributes.get("field_kind") == "irrigated" for n in result.spatial.nodes) == 12
    assert sum(n.attributes.get("field_kind") == "dry" for n in result.spatial.nodes) == 9


def test_generation_is_deterministic_and_returns_pairwise_routes():
    a = generate_xigu_town(XiguGenerationConfig(seed=73))
    b = generate_xigu_town(XiguGenerationConfig(seed=73))
    assert [n.model_dump() for n in a.spatial.nodes] == [n.model_dump() for n in b.spatial.nodes]
    assert [e.model_dump() for e in a.spatial.distance_edges] == [e.model_dump() for e in b.spatial.distance_edges]
    assert a.pairwise_travel_tu == b.pairwise_travel_tu
    assert a.resources == b.resources
    assert all(a.pairwise_travel_tu[n][n] == 0 for n in a.pairwise_travel_tu)


def test_roads_have_raster_paths_and_deep_mountain_is_not_routable():
    result = generate_xigu_town()
    assert result.roads and all(edge.path for edge in result.roads)
    assert "deep_mountain" not in result.distances_from_well
    assert len(result.distances_from_well) == len(result.spatial.nodes) - 1


def test_each_household_has_all_fields_ordered_by_actual_route_cost():
    result = generate_xigu_town()
    for home, fields in result.household_work_nodes.items():
        all_fields = {
            node.id for node in result.spatial.nodes
            if node.type == NodeType.FIELD and not node.attributes.get("abstract_zone")
        }
        assert set(fields) == all_fields
        assert fields == sorted(
            fields, key=lambda field_id: (result.pairwise_travel_tu[home][field_id], field_id)
        )


def test_resource_stock_is_bounded_and_deep_mountain_is_sealed():
    result = generate_xigu_town()
    # P4：节点 attributes 不再携带 resource_* 副本，池目录是唯一真相源。
    resource_nodes = {"river_town", "foothill_woodland", "low_mountain",
                      "game_trail", "deep_mountain"}
    for node in result.spatial.nodes:
        if node.id in resource_nodes:
            assert not ({"resource_stock", "resource_max_stock",
                         "resource_regeneration_per_tick"} & set(node.attributes)), (
                f"{node.id} 仍携带 resource_* 副本")
    pool = result.resources["river_town"]
    assert harvest_resource(pool, 999) <= pool.extraction_limit_per_tick
    assert pool.current_stock >= 0
    regenerate_resource(pool, "autumn", 100)
    assert pool.current_stock <= pool.max_stock
    sealed = result.resources["deep_mountain"]
    assert harvest_resource(sealed, 10) == 0
    assert regenerate_resource(sealed, "spring", 10) == 0


def test_invalid_district_counts_fail_fast():
    try:
        XiguGenerationConfig(residence_count=40, poor_households=20)
    except ValueError as exc:
        assert "sum of district counts" in str(exc)
    else:
        raise AssertionError("invalid district counts should fail")

def test_three_livelihood_zones_are_options_not_household_occupations():
    result = generate_xigu_town()
    zones = {n.attributes.get("livelihood_zone") for n in result.spatial.nodes}
    assert {"farming", "river", "woodland"} <= zones
    homes = [n for n in result.spatial.nodes if n.attributes.get("residence")]
    assert all(set(n.attributes["livelihood_options"]) == {"farming", "river", "woodland"} for n in homes)

def test_world_seed_creates_40_residents_in_30_households_with_open_livelihood_actions():
    from vale.core.config_loader import load_config

    base = load_config("brookvale-town-001")
    result = generate_xigu_town(base_spatial=base.spatial)
    config = build_xigu_agents_config(result, base.agents.tuning, base.agents)

    generated_ids = {node.id for node in result.spatial.nodes}
    assert {node.id for node in base.spatial.nodes} <= generated_ids
    assert not {"village_head_house", "ancestral_hall", "apothecary"} & generated_ids
    by_agent = {agent.id: agent for agent in config.agents}
    assert {"lin_yuan", "zhao_cuilan", "li_quan", "zhou_qiaoniang"} <= set(by_agent)
    assert by_agent["li_quan"].name == "李全" and by_agent["li_quan"].assets.grain == 100
    assert by_agent["zhou_qiaoniang"].name == "周巧娘" and by_agent["zhou_qiaoniang"].work_node == "market"

    residences = {n.id for n in result.spatial.nodes if n.attributes.get("residence")}
    occupied_homes = {agent.home_node for agent in config.agents}
    household_ids = {agent.household_id for agent in config.agents}

    assert len(config.agents) == 40
    generated_residents = [agent for agent in config.agents if agent.id.startswith("resident_")]
    assert len({agent.work_node for agent in generated_residents}) >= 10
    assert len(household_ids) == 30
    assert len(occupied_homes) == 30
    assert occupied_homes <= residences
    assert len(residences - occupied_homes) == 10
    assert all(agent.work_node == "market" if agent.id == "zhou_qiaoniang" else agent.work_node in result.household_work_nodes[agent.home_node] for agent in config.agents)
    assert {"fish", "hunt", "gather_firewood", "gather_herbs", "gather_hardwood"} <= set(config.tuning.gathering.actions)
    assert not hasattr(config.tuning.birth, "max_population")
    assert all(agent.assets.grain >= 0 for agent in config.agents)

def test_initial_households_register_at_head_house_and_keep_vacant_split_homes():
    from vale.core.config_loader import LoadedConfig, load_config
    from vale.core.event_log import EventLog
    from vale.core.world import World
    from vale.modules.agents import AgentModule

    base = load_config("brookvale-town-001")
    generated = generate_xigu_town(base_spatial=base.spatial)
    config = LoadedConfig(
        world=base.world,
        natural_params=base.natural_params,
        spatial=generated.spatial,
        agents=build_xigu_agents_config(generated, base.agents.tuning, base.agents),
        terrain=generated.terrain,
        resources=generated.resources,
    )
    log = EventLog(":memory:")
    world = World(config.world.world_id, log, config.world.start_tick, config)
    AgentModule()._ensure_agents(world, config.agents)
    assert world.world_id == "brookvale-town-001"
    assert len(world.state.human.agents) == 40
    assert {"lin_yuan", "zhao_cuilan", "li_quan", "zhou_qiaoniang"} <= set(world.state.human.agents)
    assert len(world.state.human.households) == 30
    assert len({h.home_node for h in world.state.human.households.values()}) == 30
    assert all(h.registry_node == "elder_house" for h in world.state.human.households.values())
    assert len(log.by_type("household_registered")) == 30
    assert len(log.by_type("household_member_registered")) == 10
    log.close()

def test_gathering_target_outside_pool_catalog_fails_at_startup():
    """P4 收敛：带池目录的世界，采集目标未登记 → 首引导即报错（坏配置快速失败）。"""
    import pytest as _pytest

    from vale.core.config_loader import LoadedConfig, load_config
    from vale.core.event_log import EventLog
    from vale.core.world import World
    from vale.modules.agents import AgentModule

    base = load_config("brookvale-town-001")
    generated = generate_xigu_town(base_spatial=base.spatial)
    agents = build_xigu_agents_config(generated, base.agents.tuning, base.agents)
    # 构造坏配置：采集目标不在池目录（剔除其池目录条目）。
    catalog = {k: v for k, v in generated.resources.items() if k != "low_mountain"}
    config = LoadedConfig(
        world=base.world, natural_params=base.natural_params,
        spatial=generated.spatial, agents=agents,
        terrain=generated.terrain, resources=catalog,
    )
    world = World(config.world.world_id, EventLog(":memory:"), config.world.start_tick, config)
    with _pytest.raises(ValueError, match="low_mountain"):
        AgentModule()._ensure_agents(world, config.agents)
