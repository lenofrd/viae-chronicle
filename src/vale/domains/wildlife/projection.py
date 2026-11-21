"""动物领域事件投影（ADR 009 §2.2B；2026-11-21 裁决归属修正）。

只重建 ``WildlifeState.pools``：fish / game 存量池的初始化、再生与采集。
归属判定只看本领域容器与本领域资源类型常量：不是动物域的池显式
``return False``，交给下一个投影（环境域）。
"""
from __future__ import annotations

from vale.core.pools import ResourcePoolState
from vale.core.replay import ProjectionBase
from vale.domains.wildlife.state import WILDLIFE_RESOURCE_TYPES


class WildlifeProjection(ProjectionBase):
    def _on_resource_pool_initialized(self, payload: dict, tick: int):
        data = dict(payload.get("pool") or {})
        if data.get("resource_type") not in WILDLIFE_RESOURCE_TYPES:
            return False  # 植被类池归环境域
        node_id = payload.get("resource_node")
        if node_id:
            self.state.wildlife.pools[node_id] = ResourcePoolState(**data)

    def _on_resource_regenerated(self, payload: dict, tick: int):
        pool = self.state.wildlife.pools.get(payload.get("resource_node"))
        if pool is None:
            return False
        if payload.get("stock_after") is not None:
            pool.current_stock = float(payload["stock_after"])

    def _on_resource_harvested(self, payload: dict, tick: int):
        pool = self.state.wildlife.pools.get(payload.get("resource_node"))
        if pool is None:
            return False
        if payload.get("stock_after") is not None:
            pool.current_stock = float(payload["stock_after"])
            pool.harvested_this_tick = float(payload.get("harvested_this_tick", 0.0))
            pool.harvest_tick = int(payload.get("harvest_tick", tick))
