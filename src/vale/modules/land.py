"""Land tenure projection and deterministic operations for Brookvale.

Spatial nodes remain the existing location graph. This module adds parcel and
building records on top of those nodes; it does not create a second map.
"""
from __future__ import annotations

from vale.core.state import BuildingState, LandParcelState, LandRightState, TerrainCellState


def _node_type(node) -> str:
    return str(getattr(node.type, "value", node.type))


def _land_use(node) -> str:
    attrs = node.attributes or {}
    kind = _node_type(node)
    if attrs.get("abstract_zone"):
        return "reserved"
    if attrs.get("restricted") or attrs.get("protected"):
        return "protected"
    if kind == "field":
        return {
            "irrigated": "farmland_irrigated",
            "dry": "farmland_dry",
        }.get(attrs.get("field_kind"), "farmland")
    if node.id == "well":
        return "public"
    if node.id == "herbalist":
        return "commercial"
    if node.id == "elder_house":
        return "public"
    if kind == "water":
        return "waterway" if attrs.get("water_body") in {"river", "canal"} else "riverbank"
    if kind == "mountain":
        return "woodland"
    if kind == "resource":
        return "riverbank" if attrs.get("livelihood_zone") == "river" else "woodland"
    if kind == "residential" and attrs.get("residence"):
        return "residential"
    if kind == "social":
        return "commercial" if node.id == "market" else "public"
    return "reserved"


def initialize_land(world) -> None:
    """Create the initial terrain/parcel/building projection once.

    Occupied homesteads belong to their household. Vacant residential slots are
    explicitly collective/reserved rather than silently treated as ownerless.
    Field nodes are collective by default; the established south-field
    holding is seeded as Li Quan household property and work assignments become rights.
    """
    if world.state.human.land_parcels:
        return

    for cell in getattr(world.config, "terrain", []) or []:
        cell_id = f"terrain:{cell.x}:{cell.y}"
        world.state.environment.terrain_cells[cell_id] = TerrainCellState(
            cell_id=cell_id,
            x=cell.x,
            y=cell.y,
            terrain=cell.terrain,
            elevation=cell.elevation,
            slope=cell.slope,
            flood_risk=cell.flood_risk,
            soil_fertility=cell.soil_fertility,
        )

    household_by_home = {
        household.home_node: household
        for household in world.state.human.households.values()
    }

    for node in sorted(world.config.spatial.nodes, key=lambda item: item.id):
        attrs = dict(node.attributes or {})
        use = _land_use(node)
        household = household_by_home.get(node.id) if attrs.get("residence") else None
        if use == "protected":
            owner_type, owner_id = "protected", "village"
        elif household is not None:
            owner_type, owner_id = "household", household.household_id
        elif attrs.get("initial_owner_agent_id") in world.state.human.agents:
            owner_agent = world.state.human.agents[attrs["initial_owner_agent_id"]]
            owner_type, owner_id = "household", owner_agent.household_id
        else:
            owner_type, owner_id = "collective", "village"

        area = float(getattr(node, "area", 1.0) or 1.0)
        buildable_area = (
            float(attrs.get("buildable_area") or area)
            if use == "residential" and attrs.get("residence") and not attrs.get("restricted")
            else float(attrs.get("buildable_area", area if use == "residential" and not attrs.get("restricted") else 0.0))
        )
        access_rights = []
        if use in {"waterway", "riverbank", "public", "commercial"}:
            access_rights.append("public_access")
        if use == "waterway":
            access_rights.append("public_passage")

        parcel = LandParcelState(
            parcel_id=f"parcel:{node.id}",
            spatial_node_id=node.id,
            land_use=use,
            area=area,
            owner_type=owner_type,
            owner_id=owner_id,
            management_authority="village_council" if owner_type != "household" else None,
            buildable_area=buildable_area,
            access_rights=access_rights,
            created_tick=world.current_tick,
            attributes={
                **attrs,
                "vacant_home": bool(attrs.get("residence") and household is None),
            },
        )
        world.state.human.land_parcels[parcel.parcel_id] = parcel
        world.event_log.append(world.current_tick, "land_parcel_created", {
            "parcel": parcel.model_dump(mode="json"),
        })

        if attrs.get("residence"):
            building = BuildingState(
                building_id=f"building:{node.id}",
                parcel_id=parcel.parcel_id,
                building_type="dwelling",
                owner_type=owner_type,
                owner_id=owner_id,
                footprint_area=min(area, float(attrs.get("building_footprint_area", area))),
                condition=100.0,
                status="occupied" if household is not None else "vacant",
                created_tick=world.current_tick,
                attributes={"spatial_node_id": node.id},
            )
            world.state.human.buildings[building.building_id] = building
            world.event_log.append(world.current_tick, "building_created", {
                "building": building.model_dump(mode="json"),
            })

    # The market's collective storehouse also provides the village granary and cistern.
    # It is deliberately not household-owned, so no family receives a private storage bonus.
    market_parcel = world.state.human.land_parcels.get("parcel:market")
    if market_parcel is not None and "building:community_storehouse" not in world.state.human.buildings:
        environment_tuning = world.config.agents.tuning.environment
        food_reserve_capacity = environment_tuning.community_food_reserve_capacity
        water_reserve_capacity = environment_tuning.community_water_reserve_capacity
        storehouse = BuildingState(
            building_id="building:community_storehouse",
            parcel_id=market_parcel.parcel_id,
            building_type="storehouse",
            owner_type="collective",
            owner_id="village",
            footprint_area=min(market_parcel.area, 1.0),
            condition=100.0,
            status="active",
            created_tick=world.current_tick,
            attributes={
                "storage_capacity": food_reserve_capacity + water_reserve_capacity,
                "community_reserve": True,
                "food_reserve_capacity": food_reserve_capacity,
                "water_reserve_capacity": water_reserve_capacity,
            },
        )
        world.state.human.buildings[storehouse.building_id] = storehouse
        world.event_log.append(world.current_tick, "building_created", {
            "building": storehouse.model_dump(mode="json"),
        })

    # The existing deterministic household work allocation is the source of
    # initial cultivation rights; it is not replaced by a second allocation.
    for household in sorted(world.state.human.households.values(), key=lambda item: item.household_id):
        for node_id in household.work_nodes or [household.work_node]:
            parcel = world.state.human.land_parcels.get(f"parcel:{node_id}")
            if parcel is None or not parcel.land_use.startswith("farmland"):
                continue
            right = LandRightState(
                right_id=f"right:{parcel.parcel_id}:{household.household_id}:cultivate",
                holder_type="household",
                holder_id=household.household_id,
                right_type="cultivate",
                purpose="household_work_assignment",
                granted_tick=world.current_tick,
            )
            if any(existing.right_id == right.right_id for existing in parcel.use_rights):
                continue
            parcel.use_rights.append(right)
            world.event_log.append(world.current_tick, "land_right_granted", {
                "parcel_id": parcel.parcel_id,
                "right": right.model_dump(mode="json"),
            })


def grant_land_right(
    world, parcel_id: str, *, holder_type: str, holder_id: str,
    right_type: str, purpose: str | None = None,
) -> LandRightState:
    """Grant a recorded right after validating the parcel and holder."""
    parcel = world.state.human.land_parcels.get(parcel_id)
    if parcel is None:
        raise KeyError(f"unknown land parcel: {parcel_id}")
    if parcel.contested:
        raise ValueError("cannot grant rights on a contested parcel")
    if parcel.owner_type == "protected" or parcel.land_use == "protected":
        raise ValueError("protected land cannot receive ordinary private-use rights")
    if holder_type == "household" and holder_id not in world.state.human.households:
        raise ValueError(f"unknown household: {holder_id}")
    if holder_type not in {"household", "collective", "public"}:
        raise ValueError(f"unsupported right holder type: {holder_type}")
    if right_type == "cultivate" and not parcel.land_use.startswith("farmland"):
        raise ValueError("cultivation rights require a farmland parcel")

    right_id = f"right:{parcel_id}:{holder_type}:{holder_id}:{right_type}"
    if any(item.right_id == right_id for item in parcel.use_rights):
        return next(item for item in parcel.use_rights if item.right_id == right_id)
    right = LandRightState(
        right_id=right_id, holder_type=holder_type, holder_id=holder_id,
        right_type=right_type, purpose=purpose, granted_tick=world.current_tick,
    )
    world.event_log.append(world.current_tick, "land_right_granted", {
        "parcel_id": parcel_id, "right": right.model_dump(mode="json"),
    })
    parcel.use_rights.append(right)
    return right


def transfer_land_ownership(
    world, parcel_id: str, *, new_owner_household_id: str, actor_id: str,
) -> LandParcelState:
    """Transfer household-owned land; collective/protected land is not saleable."""
    parcel = world.state.human.land_parcels.get(parcel_id)
    if parcel is None:
        raise KeyError(f"unknown land parcel: {parcel_id}")
    if parcel.contested:
        raise ValueError("cannot transfer a contested parcel")
    if parcel.owner_type != "household" or not parcel.owner_id:
        raise ValueError("only household-owned parcels may be transferred")
    if new_owner_household_id not in world.state.human.households:
        raise ValueError(f"unknown household: {new_owner_household_id}")
    if new_owner_household_id == parcel.owner_id:
        return parcel
    before = parcel.owner_id
    world.event_log.append(world.current_tick, "land_ownership_transferred", {
        "parcel_id": parcel_id,
        "previous_owner_household_id": before,
        "new_owner_household_id": new_owner_household_id,
        "actor_id": actor_id,
    })
    parcel.owner_id = new_owner_household_id
    for building in world.state.human.buildings.values():
        if building.parcel_id == parcel_id and building.owner_id == before:
            building.owner_type = "household"
            building.owner_id = new_owner_household_id
    return parcel


def change_land_use(
    world, parcel_id: str, *, new_land_use: str, approved_by: str,
    decision_id: str,
) -> LandParcelState:
    """Apply a council-approved use change; ordinary code cannot bypass approval."""
    parcel = world.state.human.land_parcels.get(parcel_id)
    if parcel is None:
        raise KeyError(f"unknown land parcel: {parcel_id}")
    if parcel.contested:
        raise ValueError("cannot change the use of a contested parcel")
    if parcel.owner_type == "protected" or parcel.land_use == "protected":
        raise ValueError("protected land use cannot be changed by village approval")
    if approved_by != "household_council" or not decision_id.strip():
        raise ValueError("land-use changes require a household council decision")
    decision = world.state.human.council_decisions.get(decision_id)
    expected_subject = f"land_use_change:{parcel_id}:{new_land_use}"
    if decision is None or decision.status != "approved" or decision.subject != expected_subject or not decision.major:
        raise ValueError("land-use change requires its matching approved major council decision")
    allowed_uses = {
        "residential", "farmland_irrigated", "farmland_dry", "woodland",
        "riverbank", "road", "public", "commercial", "reserved", "vacant",
    }
    if new_land_use not in allowed_uses:
        raise ValueError(f"unsupported land use: {new_land_use}")
    if new_land_use == parcel.land_use:
        return parcel
    before = parcel.land_use
    buildable_after = parcel.area if new_land_use in {"residential", "commercial"} else 0.0
    world.event_log.append(world.current_tick, "land_use_changed", {
        "parcel_id": parcel_id,
        "before": before,
        "after": new_land_use,
        "buildable_area_after": buildable_after,
        "approved_by": approved_by,
        "decision_id": decision_id,
    })
    parcel.land_use = new_land_use
    parcel.buildable_area = buildable_after
    if not new_land_use.startswith("farmland"):
        for right in list(parcel.use_rights):
            if right.right_type == "cultivate":
                world.event_log.append(world.current_tick, "land_right_revoked", {
                    "parcel_id": parcel_id, "right_id": right.right_id,
                    "reason": "parcel_use_changed", "decision_id": decision_id,
                })
                parcel.use_rights.remove(right)
    return parcel



def relocate_household(world, *, household_id: str, new_parcel_id: str,
                      decision_id: str) -> LandParcelState:
    """Move a household into an existing vacant dwelling before proposing new construction."""
    household = world.state.human.households.get(household_id)
    new_parcel = world.state.human.land_parcels.get(new_parcel_id)
    if household is None or new_parcel is None:
        raise ValueError("household and destination parcel must exist")
    if new_parcel.contested or new_parcel.land_use != "residential":
        raise ValueError("destination must be an uncontested residential parcel")
    if new_parcel.owner_type == "protected" or new_parcel.attributes.get("restricted"):
        raise ValueError("protected or restricted land cannot be occupied")
    if new_parcel.owner_type not in {"collective", "household"}:
        raise ValueError("destination ownership does not permit household relocation")
    destination = next((
        building for building in world.state.human.buildings.values()
        if building.parcel_id == new_parcel_id
        and building.building_type == "dwelling"
        and building.status == "vacant"
        and building.condition > 0
        and (building.owner_type == "collective" or building.owner_id == household_id)
    ), None)
    if destination is None:
        raise ValueError("destination parcel has no usable vacant dwelling")
    old_parcel = next((
        parcel for parcel in world.state.human.land_parcels.values()
        if parcel.spatial_node_id == household.home_node
    ), None)
    if old_parcel is None or old_parcel.owner_type != "household" or old_parcel.owner_id != household_id:
        raise ValueError("current household home parcel is not household-owned")
    old_building = next((
        building for building in world.state.human.buildings.values()
        if building.parcel_id == old_parcel.parcel_id
        and building.building_type == "dwelling"
        and building.status in {"occupied", "active"}
    ), None)
    if old_building is None:
        raise ValueError("current household dwelling is missing")
    decision = world.state.human.council_decisions.get(decision_id)
    if (decision is None or decision.status != "approved"
            or decision.subject != f"relocate:{household_id}:{new_parcel_id}"
            or household_id not in decision.affected_household_ids):
        raise ValueError("relocation requires its matching approved council decision")

    old_node = household.home_node
    old_parcel.owner_type, old_parcel.owner_id = "collective", "village"
    old_parcel.management_authority = "village_council"
    old_building.owner_type, old_building.owner_id = "collective", "village"
    old_building.status = "vacant"
    new_parcel.owner_type, new_parcel.owner_id = "household", household_id
    new_parcel.management_authority = None
    destination.owner_type, destination.owner_id = "household", household_id
    destination.status = "occupied"
    household.home_node = new_parcel.spatial_node_id
    for member_id in household.member_ids:
        agent = world.state.human.agents.get(member_id)
        if agent is None:
            continue
        # Residence belongs to HouseholdState; AgentState has no home_node field.
        if agent.location == old_node:
            agent.location = new_parcel.spatial_node_id
    world.event_log.append(world.current_tick, "household_relocated", {
        "household_id": household_id,
        "old_home_node": old_node,
        "new_home_node": new_parcel.spatial_node_id,
        "old_parcel_id": old_parcel.parcel_id,
        "new_parcel_id": new_parcel.parcel_id,
        "old_building_id": old_building.building_id,
        "new_building_id": destination.building_id,
        "member_ids": list(household.member_ids),
    })
    return new_parcel



def settle_household_land_inheritance(
    world, *, deceased_household_id: str, heir_household_id: str | None,
    deceased_agent_id: str,
) -> list[str]:
    """Transfer a dissolved household's private parcels and buildings to its heir.

    This is called only after the household's final living member dies. Land is
    indivisible: unlike portable inventory, a private parcel is inherited whole.
    With no eligible heir, private land returns to village collective ownership.
    Household-held use rights on collective land follow the heir, or are revoked.
    """
    if deceased_household_id not in world.state.human.households:
        raise KeyError(f"unknown deceased household: {deceased_household_id}")
    if heir_household_id is not None and heir_household_id not in world.state.human.households:
        raise KeyError(f"unknown heir household: {heir_household_id}")
    if heir_household_id == deceased_household_id:
        return []

    changed_parcels: list[str] = []
    for parcel in sorted(world.state.human.land_parcels.values(), key=lambda item: item.parcel_id):
        if parcel.owner_type == "household" and parcel.owner_id == deceased_household_id:
            building_ids = sorted(
                building.building_id for building in world.state.human.buildings.values()
                if building.parcel_id == parcel.parcel_id
                and building.owner_type == "household"
                and building.owner_id == deceased_household_id
            )
            if heir_household_id is not None:
                world.event_log.append(world.current_tick, "land_ownership_inherited", {
                    "parcel_id": parcel.parcel_id,
                    "previous_owner_household_id": deceased_household_id,
                    "new_owner_household_id": heir_household_id,
                    "deceased_agent_id": deceased_agent_id,
                    "building_ids": building_ids,
                })
                parcel.owner_type, parcel.owner_id = "household", heir_household_id
                parcel.management_authority = None
                for building_id in building_ids:
                    building = world.state.human.buildings[building_id]
                    building.owner_type, building.owner_id = "household", heir_household_id
            else:
                world.event_log.append(world.current_tick, "land_ownership_escheated", {
                    "parcel_id": parcel.parcel_id,
                    "previous_owner_household_id": deceased_household_id,
                    "new_owner_type": "collective",
                    "new_owner_id": "village",
                    "deceased_agent_id": deceased_agent_id,
                    "building_ids": building_ids,
                })
                parcel.owner_type, parcel.owner_id = "collective", "village"
                parcel.management_authority = "village_council"
                for building_id in building_ids:
                    building = world.state.human.buildings[building_id]
                    building.owner_type, building.owner_id = "collective", "village"
            changed_parcels.append(parcel.parcel_id)

        for right in list(parcel.use_rights):
            if right.holder_type != "household" or right.holder_id != deceased_household_id:
                continue
            if right.expires_tick is not None and right.expires_tick <= world.current_tick:
                world.event_log.append(world.current_tick, "land_right_revoked", {
                    "parcel_id": parcel.parcel_id,
                    "right_id": right.right_id,
                    "reason": "expired_during_inheritance",
                })
                parcel.use_rights.remove(right)
            elif heir_household_id is not None:
                world.event_log.append(world.current_tick, "land_right_inherited", {
                    "parcel_id": parcel.parcel_id,
                    "right_id": right.right_id,
                    "previous_holder_household_id": deceased_household_id,
                    "new_holder_household_id": heir_household_id,
                    "deceased_agent_id": deceased_agent_id,
                })
                right.holder_id = heir_household_id
                right.purpose = "inherited"
            else:
                world.event_log.append(world.current_tick, "land_right_revoked", {
                    "parcel_id": parcel.parcel_id,
                    "right_id": right.right_id,
                    "reason": "no_eligible_heir",
                })
                parcel.use_rights.remove(right)


    # Active lease contracts are household obligations/assets too. Preserve the
    # agreement when a party's household dissolves; do not silently erase rent.
    for lease_id, lease in sorted(world.state.human.land_leases.items()):
        if lease.get("status") not in {"active", "arrears"}:
            continue
        after = dict(lease)
        changed = False
        if lease.get("lessor_household_id") == deceased_household_id:
            after["lessor_household_id"] = heir_household_id or "village"
            changed = True
        if lease.get("lessee_household_id") == deceased_household_id:
            if heir_household_id is None:
                after.update(status="terminated", ended_tick=world.current_tick,
                             end_reason="lessee_household_dissolved_without_heir")
                parcel = world.state.human.land_parcels.get(lease.get("parcel_id"))
                if parcel is not None:
                    parcel.use_rights = [r for r in parcel.use_rights if r.right_id != f"lease:{lease_id}"]
            else:
                after["lessee_household_id"] = heir_household_id
            changed = True
        if changed:
            world.event_log.append(world.current_tick, "land_lease_inherited", {
                "lease_id": lease_id, "lease_after": after,
                "deceased_household_id": deceased_household_id,
                "heir_household_id": heir_household_id,
            })
            lease.update(after)

    return changed_parcels

def relinquish_household_parcel(world, parcel_id: str, *, household_id: str,
                                reason: str = "unable_to_maintain") -> None:
    """Voluntarily return private non-homestead land to the village collective."""
    parcel = world.state.human.land_parcels.get(parcel_id)
    household = world.state.human.households.get(household_id)
    if parcel is None or household is None or parcel.owner_type != "household" or parcel.owner_id != household_id:
        raise ValueError("household must own the parcel being relinquished")
    if parcel.land_use == "residential" and household.home_node == parcel.spatial_node_id:
        raise ValueError("relocate before relinquishing the current homestead")
    if any(x.get("parcel_id") == parcel_id and x.get("status") in {"active", "arrears"}
           for x in world.state.human.land_leases.values()):
        raise ValueError("settle or terminate active leases before relinquishing")
    building_ids = sorted(b.building_id for b in world.state.human.buildings.values()
                          if b.parcel_id == parcel_id and b.owner_type == "household" and b.owner_id == household_id)
    world.event_log.append(world.current_tick, "land_ownership_relinquished", {
        "parcel_id": parcel_id, "previous_owner_household_id": household_id,
        "new_owner_type": "collective", "new_owner_id": "village",
        "building_ids": building_ids, "reason": reason,
    })
    parcel.owner_type, parcel.owner_id = "collective", "village"
    parcel.management_authority = "village_council"
    for building_id in building_ids:
        building = world.state.human.buildings[building_id]
        building.owner_type, building.owner_id = "collective", "village"
    for right in list(parcel.use_rights):
        if right.holder_type == "household" and right.holder_id == household_id:
            world.event_log.append(world.current_tick, "land_right_revoked", {
                "parcel_id": parcel_id, "right_id": right.right_id, "reason": "parcel_relinquished",
            })
            parcel.use_rights.remove(right)

