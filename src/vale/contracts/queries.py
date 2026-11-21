"""跨领域只读查询契约（ADR 009 §2.5 / 迁移计划 P2）。

查询只读，不改变状态，也不暴露对方内部结构：调用方拿到的是值或只读视图。
写入经写入契约（ResourceService / EcologicalImpact）路由到状态所有者结算，
契约本身不写状态（P3c 起由架构测试红线强制）。
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping, Optional

from vale.config.schema.natural_params import Season, WeatherType
from vale.config.schema.spatial_units import SpatialNode
from vale.core.snapshots import ClimateSnapshot
from vale.core.world import World

_DEFAULT_SEASON = Season.SPRING
_DEFAULT_WEATHER = WeatherType.SUNNY
# 田块动态地力中性值（crops.md §4.5）；田块生态状态所有权归环境域（2026-11-21 裁决）。
DEFAULT_FIELD_FERTILITY = 1.0


def _is_field_node(node: SpatialNode) -> bool:
    """田地判定：类型为 field 且不是抽象区域（与既有口径一致）。"""
    return (
        getattr(node.type, "value", node.type) == "field"
        and not node.attributes.get("abstract_zone")
    )


class EnvironmentQuery:
    """自然环境只读快照：气候、水文与由此派生的农事系数。"""

    @staticmethod
    def _climate(world: World) -> Optional[ClimateSnapshot]:
        """域内派生读取（不复制，仅供本类只读派生用）。"""
        return world.state.environment.climate

    @staticmethod
    def climate(world: World) -> Optional[ClimateSnapshot]:
        """气候快照的独立副本：调用方改副本不会影响环境域状态（P6 只读契约）。"""
        climate = EnvironmentQuery._climate(world)
        return climate.model_copy() if climate is not None else None

    @staticmethod
    def season(world: World) -> Season:
        climate = EnvironmentQuery._climate(world)
        return climate.season if climate is not None else _DEFAULT_SEASON

    @staticmethod
    def weather(world: World) -> WeatherType:
        climate = EnvironmentQuery._climate(world)
        return climate.current_weather if climate is not None else _DEFAULT_WEATHER

    @staticmethod
    def temperature_c(world: World) -> float:
        climate = EnvironmentQuery._climate(world)
        return climate.temperature_c if climate is not None else 0.0

    @staticmethod
    def year(world: World) -> int:
        climate = EnvironmentQuery._climate(world)
        return climate.year if climate is not None else 1

    @staticmethod
    def season_name(world: World) -> str:
        """季节名；气候尚未初始化时返回空串（保持旧读取口径）。"""
        climate = EnvironmentQuery._climate(world)
        return climate.season.value if climate is not None else ""

    @staticmethod
    def weather_name(world: World) -> str:
        """天气名；气候尚未初始化时返回空串（保持旧读取口径）。"""
        climate = EnvironmentQuery._climate(world)
        return climate.current_weather.value if climate is not None else ""

    @staticmethod
    def irrigation_gear(world: World) -> str:
        return world.state.environment.irrigation_gear

    @staticmethod
    def moisture_factor(world: World) -> float:
        """灌溉档 → moisture 系数（任务30；004 §2.7）；未知档位按 1.0 降级。"""
        gear = EnvironmentQuery.irrigation_gear(world)
        if not gear:
            return 1.0
        table = world.config.natural_params.hydrology_evolution.moisture_by_gear
        return float(table.get(gear, 1.0))

    @staticmethod
    def field_growth(world: World, node_id: str) -> float:
        """田块长势只读快照（0–100；未引导的田块按 0.0）。"""
        return float(world.state.environment.field_growth.get(node_id, 0.0))

    @staticmethod
    def fertility_factor(world: World, node_id: str) -> float:
        """田块动态地力只读快照（动态乘数；未引导按中性值 1.0）。"""
        return float(world.state.environment.fertility_factor.get(
            node_id, DEFAULT_FIELD_FERTILITY
        ))


class SpatialQuery:
    """空间单元只读查询：节点、田块与面积。通行成本仍由 SpatialIndex 提供。"""

    @staticmethod
    def node(world: World, node_id: str) -> Optional[SpatialNode]:
        for node in world.config.spatial.nodes:
            if node.id == node_id:
                return node
        return None

    @staticmethod
    def field_nodes(world: World) -> tuple[SpatialNode, ...]:
        return tuple(n for n in world.config.spatial.nodes if _is_field_node(n))

    @staticmethod
    def field_ids(world: World) -> tuple[str, ...]:
        return tuple(n.id for n in world.config.spatial.nodes if _is_field_node(n))

    @staticmethod
    def is_field(world: World, node_id: str) -> bool:
        node = SpatialQuery.node(world, node_id)
        return node is not None and _is_field_node(node)

    @staticmethod
    def area(world: World, node_id: str) -> float:
        """田块面积乘数（spatial 节点 ``area``；非田/未知节点按 1.0）。"""
        node = SpatialQuery.node(world, node_id)
        return float(getattr(node, "area", 1.0)) if node is not None else 1.0


class WildlifeQuery:
    """动物只读查询（ADR 009 §2.5）。

    P4 起 ``WildlifeState.pools`` 承载鱼/猎物存量池（``domains.wildlife.wildlife``
    所有者）；P5 填入个体与种群后在此扩展。本类只提供读入口，不得被
    调用方用来修改动物状态。
    """

    @staticmethod
    def populations(world: World) -> Mapping[str, Any]:
        """动物域状态只读视图（当前为池目录快照；P5 扩种群）。"""
        return MappingProxyType(world.state.wildlife.model_dump())
