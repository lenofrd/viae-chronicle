"""世界状态模型：跨模块共享的结构化快照。

不允许模块往裸 dict 里乱塞。每个子系统的快照在此定义字段结构，
后续模块（水文、植被等）必须按对应结构读取。
气候快照的取值枚举复用 config.schema.natural_params，保持单一真相源。
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from config.schema.natural_params import (
    DroughtState,
    FloodState,
    Season,
    WeatherType,
)


class ClimateSnapshot(BaseModel):
    """单个 Tick 的气候快照，写入 world.state.climate。"""

    season: Season
    season_progress: float = Field(..., ge=0, le=1)
    current_weather: WeatherType
    temperature_c: float
    precipitation_mm: float = 0.0
    humidity_pct: float
    wind_level: float = 0.0
    drought_state: DroughtState = DroughtState.NONE
    drought_accumulation: float = 0.0
    flood_state: FloodState = FloodState.NONE
    flood_accumulation: float = 0.0
    days_no_soaking_rain: int = 0
    weather_trend: list[str] = Field(default_factory=list)


class WorldState(BaseModel):
    """跨模块共享状态。climate 由气候模块写入，其余子系统后续扩展。"""

    climate: Optional[ClimateSnapshot] = None
