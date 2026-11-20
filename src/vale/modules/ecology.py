"""生态资源池的事件溯源投影与采集结算（环境域所有者）。

``EnvironmentState.ecological_resources`` 的唯一所有者是环境域：池的初始化与
再生由 ``EcologyModule.step`` 驱动，采集结算由本模块的 ``harvest_from_pool``
执行；人类模块经写入契约（``contracts.resources.ResourceService.harvest``）
提交请求，契约只路由、不写状态。P3b 期间结算曾放在 ``contracts/resources.py``，
P3c 按裁决移交所有者。
"""
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


# --------------------------------------------------------------------------- #
# 采集结算（P3b 机制；P3c 起由环境域所有者执行，契约 ResourceService 只路由）
# --------------------------------------------------------------------------- #

def _harvested_this_tick(pool: dict, tick: int) -> float:
    if pool.get("harvest_tick") != tick:
        return 0.0
    return float(pool.get("harvested_this_tick", 0.0))


def _append_refusal(world, pool: dict, node_id: str, requested: float,
                    used_this_tick: float, agent_id: str, household_id: str,
                    action: str) -> None:
    stock = float(pool.get("current_stock", 0.0))
    limit = float(pool.get("extraction_limit_per_tick", 0.0))
    world.event_log.append(world.current_tick, "resource_harvest_refused", {
        "resource_node": node_id,
        "agent_id": agent_id,
        "household_id": household_id,
        "action": action,
        "requested": round(requested, 6),
        "granted": 0.0,
        "stock": round(stock, 6),
        "used_this_tick": round(used_this_tick, 6),
        "reason": "stock_depleted" if stock <= 0 else "extraction_limit",
        "extraction_limit_per_tick": round(limit, 6),
    })


def harvest_from_pool(world, node_id: str, requested: float, *, agent_id: str = "",
                      household_id: str = "", action: str = "") -> float:
    """从节点资源池结算采集，返回实际给付量（0 表示被拒）。

    校验同 tick 累计额度（``extraction_limit_per_tick``）与存量，先写事件、
    再改投影；给付量为 0 时写拒绝事件（不改状态）。

    行为等价约定：未登记资源池的节点（如测试夹具里的 ``well``）沿用 P3b 前的
    "原额给付"，由 P4 统一资源模型时再收敛。
    """
    requested = max(0.0, float(requested))
    if requested <= 0:
        return 0.0
    pool = world.state.environment.ecological_resources.get(node_id)
    if pool is None:
        return requested  # 未登记资源池：保持 P3b 前行为

    used_this_tick = _harvested_this_tick(pool, world.current_tick)
    remaining_cap = max(
        0.0, float(pool.get("extraction_limit_per_tick", 0.0)) - used_this_tick
    )
    stock = float(pool.get("current_stock", 0.0))
    granted = min(requested, remaining_cap, max(0.0, stock))
    if granted <= 0:
        _append_refusal(world, pool, node_id, requested, used_this_tick,
                        agent_id, household_id, action)
        return 0.0

    stock_before = stock
    pool["current_stock"] = round(stock_before - granted, 6)
    pool["harvest_tick"] = world.current_tick
    pool["harvested_this_tick"] = round(used_this_tick + granted, 6)
    world.event_log.append(world.current_tick, "resource_harvested", {
        "resource_node": node_id, "amount": round(granted, 3),
        "stock_before": round(stock_before, 3),
        "stock_after": pool["current_stock"],
        "harvested_this_tick": pool["harvested_this_tick"],
        "harvest_tick": world.current_tick,
        "agent_id": agent_id, "household_id": household_id,
    })
    return granted
