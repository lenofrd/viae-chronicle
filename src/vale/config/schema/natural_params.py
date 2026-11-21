"""自然环境参数的 Pydantic Schema。

通用机制：定义气候/水文的初始状态结构与演化参数结构。
演化参数（概率 / 阈值 / 速率）由具体地点提供，本 Schema 允许缺省（Optional）。
缺失值必须由用户在 locations 文档中补充，严禁臆造。
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class Season(str, Enum):
    SPRING = "spring"
    SUMMER = "summer"
    AUTUMN = "autumn"
    WINTER = "winter"


class DroughtState(str, Enum):
    NONE = "none"
    WATCH = "watch"
    WARNING = "warning"
    CRISIS = "crisis"


class FloodState(str, Enum):
    NONE = "none"
    WATCH = "watch"
    WARNING = "warning"
    CRISIS = "crisis"


class WeatherType(str, Enum):
    SUNNY = "sunny"
    CLOUDY = "cloudy"
    LIGHT_RAIN = "light_rain"
    MODERATE_RAIN = "moderate_rain"
    HEAVY_RAIN = "heavy_rain"
    OTHER = "other"


# --------------------------------------------------------------------------
# 演化参数（全部为地点参数占位，可为 null）
# --------------------------------------------------------------------------
class SeasonParams(BaseModel):
    length_ticks: Optional[int] = Field(None, ge=1, description="季节长度（Tick）")
    base_temperature_c: Optional[float] = None
    base_humidity_pct: Optional[float] = Field(None, ge=0, le=100)
    precipitation_prob: Optional[float] = Field(None, ge=0, le=1)
    precipitation_intensity_mm: Optional[float] = Field(None, ge=0)
    base_wind_level: Optional[float] = None
    trend_anchor: Optional[str] = None  # dry / wet / stable
    # 004 裁决：每日工作窗 TU 随季节（1 TU = 1 工作小时；夜间睡眠不占 TU）。
    # 溪谷镇：春 10 / 夏 9（午热）/ 秋 10 / 冬 6。[调参]
    work_window_tu: float = Field(10.0, ge=1, description="该季节每日工作窗（TU）")


class DroughtParams(BaseModel):
    no_rain_threshold_ticks: Optional[int] = Field(None, ge=1)
    watch_threshold: Optional[float] = None
    warning_threshold: Optional[float] = None
    crisis_threshold: Optional[float] = None
    recovery_rate: Optional[float] = None
    max_accumulation: Optional[float] = None


class FloodParams(BaseModel):
    heavy_rain_threshold_mm: Optional[float] = None
    watch_threshold: Optional[float] = None
    warning_threshold: Optional[float] = None
    crisis_threshold: Optional[float] = None
    linger_ticks: Optional[int] = Field(None, ge=0)


class GlobalConstraints(BaseModel):
    max_temp_delta_per_tick: Optional[float] = Field(None, ge=0)
    max_humidity_delta_per_tick: Optional[float] = Field(None, ge=0)


class ClimateEvolutionParams(BaseModel):
    seasons: dict[str, SeasonParams] = Field(default_factory=dict)
    drought: DroughtParams = Field(default_factory=DroughtParams)
    flood: FloodParams = Field(default_factory=FloodParams)
    global_constraints: GlobalConstraints = Field(default_factory=GlobalConstraints)
    transition_length_ticks: Optional[int] = Field(None, ge=0)
    max_delta_per_tick: Optional[dict[str, float]] = None
    weather_trend_window: Optional[int] = Field(None, ge=1)


# --------------------------------------------------------------------------
# 初始状态
# --------------------------------------------------------------------------
class ClimateInitialState(BaseModel):
    """开局气候状态。数值来源：locations/brookvale-town/05-setup/01-initial-state.md。
    文档未给出的数值留空（null），待用户补充，不臆造。"""
    start_tick: int = Field(..., ge=0)
    season: Season
    season_progress: Optional[float] = Field(None, ge=0, le=1)
    current_weather: Optional[WeatherType] = None
    temperature_c: Optional[float] = None
    precipitation_mm: Optional[float] = Field(None, ge=0)
    humidity_pct: Optional[float] = Field(None, ge=0, le=100)
    wind_level: Optional[float] = None
    drought_state: DroughtState = DroughtState.NONE
    drought_accumulation: Optional[float] = Field(None, ge=0)
    flood_state: FloodState = FloodState.NONE
    flood_accumulation: Optional[float] = Field(None, ge=0)
    days_no_soaking_rain: Optional[int] = Field(None, ge=0)
    weather_trend: list[WeatherType] = Field(default_factory=list)


class HydrologyInitialState(BaseModel):
    """开局水文状态（引用 05-setup 文档）。"""
    water_level_ratio: Optional[float] = Field(
        None, ge=0, description="相对基准水位的比例，1.0 = 基准"
    )
    irrigation_gear: Optional[str] = None


class IrrigationGear(str, Enum):
    """灌溉条件四档（004 §2.7）：充足 / 偏少 / 缺水 / 断水。"""
    ABUNDANT = "abundant"
    LOW = "low"
    SCARCE = "scarce"
    DRY = "dry"


class HydrologyEvolutionParams(BaseModel):
    """单点水位演化与灌溉档派生（确定性、无随机）。

    机制：有效降水日按 ``recharge_per_mm × precipitation_mm × (1 − 水位)`` 抬升（到满水位的
    剩余空间越少补水越慢，避免常年封顶 1.0），无有效降水日按 ``dry_loss_per_day`` 下降，
    夹紧 0–1；灌溉档由水位按 ``gear_thresholds``（降序下界）派生。所有数值为地点 [调参]。
    """

    recharge_per_mm: float = Field(
        0.002, ge=0, description="有效降水补水系数（按剩余水位空间 × mm 折算）"
    )
    soak_threshold_mm: float = Field(5.0, ge=0, description="有效降水阈值（mm）；低于此值按无雨日计")
    dry_loss_per_day: float = Field(0.004, ge=0, description="无有效降水日的水位下降")
    gear_thresholds: dict[str, float] = Field(
        default_factory=lambda: {"abundant": 0.80, "low": 0.55, "scarce": 0.30},
        description="水位比例 → 灌溉档下界（abundant/low/scarce 降序；低于 scarce 即 dry）",
    )
    moisture_by_gear: dict[str, float] = Field(
        default_factory=lambda: {"abundant": 1.0, "low": 0.85, "scarce": 0.7, "dry": 0.5},
        description="灌溉档 → 产量公式 moisture 系数",
    )

    @model_validator(mode="after")
    def _check_gear_tables(self) -> "HydrologyEvolutionParams":
        gears = {g.value for g in IrrigationGear}
        if set(self.gear_thresholds) != {"abundant", "low", "scarce"}:
            raise ValueError(
                "hydrology_evolution.gear_thresholds 必须恰好声明 abundant/low/scarce "
                "（dry 为兜底档，不设下界）"
            )
        a, lo, sc = (self.gear_thresholds[k] for k in ("abundant", "low", "scarce"))
        if not (1.0 >= a > lo > sc > 0.0):
            raise ValueError(
                "hydrology_evolution.gear_thresholds 必须满足 1 ≥ abundant > low > scarce > 0"
            )
        if set(self.moisture_by_gear) != gears:
            raise ValueError(
                "hydrology_evolution.moisture_by_gear 必须覆盖 abundant/low/scarce/dry 四档"
            )
        for gear, factor in self.moisture_by_gear.items():
            if not (0.0 < factor <= 1.0):
                raise ValueError(f"hydrology_evolution.moisture_by_gear[{gear}] 必须落在 (0, 1]")
        return self


class WaterSupplyParams(BaseModel):
    """单个水源（水井/河段）的库存与再生参数（P3a）。

    机制固定为：水库存量 0–capacity；每 tick 按 ``regeneration_per_tick × 水位比例``
    补水且不越容量；同一 tick 内所有取水合计不超过 ``extraction_limit_per_tick``。
    具体数值由地点配置提供（[调参]），缺省值保证旧世界能跑且两年基线不触顶。
    """

    capacity: float = Field(6000.0, gt=0, description="水源最大存量")
    initial_ratio: Optional[float] = Field(
        None, ge=0, le=1,
        description="开局存量占容量比例；None = 取开局 water_level_ratio",
    )
    regeneration_per_tick: float = Field(
        240.0, ge=0, description="水位比例 1.0 时每 tick 的补水量（实际按水位缩放）"
    )
    extraction_limit_per_tick: float = Field(
        2880.0, ge=0, description="同一 tick 内该水源允许被抽取的总量上限"
    )


class NaturalConfig(BaseModel):
    climate_initial: ClimateInitialState
    hydrology_initial: HydrologyInitialState = Field(default_factory=HydrologyInitialState)
    hydrology_evolution: HydrologyEvolutionParams = Field(default_factory=HydrologyEvolutionParams)
    climate_evolution: ClimateEvolutionParams = Field(default_factory=ClimateEvolutionParams)
    # P3a 水源库存：key 为空间节点 id；未列出的节点不设库存（取水保持旧行为）。
    water_supply: dict[str, WaterSupplyParams] = Field(
        default_factory=lambda: {"well": WaterSupplyParams()}
    )
