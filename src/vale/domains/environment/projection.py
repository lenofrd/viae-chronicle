"""环境领域事件投影（ADR 009 §2.2A；2026-11-21 裁决归属修正）。

只重建 ``EnvironmentState``：

- 水文：水位比例、灌溉档、水源库存；
- 田块生态：洪涝 / 旱灾 / 滑坡对长势与地力的冲减；
- 植被类资源池：初始化、再生、采集（fish / game 池归动物域，见
  ``domains.wildlife.projection``）。

处理器不跨领域导入：池类型归属由本领域资源所有者
``domains.environment.resources.owns_resource_type`` 判定。
"""
from __future__ import annotations

from vale.core.pools import ResourcePoolState
from vale.core.replay import ProjectionBase
from vale.domains.environment.resources import owns_resource_type
from vale.domains.environment.state import WaterSourceState


class EnvironmentProjection(ProjectionBase):
    # -- 生态资源池（植被类）------------------------------------------------- #
    def _environment_pool(self, node_id):
        if not node_id:
            return None
        return self.state.environment.ecological_resources.get(node_id)

    def _on_resource_pool_initialized(self, payload: dict, tick: int):
        data = dict(payload.get("pool") or {})
        if not owns_resource_type(data.get("resource_type")):
            return False  # 鱼/猎物池归动物域
        node_id = payload.get("resource_node")
        if node_id:
            self.state.environment.ecological_resources[node_id] = ResourcePoolState(**data)

    def _on_resource_regenerated(self, payload: dict, tick: int):
        pool = self._environment_pool(payload.get("resource_node"))
        if pool is None:
            return False
        if payload.get("stock_after") is not None:
            pool.current_stock = float(payload["stock_after"])

    def _on_resource_harvested(self, payload: dict, tick: int):
        pool = self._environment_pool(payload.get("resource_node"))
        if pool is None:
            return False
        if payload.get("stock_after") is not None:
            pool.current_stock = float(payload["stock_after"])
            pool.harvested_this_tick = float(payload.get("harvested_this_tick", 0.0))
            pool.harvest_tick = int(payload.get("harvest_tick", tick))

    # -- 田块生态 ----------------------------------------------------------- #
    def _on_field_flood_damage(self, payload: dict, tick: int) -> None:
        node_id = payload.get("field_node")
        if node_id and payload.get("after") is not None:
            self.state.environment.field_growth[node_id] = max(0.0, float(payload["after"]))

    def _on_field_drought_damage(self, payload: dict, tick: int) -> None:
        node_id = payload.get("field_node")
        if node_id and payload.get("after") is not None:
            self.state.environment.field_growth[node_id] = max(0.0, float(payload["after"]))

    def _on_landslide_damage(self, payload: dict, tick: int) -> None:
        node_id = payload.get("field_node")
        if node_id and payload.get("fertility_after") is not None:
            self.state.environment.fertility_factor[node_id] = max(.1, float(payload["fertility_after"]))

    # -- 任务30：水文与水源库存 --------------------------------------------- #
    def _on_water_level_changed(self, payload: dict, tick: int) -> None:
        if payload.get("after") is not None:
            self.state.environment.water_level_ratio = max(0.0, min(1.0, float(payload["after"])))

    def _on_water_source_initialized(self, payload: dict, tick: int) -> None:
        node_id = payload.get("water_node")
        source = payload.get("source")
        if node_id and isinstance(source, dict):
            data = dict(source)
            data.setdefault("node_id", node_id)
            self.state.environment.water_sources[node_id] = WaterSourceState(**data)

    def _on_water_source_regenerated(self, payload: dict, tick: int) -> None:
        self._set_water_stock(payload)

    def _on_water_withdrawn(self, payload: dict, tick: int) -> None:
        self._set_water_stock(payload)

    def _set_water_stock(self, payload: dict) -> None:
        node_id = payload.get("water_node")
        source = self.state.environment.water_sources.get(node_id) if node_id else None
        if source is not None and payload.get("stock_after") is not None:
            source.current_stock = max(0.0, round(float(payload["stock_after"]), 6))

    def _on_irrigation_gear_changed(self, payload: dict, tick: int) -> None:
        if payload.get("to"):
            self.state.environment.irrigation_gear = str(payload["to"])
