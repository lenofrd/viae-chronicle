from __future__ import annotations

from config.schema.natural_params import Season
from vale.core.config_loader import LoadedConfig, load_config
import pytest
from vale.core.event_log import EventLog
from vale.core.state import BuildingState
from vale.core.replay import rebuild_state
from vale.core.world import World
from vale.modules.agents import AgentModule, SpatialIndex
from vale.modules.community import (
    environmental_injury_multiplier, fatigue_efficiency,
    production_efficiency_at_node, service_capacity_available, settle_building_maintenance,
    approve_community_relief, contribute_to_community_reserve,
    request_community_relief, settle_community_reserves, settle_storage_capacity,
    update_building_needs,
)
from vale.worldgen.xigu import build_xigu_agents_config, generate_xigu_town


def make_world():
    base = load_config("brookvale-town-001")
    generated = generate_xigu_town(base_spatial=base.spatial)
    config = LoadedConfig(
        world=base.world,
        natural_params=base.natural_params,
        spatial=generated.spatial,
        agents=build_xigu_agents_config(generated, base.agents.tuning, base.agents),
        terrain=generated.terrain,
    )
    log = EventLog(":memory:")
    world = World(config.world.world_id, log, config.world.start_tick, config)
    AgentModule()._ensure_agents(world, config.agents)
    return world, log, config


def test_daily_fatigue_accumulates_labor_and_recovers_in_dwelling():
    world, log, config = make_world()
    try:
        agent = next(iter(world.state.human.agents.values()))
        agent.fatigue = 20.0
        world.event_log.append(world.current_tick, "agent_action_taken", {
            "agent_id": agent.agent_id,
            "action": "farm",
            "tu_spent": 12.0,
            "round_trip_tu": 2.0,
        })
        module = AgentModule()
        module._settle_fatigue(world, config.agents.tuning)
        event = log.by_type("agent_fatigue_settled")[-1]
        assert event["payload"]["shelter"] == "dwelling"
        assert event["payload"]["high_days_after"] == agent.fatigue_high_days
        assert event["payload"]["labor_tu"] == 10.0
        assert agent.fatigue > 20.0
        assert event["payload"]["after"] == agent.fatigue
    finally:
        log.close()


def test_legacy_world_without_building_projection_uses_dwelling_recovery():
    world, log, config = make_world()
    try:
        world.state.human.buildings.clear()
        agent = next(iter(world.state.human.agents.values()))
        agent.fatigue = 20.0
        AgentModule()._settle_fatigue(world, config.agents.tuning)
        event = log.by_type("agent_fatigue_settled")[-1]["payload"]
        assert event["shelter"] == "legacy_unmodeled_dwelling"
        assert event["recovery"] == pytest.approx(
            config.agents.tuning.environment.dwelling_fatigue_recovery_per_day
        )
    finally:
        log.close()


def test_workshop_efficiency_requires_matching_parcel_node_and_active_building():
    world, log, config = make_world()
    try:
        household = next(iter(world.state.human.households.values()))
        node_id = household.work_node
        parcel = world.state.human.land_parcels[f"parcel:{node_id}"]
        tuning = config.agents.tuning.environment
        assert production_efficiency_at_node(world, node_id, "weave", tuning) == 1.0

        world.state.human.buildings["workshop:test"] = BuildingState(
            building_id="workshop:test",
            parcel_id=parcel.parcel_id,
            building_type="workshop",
            owner_type="household",
            owner_id=household.household_id,
            footprint_area=0.25,
            condition=80.0,
            status="active",
            created_tick=world.current_tick,
        )
        assert production_efficiency_at_node(world, node_id, "weave", tuning) == 1.12
        assert production_efficiency_at_node(world, node_id, "farm", tuning) == 1.0
        world.state.human.buildings["workshop:test"].status = "ruined"
        assert production_efficiency_at_node(world, node_id, "weave", tuning) == 1.0
    finally:
        log.close()



def test_fatigue_waits_seven_days_then_extends_work_time_without_reducing_yield():
    world, log, config = make_world()
    try:
        agent = next(iter(world.state.human.agents.values()))
        module = AgentModule()
        tuning = config.agents.tuning
        agent.fatigue = 100.0
        agent.fatigue_high_days = tuning.environment.fatigue_efficiency_grace_days - 1
        assert fatigue_efficiency(agent, tuning.environment) == 1.0

        agent.fatigue_high_days += 1
        perception = module._perceive(world, agent)
        assert perception.fatigue_efficiency < 1.0
        slow_work_tu = module._tu_total("farm", perception, tuning)
        agent.fatigue_high_days = 0
        rested_perception = module._perceive(world, agent)
        normal_work_tu = module._tu_total("farm", rested_perception, tuning)
        assert slow_work_tu > normal_work_tu

        agent.fatigue_high_days = tuning.environment.fatigue_efficiency_grace_days
        perception = module._perceive(world, agent)
        before = world.state.environment.field_growth[perception.work_node]
        module._execute(world, agent, "farm", perception, tuning,
                        tu_spent=module._tu_total("farm", perception, tuning), tu_remaining=9.0)
        assert world.state.environment.field_growth[perception.work_node] - before == pytest.approx(
            tuning.agriculture.field_growth_per_farm
        )
    finally:
        log.close()


def test_public_reserves_never_auto_transfer_and_household_storage_never_decays():
    world, log, config = make_world()
    try:
        household = next(iter(world.state.human.households.values()))
        household.grain = 500.0
        household.water = 500.0
        world.state.human.community_reserves = {"grain": 0.0, "water": 0.0}
        before = (household.grain, household.water, dict(world.state.human.community_reserves))
        settle_community_reserves(world, config.agents.tuning.environment, config.agents.tuning)
        settle_storage_capacity(world, config.agents.tuning.environment)
        assert (household.grain, household.water, world.state.human.community_reserves) == before
        assert not log.by_type("community_reserve_deposited")
        assert not log.by_type("community_reserve_withdrawn")
        assert not log.by_type("household_storage_overflow_loss")
    finally:
        log.close()


def test_public_reserve_requires_explicit_voluntary_contribution_and_replays():
    world, log, config = make_world()
    try:
        household = next(iter(world.state.human.households.values()))
        contributor = world.state.human.agents[household.member_ids[0]]
        world.state.human.headman_id = contributor.agent_id
        household.grain = 25.0
        assert contribute_to_community_reserve(
            world, household.household_id, contributor.agent_id, "grain", 5.0
        ) == 5.0
        assert household.grain == 20.0
        assert world.state.human.community_reserves["grain"] == 5.0
        replayed = rebuild_state(log.all(), config).state
        assert replayed.human.households[household.household_id].grain == pytest.approx(20.0)
        assert replayed.human.community_reserves["grain"] == pytest.approx(5.0)
    finally:
        log.close()


def test_relief_requires_household_request_and_manager_approval_then_replays():
    world, log, config = make_world()
    try:
        household = next(iter(world.state.human.households.values()))
        applicant = world.state.human.agents[household.member_ids[0]]
        world.state.human.headman_id = applicant.agent_id
        world.state.human.community_reserves.update({"grain": 8.0})
        household.grain = 1.0
        request_id = request_community_relief(
            world, household.household_id, applicant.agent_id, {"grain": 4.0}
        )
        assert world.state.human.service_queues[request_id]["status"] == "pending"
        assert household.grain == 1.0
        assert world.state.human.community_reserves["grain"] == 8.0
        assert approve_community_relief(world, request_id, applicant.agent_id, {"grain": 3.0}) == {"grain": 3.0}
        assert household.grain == 4.0
        assert world.state.human.community_reserves["grain"] == 5.0
        replayed = rebuild_state(log.all(), config).state
        assert replayed.human.households[household.household_id].grain == pytest.approx(4.0)
        assert replayed.human.community_reserves["grain"] == pytest.approx(5.0)
        assert replayed.human.service_queues[request_id]["status"] == "approved"
    finally:
        log.close()


def test_household_work_plan_assigns_distinct_tasks_and_records_roles():
    world, log, config = make_world()
    try:
        module = AgentModule()
        adults = [
            agent for agent in world.state.human.agents.values()
            if agent.alive and config.agents.tuning.aging.stage_for(
                (world.current_tick - agent.birth_tick) // 360
            ).work_allowed
        ]
        first = adults[0]
        second = next(agent for agent in adults[1:] if agent.household_id != first.household_id)
        household = world.state.human.households[first.household_id]
        other = world.state.human.households[second.household_id]
        other.member_ids.remove(second.agent_id)
        household.member_ids.append(second.agent_id)
        second.household_id = household.household_id
        second.work_node = None
        first.work_node = None
        household.grain = 20.0
        household.water = 20.0
        module._reconcile_work_nodes(world, config.agents.tuning)
        assignments = module._plan_household_work(world, config.agents.tuning)
        assert first.agent_id in assignments and second.agent_id in assignments
        assert assignments[first.agent_id] != assignments[second.agent_id]
        plan_events = [
            event["payload"] for event in log.by_type("household_work_plan_created")
            if event["payload"]["household_id"] == household.household_id
        ]
        assert plan_events[-1]["distinct_task_count"] >= 2
    finally:
        log.close()


def test_weaving_requires_a_market_worksite_or_active_workshop():
    world, log, config = make_world()
    try:
        agent = world.state.human.agents["lin_yuan"]
        module = AgentModule()
        perception = module._perceive(world, agent)
        assert not perception.weave_available
        assert module.score_action("weave", perception, config.agents.tuning) == float("-inf")
        weaver = module._perceive(world, world.state.human.agents["zhou_qiaoniang"])
        assert weaver.weave_available
    finally:
        log.close()


def test_food_security_prioritizes_fishing_over_weaving_when_reserves_run_low():
    world, log, config = make_world()
    try:
        agent = world.state.human.agents["zhou_qiaoniang"]
        household = world.state.human.households[agent.household_id]
        module = AgentModule()
        agent.hunger = 10.0
        for field in ("grain", "vegetable", "meat", "fish"):
            setattr(household, field, 0.0)
        low_food = module._perceive(world, agent)
        assert low_food.household_food_days == pytest.approx(0.0)
        fish_when_low = module.score_action("fish", low_food, config.agents.tuning)
        weave_when_low = module.score_action("weave", low_food, config.agents.tuning)
        assert fish_when_low > weave_when_low

        household.grain = 200.0
        adequate_food = module._perceive(world, agent)
        fish_when_safe = module.score_action("fish", adequate_food, config.agents.tuning)
        weave_when_safe = module.score_action("weave", adequate_food, config.agents.tuning)
        assert weave_when_safe > fish_when_safe
    finally:
        log.close()


def test_field_has_explicit_spring_labor_budget_and_replays():
    world, log, config = make_world()
    try:
        agent = next(iter(world.state.human.agents.values()))
        module = AgentModule()
        tuning = config.agents.tuning
        work_node = agent.work_node or world.state.human.households[agent.household_id].work_node
        required = tuning.agriculture.field_labor_required_by_season["spring"]
        for _ in range(int(required / tuning.agriculture.field_labor_per_farm)):
            perception = module._perceive(world, agent)
            assert perception.work_field_season_labor_remaining > 0
            module._execute(
                world, agent, "farm", perception, tuning,
                tu_spent=tuning.action.tu_cost["farm"], tu_remaining=9.0,
            )
        final = module._perceive(world, agent)
        assert final.work_field_season_labor_remaining == pytest.approx(0.0)
        assert module.score_action("farm", final, tuning) == float("-inf")
        assert world.state.environment.field_growth[work_node] == pytest.approx(
            required / tuning.agriculture.field_labor_per_farm
            * tuning.agriculture.field_growth_per_farm
        )
        replayed = rebuild_state(
            [event for event in log.all() if event["event_type"] == "field_labor_progressed"],
            config,
        ).state
        assert replayed.environment.field_season_labor[work_node]["labor_completed"] == pytest.approx(required)
    finally:
        log.close()


def test_mountain_and_bad_weather_multiply_gathering_injury_exposure():
    world, log, config = make_world()
    try:
        tuning = config.agents.tuning.environment
        assert environmental_injury_multiplier(world, "low_mountain", False, tuning) == 1.8
        assert environmental_injury_multiplier(world, "deep_mountain", True, tuning) == 6.0
        assert environmental_injury_multiplier(world, "well", True, tuning) == 1.5
    finally:
        log.close()


def test_public_well_has_daily_service_throughput():
    world, log, config = make_world()
    try:
        tuning = config.agents.tuning.environment
        tuning.service_capacity_by_node["well"] = {"collect_water": 1}
        assert service_capacity_available(world, "well", "collect_water", tuning)
        world.event_log.append(world.current_tick, "agent_action_taken", {
            "agent_id": "test", "action": "collect_water", "target_node": "well",
        })
        assert not service_capacity_available(world, "well", "collect_water", tuning)
    finally:
        log.close()


def test_housing_need_has_buffer_and_replays_as_a_deliberation_signal():
    world, log, config = make_world()
    try:
        vacant = [
            building for building in world.state.human.buildings.values()
            if building.building_type == "dwelling" and building.status == "vacant"
        ]
        for building in vacant[:5]:
            building.status = "ruined"
        tuning = config.agents.tuning.environment
        for day in range(tuning.building_need_emerging_days):
            update_building_needs(world, tuning)
            world.current_tick += 1
        need = world.state.human.building_needs["village:housing_reserve"]
        assert need.stage == "emerging"
        assert need.pressure_days == tuning.building_need_emerging_days
        assert need.alternatives == ["repair", "extend", "share", "relocate"]
        replayed = rebuild_state(
            [event for event in log.all() if event["event_type"] == "building_need_updated"],
            config,
        ).state
        assert replayed.human.building_needs[need.need_id].stage == "emerging"
    finally:
        log.close()



def test_market_public_space_limits_visitors_and_rotates_queue():
    world, log, config = make_world()
    try:
        module = AgentModule()
        module._spatial = SpatialIndex(world.config.spatial)
        config.agents.tuning.environment.service_capacity_by_node["market"] = {
            "market_visitors": 1
        }
        stamina_before = {agent_id: agent.stamina for agent_id, agent in world.state.human.agents.items()}
        module._settle_market(world, config.agents.tuning)
        summary = log.by_type("market_day_summary")[-1]["payload"]
        assert summary["visitor_capacity"] == 1
        assert summary["participant_count"] <= 1
        assert summary["skipped"]["crowded"] > 0
        admitted = {row["agent_id"] for row in summary["participants"]}
        for agent_id, agent in world.state.human.agents.items():
            if agent_id not in admitted:
                assert agent.stamina == stamina_before[agent_id]
    finally:
        log.close()



def test_dwelling_crowding_reduces_daily_fatigue_recovery():
    world, log, config = make_world()
    try:
        agent = next(iter(world.state.human.agents.values()))
        agent.fatigue = 20.0
        tuning = config.agents.tuning
        household = world.state.human.households[agent.household_id]
        tuning.environment.dwelling_resident_capacity = len([
            member_id for member_id in household.member_ids
            if world.state.human.agents[member_id].alive
        ])
        tuning.environment.dwelling_comfort_ratio = 0.5
        tuning.environment.dwelling_crowding_recovery_loss_per_ratio = 1.0
        AgentModule()._settle_fatigue(world, tuning)
        event = log.by_type("agent_fatigue_settled")[-1]["payload"]
        assert event["crowding_ratio"] == 1.0
        assert event["crowding_recovery_loss"] == 0.5
        assert event["recovery"] == 1.0
    finally:
        log.close()



def test_building_wear_is_gradual_and_replayable():
    world, log, config = make_world()
    try:
        building = next(iter(world.state.human.buildings.values()))
        building.condition = 50.0
        config.agents.tuning.environment.building_condition_decay_per_day = 0.1
        settle_building_maintenance(world, config.agents.tuning.environment)
        assert building.condition == 49.9
        replayed = rebuild_state(
            [event for event in log.all() if event["event_type"] in {
                "land_parcel_created", "building_created", "building_condition_changed",
            }],
            config,
        ).state
        assert replayed.human.buildings[building.building_id].condition == 49.9
    finally:
        log.close()


def test_household_storage_has_no_capacity_loss_or_overflow_event():
    world, log, config = make_world()
    try:
        household = next(iter(world.state.human.households.values()))
        household.grain = 500.0
        household.cloth = 300.0
        settle_storage_capacity(world, config.agents.tuning.environment)
        assert household.grain == 500.0
        assert household.cloth == 300.0
        assert not log.by_type("household_storage_overflow_loss")
    finally:
        log.close()


def test_overcrowded_household_creates_buffered_dwelling_need():
    world, log, config = make_world()
    try:
        household = next(
            household for household in world.state.human.households.values()
            if sum(1 for member_id in household.member_ids
                   if world.state.human.agents[member_id].alive) > 1
        )
        building = next(
            building for building in world.state.human.buildings.values()
            if building.building_type == "dwelling"
            and world.state.human.land_parcels[building.parcel_id].spatial_node_id == household.home_node
        )
        building.attributes["resident_capacity"] = 1
        tuning = config.agents.tuning.environment
        for _ in range(tuning.building_need_emerging_days):
            update_building_needs(world, tuning)
            world.current_tick += 1
        need = world.state.human.building_needs[
            f"household:{household.household_id}:dwelling_capacity"
        ]
        assert need.stage == "emerging"
        assert need.demand > need.capacity
    finally:
        log.close()


def test_sound_dwelling_protects_residents_from_winter_cold():
    world, log, config = make_world()
    try:
        agent = world.state.human.agents["lin_yuan"]
        household = world.state.human.households[agent.household_id]
        household.cloth = 0.0
        agent.health = 90.0
        module = AgentModule()
        module._apply_cold_exposure(world, agent, config.agents.tuning, Season.WINTER)
        event = log.by_type("cold_exposure")[-1]["payload"]
        assert event["dwelling_id"] is not None
        assert event["dwelling_cold_protection"] == pytest.approx(0.75)
        assert event["loss"] == pytest.approx(
            config.agents.tuning.textile.cold_health_loss * 0.25
        )
        assert agent.health > 80.0
        replayed = rebuild_state(log.all(), config).state
        assert replayed.human.agents[agent.agent_id].health == pytest.approx(agent.health)

        dwelling = world.state.human.buildings[event["dwelling_id"]]
        dwelling.status = "ruined"
        agent.health = 90.0
        module._apply_cold_exposure(world, agent, config.agents.tuning, Season.WINTER)
        assert log.by_type("cold_exposure")[-1]["payload"]["dwelling_id"] is None
        assert agent.health == pytest.approx(
            90.0 - config.agents.tuning.textile.cold_health_loss
        )
    finally:
        log.close()


def test_fatigue_strain_and_seasonal_field_labor_replay():
    world, log, config = make_world()
    try:
        agent = next(
            a for a in world.state.human.agents.values()
            if a.work_node in world.state.environment.field_growth
        )
        module = AgentModule()
        tuning = config.agents.tuning
        agent.fatigue = 50.0
        agent.fatigue_high_days = tuning.environment.fatigue_efficiency_grace_days
        module._settle_fatigue(world, tuning)
        perception = module._perceive(world, agent)
        module._execute(
            world, agent, "farm", perception, tuning,
            tu_spent=module._tu_total("farm", perception, tuning),
            tu_remaining=10.0,
        )

        replayed = rebuild_state(log.all(), config).state
        replay_agent = replayed.human.agents[agent.agent_id]
        assert replay_agent.fatigue == pytest.approx(agent.fatigue)
        assert replay_agent.fatigue_high_days == agent.fatigue_high_days
        assert replay_agent.health == pytest.approx(agent.health)
        assert replay_agent.hunger == pytest.approx(agent.hunger)
        assert replay_agent.stamina == pytest.approx(agent.stamina)
        progress = replayed.environment.field_season_labor[agent.work_node]
        assert progress["labor_completed"] == pytest.approx(
            tuning.agriculture.field_labor_per_farm
        )
    finally:
        log.close()


def test_legacy_unmodeled_home_keeps_shelter_compatibility():
    world, log, config = make_world()
    try:
        for building_id, building in list(world.state.human.buildings.items()):
            if building.building_type == "dwelling":
                del world.state.human.buildings[building_id]
        assert world.state.human.buildings  # non-residential buildings must not disable legacy shelter
        agent = world.state.human.agents["lin_yuan"]
        household = world.state.human.households[agent.household_id]
        household.cloth = 0.0
        agent.health = 90.0
        AgentModule()._apply_cold_exposure(
            world, agent, config.agents.tuning, Season.WINTER
        )
        event = log.by_type("cold_exposure")[-1]["payload"]
        assert event["dwelling_id"] == "legacy_unmodeled_dwelling"
        assert event["dwelling_cold_protection"] == pytest.approx(0.75)
        assert event["loss"] == pytest.approx(
            config.agents.tuning.textile.cold_health_loss * 0.25
        )
        agent.fatigue = 50.0
        module = AgentModule()
        module._settle_fatigue(world, config.agents.tuning)
        fatigue_event = log.by_type("agent_fatigue_settled")[-1]["payload"]
        assert fatigue_event["shelter"] == "legacy_unmodeled_dwelling"
        assert fatigue_event["recovery"] == pytest.approx(
            config.agents.tuning.environment.dwelling_fatigue_recovery_per_day
        )
    finally:
        log.close()


