"""环境领域状态（ADR 009 §2.2A）：地形、水源与生态/田块字段容器。"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from vale.core.pools import ResourcePoolState
from vale.core.snapshots import ClimateSnapshot


class TerrainCellState(BaseModel):
    """Immutable terrain-cell data copied from the deterministic location generator."""

    cell_id: str
    x: int
    y: int
    terrain: str
    elevation: float
    slope: float
    flood_risk: float = Field(..., ge=0, le=1)
    soil_fertility: float = Field(..., ge=0, le=1)


class WaterSourceState(BaseModel):
    """水源库存（P3a）：水井/河段的可取水量与再生参数。

    ``current_stock`` 是所有取水动作的唯一可用量；环境域（domains.environment.hydrology）
    是唯一写入者，人类模块只能调用 ``withdraw_water`` 结算。
    """

    node_id: str
    capacity: float = Field(..., gt=0)
    current_stock: float = Field(default=0.0, ge=0)
    regeneration_per_tick: float = Field(default=0.0, ge=0)
    extraction_limit_per_tick: float = Field(default=0.0, ge=0)


class EnvironmentState(BaseModel):
    """自然环境领域状态（ADR 009 §2.2A）：气候、水文、地形、土壤与生态资源。

    `terrain_cells` / `soil_quality` 是确定性生成的静态副本，不参与产量；
    运行期产量只读 `fertility_factor`（动态乘数，默认 1.0）。
    """

    climate: Optional[ClimateSnapshot] = None
    terrain_cells: dict[str, TerrainCellState] = Field(default_factory=dict)
    # 任务30：水文单点状态（004 §2.7）。水位比例 0–1（1 = 基准）；
    # 灌溉档取 abundant/low/scarce/dry，由 ClimateModule 按配置阈值派生。
    water_level_ratio: float = Field(default=0.6, ge=0, le=1)
    irrigation_gear: str = Field(default="low")
    # 生态资源库存（植被类池）由 EcologyModule 写事件、WorldState 保存可重放投影；
    # 鱼/猎物池在 WildlifeState.pools（2026-11-21 裁决：动物存量归动物域）。
    ecological_resources: dict[str, ResourcePoolState] = Field(default_factory=dict)
    # 水源库存（P3a）：node_id -> 存量/容量/再生/日抽上限；由 HydrologyModule 结算。
    water_sources: dict[str, WaterSourceState] = Field(default_factory=dict)
    # 田地长势：node_id -> 0-100；环境域所有者 domains.environment.fields 结算（2026-11-21 裁决）
    field_growth: dict[str, float] = Field(default_factory=dict)
    # 田块地力（crops.md §4.5 fertility）：node_id -> 动态乘数，默认 1.0，参与产量。
    fertility_factor: dict[str, float] = Field(default_factory=dict)
    # 静态地力：node_id -> 地形生成值，不参与产量（留给未来的地力平衡任务）。
    soil_quality: dict[str, float] = Field(default_factory=dict)
