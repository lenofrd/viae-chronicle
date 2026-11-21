"""Building, fatigue, public-service and terrain effects for residents."""
from __future__ import annotations

from vale.contracts.queries import EnvironmentQuery


def fatigue_efficiency(agent, tuning) -> float:
    """Return labor speed after a sustained high-fatigue spell.

    Fatigue never multiplies harvested or gathered quantities. Once fatigue has
    remained above the configured threshold for the grace period, the same job
    consumes more work time; this keeps output per completed job unchanged.
    """
    if int(getattr(agent, "fatigue_high_days", 0)) < tuning.fatigue_efficiency_grace_days:
        return 1.0
    over = max(0.0, float(agent.fatigue) - tuning.fatigue_efficiency_threshold)
    loss = min(tuning.max_fatigue_efficiency_loss,
               over * tuning.fatigue_efficiency_loss_per_point)
    return max(1.0 - tuning.max_fatigue_efficiency_loss, 1.0 - loss)


def production_efficiency_at_node(world, node_id: str, action: str, tuning) -> float:
    """Return a bounded production multiplier from active buildings at a spatial node.

    Parcel.spatial_node_id is the sole parcel-to-map mapping. Broken or missing
    mappings grant no effect; building bonuses never teleport to a household home.
    """
    if not node_id:
        return 1.0
    bonus = 0.0
    for building in world.state.human.buildings.values():
        if building.status not in {"active", "occupied"} or building.condition <= 0:
            continue
        parcel = world.state.human.land_parcels.get(building.parcel_id)
        if parcel is None or parcel.spatial_node_id != node_id:
            continue
        by_action = tuning.production_efficiency_by_building.get(building.building_type, {})
        configured = float(by_action.get(action, 0.0))
        configured = float(building.attributes.get("efficiency_by_action", {}).get(action, configured))
        bonus += max(0.0, configured) * building.condition / 100.0
    return 1.0 + min(tuning.max_production_efficiency_bonus, bonus)


def environmental_injury_multiplier(world, node_id: str, is_raining: bool, tuning) -> float:
    """Read site exposure from spatial content; deep terrain is risky, not silently safe."""
    node = next((item for item in world.config.spatial.nodes if item.id == node_id), None)
    if node is None:
        return 1.0
    attrs = node.attributes or {}
    site = max(1.0, float(attrs.get("injury_risk_multiplier", 1.0)))
    weather = tuning.bad_weather_injury_multiplier if is_raining else 1.0
    return site * weather


def service_capacity_available(world, node_id: str, service: str, tuning) -> bool:
    """Limit public-service throughput by counting already completed uses this tick.

    Missing capacity means unconstrained for backwards compatibility. Capacity is
    a daily throughput, not a permanent occupancy limit.
    """
    node_caps = tuning.service_capacity_by_node.get(node_id, {})
    capacity = node_caps.get(service)
    if capacity is None:
        return True
    used = 0
    for event in world.event_log.by_type_at_tick("agent_action_taken", world.current_tick):
        payload = event.get("payload") or {}
        if payload.get("target_node") == node_id and payload.get("action") == service:
            used += 1
    return used < int(capacity)



def settle_community_reserves(world, environment_tuning, agent_tuning) -> None:
    """Deprecated compatibility shim: public reserves are never moved automatically."""
    return None


def _community_storehouse_and_manager(world, manager_agent_id: str | None = None):
    storehouse = next((
        building for building in world.state.human.buildings.values()
        if building.building_type == "storehouse"
        and building.attributes.get("community_reserve")
        and building.status in {"active", "occupied"}
        and building.condition > 0
    ), None)
    if storehouse is None:
        raise ValueError("no active community storehouse")
    assigned_manager = (
        storehouse.attributes.get("manager_agent_id")
        or world.state.human.headman_id
        or world.state.human.acting_headman_id
    )
    if not assigned_manager:
        raise PermissionError("community storehouse has no appointed manager")
    if manager_agent_id is not None and manager_agent_id != assigned_manager:
        raise PermissionError("only the appointed storehouse manager may approve relief")
    manager = world.state.human.agents.get(assigned_manager)
    if manager is None or not manager.alive:
        raise PermissionError("community storehouse manager is unavailable")
    return storehouse, manager


def contribute_to_community_reserve(
    world, household_id: str, contributor_agent_id: str, resource: str, amount: float
) -> float:
    """Record an explicit, voluntary household contribution to the public reserve."""
    household = world.state.human.households.get(household_id)
    if household is None:
        raise ValueError(f"unknown household: {household_id}")
    contributor = world.state.human.agents.get(contributor_agent_id)
    if (contributor is None or not contributor.alive
            or contributor_agent_id not in household.member_ids):
        raise PermissionError("contributor must be a living member of the contributing household")
    storehouse, manager = _community_storehouse_and_manager(world)
    environment = world.config.agents.tuning.environment
    food_fields = set(world.config.agents.tuning.physiology.food_fields)
    if resource not in food_fields | {"water"}:
        raise ValueError(f"unsupported public-reserve resource: {resource}")
    amount = round(float(amount), 2)
    if amount <= 0:
        raise ValueError("contribution amount must be positive")
    stock = max(0.0, float(getattr(household, resource, 0.0)))
    if amount > stock + 1e-9:
        raise ValueError("contribution exceeds household-owned stock")
    reserve = world.state.human.community_reserves
    if resource == "water":
        capacity = min(environment.community_water_reserve_capacity, float(
            storehouse.attributes.get("water_reserve_capacity", environment.community_water_reserve_capacity)
        ))
        used = float(reserve.get("water", 0.0))
    else:
        capacity = min(environment.community_food_reserve_capacity, float(
            storehouse.attributes.get("food_reserve_capacity", environment.community_food_reserve_capacity)
        ))
        used = sum(float(reserve.get(item, 0.0)) for item in food_fields)
    if amount > max(0.0, capacity - used) + 1e-9:
        raise ValueError("contribution exceeds available public storage capacity")
    after = round(stock - amount, 2)
    setattr(household, resource, after)
    reserve[resource] = round(float(reserve.get(resource, 0.0)) + amount, 2)
    world.event_log.append(world.current_tick, "community_reserve_voluntarily_deposited", {
        "household_id": household_id, "contributor_agent_id": contributor_agent_id,
        "manager_agent_id": manager.agent_id, "storehouse_id": storehouse.building_id,
        "resource": resource, "amount": amount,
        "household_inventory_after": {resource: after}, "reserve_after": {resource: reserve[resource]},
    })
    return amount


def request_community_relief(
    world, household_id: str, applicant_agent_id: str, requested_resources: dict[str, float]
) -> str:
    """A household member applies for relief; this queues but never issues stock."""
    household = world.state.human.households.get(household_id)
    applicant = world.state.human.agents.get(applicant_agent_id)
    if (household is None or applicant is None or not applicant.alive
            or applicant_agent_id not in household.member_ids):
        raise PermissionError("relief applicant must be a living member of the household")
    _community_storehouse_and_manager(world)
    allowed = set(world.config.agents.tuning.physiology.food_fields) | {"water"}
    clean = {}
    for resource, amount in requested_resources.items():
        if resource not in allowed:
            raise ValueError(f"unsupported relief resource: {resource}")
        value = round(float(amount), 2)
        if value < 0:
            raise ValueError("requested relief amounts cannot be negative")
        if value > 0:
            clean[resource] = value
    if not clean:
        raise ValueError("relief request must contain a positive amount")
    sequence = sum(
        1 for item in world.state.human.service_queues.values()
        if item.get("queue_type") == "community_relief"
        and item.get("household_id") == household_id
    ) + 1
    request_id = f"relief:{household_id}:{world.current_tick}:{sequence}"
    queue_after = {
        "queue_type": "community_relief", "request_id": request_id,
        "household_id": household_id, "applicant_agent_id": applicant_agent_id,
        "requested_resources": clean, "status": "pending", "created_tick": world.current_tick,
    }
    world.state.human.service_queues[request_id] = queue_after
    world.event_log.append(world.current_tick, "service_request_queued", {
        "queue_key": request_id, "queue_after": queue_after,
    })
    return request_id


def approve_community_relief(
    world, request_id: str, manager_agent_id: str, approved_resources: dict[str, float]
) -> dict[str, float]:
    """Issue only resources explicitly approved by the appointed storehouse manager."""
    _, manager = _community_storehouse_and_manager(world, manager_agent_id)
    request = world.state.human.service_queues.get(request_id)
    if request is None or request.get("queue_type") != "community_relief":
        raise ValueError("unknown community relief request")
    if request.get("status") != "pending":
        raise ValueError("community relief request is not pending")
    household = world.state.human.households.get(request.get("household_id", ""))
    if household is None:
        raise ValueError("relief applicant household no longer exists")
    requested = request.get("requested_resources") or {}
    clean = {}
    for resource, amount in approved_resources.items():
        value = round(float(amount), 2)
        if resource not in requested or value < 0 or value > float(requested[resource]) + 1e-9:
            raise ValueError("approved relief must not exceed the household's requested resources")
        if value > 0:
            clean[resource] = value
    if not clean:
        raise ValueError("approved relief must contain a positive amount")
    reserve = world.state.human.community_reserves
    for resource, amount in clean.items():
        if float(reserve.get(resource, 0.0)) + 1e-9 < amount:
            raise ValueError(f"insufficient public reserve: {resource}")
    for resource, amount in clean.items():
        setattr(household, resource, round(float(getattr(household, resource, 0.0)) + amount, 2))
        reserve[resource] = round(float(reserve.get(resource, 0.0)) - amount, 2)
    inventory_after = {resource: round(float(getattr(household, resource)), 2) for resource in clean}
    reserve_after = {resource: round(float(reserve.get(resource, 0.0)), 2) for resource in clean}
    world.event_log.append(world.current_tick, "community_relief_issued", {
        "request_id": request_id, "household_id": household.household_id,
        "manager_agent_id": manager.agent_id, "resources": clean,
        "household_inventory_after": inventory_after, "reserve_after": reserve_after,
    })
    queue_after = {**request, "status": "approved", "approved_resources": clean,
                   "resolved_tick": world.current_tick}
    world.state.human.service_queues[request_id] = queue_after
    world.event_log.append(world.current_tick, "service_queue_processed", {
        "queue_key": request_id, "queue_after": queue_after,
    })
    return clean


def update_building_needs(world, tuning) -> None:
    """Advance buffered demand signals for housing, workshops and household storage.

    A need is a signal for deliberation, never an automatic construction order.
    Existing alternatives (repair, extension, sharing, relocation) remain visible.
    """
    from math import ceil
    from vale.core.state import BuildingNeedState
    from vale.core.household import living_households

    def update(need_id: str, need_type: str, node_id: str, building_type: str,
               demand: float, capacity: float, pressured: bool) -> None:
        previous = world.state.human.building_needs.get(need_id)
        if not pressured and (previous is None or previous.status == "resolved"):
            return
        first_seen = previous.first_seen_tick if previous and previous.status == "active" else world.current_tick
        pressure_days = (previous.pressure_days + 1) if pressured and previous and previous.status == "active" else (1 if pressured else 0)
        if not pressured:
            stage, status = "resolved", "resolved"
        elif pressure_days >= tuning.building_need_priority_days:
            stage, status = "prioritized", "active"
        elif pressure_days >= tuning.building_need_persistent_days:
            stage, status = "persistent", "active"
        elif pressure_days >= tuning.building_need_emerging_days:
            stage, status = "emerging", "active"
        else:
            stage, status = "latent", "active"
        need = BuildingNeedState(
            need_id=need_id, need_type=need_type, location_node_id=node_id,
            target_building_type=building_type, demand=max(0.0, demand),
            capacity=max(0.0, capacity), pressure_days=pressure_days,
            stage=stage, status=status, first_seen_tick=first_seen,
            last_updated_tick=world.current_tick,
        )
        if previous is not None and previous.model_dump() == need.model_dump():
            return
        world.state.human.building_needs[need_id] = need
        world.event_log.append(world.current_tick, "building_need_updated", {
            "need": need.model_dump(mode="json"),
        })

    households = living_households(world)
    occupied_nodes = {household.home_node for household in households}
    dwellings = []
    for building in world.state.human.buildings.values():
        if building.building_type != "dwelling" or building.status in {"ruined", "demolished"}:
            continue
        parcel = world.state.human.land_parcels.get(building.parcel_id)
        if parcel is not None:
            dwellings.append((building, parcel.spatial_node_id))
    vacant = sum(1 for _, node_id in dwellings if node_id not in occupied_nodes)
    reserve_target = ceil(len(households) * tuning.dwelling_reserve_ratio)
    update(
        "village:housing_reserve", "housing_reserve", "village",
        "dwelling", float(reserve_target), float(vacant),
        bool(households) and vacant < reserve_target,
    )

    for household in households:
        residents = sum(
            1 for member_id in household.member_ids
            if member_id in world.state.human.agents and world.state.human.agents[member_id].alive
        )
        dwelling = next((
            building for building in world.state.human.buildings.values()
            if building.building_type == "dwelling"
            and building.status in {"active", "occupied", "vacant"}
            and (parcel := world.state.human.land_parcels.get(building.parcel_id)) is not None
            and parcel.spatial_node_id == household.home_node
        ), None)
        capacity = (
            float(dwelling.attributes.get("resident_capacity", tuning.dwelling_resident_capacity))
            if dwelling is not None and dwelling.condition > 0 else 0.0
        )
        update(
            f"household:{household.household_id}:dwelling_capacity",
            "housing_capacity", household.home_node, "dwelling",
            float(residents), capacity, residents > capacity,
        )

    recent_actions = [
        event for event in world.event_log.by_type_between_ticks(
            "agent_action_taken", world.current_tick - 30, world.current_tick
        )
    ]
    weave_by_node: dict[str, int] = {}
    for event in recent_actions:
        payload = event.get("payload") or {}
        if payload.get("action") == "weave":
            node = payload.get("target_node") or payload.get("work_node")
            if node:
                weave_by_node[node] = weave_by_node.get(node, 0) + 1
    threshold = int(getattr(tuning, "workshop_need_actions_per_30_days", 20))
    tracked_workshop_nodes = set(weave_by_node)
    tracked_workshop_nodes.update(
        need.location_node_id for need in world.state.human.building_needs.values()
        if need.need_type == "production_capacity" and need.status == "active"
    )
    for node_id in sorted(tracked_workshop_nodes):
        count = weave_by_node.get(node_id, 0)
        has_workshop = any(
            building.building_type == "workshop"
            and building.status in {"active", "occupied"}
            and (parcel := world.state.human.land_parcels.get(building.parcel_id)) is not None
            and parcel.spatial_node_id == node_id
            for building in world.state.human.buildings.values()
        )
        update(
            f"node:{node_id}:workshop", "production_capacity", node_id,
            "workshop", float(count), float(threshold),
            count >= threshold and not has_workshop,
        )

    for building in world.state.human.buildings.values():
        need_id = f"building:{building.building_id}:repair"
        if building.status in {"demolished", "abandoned"}:
            previous = world.state.human.building_needs.get(need_id)
            if previous is not None and previous.status == "active":
                parcel = world.state.human.land_parcels.get(building.parcel_id)
                node_id = parcel.spatial_node_id if parcel is not None else "unknown"
                update(need_id, "maintenance", node_id, building.building_type,
                       float(100.0 - building.condition),
                       float(tuning.building_repair_need_condition_threshold), False)
            continue
        pressured = building.condition < tuning.building_repair_need_condition_threshold
        if not pressured and need_id not in world.state.human.building_needs:
            continue
        parcel = world.state.human.land_parcels.get(building.parcel_id)
        node_id = parcel.spatial_node_id if parcel is not None else "unknown"
        update(
            need_id, "maintenance", node_id, building.building_type,
            float(100.0 - building.condition),
            float(tuning.building_repair_need_condition_threshold),
            pressured,
        )



def settle_building_maintenance(world, tuning) -> None:
    """Apply small, event-sourced daily wear; repairs restore condition through projects."""
    weather = EnvironmentQuery.weather_name(world)
    wet = "rain" in str(weather).lower() or "雨" in str(weather)
    weather_factor = tuning.building_weather_wear_multiplier if wet else 1.0
    for building in world.state.human.buildings.values():
        if building.status not in {"active", "occupied", "vacant"} or building.condition <= 0:
            continue
        exposure = max(0.0, float(building.attributes.get("weather_exposure", 1.0)))
        before = building.condition
        after = max(0.0, round(before - tuning.building_condition_decay_per_day * weather_factor * exposure, 2))
        if after == before:
            continue
        building.condition = after
        if after <= 0:
            building.status = "ruined"
        world.event_log.append(world.current_tick, "building_condition_changed", {
            "building_id": building.building_id,
            "condition_before": before, "condition_after": after,
            "status_after": building.status,
            "weather_factor": weather_factor, "exposure": exposure,
        })


def settle_storage_capacity(world, tuning) -> None:
    """Deprecated compatibility shim: household inventories currently have no capacity cap."""
    return None
