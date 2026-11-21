"""溪谷镇世界生成·自然段（P4，ADR 009 §3.1/§3.4）。

负责地理骨架：地形栅格、静态植被与栖息地描述、生态资源池目录。
产出 ``NatureResult``（自然环境公开结果），聚落段（settlement.py）只读它，
不得反向覆盖自然地理骨架。资源池参数的唯一真相源是本段产出的池目录
（2026-11-21 P4 裁决）：节点 attributes 不再携带 ``resource_*`` 副本，
运行时由领域所有者从 ``LoadedConfig.resources`` 引导建池。

静态植被/栖息地描述是纯数据表达（无行为）；动态生长、繁殖、退化留给
植被系统与 P5（2026-11-21 裁决：P4 只做结构迁移补齐数据表达）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from vale.core.state import ResourcePoolSpec


@dataclass(frozen=True)
class TerrainCell:
    x: int
    y: int
    terrain: str
    elevation: float
    slope: float
    flood_risk: float
    soil_fertility: float


@dataclass(frozen=True)
class VegetationProfile:
    """地形带的静态植被与栖息地描述（P4；无行为，不进运行时状态）。"""

    zone: str
    vegetation_type: str
    canopy_cover: float          # 冠层覆盖度 0–1
    habitat_condition: str       # good / moderate / poor / sealed
    habitat_notes: str


# 静态目录：地形带 -> 植被与栖息地描述。P5 种群系统按栖息地条件决定物种
# 分布（ADR 009 §2.2B）；本表在 P4 仅作为生成结果的公开数据。[调参] 来源：
# 与 worldgen.xigu._terrain_at 的地形带划分一一对应，数值为描述性初值。
VEGETATION_PROFILES: dict[str, VegetationProfile] = {
    zone: VegetationProfile(zone, *values) for zone, values in {
        "river_bank": ("河谷柳灌丛带", .35, "moderate", "水陆交错带，水鸟与小型水栖动物觅食地"),
        "irrigated_lowland": ("开垦低地农田植被", .15, "poor", "人工耕作覆盖，缺乏连片自然植被"),
        "settlement": ("村落杂木与宅旁树", .10, "poor", "人居密集，仅零星树木"),
        "settlement_edge": ("村落边缘疏草带", .20, "poor", "半扰动边缘，小型动物途经"),
        "foothill": ("山脚次生灌草与疏林", .45, "moderate", "樵采扰动带，灌木与散生乔木"),
        "shallow_forest": ("浅山针阔混交林", .75, "good", "连片林冠，野兽栖息与迁徙通道"),
        "deep_mountain": ("深山原始针叶林（封闭）", .90, "sealed", "禁区：无人为扰动，大型兽核心栖息地"),
    }.items()
}


@dataclass
class NatureResult:
    """自然环境公开结果：聚落段只读，不覆盖。"""

    terrain: list[TerrainCell]
    resources: dict[str, ResourcePoolSpec]
    vegetation: dict[str, VegetationProfile] = field(default_factory=dict)


def terrain_at(x: float, y: float) -> tuple[str, float, float, float, float]:
    """(terrain, elevation, slope, flood_risk, soil_fertility) at grid coordinates."""
    if x < 9:
        return "river_bank", 1 + abs(y) * .015, .08, .78, .72
    if x < 18.5:
        return "irrigated_lowland", 1.5 + abs(y) * .02, .05, .66, .98
    if x < 30:
        return ("settlement_edge" if abs(y) > 13 else "settlement",
                3.0, .12 if abs(y) > 13 else .06, .22 if abs(y) > 13 else .12, .76)
    if x < 38:
        return "foothill", 5 + (x - 23) * .7, .24, .08, .66
    if x < 50:
        return "shallow_forest", 12 + (x - 31) * 1.4, .42, .03, .48
    return "deep_mountain", 30 + (x - 43) * 2, .72, .01, .28


def make_terrain(config) -> list[TerrainCell]:
    cells = []
    for x in range(0, config.map_width, 2):
        for y in range(-config.map_height // 2, config.map_height // 2, 2):
            terrain, elevation, slope, flood, fertility = terrain_at(x, y)
            cells.append(TerrainCell(x, y, terrain, round(elevation, 3), round(slope, 3),
                                     round(flood, 3), round(fertility, 3)))
    return cells


def make_resource_catalog() -> dict[str, ResourcePoolSpec]:
    """生态资源池目录（键 = 资源节点 id）。

    fish / game 类型池归动物域（modules.wildlife 拥有并结算）；其余归环境域
    （modules.ecology）。deep_mountain 为受限封禁池。
    """
    return {
        "river_town": ResourcePoolSpec(
            resource_id="river_town", resource_type="fish",
            current_stock=90, max_stock=140,
            regeneration_per_tick=5, extraction_limit_per_tick=12,
            seasonal_weights={"spring": .8, "summer": 1, "autumn": 1.2, "winter": .35}),
        "foothill_woodland": ResourcePoolSpec(
            resource_id="foothill_woodland", resource_type="firewood",
            current_stock=120, max_stock=180,
            regeneration_per_tick=3, extraction_limit_per_tick=8),
        "low_mountain": ResourcePoolSpec(
            resource_id="low_mountain", resource_type="herbs_and_hardwood",
            current_stock=70, max_stock=100,
            regeneration_per_tick=1.2, extraction_limit_per_tick=4,
            seasonal_weights={"spring": 1.4, "summer": 1.2, "autumn": .8, "winter": .3}),
        "game_trail": ResourcePoolSpec(
            resource_id="game_trail", resource_type="game",
            current_stock=45, max_stock=70,
            regeneration_per_tick=1.8, extraction_limit_per_tick=5,
            seasonal_weights={"spring": .7, "summer": .9, "autumn": 1.3, "winter": .8}),
        "deep_mountain": ResourcePoolSpec(
            resource_id="deep_mountain", resource_type="rare_medicinal_and_event",
            current_stock=0, max_stock=0,
            regeneration_per_tick=0, extraction_limit_per_tick=0,
            restricted=True),
    }


def generate_nature(config) -> NatureResult:
    """自然段入口：地形栅格 + 资源池目录 + 静态植被/栖息地描述。"""
    return NatureResult(
        terrain=make_terrain(config),
        resources=make_resource_catalog(),
        vegetation=dict(VEGETATION_PROFILES),
    )


def regenerate_resource(pool: ResourcePoolSpec, season: str, ticks: int = 1) -> float:
    """Capped seasonal regeneration; returns the amount added."""
    if pool.restricted or ticks <= 0:
        return 0.0
    amount = min(max(0.0, pool.max_stock - pool.current_stock),
                 max(0.0, pool.regeneration_per_tick * pool.seasonal_weights.get(season, 1.0) * ticks))
    pool.current_stock = round(pool.current_stock + amount, 6)
    return amount


def harvest_resource(pool: ResourcePoolSpec, requested: float) -> float:
    """Enforce per-tick extraction limit and stock conservation."""
    if pool.restricted or requested <= 0:
        return 0.0
    amount = min(requested, pool.extraction_limit_per_tick, pool.current_stock)
    pool.current_stock = round(max(0.0, pool.current_stock - amount), 6)
    if amount >= pool.extraction_limit_per_tick > 0:
        pool.degradation = min(1.0, pool.degradation + amount / max(pool.max_stock, 1.0) * 0.01)
    return amount
