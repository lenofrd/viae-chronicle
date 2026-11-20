"""自然资源采集的统一写入契约（P3b，ResourceService）。

ADR 009 §2.4/§2.5：资源服务只是按资源类型路由到状态所有者的门面，本身不拥有库存；
人类模块不得直接改写环境域的资源池。本契约做三件事：

1. 路由：生态资源池归环境域（``EnvironmentState.ecological_resources``），
   生活用水归水源库存（P3a 的 ``contracts.water``）；
2. 校验：同 tick 累计采集不超过池的 ``extraction_limit_per_tick``，且不超过存量；
3. 结算：先写事件，再更新投影；给付量为 0 时写拒绝事件（不改状态）。

行为等价约定：未登记资源池的节点（如测试夹具里的 ``well``）沿用 P3b 前的
"原额给付"，由 P4 统一资源模型时再收敛。
"""
from __future__ import annotations

from vale.contracts import water as water_contract


def _pool_at(world, node_id: str):
    return world.state.environment.ecological_resources.get(node_id)


def _harvested_this_tick(pool: dict, tick: int) -> float:
    if pool.get("harvest_tick") != tick:
        return 0.0
    return float(pool.get("harvested_this_tick", 0.0))


class ResourceService:
    """资源获取命令的统一入口（采集/捕鱼/打猎/取水）。"""

    @staticmethod
    def harvest(world, node_id: str, requested: float, *, agent_id: str = "",
                household_id: str = "", action: str = "") -> float:
        """从节点资源池结算采集，返回实际给付量（0 表示被拒）。"""
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

    @staticmethod
    def is_resource_node(world, node_id: str) -> bool:
        """该节点是否登记了生态资源池（供调用方区分失败原因）。"""
        return _pool_at(world, node_id) is not None

    @staticmethod
    def withdraw_water(world, node_id: str, amount: float, *, requester_id: str = "") -> float:
        """生活用水：路由到 P3a 的水源库存结算。"""
        return water_contract.withdraw_water(
            world, node_id, amount, requester_id=requester_id
        )


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
