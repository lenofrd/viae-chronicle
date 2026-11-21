"""里程碑 3：日历换算纯函数测试。

验证年/月/日/节气由 tick 正确换算，且月份与季节的对应满足
「秋收只能在秋季（第 7-9 月）」的约束。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vale.config.schema.natural_params import Season  # noqa: E402

from vale.core import calendar  # noqa: E402


def test_solar_terms_count_and_order():
    assert len(calendar.SOLAR_TERMS) == 24
    assert calendar.SOLAR_TERMS[0] == "立春"
    assert calendar.SOLAR_TERMS[-1] == "大寒"
    # 每季 6 个节气
    assert calendar.SOLAR_TERMS[6] == "立夏"
    assert calendar.SOLAR_TERMS[12] == "立秋"
    assert calendar.SOLAR_TERMS[18] == "立冬"


def test_calendar_from_tick_at_start_is_lichun():
    # tick == start_tick，开局 progress=0.0 → 第1年1月1日 立春
    y, m, d, st, doy = calendar.calendar_from_tick(tick=1, start_tick=1, start_day_of_year_1based=1)
    assert (y, m, d, doy) == (1, 1, 1, 1)
    assert st == "立春"


def test_calendar_rolls_month_and_solar_term():
    # 每节气 15 天：第 16 天进入「雨水」，第 31 天进入 2 月「惊蛰」
    _, m1, d16, st16, _ = calendar.calendar_from_tick(tick=16, start_tick=1, start_day_of_year_1based=1)
    assert st16 == "雨水"
    _, m31, _, st31, _ = calendar.calendar_from_tick(tick=31, start_tick=1, start_day_of_year_1based=1)
    assert m31 == 2
    assert st31 == "惊蛰"


def test_calendar_season_boundaries_by_day_of_year():
    # 春季 day 1-90，夏季 91-180，秋季 181-270，冬季 271-360
    cases = {
        1: ("立春", Season.SPRING),
        90: ("谷雨", Season.SPRING),
        91: ("立夏", Season.SUMMER),
        180: ("大暑", Season.SUMMER),
        181: ("立秋", Season.AUTUMN),
        270: ("霜降", Season.AUTUMN),
        271: ("立冬", Season.WINTER),
        360: ("大寒", Season.WINTER),
    }
    for doy, (term, season) in cases.items():
        y, m, d, st, out_doy = calendar.calendar_from_tick(
            tick=doy, start_tick=1, start_day_of_year_1based=1
        )
        assert out_doy == doy
        assert st == term, f"day_of_year {doy}: expected {term}, got {st}"
        assert calendar.season_for_month(m) == season


def test_calendar_year_rollover():
    # 第 361 天 → 第 2 年 1 月 1 日 立春
    y, m, d, st, doy = calendar.calendar_from_tick(tick=361, start_tick=1, start_day_of_year_1based=1)
    assert y == 2
    assert (m, d, doy) == (1, 1, 1)
    assert st == "立春"


def test_season_for_month_covers_autumn_months_7_to_9():
    """需求 2.3：秋收只能在秋季（第 7-9 月）。"""
    for m in (7, 8, 9):
        assert calendar.season_for_month(m) == Season.AUTUMN, f"month {m} should be autumn"
    for m in (1, 2, 3):
        assert calendar.season_for_month(m) == Season.SPRING
    for m in (4, 5, 6):
        assert calendar.season_for_month(m) == Season.SUMMER
    for m in (10, 11, 12):
        assert calendar.season_for_month(m) == Season.WINTER


def test_start_day_of_year_from_progress():
    # spring progress=0.0 → 第 1 天；progress=0.9 → 第 82 天（已过 81 天）
    assert calendar.start_day_of_year(Season.SPRING, 0.0) == 1
    assert calendar.start_day_of_year(Season.SPRING, 0.9) == 82
    # summer 首日 = 91
    assert calendar.start_day_of_year(Season.SUMMER, 0.0) == 91
    assert calendar.start_day_of_year(Season.AUTUMN, 0.0) == 181
    assert calendar.start_day_of_year(Season.WINTER, 0.0) == 271


def test_season_progress_from_day_of_year_consistent():
    # 季首日 progress=0.0；季末 progress 接近 1 但 <1
    assert calendar.season_progress_from_day_of_year(1) == 0.0
    assert calendar.season_progress_from_day_of_year(91) == 0.0  # 夏首日
    assert calendar.season_progress_from_day_of_year(180) == pytest.approx(89 / 90)
    assert calendar.season_progress_from_day_of_year(90) < 1.0
