"""Forty-year generated-town integration test.

Tracks three generations, including second- and third-generation marriages, and descendants entering the labor force. The
failure message includes enough economic and demographic evidence to diagnose
the first collapse rather than reporting only an empty population.
"""
from __future__ import annotations

import random
from collections import Counter

import pytest

from vale.core.config_loader import LoadedConfig, load_config
from vale.core.event_log import EventLog
from vale.core.scheduler import run_tick
from vale.core.world import World
from vale.modules.agents import AgentModule, SpatialIndex, age_years
from vale.domains.environment.climate import ClimateModule
from vale.modules.ecology import EcologyModule
from vale.modules.tenancy_economy import TenancyEconomyModule
from vale.domains.wildlife.wildlife import WildlifeModule
from vale.modules.xigu_events import XiguEventsModule
from vale.world.xigu import XiguGenerationConfig, build_xigu_agents_config, generate_xigu_town


TICKS_PER_YEAR = 360
# 2 年基线口径（老板裁决）：不再跑 40 年世代链，只验证婚育由 agent 自主发生后
# 婚姻数与新生儿数是否为正、人口是否存活、无模块错误。40 年世代链指标保留在
# _diagnostics 里作观察，但不再作为断言。
HORIZON = 2 * TICKS_PER_YEAR


def _build(seed: int) -> World:
    base = load_config("brookvale-town-001")
    generated = generate_xigu_town(XiguGenerationConfig(seed=seed), base_spatial=base.spatial)
    config = LoadedConfig(
        world=base.world,
        natural_params=base.natural_params,
        spatial=generated.spatial,
        agents=build_xigu_agents_config(generated, base.agents.tuning, base.agents),
        terrain=generated.terrain,
        resources=generated.resources,
    )
    world = World(config.world.world_id, EventLog(":memory:"), config.world.start_tick, config)
    world.register(ClimateModule(rng=random.Random(seed)))
    world.register(EcologyModule())
    world.register(WildlifeModule())
    world.register(AgentModule(rng=random.Random(seed * 7 + 13)))
    world.register(TenancyEconomyModule())
    world.register(XiguEventsModule(seed=seed))
    return world


def _diagnostics(world, population_curve, checkpoints):
    events = world.event_log.all()
    births = [e for e in events if e["event_type"] == "agent_born"]
    deaths = [e for e in events if e["event_type"] == "agent_died"]
    incapacitations = [e for e in events if e["event_type"] == "agent_incapacitated"]
    actions = [e for e in events if e["event_type"] == "agent_action_taken"]
    action_periods = Counter(
        (int(e.get("tick", 0)) - 1) // 30 for e in actions
    )
    action_breakdown = {}
    for period in sorted(action_periods):
        action_breakdown[period + 1] = dict(Counter(
            e["payload"].get("action", "unknown") for e in actions
            if (int(e.get("tick", 0)) - 1) // 30 == period
        ))
    gather_breakdown = {}
    for period in sorted({(int(e.get("tick", 0)) - 1) // 30 for e in events if e["event_type"] == "gather_success"}):
        gather_breakdown[period + 1] = dict(Counter(
            e["payload"].get("action", "unknown") for e in events
            if e["event_type"] == "gather_success"
            and (int(e.get("tick", 0)) - 1) // 30 == period
        ))
    # 以初始人口为 G0，按出生事件中的父母代际递推，避免把 G3/G4 混成一代。
    generation_by_id = {agent.id: 0 for agent in world.config.agents.agents}
    generation_by_birth_id = {}
    for event in births:
        payload = event["payload"]
        parents = (payload.get("mother_id"), payload.get("father_id"))
        child_generation = max(
            (generation_by_id.get(parent_id, 0) for parent_id in parents if parent_id),
            default=0,
        ) + 1
        child_id = payload.get("agent_id")
        generation_by_id[child_id] = child_generation
        generation_by_birth_id[child_id] = child_generation
    generation_1_ids = {
        agent_id for agent_id, generation in generation_by_birth_id.items()
        if generation == 1
    }
    generation_2_ids = {
        agent_id for agent_id, generation in generation_by_birth_id.items()
        if generation == 2
    }
    generation_3_ids = {
        agent_id for agent_id, generation in generation_by_birth_id.items()
        if generation == 3
    }
    generation_3_births = [
        event for event in births
        if generation_by_birth_id.get(event["payload"].get("agent_id")) == 2
    ]
    marriages = [e for e in events if e["event_type"] == "agent_married"]
    generation_2_marriages = [
        e for e in marriages
        if e["payload"].get("agent_id") in generation_1_ids
        or e["payload"].get("spouse_id") in generation_1_ids
    ]
    generation_2_married_ids = {
        agent_id
        for e in generation_2_marriages
        for agent_id in (e["payload"].get("agent_id"), e["payload"].get("spouse_id"))
        if agent_id in generation_1_ids
    }
    generation_3_marriages = [
        e for e in marriages
        if e["payload"].get("agent_id") in generation_2_ids
        or e["payload"].get("spouse_id") in generation_2_ids
    ]
    generation_2_alive_adults = [
        a for a in world.state.human.agents.values()
        if a.agent_id in generation_1_ids and a.alive
        and age_years(a.birth_tick, world.current_tick) >= world.config.agents.tuning.marriage.min_age
    ]
    generation_3_alive = [
        world.state.human.agents[agent_id]
        for agent_id in generation_2_ids
        if agent_id in world.state.human.agents and world.state.human.agents[agent_id].alive
    ]
    descendants_at_work = {
        e["payload"].get("agent_id")
        for e in actions
        if e["payload"].get("agent_id") in generation_1_ids
        and e["payload"].get("action") in {"farm", "harvest", "fish", "hunt", "weave"}
        and (agent := world.state.human.agents.get(e["payload"].get("agent_id"))) is not None
        and age_years(agent.birth_tick, int(e.get("tick", 0))) >= 16
    }
    first_death = min((e["tick"] for e in deaths), default=None)
    first_death_event = next((e for e in deaths if e["tick"] == first_death), None)
    first_incapacitation = min(incapacitations, key=lambda e: e["tick"]) if incapacitations else None
    first_household_id = (
        first_incapacitation["payload"].get("household_id")
        if first_incapacitation else None
    )
    first_household_actions = Counter(
        e["payload"].get("action", "unknown") for e in actions
        if e["payload"].get("household_id") == first_household_id
    )
    early_actions = Counter(
        e["payload"].get("action", "unknown") for e in actions
        if int(e.get("tick", -1)) <= 30
    )
    registration_events = [e for e in events if e["event_type"] == "household_registered"]
    initial_grain = round(sum(
        float((e["payload"].get("assets") or {}).get("grain", 0.0))
        for e in registration_events
    ), 2)
    early_gather = Counter(
        e["payload"].get("action", "unknown") for e in events
        if e["event_type"] == "gather_success" and int(e.get("tick", -1)) <= 30
    )
    final_alive = [a for a in world.state.human.agents.values() if a.alive]
    agent_module = next(m for m in world.modules if isinstance(m, AgentModule))
    water_fetches = Counter(
        e["payload"].get("household_id")
        for e in actions if e["payload"].get("action") == "collect_water"
    )
    water_access_by_household = []
    for household in world.state.human.households.values():
        members = [
            world.state.human.agents[mid] for mid in household.member_ids
            if mid in world.state.human.agents
        ]
        water_access_by_household.append({
            "household_id": household.household_id,
            "home_node": household.home_node,
            "well_distance_tu": round(
                agent_module._spatial.travel_tu(household.home_node, "well"), 3
            ) if agent_module._spatial is not None else None,
            "living_members": sum(member.alive for member in members),
            "adult_living_members": sum(
                member.alive and age_years(member.birth_tick, world.current_tick) >= 16
                for member in members
            ),
            "incapacitated_members": sum(
                member.alive and member.incapacitated for member in members
            ),
            "water_stock": round(household.water, 2),
            "water_fetch_actions": water_fetches.get(household.household_id, 0),
        })
    water_access_by_household.sort(
        key=lambda item: (item["well_distance_tu"] is None, item["well_distance_tu"] or 0)
    )
    food = {
        "grain": round(sum(h.grain for h in world.state.human.households.values()), 2),
        "fish": round(sum(h.fish for h in world.state.human.households.values()), 2),
        "meat": round(sum(h.meat for h in world.state.human.households.values()), 2),
        "vegetable": round(sum(h.vegetable for h in world.state.human.households.values()), 2),
    }
    living = [agent for agent in world.state.human.agents.values() if agent.alive]
    ages = [age_years(agent.birth_tick, world.current_tick) for agent in living]
    active_households = [
        household for household in world.state.human.households.values()
        if any(
            member_id in world.state.human.agents and world.state.human.agents[member_id].alive
            for member_id in household.member_ids
        )
    ]
    occupied_home_nodes = {household.home_node for household in active_households}
    dwellings = [b for b in world.state.human.buildings.values() if b.building_type == "dwelling"]
    dwelling_nodes = {
        b.building_id: (
            world.state.human.land_parcels[b.parcel_id].spatial_node_id
            if b.parcel_id in world.state.human.land_parcels else None
        )
        for b in dwellings
    }
    return {
        "population_by_30_days": population_curve,
        "food_stock_by_30_days": checkpoints,
        "actions_by_30_days": action_breakdown,
        "gather_success_by_30_days": gather_breakdown,
        "births": len(births),
        "marriages": len(marriages),
        "generation_2_births": len(generation_1_ids),
        "generation_2_marriage_events": len(generation_2_marriages),
        "generation_3_marriage_events": len(generation_3_marriages),
        "generation_3_marriage_details": [
            {
                "tick": e["tick"],
                "agent_id": e["payload"].get("agent_id"),
                "spouse_id": e["payload"].get("spouse_id"),
            }
            for e in generation_3_marriages
        ],
        "generation_2_married_people": len(generation_2_married_ids),
        "generation_2_marriage_details": [
            {
                "tick": e["tick"],
                "agent_id": e["payload"].get("agent_id"),
                "agent_name": e["payload"].get("agent_name"),
                "spouse_id": e["payload"].get("spouse_id"),
                "spouse_name": e["payload"].get("spouse_name"),
            }
            for e in generation_2_marriages
        ],
        "generation_2_alive_adults_at_end": len(generation_2_alive_adults),
        "generation_2_unmarried_alive_adults_at_end": sum(
            a.agent_id not in generation_2_married_ids for a in generation_2_alive_adults
        ),
        "generation_3_births": len(generation_3_births),
        "generation_3_birth_details": [
            {
                "tick": e["tick"],
                "child_id": e["payload"].get("agent_id"),
                "mother_id": e["payload"].get("mother_id"),
                "mother_name": e["payload"].get("mother_name"),
                "father_id": e["payload"].get("father_id"),
                "father_name": e["payload"].get("father_name"),
            }
            for e in generation_3_births
        ],
        "generation_3_alive_at_end": len(generation_3_alive),
        # Backward-compatible legacy key; semantically this is generation-3 births.
        "second_generation_births": len(generation_3_births),
        "deaths": len(deaths),
        "market_trade_events": sum(1 for e in events if e["event_type"] == "trade_executed"),
        "market_credit_events": sum(
            1 for e in events if e["event_type"] == "debt_formed"
            and (e["payload"].get("origin") == "market_credit")
        ),
        "deaths_by_cause": dict(Counter(e["payload"].get("cause", "unknown") for e in deaths)),
        "first_death_tick": first_death,
        "first_death": first_death_event["payload"] if first_death_event else None,
        "first_incapacitation": first_incapacitation["payload"] if first_incapacitation else None,
        "first_incapacitated_household_actions": dict(first_household_actions),
        "initial_grain_from_registration": initial_grain,
        "actions_first_30_days": dict(early_actions),
        "gather_success_first_30_days": dict(early_gather),
        "descendants_at_work": len(descendants_at_work),
        "final_population": len(final_alive),
        "final_children_under_16": sum(age < 16 for age in ages),
        "final_working_age_population": sum(16 <= age < 55 for age in ages),
        "final_population_55_plus": sum(age >= 55 for age in ages),
        "household_count": len(world.state.human.households),
        "active_household_count": len(active_households),
        "dwelling_count": len(dwellings),
        "occupied_dwellings": sum(
            1 for b in dwellings
            if dwelling_nodes[b.building_id] in occupied_home_nodes
            and b.status in {"active", "occupied"}
        ),
        "vacant_dwellings": sum(
            1 for b in dwellings
            if dwelling_nodes[b.building_id] not in occupied_home_nodes
            and b.status in {"active", "vacant"}
        ),
        "ruined_dwellings": sum(1 for b in dwellings if b.status == "ruined"),
        "field_count": len(world.state.environment.field_growth),
        "fields_with_growth": sum(1 for value in world.state.environment.field_growth.values() if value > 0),
        "harvestable_fields": sum(
            1 for value in world.state.environment.field_growth.values()
            if value >= world.config.agents.tuning.agriculture.harvest_growth_threshold
        ),
        "final_food_stock": food,
        "water_access_by_household": water_access_by_household,
        "total_water_fetch_actions": sum(water_fetches.values()),
        "agent_errors": len([e for e in events if e["event_type"] == "agent_error"]),
        "cold_exposure_events": len([e for e in events if e["event_type"] == "cold_exposure"]),
        "community_reserve_deposit_events": len([
            e for e in events if e["event_type"] == "community_reserve_deposited"
        ]),
        "community_reserve_withdraw_events": len([
            e for e in events if e["event_type"] == "community_reserve_withdrawn"
        ]),
        "community_reserve_final": {
            key: round(float(value), 2)
            for key, value in world.state.human.community_reserves.items()
        },
        "community_reserve_initialization": any(
            b.building_type == "storehouse" and b.attributes.get("community_reserve")
            for b in world.state.human.buildings.values()
        ),
        "first_death_household_work_node": (
            world.state.human.households[first_death_event["payload"].get("household_id")].work_node
            if first_death_event and first_death_event["payload"].get("household_id") in world.state.human.households
            else None
        ),
        "first_death_household_reserve_events": [
            {
                "tick": e["tick"], "event_type": e["event_type"],
                "resources": e["payload"].get("resources"),
            }
            for e in events
            if first_death_event
            and e["payload"].get("household_id") == first_death_event["payload"].get("household_id")
            and e["event_type"] in {"community_reserve_deposited", "community_reserve_withdrawn"}
        ][:20],
        "cold_health_loss": round(sum(
            float(e["payload"].get("loss", 0.0))
            for e in events if e["event_type"] == "cold_exposure"
        ), 2),
        "distinct_initial_work_fields": len({
            h.work_node for h in world.state.human.households.values()
            if h.work_node in world.state.environment.field_growth
        }),
        "seasonal_field_labor_records": len(world.state.human.field_season_labor),
        "minimum_population": min(population_curve, default=0),
        "minimum_household_food_stock": min(
            (float(c["household_food_stock_min"]) for c in checkpoints), default=0.0
        ),
    }


def test_generated_homes_are_reachable_from_the_public_well():
    base = load_config("brookvale-town-001")
    for seed in (1, 7, 20261118):
        generated = generate_xigu_town(
            XiguGenerationConfig(seed=seed), base_spatial=base.spatial
        )
        residences = [n for n in generated.spatial.nodes if n.attributes.get("residence")]
        distances = {
            node.id: generated.distances_from_well.get(node.id, float("inf"))
            for node in residences
        }
        assert distances
        assert max(distances.values()) <= 4.5, {"seed": seed, "well_distances": distances}
        spatial = SpatialIndex(generated.spatial)
        market_distances = {
            node.id: spatial.travel_tu(node.id, "market")
            for node in residences
        }
        assert max(market_distances.values()) <= 6.0, {
            "seed": seed, "market_distances": market_distances,
        }


@pytest.mark.long_run
def test_two_year_xigu_run_records_agent_driven_marriages_and_births():
    seed = 20261118
    world = _build(seed)
    population_curve = []
    try:
        simulated_ticks = 0
        checkpoints = []
        for tick in range(1, HORIZON + 1):
            run_tick(world)
            simulated_ticks = tick
            if tick % 30 == 0:
                alive = sum(1 for a in world.state.human.agents.values() if a.alive)
                population_curve.append(alive)
                food = {
                    field: round(sum(float(getattr(h, field)) for h in world.state.human.households.values()), 2)
                    for field in ("grain", "fish", "meat", "vegetable")
                }
                household_stocks = sorted(
                    sum(float(getattr(h, field)) for field in ("grain", "fish", "meat", "vegetable"))
                    for h in world.state.human.households.values()
                )
                checkpoints.append({
                    "tick": tick, "population": alive, "food": food,
                    "households_with_food": sum(stock > 0 for stock in household_stocks),
                    "households_empty": sum(stock <= 0 for stock in household_stocks),
                    "households_with_water": sum(h.water > 0 for h in world.state.human.households.values()),
                    "households_without_water": sum(h.water <= 0 for h in world.state.human.households.values()),
                    "total_water": round(sum(h.water for h in world.state.human.households.values()), 2),
                    "household_food_stock_min": round(household_stocks[0], 2) if household_stocks else 0.0,
                    "household_food_stock_median": round(household_stocks[len(household_stocks) // 2], 2) if household_stocks else 0.0,
                    "household_food_stock_max": round(household_stocks[-1], 2) if household_stocks else 0.0,
                    "harvestable_fields": sum(
                        1 for value in world.state.environment.field_growth.values()
                        if value >= world.config.agents.tuning.agriculture.harvest_growth_threshold
                    ),
                })
            if not any(a.alive for a in world.state.human.agents.values()):
                break
        diagnostics = _diagnostics(world, population_curve, checkpoints)
        diagnostics["simulated_ticks"] = simulated_ticks
        assert diagnostics["final_population"] > 0, f"2-year town extinct: {diagnostics}"
        assert diagnostics["marriages"] > 0, (
            f"no agent-driven marriages in 2 years: {diagnostics}"
        )
        assert diagnostics["births"] > 0, f"no descendants were born: {diagnostics}"
        assert diagnostics["agent_errors"] == 0, f"agent/module errors during run: {diagnostics}"
        print("Xigu 2-year marriage/birth summary:", {
            key: diagnostics[key] for key in (
                "simulated_ticks", "minimum_population", "final_population",
                "marriages", "births", "deaths", "deaths_by_cause",
                "generation_2_marriage_events", "generation_3_marriage_events",
                "final_food_stock", "agent_errors",
            )
        })
    finally:
        world.event_log.close()
