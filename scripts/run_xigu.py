"""Run a deterministic, generated 溪谷镇 simulation.

Usage: python scripts/run_xigu.py 360
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from collections import Counter

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from vale.core.config_loader import LoadedConfig, load_config
from vale.core.event_log import EventLog
from vale.core.scheduler import run_tick
from vale.core.world import World
from vale.modules.agents import AgentModule
from vale.modules.climate import ClimateModule
from vale.modules.ecology import EcologyModule
from vale.modules.xigu_events import XiguEventsModule
from vale.modules.tenancy_economy import TenancyEconomyModule
from vale.worldgen.xigu import XiguGenerationConfig, build_xigu_agents_config, generate_xigu_town


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("days", type=int, nargs="?", default=360)
    parser.add_argument("--seed", type=int, default=20261118)
    args = parser.parse_args()
    base = load_config("brookvale-town-001")
    generated = generate_xigu_town(XiguGenerationConfig(seed=args.seed), base_spatial=base.spatial)
    config = LoadedConfig(
        world=base.world,
        natural_params=base.natural_params,
        spatial=generated.spatial,
        agents=build_xigu_agents_config(generated, base.agents.tuning, base.agents),
        terrain=generated.terrain,
    )
    db_dir = os.path.join(ROOT, "data", "worlds", config.world.world_id)
    os.makedirs(db_dir, exist_ok=True)
    db_path = os.path.join(db_dir, "events.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    log = EventLog(db_path)
    world = World(config.world.world_id, log, config.world.start_tick, config)
    world.register(ClimateModule())
    world.register(EcologyModule())
    world.register(AgentModule())
    world.register(TenancyEconomyModule())
    world.register(XiguEventsModule(seed=args.seed))
    initial_population = len(config.agents.agents)
    for _ in range(args.days):
        run_tick(world)
    events = log.all()
    births = [e for e in events if e["event_type"] == "agent_born"]
    deaths = [e for e in events if e["event_type"] == "agent_died"]
    first_death = min(deaths, key=lambda e: e["tick"]) if deaths else None
    early_actions = Counter(
        e["payload"].get("action", "unknown") for e in events
        if e["event_type"] == "agent_action_taken" and int(e.get("tick", -1)) <= 30
    )
    initial_grain = round(sum(
        float((e["payload"].get("assets") or {}).get("grain", 0.0))
        for e in events if e["event_type"] == "household_registered"
    ), 2)
    born_ids = {e["payload"].get("agent_id") for e in births}
    descendant_workers = {
        e["payload"].get("agent_id") for e in events
        if e["event_type"] == "agent_action_taken"
        and e["payload"].get("agent_id") in born_ids
        and e["payload"].get("action") in {"farm", "harvest", "fish", "hunt", "weave"}
    }
    report = {
        "days": args.days,
        "initial_population": initial_population,
        "final_population": sum(1 for a in world.state.human.agents.values() if a.alive),
        "births": len(births),
        "deaths": len(deaths),
        "deaths_by_cause": dict(Counter(e["payload"].get("cause", "unknown") for e in deaths)),
        "first_death_tick": first_death["tick"] if first_death else None,
        "first_death": first_death["payload"] if first_death else None,
        "initial_grain_from_registration": initial_grain,
        "actions_first_30_days": dict(early_actions),
        "descendants_at_work": len(descendant_workers),
        "agent_errors": sum(1 for e in events if e["event_type"] == "agent_error"),
        "food_stock": {
            field: round(sum(float(getattr(h, field)) for h in world.state.human.households.values()), 2)
            for field in ("grain", "vegetable", "meat", "fish")
        },
    }
    print("溪谷镇长期模拟诊断：")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"事件库：{db_path}")
    log.close()


if __name__ == "__main__":
    main()
