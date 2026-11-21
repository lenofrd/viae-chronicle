"""生态资源池与田块生态状态的事件溯源投影与结算（环境域所有者）。

``EnvironmentState.ecological_resources`` 的唯一所有者是环境域：池的初始化与
再生由 ``EcologyModule.step`` 驱动，采集结算由本模块的 ``harvest_from_pool``
执行；人类模块经写入契约（``contracts.resources.ResourceService.harvest``）
提交请求，契约只路由、不写状态。P3b 期间结算曾放在 ``contracts/resources.py``，
P3c 按裁决移交所有者。

P4（2026-11-21 裁决）之后的边界：池参数唯一真相源是生成器产出的池目录
（``LoadedConfig.resources``，``ResourcePoolSpec``），节点 attributes 不再携带
``resource_*`` 副本；``resource_type`` 为 fish/game 的池归动物域
（``modules.wildlife`` 拥有并结算），其余归本模块；地形栅格 ``terrain_cells``
由本模块从生成结果引导（``ensure_terrain_cells``），不再由人文域土地模块
跨域写入；未登记池的原额给付 fallback 取消（采集指向未登记池启动即报错，
运行期直达则抛错），受限池拒绝 reason 专列 ``restricted``。

田块生态状态（``field_growth`` 长势、``fertility_factor`` 动态地力、
``soil_quality`` 静态地力）按 2026-11-21 裁决与 ADR 009 §2.3/§2.4 修订同样
归环境域所有者：农事意图、灾害冲减、收获复位均由本模块结算，人类模块经
``contracts.impacts.EcologicalImpact`` 提交意图。产量换算与收成入家庭库存
归人文域（ADR §2.6 规则 10）。
"""
from __future__ import annotations

from vale.contracts.queries import DEFAULT_FIELD_FERTILITY, EnvironmentQuery, SpatialQuery
from vale.core.state import (
    ResourcePoolSpec,
    ResourcePoolState,
    TerrainCellState,
    WILDLIFE_RESOURCE_TYPES,
)


def pool_specs(world) -> dict[str, ResourcePoolSpec]:
    """生成器产出的资源池目录（键 = 资源节点 id；缺省配置返回空目录）。"""
    return dict(getattr(world.config, "resources", None) or {})


def ensure_terrain_cells(world) -> None:
    """地形栅格引导（P4 归口）：生成结果经引导路径写入环境域，静默不写事件。"""
    if world.state.environment.terrain_cells:
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
    """封顶季节性再生（共享机制：环境域与动物域池同一结算口径）。"""
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


class EcologyModule:
    name = "ecology"
    depends_on = ["climate"]

    def step(self, world) -> None:
        ensure_terrain_cells(world)
        season = EnvironmentQuery.season(world).value
        pools = world.state.environment.ecological_resources
        for node_id, spec in pool_specs(world).items():
            if spec.resource_type in WILDLIFE_RESOURCE_TYPES:
                continue  # 鱼/猎物池归动物域（modules.wildlife 拥有并结算）
            pool = pools.get(node_id)
            if pool is None:
                pools[node_id] = bootstrap_pool(world, node_id, spec)
                continue
            regenerate_pool(world, pool, node_id, season)


# --------------------------------------------------------------------------- #
# 田块生态结算（2026-11-21 裁决：田块生态状态归环境域所有者，契约只路由）
# --------------------------------------------------------------------------- #

def ensure_field_states(world) -> None:
    """田块生态状态引导（环境域所有者执行，触发时序保持原状以维持确定性）。

    长势初始化为 0、动态地力为中性值、静态地力抄自地形生成输入
    （``soil_fertility``，仅供未来地力平衡任务使用，不参与产量）。
    静默初始化，不写事件（与既有行为一致）。
    """
    if not world.state.environment.field_growth:
        for n in SpatialQuery.field_nodes(world):
            world.state.environment.field_growth[n.id] = 0.0
    if not world.state.environment.fertility_factor:
        for n in SpatialQuery.field_nodes(world):
            world.state.environment.fertility_factor[n.id] = DEFAULT_FIELD_FERTILITY
    if not world.state.environment.soil_quality:
        for n in world.config.spatial.nodes:
            quality = n.attributes.get("soil_fertility")
            if (getattr(n.type, "value", n.type) == "field"
                    and not n.attributes.get("abstract_zone")
                    and quality is not None):
                world.state.environment.soil_quality[n.id] = float(quality)


def apply_farm_growth(world, field_node: str, delta: float, *,
                      agent_id: str = "", household_id: str = "") -> float:
    """结算农事长势增量，返回结算后长势。

    校验田块存在（非田块拒绝），增量夹到非负，长势夹到 0–100
    （ADR §2.6 规则 10）；上限语义由人文侧意图携带（``max_field_growth``），
    环境域不读农业配置。静默结算：因果记录由 ``agent_action_taken`` 事件载荷
    携带（field_growth_before/after），与既有事件流保持一致。
    """
    if not SpatialQuery.is_field(world, field_node):
        raise ValueError(f"farm growth intent on non-field node: {field_node}")
    growth = world.state.environment.field_growth
    before = float(growth.get(field_node, 0.0))
    after = min(100.0, max(0.0, before + max(0.0, float(delta))))
    growth[field_node] = after
    return after


def reset_field_growth(world, field_node: str, *,
                       agent_id: str = "", household_id: str = "") -> float:
    """收获复位田块长势（归零），返回复位前长势。校验同 ``apply_farm_growth``。"""
    if not SpatialQuery.is_field(world, field_node):
        raise ValueError(f"harvest reset intent on non-field node: {field_node}")
    growth = world.state.environment.field_growth
    before = float(growth.get(field_node, 0.0))
    growth[field_node] = 0.0
    return before


def apply_flood_damage(world, field_node: str, damage: float, *, precipitation_mm: float) -> float:
    """洪涝冲减田块长势，返回实际扣减量（请求量先夹到当前值）。"""
    growth = world.state.environment.field_growth
    before = float(growth.get(field_node, 0.0))
    actual = min(before, max(0.0, float(damage)))
    if actual <= 0:
        return 0.0
    after = round(max(0.0, before - actual), 4)
    growth[field_node] = after
    world.event_log.append(world.current_tick, "field_flood_damage", {
        "field_node": field_node, "before": round(before, 4),
        "damage": round(actual, 4), "after": after,
        "precipitation_mm": precipitation_mm,
    })
    return actual


def apply_drought_damage(world, field_node: str, damage: float, *, drought_state: str) -> float:
    """旱灾冲减田块长势，返回实际扣减量（请求量先夹到当前值）。"""
    growth = world.state.environment.field_growth
    before = float(growth.get(field_node, 0.0))
    actual = min(before, max(0.0, float(damage)))
    if actual <= 0:
        return 0.0
    after = round(max(0.0, before - actual), 4)
    growth[field_node] = after
    world.event_log.append(world.current_tick, "field_drought_damage", {
        "field_node": field_node, "before": round(before, 4),
        "damage": round(actual, 4), "after": after,
        "drought_state": drought_state,
    })
    return actual


def apply_landslide(world, field_node: str, *, amount: float, source_node: str,
                    resource_stock_ratio: float) -> float:
    """滑坡扣减田块地力，返回扣减后的地力。"""
    factors = world.state.environment.fertility_factor
    before = float(factors.get(field_node, 1.0))
    after = round(max(.1, before - max(0.0, float(amount))), 4)
    factors[field_node] = after
    world.event_log.append(world.current_tick, "landslide_damage", {
        "source_node": source_node, "field_node": field_node,
        "fertility_before": before, "fertility_after": after,
        "resource_stock_ratio": round(resource_stock_ratio, 4),
    })
    return after


# --------------------------------------------------------------------------- #
# 采集结算（P3b 机制；P3c 起由环境域所有者执行，契约 ResourceService 只路由；
# P4 起 State 化 + 收敛：共享结算机制供动物域（modules.wildlife）复用）
# --------------------------------------------------------------------------- #

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
    """资源池采集结算机制（共享：环境域与动物域所有者同一口径）。

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


def harvest_from_pool(world, node_id: str, requested: float, *, agent_id: str = "",
                      household_id: str = "", action: str = "") -> float:
    """环境域采集结算（植被类池），返回实际给付量（0 表示被拒）。

    P4 收敛：目标节点未登记资源池不再原额给付，直接抛错（采集目标必须在
    池目录登记，启动校验拦截坏配置；运行期直达此处即状态异常，快速失败）。
    """
    pool = world.state.environment.ecological_resources.get(node_id)
    if pool is None:
        raise ValueError(f"harvest targets unregistered resource pool: {node_id}")
    return settle_pool_harvest(world, pool, node_id, requested,
                               agent_id=agent_id, household_id=household_id,
                               action=action)
