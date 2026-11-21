"""跨领域只读快照（基础设施值对象）。

`ClimateSnapshot` 是契约查询（`contracts.queries.EnvironmentQuery`）返回的只读气候快照，
被环境域、查询契约与观察层共同消费。它不参与状态所有权（气候状态的唯一所有者也
不在此处），只作为跨领域共享的数据形状存在，因此留在基础设施层而不是领域内。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from vale.config.schema.natural_params import (
    DroughtState,
    FloodState,
    Season,
    WeatherType,
)


class ClimateSnapshot(BaseModel):
    """单个 Tick 的气候快照，写入 world.state.environment.climate。

    年/月/日/节气由绝对 tick 换算（见 vale.core.calendar），季节也由月份派生，
    保证「日期」与「季节」是同一真相源，互不漂移。
    """

    season: Season
    season_progress: float = Field(..., ge=0, le=1)
    year: int = Field(..., ge=1)
    month: int = Field(..., ge=1, le=12)
    day: int = Field(..., ge=1, le=30)
    solar_term: str
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
