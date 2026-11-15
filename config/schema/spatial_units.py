"""空间节点与拓扑的 Pydantic Schema。

通用机制：只定义结构与类型，不写死任何具体地点的数值。
具体节点与耗时来自 config/worlds/<world_id>/spatial-units.yaml。
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class NodeType(str, Enum):
    SOCIAL = "social"          # 社交 / 议事节点
    RESIDENTIAL = "residential"
    RESOURCE = "resource"      # 资源点（水井、柴林、药山等）
    FIELD = "field"
    WATER = "water"            # 河流 / 水渠
    MOUNTAIN = "mountain"


class SpatialNode(BaseModel):
    id: str = Field(..., description="节点唯一标识（snake_case）")
    name: str
    type: NodeType
    district: Optional[str] = None
    description: str = ""
    travel_cost_from_well_tu: Optional[float] = Field(
        None, ge=0,
        description="从镇中心水井出发的单程耗时（TU），来源：05-distances.md",
    )
    # 仅 field 节点有意义：该田块种什么作物（同时是 AgentState 的产出字段名）。
    # 缺省 grain，向后兼容；新增作物（如 fruit）只需在配置与 base_yield 中加一项。
    crop_type: str = Field("grain", description="田块作物类型（grain / vegetable / 未来 fruit）")
    # crops.md §4.5 产量公式因子：田块面积（仅 field 节点参与计算）。
    # 默认 1.0 = 与既有固定产出等价；阶段二只作乘数占位，不提产。
    area: float = Field(1.0, gt=0, description="田块面积乘数（crops.md §4.5 area，默认 1.0）")
    attributes: dict = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _id_must_be_snake(cls, v: str) -> str:
        if not v or not v.replace("_", "").isalnum():
            raise ValueError(f"invalid node id: {v!r}")
        return v


class DistanceEdge(BaseModel):
    from_id: str
    to_id: str
    one_way_tu: float = Field(..., ge=0)
    difficulty: str = "平地"
    risk: str = "无"


class SpatialConfig(BaseModel):
    nodes: list[SpatialNode] = Field(..., min_length=1)
    distance_edges: list[DistanceEdge] = Field(default_factory=list)

    @field_validator("nodes")
    @classmethod
    def _ids_unique(cls, v: list[SpatialNode]) -> list[SpatialNode]:
        ids = [n.id for n in v]
        if len(ids) != len(set(ids)):
            raise ValueError("spatial node ids must be unique")
        return v
