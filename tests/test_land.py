from __future__ import annotations

import pytest

from vale.core.config_loader import LoadedConfig, load_config
from vale.core.event_log import EventLog
from vale.core.replay import rebuild_state
from vale.core.world import World
from vale.modules.agents import AgentModule
from vale.modules.land import (
    change_land_use, grant_land_right, transfer_land_ownership, relocate_household,
    settle_household_land_inheritance,
)
from vale.modules.governance import cast_council_vote, propose_council_decision, register_representative
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
        resources=generated.resources,
    )
    log = EventLog(":memory:")
    world = World(config.world.world_id, log, config.world.start_tick, config)
    AgentModule()._ensure_agents(world, config.agents)
    # P4：地形栅格由环境域引导（不再由 land 模块跨域写入），显式触发一次。
    from vale.modules.ecology import ensure_terrain_cells
    ensure_terrain_cells(world)
    return world, log, config


def test_land_initialization_layers_cells_parcels_and_buildings_on_brookvale():
    world, log, _ = make_world()
    try:
        residences = [n for n in world.config.spatial.nodes if n.attributes.get("residence")]
        fields = [n for n in world.config.spatial.nodes if n.type.value == "field" and not n.attributes.get("abstract_zone")]
        assert world.world_id == "brookvale-town-001"
        assert len(world.state.environment.terrain_cells) == len(world.config.terrain)
        assert len(world.state.human.land_parcels) == len(world.config.spatial.nodes)
        assert len(world.state.human.buildings) == len(residences) + 1
        assert world.state.human.buildings["building:community_storehouse"].owner_type == "collective"

        home_parcels = [world.state.human.land_parcels[f"parcel:{n.id}"] for n in residences]
        owned = [p for p in home_parcels if p.owner_type == "household"]
        vacant = [p for p in home_parcels if p.attributes["vacant_home"]]
        assert len(owned) == 30
        assert len(vacant) == 10
        assert all(p.owner_id in world.state.human.households for p in owned)
        assert all(p.owner_type == "collective" and p.owner_id == "village" for p in vacant)

        field_parcels = [world.state.human.land_parcels[f"parcel:{n.id}"] for n in fields]
        assert len(field_parcels) == 21
        sacred_oak = world.state.human.land_parcels["parcel:sacred_oak"]
        assert sacred_oak.land_use == "protected" and sacred_oak.owner_type == "protected"
        li_quan_household = world.state.human.agents["li_quan"].household_id
        private_fields = [p for p in field_parcels if p.owner_type == "household"]
        assert len(private_fields) == 1
        assert private_fields[0].owner_id == li_quan_household
        assert all(p.owner_type == "collective" for p in field_parcels if p not in private_fields)
        for household in world.state.human.households.values():
            for node_id in household.work_nodes:
                parcel = world.state.human.land_parcels[f"parcel:{node_id}"]
                assert any(
                    right.holder_id == household.household_id
                    and right.right_type == "cultivate"
                    for right in parcel.use_rights
                )
        assert len(log.by_type("land_parcel_created")) == len(world.state.human.land_parcels)
        assert len(log.by_type("building_created")) == len(residences) + 1
        assert "building:community_storehouse" in world.state.human.buildings
    finally:
        log.close()


def test_household_can_transfer_owned_homestead_and_replay_it():
    world, log, config = make_world()
    try:
        households = sorted(world.state.human.households)
        parcel = next(
            p for p in world.state.human.land_parcels.values()
            if p.land_use == "residential" and p.owner_type == "household"
        )
        new_owner = next(h for h in households if h != parcel.owner_id)
        transfer_land_ownership(
            world, parcel.parcel_id,
            new_owner_household_id=new_owner,
            actor_id=world.state.human.households[parcel.owner_id].head_id or "head",
        )
        assert parcel.owner_id == new_owner

        land_events = [
            event for event in log.all()
            if event["event_type"].startswith("land_")
            or event["event_type"].startswith("building_")
        ]
        replayed = rebuild_state(land_events, config).state
        assert replayed.human.land_parcels[parcel.parcel_id].owner_id == new_owner
        assert replayed.human.buildings[f"building:{parcel.spatial_node_id}"].owner_id == new_owner
    finally:
        log.close()


def test_collective_and_protected_land_cannot_be_sold_or_granted_private_cultivation():
    world, log, _ = make_world()
    try:
        households = sorted(world.state.human.households)
        with pytest.raises(ValueError, match="only household-owned"):
            transfer_land_ownership(
                world, "parcel:deep_mountain",
                new_owner_household_id=households[0], actor_id="village_head",
            )
        with pytest.raises(ValueError, match="protected land"):
            grant_land_right(
                world, "parcel:deep_mountain", holder_type="household",
                holder_id=households[0], right_type="gather",
            )
    finally:
        log.close()


def test_farmland_use_change_requires_council_decision_and_is_replayable():
    world, log, config = make_world()
    try:
        parcel = next(
            p for p in world.state.human.land_parcels.values()
            if p.land_use == "farmland_irrigated"
        )
        with pytest.raises(ValueError, match="household council decision"):
            change_land_use(
                world, parcel.parcel_id, new_land_use="residential",
                approved_by="headman", decision_id="",
            )
        for household in world.state.human.households.values():
            adult = next((world.state.human.agents[aid] for aid in household.member_ids
                          if world.state.human.agents[aid].alive
                          and (world.current_tick - world.state.human.agents[aid].birth_tick) // 365 >= 18), None)
            if adult:
                register_representative(world, household.household_id, adult.agent_id)
        reps = list(world.state.human.representatives.values())
        decision = propose_council_decision(
            world, "council-0001",
            subject=f"land_use_change:{parcel.parcel_id}:residential",
            proposer_agent_id=reps[0].agent_id, major=True,
        )
        for rep in reps:
            cast_council_vote(world, decision.decision_id, rep.agent_id, True)
            if decision.status != "voting":
                break
        assert decision.status == "approved"
        change_land_use(
            world, parcel.parcel_id, new_land_use="residential",
            approved_by="household_council", decision_id=decision.decision_id,
        )
        events = [
            event for event in log.all()
            if event["event_type"].startswith("land_")
        ]
        replayed = rebuild_state(events, config).state
        assert replayed.human.land_parcels[parcel.parcel_id].land_use == "residential"
    finally:
        log.close()



def test_household_can_relocate_to_vacant_reserved_dwelling_with_council_approval():
    world, log, config = make_world()
    try:
        household = next(iter(world.state.human.households.values()))
        destination = next(
            building for building in world.state.human.buildings.values()
            if building.building_type == "dwelling" and building.status == "vacant"
        )
        new_parcel = world.state.human.land_parcels[destination.parcel_id]
        old_node = household.home_node
        for candidate in world.state.human.households.values():
            adult = next((
                world.state.human.agents[aid] for aid in candidate.member_ids
                if world.state.human.agents[aid].alive
                and (world.current_tick - world.state.human.agents[aid].birth_tick) // 365 >= 18
            ), None)
            if adult:
                register_representative(world, candidate.household_id, adult.agent_id)
        reps = list(world.state.human.representatives.values())
        decision = propose_council_decision(
            world, "relocation-decision",
            subject=f"relocate:{household.household_id}:{new_parcel.parcel_id}",
            proposer_agent_id=next(rep.agent_id for rep in reps
                                    if rep.household_id != household.household_id),
            affected_household_ids=[household.household_id], major=False,
        )
        for rep in reps:
            if rep.household_id == household.household_id:
                continue
            cast_council_vote(world, decision.decision_id, rep.agent_id, True)
            if decision.status != "voting":
                break
        assert decision.status == "approved"
        relocate_household(
            world, household_id=household.household_id,
            new_parcel_id=new_parcel.parcel_id, decision_id=decision.decision_id,
        )
        assert household.home_node == new_parcel.spatial_node_id
        assert world.state.human.land_parcels[f"parcel:{old_node}"].owner_type == "collective"
        assert new_parcel.owner_id == household.household_id
        assert destination.status == "occupied"
        assert world.state.human.buildings[f"building:{old_node}"].status == "vacant"

        replay_events = [
            event for event in log.all()
            if event["event_type"] in {"land_parcel_created", "building_created", "household_relocated"}
        ]
        replay_events.append({
            "id": 0, "event_type": "household_registered", "tick": world.current_tick,
            "payload": {"household_id": household.household_id,
                        "home_node": old_node, "work_node": household.work_node,
                        "registered_tick": world.current_tick},
        })
        replay_events.sort(key=lambda event: event.get("id", 10**9))
        replayed = rebuild_state(replay_events, config).state
        assert replayed.human.households[household.household_id].home_node == new_parcel.spatial_node_id
        assert replayed.human.land_parcels[new_parcel.parcel_id].owner_id == household.household_id
        assert replayed.human.buildings[destination.building_id].status == "occupied"
    finally:
        log.close()



def test_last_member_inherits_private_land_buildings_and_collective_use_rights_with_replay():
    world, log, config = make_world()
    try:
        deceased_hh = next(iter(world.state.human.households.values()))
        heir_hh = next(h for h in world.state.human.households.values()
                       if h.household_id != deceased_hh.household_id)
        private_parcel = next(
            p for p in world.state.human.land_parcels.values()
            if p.owner_type == "household" and p.owner_id == deceased_hh.household_id
        )
        building = next(
            b for b in world.state.human.buildings.values() if b.parcel_id == private_parcel.parcel_id
        )
        collective_field = next(
            p for p in world.state.human.land_parcels.values()
            if p.land_use.startswith("farmland") and p.owner_type == "collective"
            and any(r.holder_id == deceased_hh.household_id for r in p.use_rights)
        )
        right = next(r for r in collective_field.use_rights
                     if r.holder_id == deceased_hh.household_id)
        changed = settle_household_land_inheritance(
            world, deceased_household_id=deceased_hh.household_id,
            heir_household_id=heir_hh.household_id, deceased_agent_id=deceased_hh.head_id,
        )
        assert private_parcel.parcel_id in changed
        assert private_parcel.owner_id == heir_hh.household_id
        assert building.owner_id == heir_hh.household_id
        assert right.holder_id == heir_hh.household_id

        events = [
            e for e in log.all()
            if e["event_type"] in {
                "land_parcel_created", "building_created", "land_right_granted",
                "land_ownership_inherited", "land_right_inherited",
            }
        ]
        replayed = rebuild_state(events, config).state
        assert replayed.human.land_parcels[private_parcel.parcel_id].owner_id == heir_hh.household_id
        assert replayed.human.buildings[building.building_id].owner_id == heir_hh.household_id
        replay_right = next(r for r in replayed.human.land_parcels[collective_field.parcel_id].use_rights
                            if r.right_id == right.right_id)
        assert replay_right.holder_id == heir_hh.household_id
    finally:
        log.close()


def test_private_land_returns_to_village_when_household_has_no_heir():
    world, log, config = make_world()
    try:
        deceased_hh = next(iter(world.state.human.households.values()))
        private_parcel = next(
            p for p in world.state.human.land_parcels.values()
            if p.owner_type == "household" and p.owner_id == deceased_hh.household_id
        )
        building = next(
            b for b in world.state.human.buildings.values() if b.parcel_id == private_parcel.parcel_id
        )
        changed = settle_household_land_inheritance(
            world, deceased_household_id=deceased_hh.household_id,
            heir_household_id=None, deceased_agent_id=deceased_hh.head_id,
        )
        assert private_parcel.parcel_id in changed
        assert private_parcel.owner_type == "collective"
        assert private_parcel.owner_id == "village"
        assert private_parcel.management_authority == "village_council"
        assert building.owner_type == "collective" and building.owner_id == "village"
        events = [
            e for e in log.all()
            if e["event_type"] in {
                "land_parcel_created", "building_created", "land_ownership_escheated",
            }
        ]
        replayed = rebuild_state(events, config).state
        assert replayed.human.land_parcels[private_parcel.parcel_id].owner_type == "collective"
        assert replayed.human.buildings[building.building_id].owner_id == "village"
    finally:
        log.close()

def test_household_inheritance_transfers_active_land_lease_party():
    from vale.modules.land import settle_household_land_inheritance
    world, log, config = make_world()
    try:
        source = next(iter(world.state.human.households.values()))
        heir = next(h for h in world.state.human.households.values() if h.household_id != source.household_id)
        world.state.human.land_leases["lease-in"] = {
            "lease_id": "lease-in", "parcel_id": next(iter(world.state.human.land_parcels)),
            "lessor_household_id": source.household_id,
            "lessee_household_id": heir.household_id, "status": "active",
            "rent_item": "coin", "rent_per_period": 1, "next_due_tick": 30,
            "expires_tick": 100,
        }
        settle_household_land_inheritance(
            world, deceased_household_id=source.household_id,
            heir_household_id=heir.household_id, deceased_agent_id=source.head_id,
        )
        assert world.state.human.land_leases["lease-in"]["lessor_household_id"] == heir.household_id
    finally:
        log.close()

def test_household_can_relinquish_non_residential_land_to_collective():
    from vale.modules.land import relinquish_household_parcel
    world, log, _ = make_world()
    try:
        parcel = next(p for p in world.state.human.land_parcels.values()
                      if p.owner_type == "household" and p.land_use.startswith("farmland"))
        relinquish_household_parcel(world, parcel.parcel_id, household_id=parcel.owner_id)
        assert parcel.owner_type == "collective" and parcel.owner_id == "village"
        assert parcel.management_authority == "village_council"
    finally:
        log.close()
