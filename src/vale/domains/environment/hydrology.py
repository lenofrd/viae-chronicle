"""水源库存的读-校验-写结算（P3a 机制；P3c 起结算归环境域水文实现）。

ADR 009 §2.4/§2.5：``EnvironmentState.water_sources`` 的唯一所有者是环境域，
结算、校验与事件都由本模块执行；人类模块经写入契约
（``contracts.resources.ResourceService.withdraw_water``）提交请求，契约只路由、
不写状态。P3a 期间结算曾放在 ``contracts/water.py``，P3c 按裁决移交所有者。

机制（确定性、无随机）：
- 存量夹在 ``0..capacity``；
- 每 tick 补水 ``regeneration_per_tick × water_level_ratio``，到容量即止；
- 同 tick 内累计取水不超过 ``extraction_limit_per_tick``；
- 每次存量变化先写事件，再改状态（事件流是唯一真相）。
"""
from __future__ import annotations

from typing import Optional

from vale.core.state import WaterSourceState


def _params(world, node_id: str):
    supply = getattr(getattr(world.config, "natural_params", None), "water_supply", None) or {}
    return supply.get(node_id)


def ensure_source(world, node_id: str) -> Optional[WaterSourceState]:
    """返回水源库存；未配置该节点的水源时返回 None（调用方保持旧行为）。"""
    source = world.state.environment.water_sources.get(node_id)
    if source is not None:
        return source
    params = _params(world, node_id)
    if params is None:
        return None
    ratio = (
        params.initial_ratio
        if params.initial_ratio is not None
        else float(world.state.environment.water_level_ratio)
    )
    source = WaterSourceState(
        node_id=node_id,
        capacity=float(params.capacity),
        current_stock=round(float(params.capacity) * float(ratio), 6),
        regeneration_per_tick=float(params.regeneration_per_tick),
        extraction_limit_per_tick=float(params.extraction_limit_per_tick),
    )
    world.state.environment.water_sources[node_id] = source
    world.event_log.append(world.current_tick, "water_source_initialized", {
        "water_node": node_id,
        "source": source.model_dump(),
        "water_level_ratio": round(float(world.state.environment.water_level_ratio), 6),
    })
    return source


def _extracted_this_tick(world, node_id: str) -> float:
    return sum(
        float((event.get("payload") or {}).get("amount", 0.0))
        for event in world.event_log.by_type_at_tick("water_withdrawn", world.current_tick)
        if (event.get("payload") or {}).get("water_node") == node_id
    )


def withdraw_water(world, node_id: str, amount: float, *, requester_id: str = "") -> float:
    """从水源取水并返回实际给付量（可能因存量/日抽上限而少于请求量）。"""
    requested = max(0.0, float(amount))
    if requested <= 0:
        return 0.0
    source = ensure_source(world, node_id)
    if source is None:
        return requested  # 未配置库存的节点：保持 P3a 前的行为

    limit_left = max(0.0, source.extraction_limit_per_tick - _extracted_this_tick(world, node_id))
    granted = round(min(requested, source.current_stock, limit_left), 6)
    before = round(source.current_stock, 6)
    if granted <= 0:
        _append_refusal(world, node_id, requester_id, requested, 0.0, before)
        return 0.0

    source.current_stock = round(before - granted, 6)
    world.event_log.append(world.current_tick, "water_withdrawn", {
        "water_node": node_id,
        "requester_id": requester_id,
        "requested": round(requested, 6),
        "amount": granted,
        "stock_before": before,
        "stock_after": source.current_stock,
    })
    if granted < requested:
        _append_refusal(world, node_id, requester_id, requested, granted, source.current_stock)
    return granted


def _append_refusal(world, node_id: str, requester_id: str, requested: float,
                    granted: float, stock: float) -> None:
    world.event_log.append(world.current_tick, "water_withdrawal_refused", {
        "water_node": node_id,
        "requester_id": requester_id,
        "requested": round(requested, 6),
        "granted": round(granted, 6),
        "stock": round(stock, 6),
        "reason": "insufficient_stock" if stock <= 0 else "extraction_limit",
    })


def regenerate_water_sources(world) -> None:
    """按当前水位比例为所有已配置水源补水（每 tick 由 climate 模块调用）。"""
    ratio = float(world.state.environment.water_level_ratio)
    supply = getattr(getattr(world.config, "natural_params", None), "water_supply", None) or {}
    for node_id in sorted(supply):
        source = ensure_source(world, node_id)
        if source is None:
            continue
        before = round(source.current_stock, 6)
        amount = round(min(source.capacity - before, source.regeneration_per_tick * ratio), 6)
        if amount <= 0:
            continue
        source.current_stock = round(before + amount, 6)
        world.event_log.append(world.current_tick, "water_source_regenerated", {
            "water_node": node_id,
            "amount": amount,
            "stock_before": before,
            "stock_after": source.current_stock,
            "water_level_ratio": round(ratio, 6),
        })
