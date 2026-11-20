"""Council-authorized, resource-constrained household construction."""
from __future__ import annotations

from vale.contracts.queries import EnvironmentQuery
from vale.core.state import BuildingNeedState, BuildingState, ConstructionProjectState
from vale.modules.agents import age_years

# Costs are deliberately explicit and modest; future economy balancing can
# move these into location tuning without changing the event contract.
BUILDING_RECIPES = {
    "dwelling": {"coin": 5.0, "hardwood": 10.0, "labor": 4},
    "shed": {"coin": 2.0, "hardwood": 4.0, "labor": 2},
    "workshop": {"coin": 6.0, "hardwood": 8.0, "labor": 4},
    "storehouse": {"coin": 3.0, "hardwood": 6.0, "labor": 3},
}


def request_building(world, project_id: str, *, parcel_id: str,
                     household_id: str, building_type: str,
                     footprint_area: float, decision_id: str):
    if project_id in world.state.human.construction_projects or project_id in world.state.human.buildings:
        raise ValueError("project id already exists")
    recipe = BUILDING_RECIPES.get(building_type)
    if recipe is None:
        raise ValueError(f"unsupported building type: {building_type}")
    household = world.state.human.households.get(household_id)
    parcel = world.state.human.land_parcels.get(parcel_id)
    if household is None or parcel is None:
        raise ValueError("household and parcel must exist")
    if parcel.contested or parcel.land_use not in {"residential", "commercial"}:
        raise ValueError("construction requires an uncontested residential or commercial parcel")
    if parcel.owner_type == "protected" or parcel.attributes.get("restricted"):
        raise ValueError("protected or restricted land cannot be built on")
    if parcel.owner_type == "household" and parcel.owner_id != household_id:
        raise ValueError("household does not own the construction parcel")
    if parcel.owner_type not in {"household", "collective"}:
        raise ValueError("parcel ownership does not permit household construction")
    if footprint_area <= 0:
        raise ValueError("building footprint must be positive")
    occupied = sum(b.footprint_area for b in world.state.human.buildings.values()
                   if b.parcel_id == parcel_id and b.status != "demolished")
    reserved = sum(p.footprint_area for p in world.state.human.construction_projects.values()
                   if p.parcel_id == parcel_id and p.status in {"under_construction", "paused"} and p.building_type in {"dwelling", "shed", "workshop", "storehouse", "expansion"})
    if occupied + reserved + footprint_area > parcel.buildable_area + 1e-9:
        raise ValueError("building footprint exceeds the parcel's remaining buildable area")
    decision = world.state.human.council_decisions.get(decision_id)
    if (decision is None or decision.status != "approved"
            or decision.subject != f"construction:{project_id}"
            or household_id not in decision.affected_household_ids):
        raise ValueError("construction requires its matching approved council decision")
    if household.coin < recipe["coin"] or household.hardwood < recipe["hardwood"]:
        raise ValueError("household lacks the required coin or hardwood")
    household.coin = round(household.coin - recipe["coin"], 2)
    household.hardwood = round(household.hardwood - recipe["hardwood"], 2)
    project = ConstructionProjectState(
        project_id=project_id, parcel_id=parcel_id, household_id=household_id,
        building_type=building_type, footprint_area=footprint_area,
        materials_required={"coin": recipe["coin"], "hardwood": recipe["hardwood"]},
        labor_required=int(recipe["labor"]), council_decision_id=decision_id,
        created_tick=world.current_tick,
    )
    world.event_log.append(world.current_tick, "construction_project_created", {
        "project": project.model_dump(mode="json"),
        "coin_after": household.coin, "hardwood_after": household.hardwood,
    })
    world.state.human.construction_projects[project_id] = project
    return project


def request_repair(world, project_id: str, *, building_id: str,
                   household_id: str, decision_id: str):
    """Create a council-authorized repair project for a household-owned building."""
    import math

    if project_id in world.state.human.construction_projects or project_id in world.state.human.buildings:
        raise ValueError("project id already exists")
    building = world.state.human.buildings.get(building_id)
    household = world.state.human.households.get(household_id)
    if building is None or household is None:
        raise ValueError("building and household must exist")
    if building.owner_type != "household" or building.owner_id != household_id:
        raise ValueError("household must own the building being repaired")
    if building.status in {"demolished", "abandoned"} or building.condition >= 100:
        raise ValueError("building does not require repair")
    parcel = world.state.human.land_parcels.get(building.parcel_id)
    if parcel is None or parcel.contested or parcel.owner_type == "protected" or parcel.attributes.get("restricted"):
        raise ValueError("repair site is unavailable or protected")
    decision = world.state.human.council_decisions.get(decision_id)
    if (decision is None or decision.status != "approved"
            or decision.subject != f"repair:{building_id}"
            or household_id not in decision.affected_household_ids):
        raise ValueError("repair requires its matching approved council decision")
    coin_cost, hardwood_cost = 1.0, 2.0
    if household.coin < coin_cost or household.hardwood < hardwood_cost:
        raise ValueError("household lacks repair materials")
    household.coin = round(household.coin - coin_cost, 2)
    household.hardwood = round(household.hardwood - hardwood_cost, 2)
    labor_required = max(1, math.ceil((100.0 - building.condition) / 20.0))
    project = ConstructionProjectState(
        project_id=project_id, parcel_id=building.parcel_id,
        household_id=household_id, building_type="repair",
        footprint_area=building.footprint_area,
        materials_required={"coin": coin_cost, "hardwood": hardwood_cost},
        labor_required=labor_required, council_decision_id=decision_id,
        target_building_id=building_id, created_tick=world.current_tick,
    )
    world.event_log.append(world.current_tick, "construction_project_created", {
        "project": project.model_dump(mode="json"),
        "coin_after": household.coin, "hardwood_after": household.hardwood,
    })
    world.state.human.construction_projects[project_id] = project
    return project


def request_expansion(world, project_id: str, *, building_id: str,
                      household_id: str, footprint_area: float, decision_id: str):
    """Approve and schedule a bounded extension to an existing household building."""
    import math

    if project_id in world.state.human.construction_projects or project_id in world.state.human.buildings:
        raise ValueError("project id already exists")
    building = world.state.human.buildings.get(building_id)
    household = world.state.human.households.get(household_id)
    if building is None or household is None or building.owner_type != "household" or building.owner_id != household_id:
        raise ValueError("household must own the building being expanded")
    if building.status in {"ruined", "demolished", "abandoned"} or footprint_area <= 0:
        raise ValueError("building or expansion area is invalid")
    parcel = world.state.human.land_parcels.get(building.parcel_id)
    if parcel is None or parcel.contested or parcel.owner_type == "protected" or parcel.attributes.get("restricted"):
        raise ValueError("expansion site is unavailable or protected")
    decision = world.state.human.council_decisions.get(decision_id)
    subject = f"expand:{building_id}:{footprint_area:g}"
    if (decision is None or decision.status != "approved"
            or decision.subject != subject
            or household_id not in decision.affected_household_ids):
        raise ValueError("expansion requires its matching approved council decision")
    occupied = sum(b.footprint_area for b in world.state.human.buildings.values()
                   if b.parcel_id == parcel.parcel_id and b.status not in {"demolished", "ruined"})
    reserved = sum(p.footprint_area for p in world.state.human.construction_projects.values()
                   if p.parcel_id == parcel.parcel_id and p.status in {"under_construction", "paused"} and p.building_type in {"dwelling", "shed", "workshop", "storehouse", "expansion"})
    if occupied + reserved + footprint_area > parcel.buildable_area + 1e-9:
        raise ValueError("expansion exceeds the parcel's remaining buildable area")
    units = max(1, math.ceil(footprint_area / 0.25))
    coin_cost, hardwood_cost = float(units), float(2 * units)
    if household.coin < coin_cost or household.hardwood < hardwood_cost:
        raise ValueError("household lacks expansion materials")
    household.coin = round(household.coin - coin_cost, 2)
    household.hardwood = round(household.hardwood - hardwood_cost, 2)
    project = ConstructionProjectState(
        project_id=project_id, parcel_id=building.parcel_id,
        household_id=household_id, building_type="expansion",
        footprint_area=footprint_area,
        materials_required={"coin": coin_cost, "hardwood": hardwood_cost},
        labor_required=2 * units, council_decision_id=decision_id,
        target_building_id=building_id, created_tick=world.current_tick,
    )
    world.event_log.append(world.current_tick, "construction_project_created", {
        "project": project.model_dump(mode="json"),
        "coin_after": household.coin, "hardwood_after": household.hardwood,
    })
    world.state.human.construction_projects[project_id] = project
    return project


def share_building_access(world, *, building_id: str,
                            owner_household_id: str, beneficiary_household_id: str,
                            decision_id: str):
    """Share a usable workshop/storehouse as an alternative to duplicate construction."""
    building = world.state.human.buildings.get(building_id)
    owner = world.state.human.households.get(owner_household_id)
    beneficiary = world.state.human.households.get(beneficiary_household_id)
    if building is None or owner is None or beneficiary is None:
        raise ValueError("building and both households must exist")
    if building.owner_type != "household" or building.owner_id != owner_household_id:
        raise ValueError("only the owning household may share this building")
    if building.building_type not in {"workshop", "storehouse"}:
        raise ValueError("only workshops and storehouses support household sharing")
    if building.status not in {"active", "occupied"} or building.condition <= 0:
        raise ValueError("unusable buildings cannot be shared")
    if owner_household_id == beneficiary_household_id:
        raise ValueError("owner household does not need a shared access right")
    decision = world.state.human.council_decisions.get(decision_id)
    if (decision is None or decision.status != "approved"
            or decision.subject != f"share:{building_id}:{beneficiary_household_id}"
            or not {owner_household_id, beneficiary_household_id}.issubset(
                set(decision.affected_household_ids)
            )):
        raise ValueError("sharing requires an approved decision naming both households")
    shared = set(building.attributes.get("shared_with_household_ids", []))
    if beneficiary_household_id in shared:
        return building
    shared.add(beneficiary_household_id)
    building.attributes["shared_with_household_ids"] = sorted(shared)
    world.event_log.append(world.current_tick, "building_access_shared", {
        "building_id": building_id,
        "owner_household_id": owner_household_id,
        "beneficiary_household_id": beneficiary_household_id,
        "shared_with_household_ids": sorted(shared),
        "building_type": building.building_type,
    })
    return building


def request_demolition(world, project_id: str, *, building_id: str,
                       household_id: str, decision_id: str):
    """Schedule an approved one-day demolition and release the parcel footprint."""
    if project_id in world.state.human.construction_projects or project_id in world.state.human.buildings:
        raise ValueError("project id already exists")
    building = world.state.human.buildings.get(building_id)
    if building is None or building.owner_type != "household" or building.owner_id != household_id:
        raise ValueError("household must own the building being demolished")
    if building.status in {"demolished", "abandoned"}:
        raise ValueError("building is already unavailable")
    parcel = world.state.human.land_parcels.get(building.parcel_id)
    if parcel is None or parcel.contested or parcel.owner_type == "protected" or parcel.attributes.get("restricted"):
        raise ValueError("protected or missing parcel cannot be demolished")
    decision = world.state.human.council_decisions.get(decision_id)
    if (decision is None or decision.status != "approved"
            or decision.subject != f"demolish:{building_id}"
            or household_id not in decision.affected_household_ids):
        raise ValueError("demolition requires its matching approved council decision")
    project = ConstructionProjectState(
        project_id=project_id, parcel_id=building.parcel_id,
        household_id=household_id, building_type="demolition",
        footprint_area=building.footprint_area,
        labor_required=1, council_decision_id=decision_id,
        target_building_id=building_id, created_tick=world.current_tick,
    )
    world.event_log.append(world.current_tick, "construction_project_created", {
        "project": project.model_dump(mode="json"),
        "coin_after": world.state.human.households[household_id].coin,
        "hardwood_after": world.state.human.households[household_id].hardwood,
    })
    world.state.human.construction_projects[project_id] = project
    return project


def advance_construction(world, project_id: str, *, worker_id=None):
    project = world.state.human.construction_projects.get(project_id)
    if project is None or project.status not in {"under_construction", "paused"}:
        raise ValueError("construction project is not active")
    if world.current_tick <= project.created_tick:
        raise ValueError("construction work begins on a later tick than approval")
    parcel = world.state.human.land_parcels.get(project.parcel_id)
    valid_nodes = {node.id for node in world.config.spatial.nodes}
    if parcel is None or parcel.spatial_node_id not in valid_nodes:
        raise ValueError("construction parcel must resolve to an existing spatial node")
    if project.status == "paused":
        project.status = "under_construction"
        project.paused_tick = None
    if project.last_work_tick == world.current_tick:
        raise ValueError("a project can receive labor only once per tick")
    household = world.state.human.households[project.household_id]
    workers = [
        world.state.human.agents[agent_id] for agent_id in household.member_ids
        if agent_id in world.state.human.agents
        and world.state.human.agents[agent_id].alive
        and not world.state.human.agents[agent_id].incapacitated
        and age_years(world.state.human.agents[agent_id].birth_tick, world.current_tick) >= 16
        and world.state.human.agents[agent_id].stamina >= 5.0
    ]
    if not workers:
        raise ValueError("household has no available worker with sufficient stamina")
    if worker_id is not None:
        worker = next((a for a in workers if a.agent_id == worker_id), None)
        if worker is None:
            raise ValueError("selected construction worker is unavailable")
    else:
        worker = max(workers, key=lambda agent: (agent.stamina, agent.agent_id))
    worker.stamina = round(worker.stamina - 5.0, 2)
    environment = world.config.agents.tuning.environment
    # Fatigue is already represented as additional action time by AgentModule.
    # Construction progress per completed work action remains constant.
    labor_factor = 1.0
    weather = EnvironmentQuery.weather_name(world)
    if "rain" in str(weather).lower() or "雨" in str(weather):
        labor_factor *= environment.construction_bad_weather_multiplier
    season = EnvironmentQuery.season_name(world)
    labor_factor *= environment.construction_season_multiplier.get(str(season), 1.0)
    labor_contribution = max(0.1, labor_factor)
    project.labor_completed = round(min(float(project.labor_required), project.labor_completed + labor_contribution), 3)
    project.last_work_tick = world.current_tick
    if project.labor_completed >= project.labor_required:
        project.status = "completed"
    world.event_log.append(world.current_tick, "construction_worked", {
        "project": project.model_dump(mode="json"),
        "worker_id": worker.agent_id,
        "stamina_after": worker.stamina,
        "labor_contribution": round(labor_contribution, 3),
        "spatial_node_id": parcel.spatial_node_id,
    })
    if project.status == "completed":
        if project.target_building_id:
            building = world.state.human.buildings.get(project.target_building_id)
            if building is None:
                raise ValueError("target building no longer exists")
            if project.building_type == "repair":
                before = building.condition
                building.condition = min(100.0, round(before + project.labor_required * 20.0, 2))
                if building.condition > 0 and building.status == "ruined":
                    building.status = "active"
                world.event_log.append(world.current_tick, "building_repaired", {
                    "building_id": building.building_id,
                    "condition_before": before, "condition_after": building.condition,
                    "project_id": project.project_id,
                })
            elif project.building_type == "expansion":
                before = building.footprint_area
                building.footprint_area = round(before + project.footprint_area, 3)
                world.event_log.append(world.current_tick, "building_expanded", {
                    "building_id": building.building_id,
                    "footprint_before": before, "footprint_after": building.footprint_area,
                    "project_id": project.project_id,
                })
            elif project.building_type == "demolition":
                building.status = "demolished"
                building.condition = 0.0
                world.event_log.append(world.current_tick, "building_demolished", {
                    "building_id": building.building_id,
                    "footprint_released": building.footprint_area,
                    "project_id": project.project_id,
                })
        else:
            building = BuildingState(
                building_id=f"building:{project.project_id}",
                parcel_id=project.parcel_id, building_type=project.building_type,
                owner_type="household", owner_id=project.household_id,
                footprint_area=project.footprint_area, condition=100.0,
                status="active", created_tick=project.created_tick,
                completed_tick=world.current_tick,
                attributes={"construction_project_id": project.project_id},
            )
            world.event_log.append(world.current_tick, "building_created", {
                "building": building.model_dump(mode="json"),
            })
            world.state.human.buildings[building.building_id] = building
    return project


def pause_construction(world, project_id: str, *, reason: str = "household_choice"):
    project = world.state.human.construction_projects.get(project_id)
    if project is None or project.status != "under_construction":
        raise ValueError("only active construction can be paused")
    project.status = "paused"
    project.paused_tick = world.current_tick
    world.event_log.append(world.current_tick, "construction_paused", {"project": project.model_dump(mode="json"), "reason": reason})
    return project

def cancel_construction(world, project_id: str, *, reason: str = "household_choice"):
    project = world.state.human.construction_projects.get(project_id)
    if project is None or project.status not in {"under_construction", "paused"}:
        raise ValueError("construction project is not cancellable")
    project.status = "cancelled"
    project.cancelled_tick = world.current_tick
    project.cancel_reason = reason
    world.event_log.append(world.current_tick, "construction_cancelled", {"project": project.model_dump(mode="json"), "reason": reason})
    return project

def abandon_construction(world, project_id: str, *, reason: str = "long_inactivity"):
    project = world.state.human.construction_projects.get(project_id)
    if project is None or project.status != "paused":
        raise ValueError("only paused construction can be abandoned")
    project.status = "abandoned"
    project.abandoned_tick = world.current_tick
    project.cancel_reason = reason
    world.event_log.append(world.current_tick, "construction_abandoned", {"project": project.model_dump(mode="json"), "reason": reason})
    return project

def resume_construction(world, project_id: str):
    project = world.state.human.construction_projects.get(project_id)
    if project is None or project.status != "paused":
        raise ValueError("only paused construction can be resumed")
    return advance_construction(world, project_id)

def resolve_building_need(world, need_id: str, *, alternative: str, reference_id: str | None = None):
    """Close a persistent building need only after a concrete alternative exists."""
    need = world.state.human.building_needs.get(need_id)
    if need is None or need.status != "active":
        raise ValueError("building need is not active")
    if alternative not in need.alternatives and alternative not in {"rent", "defer"}:
        raise ValueError("alternative is not available for this need")
    if alternative in {"repair", "extend", "share"}:
        building = world.state.human.buildings.get(reference_id or "")
        if building is None or building.status not in {"active", "occupied"}:
            raise ValueError("a usable building reference is required")
        if alternative == "repair" and building.condition >= 100:
            raise ValueError("building does not need repair")
        if alternative == "extend" and building.footprint_area <= 0:
            raise ValueError("building cannot be extended")
        if alternative == "share" and not building.attributes.get("shared_with_household_ids"):
            raise ValueError("building has not been shared")
    elif alternative == "rent":
        if not any(
            lease.get("status") == "active"
            and lease.get("lessee_household_id") == reference_id
            and world.state.human.land_parcels.get(lease.get("parcel_id")) is not None
            and world.state.human.land_parcels[lease["parcel_id"]].spatial_node_id == need.location_node_id
            for lease in world.state.human.land_leases.values()
        ):
            raise ValueError("an active lease at the needed location is required")
    elif alternative == "relocate":
        household = world.state.human.households.get(reference_id or "")
        if household is None or household.home_node == need.location_node_id:
            raise ValueError("a household relocated away from the pressured location is required")
    elif alternative != "defer":
        raise ValueError("unsupported need resolution")
    after = need.model_copy(update={
        "status": "deferred" if alternative == "defer" else "resolved_by_alternative",
        "stage": "deferred" if alternative == "defer" else "resolved",
        "last_updated_tick": world.current_tick,
    })
    world.event_log.append(world.current_tick, "building_need_resolved", {
        "need": after.model_dump(mode="json"), "alternative": alternative,
        "reference_id": reference_id,
    })
    world.state.human.building_needs[need_id] = after
    return after
