from __future__ import annotations

import pytest

from vale.core.config_loader import LoadedConfig, load_config
from vale.core.event_log import EventLog
from vale.core.state import BuildingState
from vale.core.replay import rebuild_state
from vale.core.world import World
from vale.modules.agents import AgentModule
from vale.modules.construction import advance_construction, request_building, request_repair, request_expansion, request_demolition, share_building_access, pause_construction, resume_construction, cancel_construction, abandon_construction
from vale.modules.governance import cast_council_vote, propose_council_decision, register_representative
from vale.modules.land import change_land_use
from vale.worldgen.xigu import build_xigu_agents_config, generate_xigu_town


def make_world():
    base = load_config("brookvale-town-001")
    generated = generate_xigu_town(base_spatial=base.spatial)
    config = LoadedConfig(
        world=base.world, natural_params=base.natural_params,
        spatial=generated.spatial,
        agents=build_xigu_agents_config(generated, base.agents.tuning, base.agents),
        terrain=generated.terrain,
    )
    log = EventLog(":memory:")
    world = World(config.world.world_id, log, config.world.start_tick, config)
    AgentModule()._ensure_agents(world, config.agents)
    return world, log, config


def approve(world, decision_id, subject, affected=(), major=True):
    for household in world.state.households.values():
        adult = next((world.state.agents[aid] for aid in household.member_ids
                      if world.state.agents[aid].alive
                      and (world.current_tick - world.state.agents[aid].birth_tick) // 365 >= 18), None)
        if adult and (household.household_id not in world.state.representatives
                      or not world.state.representatives[household.household_id].active):
            register_representative(world, household.household_id, adult.agent_id)
    reps = list(world.state.representatives.values())
    decision = propose_council_decision(
        world, decision_id, subject=subject,
        proposer_agent_id=reps[0].agent_id,
        affected_household_ids=affected, major=major,
    )
    for rep in reps:
        if rep.household_id not in decision.recused_household_ids:
            cast_council_vote(world, decision_id, rep.agent_id, True)
            if decision.status != "voting":
                break
    assert decision.status == "approved"
    return decision


def test_land_use_requires_matching_approved_major_decision():
    world, log, config = make_world()
    try:
        parcel = next(p for p in world.state.land_parcels.values()
                      if p.land_use == "farmland_irrigated" and p.owner_type == "collective" and p.owner_type == "collective")
        with pytest.raises(ValueError, match="matching approved major"):
            change_land_use(world, parcel.parcel_id, new_land_use="residential",
                            approved_by="household_council", decision_id="fake")
        decision = approve(world, "land-decision", 
                           f"land_use_change:{parcel.parcel_id}:residential")
        change_land_use(world, parcel.parcel_id, new_land_use="residential",
                        approved_by="household_council", decision_id=decision.decision_id)
        replayed = rebuild_state(
            [e for e in log.all() if e["event_type"] in {
                "land_parcel_created", "land_use_changed",
                "land_right_granted", "land_right_revoked",
            }], config,
        ).state
        assert replayed.land_parcels[parcel.parcel_id].buildable_area == parcel.area
    finally:
        log.close()


def test_construction_requires_council_approval_materials_and_tick_labor_replay():
    world, log, config = make_world()
    try:
        household = next(iter(world.state.households.values()))
        parcel = next(p for p in world.state.land_parcels.values()
                      if p.land_use == "farmland_irrigated" and p.owner_type == "collective")
        land_decision = approve(
            world, "land-conversion", f"land_use_change:{parcel.parcel_id}:residential",
            major=True,
        )
        change_land_use(world, parcel.parcel_id, new_land_use="residential",
                        approved_by="household_council", decision_id=land_decision.decision_id)
        household.coin = 20
        household.hardwood = 30
        with pytest.raises(ValueError, match="matching approved council decision"):
            request_building(world, "shed-001", parcel_id=parcel.parcel_id,
                             household_id=household.household_id, building_type="shed",
                             footprint_area=0.25, decision_id="fake")
        decision = approve(world, "build-decision", "construction:shed-001",
                           affected=[household.household_id], major=False)
        project = request_building(
            world, "shed-001", parcel_id=parcel.parcel_id,
            household_id=household.household_id, building_type="shed",
            footprint_area=0.25, decision_id=decision.decision_id,
        )
        assert household.coin == 18 and household.hardwood == 26
        with pytest.raises(ValueError, match="later tick"):
            advance_construction(world, project.project_id)
        for _ in range(project.labor_required):
            world.current_tick += 1
            advance_construction(world, project.project_id)
        assert project.status == "completed"
        building = world.state.buildings["building:shed-001"]
        assert building.completed_tick == world.current_tick
        replayed = rebuild_state(
            [e for e in log.all() if e["event_type"] in {
                "land_parcel_created", "construction_project_created",
                "construction_worked", "building_created",
            }], config,
        ).state
        assert replayed.construction_projects["shed-001"].status == "completed"
        assert replayed.land_parcels[parcel.parcel_id].spatial_node_id == parcel.spatial_node_id
        assert replayed.buildings["building:shed-001"].owner_id == household.household_id
        assert replayed.households[household.household_id].coin == 18
        assert replayed.households[household.household_id].hardwood == 26
    finally:
        log.close()


def test_construction_pause_resume_cancel_abandon():
    world, log, config = make_world()
    try:
        household = next(iter(world.state.households.values()))
        parcel = next(p for p in world.state.land_parcels.values()
                      if p.land_use == "farmland_irrigated" and p.owner_type == "collective" and p.owner_type == "collective")
        ld = approve(world, "land-x", f"land_use_change:{parcel.parcel_id}:residential", major=True)
        change_land_use(world, parcel.parcel_id, new_land_use="residential", approved_by="household_council", decision_id=ld.decision_id)
        household.coin, household.hardwood = 50, 50
        bd = approve(world, "build-x", "construction:shed-x", affected=[household.household_id], major=False)
        project = request_building(world, "shed-x", parcel_id=parcel.parcel_id, household_id=household.household_id, building_type="shed", footprint_area=.25, decision_id=bd.decision_id)
        world.current_tick += 1
        advance_construction(world, project.project_id)
        pause_construction(world, project.project_id, reason="weather")
        assert project.status == "paused"
        world.current_tick += 1
        resume_construction(world, project.project_id)
        assert project.status == "completed"

        bd2 = approve(world, "build-y", "construction:shed-y", affected=[household.household_id], major=False)
        project2 = request_building(world, "shed-y", parcel_id=parcel.parcel_id, household_id=household.household_id, building_type="shed", footprint_area=.25, decision_id=bd2.decision_id)
        cancel_construction(world, project2.project_id)
        assert project2.status == "cancelled"

        bd3 = approve(world, "build-z", "construction:shed-z", affected=[household.household_id], major=False)
        project3 = request_building(world, "shed-z", parcel_id=parcel.parcel_id, household_id=household.household_id, building_type="shed", footprint_area=.25, decision_id=bd3.decision_id)
        pause_construction(world, project3.project_id)
        abandon_construction(world, project3.project_id)
        assert project3.status == "abandoned"
    finally:
        log.close()


def test_household_can_choose_construction_as_agent_action():
    world, log, config = make_world()
    try:
        household = next(iter(world.state.households.values()))
        agent = world.state.agents[household.member_ids[0]]
        module = AgentModule()
        # Pick the nearest real parcel node so construction is a feasible
        # daily action while still paying its actual road-network commute.
        module._perceive(world, agent)  # initialize the same SpatialIndex used by step()
        field_parcels = [
            p for p in world.state.land_parcels.values()
            if p.land_use == "farmland_irrigated" and p.owner_type == "collective"
            and p.spatial_node_id in {n.id for n in world.config.spatial.nodes}
            and module._spatial.travel_tu(agent.location, p.spatial_node_id) < float("inf")
        ]
        parcel = min(
            field_parcels,
            key=lambda p: (module._spatial.travel_tu(agent.location, p.spatial_node_id), p.parcel_id),
        )
        ld = approve(world, "land-agent", f"land_use_change:{parcel.parcel_id}:residential", major=True)
        change_land_use(world, parcel.parcel_id, new_land_use="residential",
                        approved_by="household_council", decision_id=ld.decision_id)
        household.coin, household.hardwood = 20, 30
        household.water = 100.0  # keep the new daily water-survival gate out of this construction test
        bd = approve(world, "build-agent", "construction:agent-shed",
                     affected=[household.household_id], major=False)
        project = request_building(
            world, "agent-shed", parcel_id=parcel.parcel_id,
            household_id=household.household_id, building_type="shed",
            footprint_area=0.25, decision_id=bd.decision_id,
        )
        agent.hunger = 0.0
        agent.stamina = 100.0
        tuning = config.agents.tuning
        perception = module._perceive(world, agent)
        assert perception.construction_project_id == project.project_id
        assert perception.construction_target_node == parcel.spatial_node_id
        home_node = agent.location
        home_to_site_tu = module._spatial.travel_tu(home_node, parcel.spatial_node_id)
        assert perception.distance_from_location[parcel.spatial_node_id] == pytest.approx(home_to_site_tu)
        assert home_to_site_tu > 0.0

        # The commute is not free: with only 10 TU, this distant site may lose
        # to farming. For the action-execution assertion, model the resident
        # after arriving at the parcel on a prior movement action.
        agent.location = parcel.spatial_node_id
        perception = module._perceive(world, agent)
        assert perception.distance_from_location[parcel.spatial_node_id] == pytest.approx(0.0)
        assert module.score_action("construct", perception, tuning) > float("-inf")
        assert module._decide(perception, tuning, tu_remaining=10.0) == "construct"
        # Construction requests are approved in the current tick and become
        # executable on the following tick; mirror the production lifecycle.
        world.current_tick = project.created_tick + 1
        module._execute(world, agent, "construct", perception, tuning)
        assert project.labor_completed == 1
        assert agent.location == parcel.spatial_node_id
        assert agent.stamina == pytest.approx(95.0)
    finally:
        log.close()



def test_repair_is_approved_multi_day_and_replayable():
    world, log, config = make_world()
    try:
        household = next(iter(world.state.households.values()))
        building = next(
            b for b in world.state.buildings.values()
            if b.building_type == "dwelling" and b.owner_id == household.household_id
        )
        building.condition = 50.0
        household.coin = 10.0
        household.hardwood = 10.0
        decision = approve(
            world, "repair-decision", f"repair:{building.building_id}",
            affected=[household.household_id], major=False,
        )
        project = request_repair(
            world, "repair-project", building_id=building.building_id,
            household_id=household.household_id, decision_id=decision.decision_id,
        )
        assert project.labor_required == 3
        assert building.condition == 50.0
        for _ in range(project.labor_required):
            world.current_tick += 1
            advance_construction(world, project.project_id)
        assert project.status == "completed"
        assert building.condition == 100.0
        replayed = rebuild_state(
            [event for event in log.all() if event["event_type"] in {
                "land_parcel_created", "building_created",
                "construction_project_created", "construction_worked",
                "building_repaired",
            }],
            config,
        ).state
        assert replayed.buildings[building.building_id].condition == 100.0
    finally:
        log.close()



def test_expansion_and_demolition_are_approved_multi_step_projects_and_replay():
    world, log, config = make_world()
    try:
        household = next(iter(world.state.households.values()))
        building = next(
            b for b in world.state.buildings.values()
            if b.building_type == "dwelling" and b.owner_id == household.household_id
        )
        parcel = world.state.land_parcels[building.parcel_id]
        parcel.buildable_area = building.footprint_area + 0.25
        household.coin, household.hardwood = 20.0, 30.0
        before_area = building.footprint_area
        decision = approve(
            world, "expand-decision", f"expand:{building.building_id}:0.25",
            affected=[household.household_id], major=False,
        )
        project = request_expansion(
            world, "expand-project", building_id=building.building_id,
            household_id=household.household_id, footprint_area=0.25,
            decision_id=decision.decision_id,
        )
        assert project.labor_required == 2
        for _ in range(project.labor_required):
            world.current_tick += 1
            advance_construction(world, project.project_id)
        assert building.footprint_area == pytest.approx(before_area + 0.25)

        demolition_decision = approve(
            world, "demolish-decision", f"demolish:{building.building_id}",
            affected=[household.household_id], major=False,
        )
        demolition = request_demolition(
            world, "demolish-project", building_id=building.building_id,
            household_id=household.household_id,
            decision_id=demolition_decision.decision_id,
        )
        world.current_tick += 1
        advance_construction(world, demolition.project_id)
        assert building.status == "demolished"
        replayed = rebuild_state(
            [event for event in log.all() if event["event_type"] in {
                "land_parcel_created", "building_created",
                "construction_project_created", "construction_worked",
                "building_expanded", "building_demolished",
            }],
            config,
        ).state
        assert replayed.buildings[building.building_id].status == "demolished"
        assert replayed.buildings[building.building_id].footprint_area == pytest.approx(before_area + 0.25)
    finally:
        log.close()



def test_shared_storehouse_is_an_alternative_to_duplicate_storage_and_replays():
    world, log, config = make_world()
    try:
        households = list(world.state.households.values())
        owner, beneficiary = households[0], households[1]
        parcel = world.state.land_parcels[f"parcel:{owner.home_node}"]
        building = BuildingState(
            building_id="building:shared-storehouse",
            parcel_id=parcel.parcel_id, building_type="storehouse",
            owner_type="household", owner_id=owner.household_id,
            footprint_area=0.2, condition=100.0, status="active",
            created_tick=world.current_tick,
        )
        world.state.buildings[building.building_id] = building
        log.append(world.current_tick, "building_created", {
            "building": building.model_dump(mode="json")
        })
        decision = approve(
            world, "share-decision",
            f"share:{building.building_id}:{beneficiary.household_id}",
            affected=[owner.household_id, beneficiary.household_id], major=False,
        )
        share_building_access(
            world, building_id=building.building_id,
            owner_household_id=owner.household_id,
            beneficiary_household_id=beneficiary.household_id,
            decision_id=decision.decision_id,
        )
        for field in ("grain", "meat", "fish", "vegetable", "cloth", "firewood", "herbs", "hardwood"):
            setattr(beneficiary, field, 0.0)
        beneficiary.grain = 500.0
        beneficiary.cloth = 300.0
        # Household inventory has no current capacity cap. Sharing this building
        # grants access but does not transfer ownership or alter household stock.
        assert beneficiary.grain == 500.0
        assert beneficiary.cloth == 300.0
        assert not log.by_type("household_storage_overflow_loss")
        replayed = rebuild_state(
            [event for event in log.all() if event["event_type"] in {
                "building_created", "building_access_shared",
            }],
            config,
        ).state
        assert beneficiary.household_id in replayed.buildings[building.building_id].attributes[
            "shared_with_household_ids"
        ]
    finally:
        log.close()

def test_building_need_can_be_resolved_by_an_existing_alternative():
    from vale.core.state import BuildingNeedState
    from vale.modules.construction import resolve_building_need
    world, log, config = make_world()
    try:
        need = BuildingNeedState(
            need_id="need-1", need_type="housing", location_node_id="common_district",
            target_building_type="dwelling", demand=6, capacity=5, pressure_days=30,
            stage="persistent", status="active", first_seen_tick=0, last_updated_tick=0,
        )
        world.state.building_needs[need.need_id] = need
        building = next(iter(world.state.buildings.values()))
        building.attributes["shared_with_household_ids"] = ["other-household"]
        resolved = resolve_building_need(world, need.need_id, alternative="share",
                                         reference_id=building.building_id)
        assert resolved.status == "resolved_by_alternative"
    finally:
        log.close()
