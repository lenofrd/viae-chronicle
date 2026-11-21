"""资源池共享账本机制（基础设施，供环境域与动物域复用）。

P4 起资源池按域归属：植被类池归 ``domains.environment.resources``，鱼/猎物池归
``domains.wildlife.wildlife``。两域使用同一套初始化 / 封顶季节性再生 / 同 tick
额度采集结算口径，因此机制留在此处作通用实现：只操作传入的 ``ResourcePoolState``
与 ``world.event_log``，不决定池归属、不读取任一领域的内部状态；池实例的定位与
域内校验由各域所有者完成。

调用方边界：环境域与动物域各自遍历池目录、按 ``WILDLIFE_RESOURCE_TYPES`` 分流，
本模块不判断资源类型归属。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

# 资源类型归属（跨领域共享定义）：目录中 resource_type 命中此集合的池由
# domains.wildlife.wildlife 拥有并结算，其余归 domains.environment.resources。
# 放在共享基础设施，避免环境域依赖动物域内部状态模块；P5 扩种群时再扩集合。
WILDLIFE_RESOURCE_TYPES = frozenset({"fish", "game"})


def pool_specs(world) -> dict[str, ResourcePoolSpec]:
    """生成器产出的资源池目录（键 = 资源节点 id；缺省配置返回空目录）。"""
    return dict(getattr(world.config, "resources", None) or {})


def bootstrap_pool(world, node_id: str, spec: ResourcePoolSpec) -> ResourcePoolState:
    """按池目录条目建运行时池并宣告事件；字段序即 ``ResourcePoolState`` 字段序。"""
    pool = ResourcePoolState(
        resource_type=spec.resource_type,
        current_stock=float(spec.current_stock),
        max_stock=float(spec.max_stock),
        regeneration_per_tick=float(spec.regeneration_per_tick),
        extraction_limit_per_tick=float(spec.extraction_limit_per_tick),
        seasonal_weights=dict(spec.seasonal_weights),
        restricted=spec.restricted,
        degradation=float(spec.degradation),
        harvested_this_tick=0.0,
        harvest_tick=world.current_tick,
    )
    world.event_log.append(world.current_tick, "resource_pool_initialized", {
        "resource_node": node_id, "pool": pool.model_dump(mode="json"),
    })
    return pool


def regenerate_pool(world, pool: ResourcePoolState, node_id: str, season: str) -> None:
    """封顶季节性再生（环境域与动物域池同一结算口径）。"""
    if pool.restricted:
        return
    before = pool.current_stock
    weight = float(pool.seasonal_weights.get(season, 1.0))
    amount = min(max(0.0, pool.max_stock - before),
                 max(0.0, pool.regeneration_per_tick * weight))
    if amount <= 0:
        return
    pool.current_stock = round(before + amount, 6)
    world.event_log.append(world.current_tick, "resource_regenerated", {
        "resource_node": node_id, "season": season,
        "amount": round(amount, 6), "stock_before": round(before, 6),
        "stock_after": pool.current_stock,
    })


def _harvested_this_tick(pool: ResourcePoolState, tick: int) -> float:
    if pool.harvest_tick != tick:
        return 0.0
    return pool.harvested_this_tick


def _append_refusal(world, pool: ResourcePoolState, node_id: str, requested: float,
                    used_this_tick: float, agent_id: str, household_id: str,
                    action: str) -> None:
    stock = pool.current_stock
    limit = pool.extraction_limit_per_tick
    if pool.restricted:
        reason = "restricted"
    elif stock <= 0:
        reason = "stock_depleted"
    else:
        reason = "extraction_limit"
    world.event_log.append(world.current_tick, "resource_harvest_refused", {
        "resource_node": node_id,
        "agent_id": agent_id,
        "household_id": household_id,
        "action": action,
        "requested": round(requested, 6),
        "granted": 0.0,
        "stock": round(stock, 6),
        "used_this_tick": round(used_this_tick, 6),
        "reason": reason,
        "extraction_limit_per_tick": round(limit, 6),
    })


def settle_pool_harvest(world, pool: ResourcePoolState, node_id: str,
                        requested: float, *, agent_id: str = "",
                        household_id: str = "", action: str = "") -> float:
    """资源池采集结算机制（环境域与动物域所有者同一口径）。

    校验同 tick 累计额度（``extraction_limit_per_tick``）与存量，先写事件、
    再改投影；给付量为 0 时写拒绝事件（不改状态）。调用方负责定位所属域
    的池实例。
    """
    requested = max(0.0, float(requested))
    if requested <= 0:
        return 0.0
    used_this_tick = _harvested_this_tick(pool, world.current_tick)
    remaining_cap = max(0.0, pool.extraction_limit_per_tick - used_this_tick)
    stock = pool.current_stock
    granted = min(requested, remaining_cap, max(0.0, stock))
    if granted <= 0:
        _append_refusal(world, pool, node_id, requested, used_this_tick,
                        agent_id, household_id, action)
        return 0.0

    stock_before = stock
    pool.current_stock = round(stock_before - granted, 6)
    pool.harvest_tick = world.current_tick
    pool.harvested_this_tick = round(used_this_tick + granted, 6)
    world.event_log.append(world.current_tick, "resource_harvested", {
        "resource_node": node_id, "amount": round(granted, 3),
        "stock_before": round(stock_before, 3),
        "stock_after": pool.current_stock,
        "harvested_this_tick": pool.harvested_this_tick,
        "harvest_tick": world.current_tick,
        "agent_id": agent_id, "household_id": household_id,
    })
    return granted



class ResourcePoolSpec(BaseModel):
    """资源池生成参数（P4）：世界生成自然段产出的池目录条目。

    由生成器写入 ``LoadedConfig.resources``（键 = 资源节点 id），供领域所有者
    首 tick 引导建池；``current_stock`` 即初始存量。池参数唯一真相源从节点
    attributes 副本迁到本目录（2026-11-21 P4 裁决）。
    """

    resource_id: str
    resource_type: str
    current_stock: float = Field(default=0.0, ge=0)
    max_stock: float = Field(default=0.0, ge=0)
    regeneration_per_tick: float = Field(default=0.0, ge=0)
    extraction_limit_per_tick: float = Field(default=0.0, ge=0)
    seasonal_weights: dict[str, float] = Field(default_factory=dict)
    degradation: float = Field(default=0.0, ge=0)
    restricted: bool = False


class ResourcePoolState(BaseModel):
    """资源池运行时投影（P4，事件溯源）；字段序即事件载荷键序。

    ``current_stock`` / ``harvested_this_tick`` / ``degradation`` 由领域所有者
    结算：植被类池归环境域（``domains.environment.resources``），鱼/猎物池归动物域
    （``domains.wildlife.wildlife``，2026-11-21 裁决）。
    """

    resource_type: str
    current_stock: float = Field(default=0.0, ge=0)
    max_stock: float = Field(default=0.0, ge=0)
    regeneration_per_tick: float = Field(default=0.0, ge=0)
    extraction_limit_per_tick: float = Field(default=0.0, ge=0)
    seasonal_weights: dict[str, float] = Field(default_factory=dict)
    restricted: bool = False
    degradation: float = Field(default=0.0, ge=0)
    harvested_this_tick: float = Field(default=0.0, ge=0)
    harvest_tick: int = Field(default=-1, ge=0)
