"""气候演化模块（阶段四）。

实现 Module 接口：name / depends_on=[] / step(world)。
读取 world.config.natural_params 的演化参数，每个 Tick：
  1. 由绝对 tick 换算日历（年/月/日/节气）与季节（单一真相源，见 vale.core.calendar）；
  2. 按当前季节 precipitation_prob 判定是否降雨；
  3. 更新温度、湿度（受 max_*_delta_per_tick 限制，禁止瞬移）；
  4. 未雨累加 drought_accumulation（超 no_rain_threshold 才计），降雨按 recovery_rate 降低；
  5. 写回 world.state.environment.climate（含日期字段）；
  6. 发 weather_changed 事件（载荷含日期），跨季时发 season_changed 事件。

第一版只跑旱情路径，洪水阈值留空不触发汛情。
"""
from __future__ import annotations

import random
from typing import Any

from vale.config.schema.natural_params import DroughtState, IrrigationGear, Season, WeatherType
from vale.modules.hydrology import regenerate_water_sources

from ..core.calendar import (
    calendar_from_tick,
    season_for_month,
    season_progress_from_day_of_year,
    start_day_of_year,
)
from ..core.state import ClimateSnapshot

# weather_trend_window 地点参数缺失，使用默认值 7，待确认
DEFAULT_TREND_WINDOW = 7


def _derive_time(world) -> dict:
    """由绝对 tick 换算当前日历 + 季节（单一真相源，杜绝季节与日期漂移）。

    开局日由 climate_initial 的 (season, season_progress) 决定，年份由 world.start_year 决定。
    """
    cfg = world.config
    init = cfg.natural_params.climate_initial
    start_doy = start_day_of_year(init.season, init.season_progress or 0.0)
    year, month, day, solar_term, doy = calendar_from_tick(
        world.current_tick,
        cfg.world.start_tick,
        start_doy,
        getattr(cfg.world, "start_year", 1),
    )
    return {
        "year": year,
        "month": month,
        "day": day,
        "solar_term": solar_term,
        "day_of_year": doy,
        "season": season_for_month(month),
        "season_progress": season_progress_from_day_of_year(doy),
    }


class ClimateModule:
    name = "climate"
    depends_on: list[str] = []

    def __init__(self, rng: Any = None, trend_window: int = DEFAULT_TREND_WINDOW) -> None:
        # rng 只需提供 random() 与 uniform(a, b)；默认用独立 Random 实例
        self.rng = rng if rng is not None else random.Random()
        self.trend_window = trend_window

    # ------------------------------------------------------------------
    # 初始化（首次 step 时从配置载入初始状态）
    # ------------------------------------------------------------------
    def _ensure_initialized(self, world) -> None:
        if world.state.environment.climate is not None:
            return
        cfg = world.config.natural_params
        init = cfg.climate_initial
        # 开局日历/季节由 tick 换算（与 step 同源），保证初始快照的日期与季节自洽
        t = _derive_time(world)
        season = t["season"]
        sparams = cfg.climate_evolution.seasons.get(season.value)

        # 文档未给开局当日温湿度 → 用当前季节基准
        temp = init.temperature_c
        if temp is None:
            temp = sparams.base_temperature_c if sparams and sparams.base_temperature_c is not None else 20.0
        hum = init.humidity_pct
        if hum is None:
            hum = sparams.base_humidity_pct if sparams and sparams.base_humidity_pct is not None else 50.0

        # 旱情累积初始值：文档未给，取 days_no_soaking_rain 使其与 drought_state=watch 自洽
        acc = init.drought_accumulation
        if acc is None:
            acc = float(init.days_no_soaking_rain or 0)

        world.state.environment.climate = ClimateSnapshot(
            season=season,
            season_progress=t["season_progress"],
            year=t["year"],
            month=t["month"],
            day=t["day"],
            solar_term=t["solar_term"],
            current_weather=init.current_weather or WeatherType.SUNNY,
            temperature_c=float(temp),
            precipitation_mm=float(init.precipitation_mm or 0.0),
            humidity_pct=float(hum),
            wind_level=float(init.wind_level or 0.0),
            drought_state=init.drought_state,
            drought_accumulation=float(acc),
            flood_state=init.flood_state,
            flood_accumulation=float(init.flood_accumulation or 0.0),
            days_no_soaking_rain=int(init.days_no_soaking_rain or 0),
            weather_trend=[w.value for w in init.weather_trend] if init.weather_trend else [],
        )

        # 任务30：水文初始状态（缺省时沿用 WorldState 默认 0.6 / low）
        hydro_init = cfg.hydrology_initial
        if hydro_init.water_level_ratio is not None:
            world.state.environment.water_level_ratio = float(hydro_init.water_level_ratio)
        if hydro_init.irrigation_gear:
            world.state.environment.irrigation_gear = hydro_init.irrigation_gear

    # ------------------------------------------------------------------
    # 每 Tick 演化
    # ------------------------------------------------------------------
    def step(self, world) -> None:
        self._ensure_initialized(world)
        cfg = world.config.natural_params
        evo = cfg.climate_evolution
        snap: ClimateSnapshot = world.state.environment.climate
        # 时间换算（单一真相源）：季节与进度均由 tick 派生，跨季靠与上一 tick 快照对比判定
        t = _derive_time(world)
        season = t["season"]
        new_progress = t["season_progress"]
        season_changed = season != snap.season
        sparams = evo.seasons[season.value]
        constraints = evo.global_constraints

        max_temp_delta = constraints.max_temp_delta_per_tick
        max_temp_delta = max_temp_delta if max_temp_delta is not None else float("inf")
        max_hum_delta = constraints.max_humidity_delta_per_tick
        max_hum_delta = max_hum_delta if max_hum_delta is not None else float("inf")

        # 1. 降雨判定
        rains = self.rng.random() < sparams.precipitation_prob
        precip = float(sparams.precipitation_intensity_mm) if rains else 0.0
        weather = WeatherType.MODERATE_RAIN if rains else WeatherType.SUNNY

        # 2. 温湿度朝“基准+扰动”移动，但单日变化受限（禁止瞬移）
        target_temp = sparams.base_temperature_c + self.rng.uniform(-3.0, 3.0)
        temp = self._move_toward(snap.temperature_c, target_temp, max_temp_delta)
        target_hum = sparams.base_humidity_pct + self.rng.uniform(-5.0, 5.0)
        hum = self._move_toward(snap.humidity_pct, target_hum, max_hum_delta)
        hum = max(0.0, min(100.0, hum))

        # 3. 旱情累积
        new_acc = snap.drought_accumulation
        days_no_rain = snap.days_no_soaking_rain
        if rains:
            new_acc = max(0.0, new_acc - float(evo.drought.recovery_rate or 0.0))
            days_no_rain = 0
        else:
            days_no_rain += 1
            threshold = evo.drought.no_rain_threshold_ticks or 0
            if days_no_rain > threshold:
                new_acc += 1.0
        max_acc = evo.drought.max_accumulation
        if max_acc is not None:
            new_acc = min(new_acc, float(max_acc))
        new_drought_state = self._classify_drought(new_acc, evo.drought)

        # 4. 跨季判定已在顶部由日历派生完成（season_changed），此处不再用浮点累积

        # 5. weather_trend 滑动窗口
        trend = list(snap.weather_trend) + [weather.value]
        if len(trend) > self.trend_window:
            trend = trend[-self.trend_window:]

        # 6. 写回快照
        world.state.environment.climate = snap.model_copy(
            update={
                "season": season,
                "season_progress": new_progress,
                "year": t["year"],
                "month": t["month"],
                "day": t["day"],
                "solar_term": t["solar_term"],
                "current_weather": weather,
                "temperature_c": temp,
                "precipitation_mm": precip,
                "humidity_pct": hum,
                "drought_state": new_drought_state,
                "drought_accumulation": new_acc,
                "days_no_soaking_rain": days_no_rain,
                "weather_trend": trend,
            }
        )

        # 7. 发事件
        world.event_log.append(
            tick=world.current_tick,
            event_type="weather_changed",
            payload={
                "year": t["year"],
                "month": t["month"],
                "day": t["day"],
                "solar_term": t["solar_term"],
                "season": season.value,
                "season_progress": round(new_progress, 4),
                "weather": weather.value,
                "temperature_c": round(temp, 2),
                "precipitation_mm": precip,
                "humidity_pct": round(hum, 2),
                "drought_accumulation": new_acc,
                "drought_state": new_drought_state.value,
                "days_no_soaking_rain": days_no_rain,
            },
        )
        if season_changed:
            world.event_log.append(
                tick=world.current_tick,
                event_type="season_changed",
                payload={
                    "from": snap.season.value,
                    "to": season.value,
                    "year": t["year"],
                    "month": t["month"],
                    "day": t["day"],
                },
            )

        # 8. 任务30：水文演化（确定性，随当日降水）
        self._evolve_hydrology(world, cfg, precip)
        # P3a：按最新水位为水源补水（水源库存归环境域，结算在 modules.hydrology，P3c）
        regenerate_water_sources(world)

    # ------------------------------------------------------------------
    def _evolve_hydrology(self, world, cfg, precip_mm: float) -> None:
        """单点水位演化 + 灌溉档派生；仅在数值变化时写事件（004 §2.7）。"""
        evo = cfg.hydrology_evolution
        before = float(world.state.environment.water_level_ratio)
        if precip_mm >= evo.soak_threshold_mm:
            # 有效降水按「到满水位的剩余空间」补水：避免常年封顶 1.0，使水位随旱涝摆动
            after = before + evo.recharge_per_mm * precip_mm * (1.0 - before)
            reason = "rain"
        else:
            after = before - evo.dry_loss_per_day
            reason = "dry"
        after = round(max(0.0, min(1.0, after)), 6)
        prev_gear = world.state.environment.irrigation_gear
        gear = self._classify_irrigation(after, evo.gear_thresholds)
        world.state.environment.water_level_ratio = after
        world.state.environment.irrigation_gear = gear
        if abs(after - before) > 1e-9:
            world.event_log.append(
                tick=world.current_tick,
                event_type="water_level_changed",
                payload={
                    "before": before,
                    "after": after,
                    "precipitation_mm": precip_mm,
                    "reason": reason,
                },
            )
        if gear != prev_gear:
            world.event_log.append(
                tick=world.current_tick,
                event_type="irrigation_gear_changed",
                payload={"from": prev_gear, "to": gear, "water_level_ratio": after},
            )

    @staticmethod
    def _classify_irrigation(level: float, thresholds: dict[str, float]) -> str:
        if level >= thresholds["abundant"]:
            return IrrigationGear.ABUNDANT.value
        if level >= thresholds["low"]:
            return IrrigationGear.LOW.value
        if level >= thresholds["scarce"]:
            return IrrigationGear.SCARCE.value
        return IrrigationGear.DRY.value

    # ------------------------------------------------------------------
    @staticmethod
    def _move_toward(current: float, target: float, max_delta: float) -> float:
        diff = target - current
        if abs(diff) <= max_delta:
            return target
        return current + (max_delta if diff > 0 else -max_delta)

    @staticmethod
    def _classify_drought(acc: float, dp) -> DroughtState:
        if dp.crisis_threshold is not None and acc >= dp.crisis_threshold:
            return DroughtState.CRISIS
        if dp.warning_threshold is not None and acc >= dp.warning_threshold:
            return DroughtState.WARNING
        if dp.watch_threshold is not None and acc >= dp.watch_threshold:
            return DroughtState.WATCH
        return DroughtState.NONE
