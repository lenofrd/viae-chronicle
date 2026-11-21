"""田块生态状态结算（环境域所有者，2026-11-21 裁决）。

``field_growth`` 长势、``fertility_factor`` 动态地力、``soil_quality`` 静态地力
归环境域所有者：农事意图、灾害冲减、收获复位均由本模块结算，人类模块经
``contracts.impacts.EcologicalImpact`` 提交意图。产量换算与收成入家庭库存
归人文域（ADR §2.6 规则 10）。
"""
from __future__ import annotations

from vale.contracts.queries import DEFAULT_FIELD_FERTILITY, SpatialQuery


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
