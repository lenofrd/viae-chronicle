"""Event-sourced renewable-resource projection for spatial resource nodes."""
from __future__ import annotations

from vale.contracts.queries import EnvironmentQuery


class EcologyModule:
    name = "ecology"
    depends_on = ["climate"]

    def step(self, world) -> None:
        season = EnvironmentQuery.season(world).value
        for node in world.config.spatial.nodes:
            attrs = node.attributes or {}
            if "resource_stock" not in attrs:
                continue
            pool = world.state.environment.ecological_resources.get(node.id)
            if pool is None:
                pool = {
                    "resource_type": attrs.get("resource_type", "generic"),
                    "current_stock": float(attrs["resource_stock"]),
                    "max_stock": float(attrs.get("resource_max_stock", attrs["resource_stock"])),
                    "regeneration_per_tick": float(attrs.get("resource_regeneration_per_tick", 0.0)),
                    "extraction_limit_per_tick": float(attrs.get("resource_extraction_limit_per_tick", 0.0)),
                    "seasonal_weights": dict(attrs.get("resource_seasonal_weights", {})),
                    "restricted": bool(attrs.get("restricted", False)),
                    "degradation": 0.0,
                    "harvested_this_tick": 0.0,
                    "harvest_tick": world.current_tick,
                }
                world.state.environment.ecological_resources[node.id] = pool
                world.event_log.append(world.current_tick, "resource_pool_initialized", {
                    "resource_node": node.id, "pool": dict(pool),
                })
                continue
            if pool.get("restricted"):
                continue
            before = float(pool["current_stock"])
            weight = float(pool.get("seasonal_weights", {}).get(season, 1.0))
            amount = min(max(0.0, float(pool["max_stock"]) - before),
                         max(0.0, float(pool["regeneration_per_tick"]) * weight))
            if amount <= 0:
                continue
            pool["current_stock"] = round(before + amount, 6)
            world.event_log.append(world.current_tick, "resource_regenerated", {
                "resource_node": node.id, "season": season,
                "amount": round(amount, 6), "stock_before": round(before, 6),
                "stock_after": pool["current_stock"],
            })
