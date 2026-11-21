"""时间刻度换算（里程碑 3：时间现实化）。

约定（用户裁决）：
  1 年 = 360 天；1 季 = 3 个月 = 90 天；1 月 = 30 天；1 节气 = 15 天（全年 24 节气）。

本模块只提供纯函数：把绝对 tick 换算成 年/月/日/节气/年内日序，以及由月份反查季节。
它是「日历」的单一真相源——气候模块的季节与进度也从这里派生，保证季节与日期永不漂移。

季节与月份的对应（按节气历）：
  春：1-3 月（立春起）  夏：4-6 月  秋：7-9 月  冬：10-12 月
"""
from __future__ import annotations

from vale.config.schema.natural_params import Season

# 时间常数
DAYS_PER_MONTH = 30
MONTHS_PER_YEAR = 12
DAYS_PER_YEAR = DAYS_PER_MONTH * MONTHS_PER_YEAR  # 360
DAYS_PER_SOLAR_TERM = 15
SOLAR_TERMS_PER_YEAR = DAYS_PER_YEAR // DAYS_PER_SOLAR_TERM  # 24

# 24 节气，按年内日序排列：index = (day_of_year - 1) // 15
SOLAR_TERMS: list[str] = [
    # 春（1-3 月）
    "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
    # 夏（4-6 月）
    "立夏", "小满", "芒种", "夏至", "小暑", "大暑",
    # 秋（7-9 月）
    "立秋", "处暑", "白露", "秋分", "寒露", "霜降",
    # 冬（10-12 月）
    "立冬", "小雪", "大雪", "冬至", "小寒", "大寒",
]

# 各季首日的年内日序（1-based）
_SEASON_FIRST_DAY: dict[Season, int] = {
    Season.SPRING: 1,
    Season.SUMMER: 91,
    Season.AUTUMN: 181,
    Season.WINTER: 271,
}


def season_for_month(month: int) -> Season:
    """月份（1-12）→ 季节。月份越界时按模 12 归一。"""
    m = ((month - 1) % MONTHS_PER_YEAR) + 1
    if m <= 3:
        return Season.SPRING
    if m <= 6:
        return Season.SUMMER
    if m <= 9:
        return Season.AUTUMN
    return Season.WINTER


def start_day_of_year(season: Season, season_progress: float, season_length: int = 90) -> int:
    """把开局 (season, season_progress) 换算成 1-based 年内日序。

    season_progress=0.0 → 该季第一天；progress 越大越靠近季末。
    """
    base = _SEASON_FIRST_DAY[season]
    days_into = int(season_progress * season_length)  # 0 .. season_length-1
    return base + days_into


def calendar_from_tick(
    tick: int,
    start_tick: int,
    start_day_of_year_1based: int,
    start_year: int = 1,
) -> tuple[int, int, int, str, int]:
    """绝对 tick → (year, month, day, solar_term, day_of_year)。

    - tick == start_tick 对应开局那天（start_day_of_year_1based / start_year）。
    - day_of_year 为 1-based（1..360），跨年自动回到 1 并进位 year。
    """
    elapsed = tick - start_tick  # 自开局以来经过的天数（0-based）
    total_0based = (start_day_of_year_1based - 1) + elapsed
    day_of_year = (total_0based % DAYS_PER_YEAR) + 1  # 1..360
    year = start_year + (total_0based // DAYS_PER_YEAR)
    month = ((day_of_year - 1) // DAYS_PER_MONTH) + 1  # 1..12
    day = ((day_of_year - 1) % DAYS_PER_MONTH) + 1  # 1..30
    solar_term = SOLAR_TERMS[(day_of_year - 1) // DAYS_PER_SOLAR_TERM]
    return year, month, day, solar_term, day_of_year


def season_progress_from_day_of_year(day_of_year: int, season_length: int = 90) -> float:
    """由年内日序反推当前季节进度（0.0 = 季首日，<1.0），与日历保持一致。"""
    season_index = (day_of_year - 1) // season_length  # 0..3
    days_into = (day_of_year - 1) - season_index * season_length  # 0..89
    return days_into / season_length
