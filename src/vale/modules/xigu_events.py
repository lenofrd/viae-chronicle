"""Emergent seasonal hazards and village social events for Xigu."""
from __future__ import annotations

import random

from vale.contracts.impacts import EcologicalImpact


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
            EcologicalImpact.flood_damage(
                world, node.id, damage,
                precipitation_mm=climate.precipitation_mm,
            )

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
            EcologicalImpact.drought_damage(
                world, node.id, damage,
                drought_state=climate.drought_state.value,
            )

    def _apply_landslide(self, world, climate) -> None:
        if climate.precipitation_mm < 18 or climate.year in self._landslide_years:
            return
        pool = world.state.environment.ecological_resources.get("low_mountain")
        if not pool or pool.restricted:
            return
        maximum = max(1.0, float(pool.max_stock))
        if float(pool.current_stock) / maximum > .2:
            return
        candidates = [n for n in world.config.spatial.nodes
                      if n.type.value == "field" and n.attributes.get("field_kind") == "dry"]
        if not candidates:
            return
        target = max(candidates, key=lambda n: (float(n.attributes.get("x", 0)), n.id))
        EcologicalImpact.landslide(
            world, target.id, amount=.08, source_node="low_mountain",
            resource_stock_ratio=float(pool.current_stock) / maximum,
        )
        self._landslide_years.add(climate.year)

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
        EcologicalImpact.wildlife_attack(
            world, source.get("agent_id"), 8.0, location=source.get("target_node"),
        )

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
