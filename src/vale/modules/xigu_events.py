"""Emergent seasonal hazards and village social events for Xigu."""
from __future__ import annotations

import random


class XiguEventsModule:
    name = "xigu_events"
    depends_on = ["agents", "ecology"]

    def __init__(self, seed: int = 20261118) -> None:
        self.seed = seed
        self._rituals_seen: set[tuple[int, str]] = set()
        self._landslide_years: set[int] = set()

    def step(self, world) -> None:
        tick = world.current_tick
        climate = world.state.environment.climate
        if climate is None:
            return
        tuning = world.config.agents.tuning
        market = tuning.market
        market_day = tick % market.market_day_interval == market.market_day_offset
        if market_day:
            world.event_log.append(tick, "market_day_opened", {
                "market_node": market.market_node, "year": climate.year,
                "season": climate.season.value, "day": climate.day,
            })

        season = climate.season.value
        if season in {"spring", "autumn"} and climate.season_progress <= .02:
            key = (climate.year, season)
            if key not in self._rituals_seen:
                self._rituals_seen.add(key)
                world.event_log.append(tick, "seasonal_ritual", {
                    "location": "shrine", "season": season,
                    "year": climate.year, "participants": "available_households",
                })

        self._apply_flood_damage(world, climate)
        self._apply_drought_damage(world, climate)
        self._apply_landslide(world, climate)
        self._apply_wildlife_encounter(world, tick)
        if market_day:
            self._social_echoes(world, tick)

    def _apply_flood_damage(self, world, climate) -> None:
        if climate.season.value != "spring" or climate.precipitation_mm <= 0:
            return
        for node in world.config.spatial.nodes:
            attrs = node.attributes or {}
            if attrs.get("field_kind") != "irrigated":
                continue
            threshold = float(attrs.get("flood_damage_threshold_mm", 18.0))
            if climate.precipitation_mm < threshold:
                continue
            before = float(world.state.environment.field_growth.get(node.id, 0.0))
            ratio = float(attrs.get("flood_damage_ratio", .12))
            damage = min(before, before * ratio * max(.1, float(attrs.get("flood_risk", .5))))
            if damage <= 0:
                continue
            after = round(max(0.0, before - damage), 4)
            world.state.environment.field_growth[node.id] = after
            world.event_log.append(world.current_tick, "field_flood_damage", {
                "field_node": node.id, "before": round(before, 4),
                "damage": round(damage, 4), "after": after,
                "precipitation_mm": climate.precipitation_mm,
            })

    def _apply_drought_damage(self, world, climate) -> None:
        if climate.season.value != "summer" or climate.drought_state.value not in {"warning", "crisis"}:
            return
        for node in world.config.spatial.nodes:
            if node.type.value != "field":
                continue
            before = float(world.state.environment.field_growth.get(node.id, 0.0))
            damage = min(before, max(.1, before * .025))
            if damage <= 0:
                continue
            after = round(max(0.0, before - damage), 4)
            world.state.environment.field_growth[node.id] = after
            world.event_log.append(world.current_tick, "field_drought_damage", {
                "field_node": node.id, "before": round(before, 4),
                "damage": round(damage, 4), "after": after,
                "drought_state": climate.drought_state.value,
            })

    def _apply_landslide(self, world, climate) -> None:
        if climate.precipitation_mm < 18 or climate.year in self._landslide_years:
            return
        pool = world.state.environment.ecological_resources.get("low_mountain")
        if not pool or pool.get("restricted"):
            return
        maximum = max(1.0, float(pool.get("max_stock", 1.0)))
        if float(pool.get("current_stock", 0.0)) / maximum > .2:
            return
        candidates = [n for n in world.config.spatial.nodes
                      if n.type.value == "field" and n.attributes.get("field_kind") == "dry"]
        if not candidates:
            return
        target = max(candidates, key=lambda n: (float(n.attributes.get("x", 0)), n.id))
        before = float(world.state.environment.fertility_factor.get(target.id, 1.0))
        after = round(max(.1, before - .08), 4)
        world.state.environment.fertility_factor[target.id] = after
        self._landslide_years.add(climate.year)
        world.event_log.append(world.current_tick, "landslide_damage", {
            "source_node": "low_mountain", "field_node": target.id,
            "fertility_before": before, "fertility_after": after,
            "resource_stock_ratio": round(float(pool["current_stock"]) / maximum, 4),
        })

    def _apply_wildlife_encounter(self, world, tick: int) -> None:
        query_at_tick = getattr(world.event_log, "by_type_at_tick", None)
        if callable(query_at_tick):
            action_events = query_at_tick("agent_action_taken", tick)
        else:
            # Minimal sinks may expose only all(); keep the event adapter optional.
            all_events = getattr(world.event_log, "all", None)
            action_events = [
                event for event in (all_events() if callable(all_events) else [])
                if event.get("event_type") == "agent_action_taken"
                and int(event.get("tick", -1)) == tick
            ]
        todays = [e for e in action_events
                  if e.get("payload", {}).get("target_node") in {"low_mountain", "game_trail"}]
        if not todays:
            return
        rng = random.Random(self.seed + tick)
        if rng.random() >= .025:
            return
        source = rng.choice(todays)["payload"]
        agent = world.state.human.agents.get(source.get("agent_id"))
        if agent is None or not agent.alive:
            return
        before = agent.health
        agent.health = max(0.0, before - 8.0)
        agent.last_injury_tick = tick
        world.event_log.append(tick, "wildlife_attack", {
            "agent_id": agent.agent_id, "agent_name": agent.name,
            "health_before": round(before, 2), "health_after": round(agent.health, 2),
            "location": source.get("target_node"), "injury": 8.0,
        })

    def _social_echoes(self, world, tick: int) -> None:
        between = getattr(world.event_log, "between_ticks", None)
        if callable(between):
            recent = between(tick - 11, tick - 1)
        else:
            all_events = getattr(world.event_log, "all", None)
            recent = [
                event for event in (all_events() if callable(all_events) else [])
                if tick - 11 <= int(event.get("tick", -1)) <= tick - 1
            ]
        dispute = [e for e in recent if e.get("event_type") in {
            "debt_defaulted", "debt_deferred", "debt_dispute_resolved",
        }]
        if dispute:
            source = dispute[-1]
            world.event_log.append(tick, "clan_mediation_convened", {
                "source_event_id": source.get("id"),
                "source_event_type": source.get("event_type"),
                "location": "ancestral_hall",
            })
        rumor_sources = [e for e in recent if e.get("event_type") in {
            "gather_injury", "wildlife_attack", "field_flood_damage",
            "field_drought_damage", "landslide_damage", "debt_defaulted",
            "debt_deferred", "agent_born", "agent_died",
        }]
        if rumor_sources:
            source = random.Random(self.seed ^ tick).choice(rumor_sources)
            world.event_log.append(tick, "rumor_spread", {
                "source_event_id": source.get("id"),
                "source_event_type": source.get("event_type"),
                "market_node": "market",
                "reliability": "unverified",
            })
