"""P1 专项测试：Kernel GridSpace 最小闭环（ADR 011 · 04-grid-space.md 契约）。

验收口径（任务书 §三 P1）：

- 同一坐标与同一 GridSpec 稳定映射到同一 Cell；越界与 Mask 外位置可明确识别；
- 多分辨率 GridSpec（30/250/900 m）不因相同 row/col 误认同一 Cell；
- 河段/田块/聚落节点可引用栅格位置或覆盖范围（GridBinding）；
- 现有移动路径与成本基线不受影响（SpatialIndex 语义不变，Cell 不是图节点）；
- 坐标↔像元互转的边界、轴序与旋转拒绝口径显式可测。
"""
from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from vale.config.schema.spatial_units import DistanceEdge, NodeType, SpatialConfig, SpatialNode
from vale.core.grid_space import CellRef, CellValidity, GridBinding, GridSpace, GridSpec
from vale.domains.society.agents.spatial import SpatialIndex

# P0 冻结的种子网格契约值（world.yaml environment_seed.grid；测试用副本）。
CRS_ALBERS = (
    '+proj=aea +lat_1=30 +lat_2=36 +lat_0=33 +lon_0=108.5 '
    '+datum=WGS84 +units=m +no_defs +type=crs'
)
SPEC_30M = GridSpec(
    grid_id="seed_30m",
    crs=CRS_ALBERS,
    transform=(30.0, 0.0, -404820.0, 0.0, -30.0, 337440.0),
    width=668,
    height=666,
    pixel_size=30.0,
    nodata=-9999.0,
    version="environment-seed-v2/manifest-v3",
)
# 6 列 × 5 行、像元 10 m、原点 (0, 50) 的小网格：mask / 邻域 / 窗口测试用。
SPEC_SMALL = GridSpec(
    grid_id="small",
    crs="local-meters",
    transform=(10.0, 0.0, 0.0, 0.0, -10.0, 50.0),
    width=6,
    height=5,
    pixel_size=10.0,
    nodata=-1.0,
    version="test",
)


# ---------------------------------------------------------------------------
# 一、GridSpec 构造与拒绝（坏定义启动即报错）
# ---------------------------------------------------------------------------


def test_grid_spec_accepts_frozen_seed_grid_and_reports_bounds() -> None:
    spec = SPEC_30M
    assert spec.grid_id == "seed_30m"
    assert spec.crs == CRS_ALBERS          # 只登记不解释
    assert spec.nodata == -9999.0
    assert spec.version == "environment-seed-v2/manifest-v3"
    # x ∈ [-404820, -404820 + 668*30]，y ∈ [337440 - 666*30, 337440]
    assert spec.bounds == (-404820.0, 317460.0, -384780.0, 337440.0)


def test_grid_spec_is_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        SPEC_30M.width = 100  # type: ignore[misc]


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"transform": (30.0, 0.0, -404820.0, 0.0, -30.0)}, "6 元仿射"),
        ({"transform": (30.0, 0.1, -404820.0, 0.0, -30.0, 337440.0)}, "旋转"),
        ({"transform": (30.0, 0.0, -404820.0, -0.1, -30.0, 337440.0)}, "旋转"),
        ({"transform": (30.0, 0.0, -404820.0, 0.0, 30.0, 337440.0)}, "北向上"),
        ({"transform": (-30.0, 0.0, -404820.0, 0.0, -30.0, 337440.0)}, "北向上"),
        ({"pixel_size": 10.0}, "pixel_size.*不一致"),
        ({"width": 0}, "正整数"),
        ({"height": -1}, "正整数"),
        ({"pixel_size": 0.0}, "必须为正"),
        ({"grid_id": ""}, "grid_id"),
        ({"crs": ""}, "crs"),
        ({"version": " "}, "version"),
        ({"nodata": float("nan")}, "有限数值"),
        ({"transform": (30.0, 0.0, float("inf"), 0.0, -30.0, 337440.0)}, "有限数值"),
        ({"transform": (30.0, 0.0, "x", 0.0, -30.0, 337440.0)}, "数值"),
        ({"transform": 123456}, "仿射序列"),
    ],
)
def test_grid_spec_rejects_invalid_definitions(kwargs: dict, match: str) -> None:
    base = {
        "grid_id": "bad", "crs": "crs", "transform": SPEC_30M.transform,
        "width": 668, "height": 666, "pixel_size": 30.0,
        "nodata": -9999.0, "version": "v",
    }
    with pytest.raises(ValueError, match=match):
        GridSpec(**{**base, **kwargs})


def test_cell_ref_rejects_non_negative_integers() -> None:
    with pytest.raises(ValueError, match="row"):
        CellRef(grid_id="g", row=-1, col=0)
    with pytest.raises(ValueError, match="col"):
        CellRef(grid_id="g", row=0, col=-1)
    with pytest.raises(ValueError, match="grid_id"):
        CellRef(grid_id="", row=0, col=0)


# ---------------------------------------------------------------------------
# 二、坐标↔像元互转：稳定、可复现、边界约定明确
# ---------------------------------------------------------------------------


def test_locate_is_stable_and_round_trips() -> None:
    grid = GridSpace(SPEC_30M)
    other = GridSpace(SPEC_30M)
    sampled = [
        (row, col)
        for row in range(0, SPEC_30M.height, 61)
        for col in range(0, SPEC_30M.width, 67)
    ] + [(SPEC_30M.height - 1, SPEC_30M.width - 1), (0, 0)]
    for row, col in sampled:
        cell = CellRef(grid_id="seed_30m", row=row, col=col)
        x, y = grid.cell_center(row, col)
        assert grid.locate(x, y) == cell
        assert grid.locate(x, y) == grid.locate(x, y)      # 重复调用稳定
        assert other.locate(x, y) == cell                  # 同一 GridSpec 重建可复现


def test_locate_boundary_conventions() -> None:
    grid = GridSpace(SPEC_30M)
    gid = "seed_30m"
    x_min, y_min, x_max, y_max = SPEC_30M.bounds
    # 左/上外沿属于像元 0；内部边界归属行/列号较大的一侧。
    assert grid.locate(x_min, y_max) == CellRef(gid, 0, 0)
    assert grid.locate(x_min + 30.0, y_max) == CellRef(gid, 0, 1)
    assert grid.locate(x_min, y_max - 30.0) == CellRef(gid, 1, 0)
    # 右/下外沿越界；右/下外沿内侧一瞬属于最后一行/列。
    assert grid.locate(x_max, y_max) is None
    assert grid.locate(x_min, y_min) is None
    assert grid.locate(x_max - 1e-6, y_min + 1e-6) == CellRef(gid, 665, 667)
    # 网格外坐标返回 None，不静默夹取到边缘像元。
    assert grid.locate(x_min - 30.0, y_max) is None
    assert grid.locate(x_min, y_max + 30.0) is None
    assert grid.locate(x_max + 30.0, y_min - 30.0) is None


def test_cell_center_and_bounds_values() -> None:
    grid = GridSpace(SPEC_30M)
    assert grid.cell_center(0, 0) == (-404805.0, 337425.0)
    assert grid.cell_center(665, 667) == (-384795.0, 317475.0)
    assert grid.cell_bounds(1, 2) == (-404760.0, 337380.0, -404730.0, 337410.0)
    for row, col in [(-1, 0), (0, -1), (666, 0), (0, 668)]:
        with pytest.raises(ValueError, match="越界"):
            grid.cell_center(row, col)
        with pytest.raises(ValueError, match="越界"):
            grid.cell_bounds(row, col)


# ---------------------------------------------------------------------------
# 三、越界与 Mask 外位置可明确识别（三态不混同）
# ---------------------------------------------------------------------------

MASK = {(1, 1), (2, 2), (2, 3)}


def test_validity_distinguishes_mask_from_out_of_bounds() -> None:
    grid = GridSpace(SPEC_SMALL, valid_cells=MASK)
    assert grid.mask_defined
    assert grid.validity(1, 1) is CellValidity.VALID
    assert grid.validity(0, 0) is CellValidity.MASKED
    for row, col in [(-1, 0), (0, -1), (5, 0), (0, 6), (5, 6)]:
        assert grid.validity(row, col) is CellValidity.OUT_OF_BOUNDS
    assert grid.is_valid(CellRef(grid_id="small", row=1, col=1))
    assert not grid.is_valid(CellRef(grid_id="small", row=0, col=0))

    unmasked = GridSpace(SPEC_SMALL)
    assert not unmasked.mask_defined
    assert unmasked.validity(4, 5) is CellValidity.VALID


def test_mask_construction_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="越界像元"):
        GridSpace(SPEC_SMALL, valid_cells=[(0, 0), (6, 0)])
    for bad in [(1,), (1, 2, 3), ("a", 1), (True, 1)]:
        with pytest.raises(ValueError, match="二元组"):
            GridSpace(SPEC_SMALL, valid_cells=[bad])


def test_locate_identifies_masked_positions() -> None:
    grid = GridSpace(SPEC_SMALL, valid_cells=MASK)
    masked = grid.locate(5.0, 45.0)      # (row 0, col 0)：界内但 Mask 外
    assert masked is not None
    assert grid.validity(masked.row, masked.col) is CellValidity.MASKED
    valid = grid.locate(15.0, 35.0)      # (row 1, col 1)：Mask 内
    assert valid == CellRef(grid_id="small", row=1, col=1)
    assert grid.validity(valid.row, valid.col) is CellValidity.VALID
    assert grid.locate(-1.0, 25.0) is None   # 越界
    with pytest.raises(ValueError, match="不符"):
        grid.is_valid(CellRef(grid_id="seed_30m", row=1, col=1))


# ---------------------------------------------------------------------------
# 四、邻域与窗口查询（几何邻近 ≠ 可通行）
# ---------------------------------------------------------------------------


def test_neighbor_geometry_and_order() -> None:
    grid = GridSpace(SPEC_SMALL)
    gid = "small"
    interior = CellRef(grid_id=gid, row=2, col=3)
    assert grid.neighbors(interior, connectivity=8) == [
        CellRef(gid, 1, 2), CellRef(gid, 1, 3), CellRef(gid, 1, 4),
        CellRef(gid, 2, 2), CellRef(gid, 2, 4),
        CellRef(gid, 3, 2), CellRef(gid, 3, 3), CellRef(gid, 3, 4),
    ]
    assert grid.neighbors(interior, connectivity=4) == [
        CellRef(gid, 1, 3), CellRef(gid, 2, 2), CellRef(gid, 2, 4), CellRef(gid, 3, 3),
    ]
    corner = CellRef(grid_id=gid, row=0, col=0)
    assert grid.neighbors(corner, connectivity=8) == [
        CellRef(gid, 0, 1), CellRef(gid, 1, 0), CellRef(gid, 1, 1),
    ]
    assert grid.neighbors(corner, connectivity=4) == [CellRef(gid, 0, 1), CellRef(gid, 1, 0)]
    assert grid.neighbors(CellRef(gid, 4, 5), connectivity=8) == [
        CellRef(gid, 3, 4), CellRef(gid, 3, 5), CellRef(gid, 4, 4),
    ]
    with pytest.raises(ValueError, match="connectivity"):
        grid.neighbors(interior, connectivity=5)
    with pytest.raises(ValueError, match="越界"):
        grid.neighbors(CellRef(gid, 9, 0))
    with pytest.raises(ValueError, match="不符"):
        grid.neighbors(CellRef(grid_id="seed_30m", row=1, col=1))
    # Mask 外像元照常是几何邻居（空间邻近是几何事实，不代表可通行/有效）。
    masked_grid = GridSpace(SPEC_SMALL, valid_cells=MASK)
    neighbors = masked_grid.neighbors(CellRef(gid, 2, 2), connectivity=4)
    assert CellRef(gid, 1, 2) in neighbors
    assert masked_grid.validity(1, 2) is CellValidity.MASKED


def test_window_queries() -> None:
    grid = GridSpace(SPEC_SMALL)
    gid = "small"
    center = CellRef(gid, 2, 3)
    assert grid.window(center, radius=0) == [center]
    assert grid.window(center, radius=1) == [
        CellRef(gid, 1, 2), CellRef(gid, 1, 3), CellRef(gid, 1, 4),
        CellRef(gid, 2, 2), CellRef(gid, 2, 3), CellRef(gid, 2, 4),
        CellRef(gid, 3, 2), CellRef(gid, 3, 3), CellRef(gid, 3, 4),
    ]
    # 角落窗口按网格边界裁剪（集合枚举语义，非位置夹取）。
    assert grid.window(CellRef(gid, 0, 0), radius=1) == [
        CellRef(gid, 0, 0), CellRef(gid, 0, 1),
        CellRef(gid, 1, 0), CellRef(gid, 1, 1),
    ]
    whole = grid.window(CellRef(gid, 0, 0), radius=99)
    assert len(whole) == SPEC_SMALL.width * SPEC_SMALL.height
    assert whole == [
        CellRef(gid, row, col) for row in range(SPEC_SMALL.height)
        for col in range(SPEC_SMALL.width)
    ]
    assert grid.window(center, radius=1) == grid.window(center, radius=1)  # 确定性
    with pytest.raises(ValueError, match="radius"):
        grid.window(center, radius=-1)
    with pytest.raises(ValueError, match="radius"):
        grid.window(center, radius=1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="越界"):
        grid.window(CellRef(gid, 5, 0), radius=1)
    with pytest.raises(ValueError, match="不符"):
        grid.window(CellRef(grid_id="seed_30m", row=1, col=1), radius=1)


# ---------------------------------------------------------------------------
# 五、多分辨率网格身份独立（30/250/900 m 专项）
# ---------------------------------------------------------------------------


def _spec(grid_id: str, pixel: float, width: int, height: int) -> GridSpec:
    return GridSpec(
        grid_id=grid_id,
        crs=CRS_ALBERS,
        transform=(pixel, 0.0, -404820.0, 0.0, -pixel, 337440.0),
        width=width,
        height=height,
        pixel_size=pixel,
        nodata=-9999.0,
        version="environment-seed-v2/manifest-v3",
    )


def test_multi_resolution_cells_have_independent_identity() -> None:
    # 同一地区三种分辨率覆盖同一范围：不同 GridSpec、不同 grid_id。
    specs = {
        "seed_30m": _spec("seed_30m", 30.0, 668, 666),
        "seed_250m": _spec("seed_250m", 250.0, 81, 80),
        "seed_900m": _spec("seed_900m", 900.0, 23, 23),
    }
    grids = {gid: GridSpace(spec) for gid, spec in specs.items()}
    top_left = [CellRef(gid, 0, 0) for gid in specs]
    # 相同 row/col 不构成同一 Cell：身份 = (grid_id, row, col)。
    assert len(set(top_left)) == 3
    assert top_left[0] != top_left[1] and top_left[1] != top_left[2]
    assert CellRef("seed_30m", 0, 0) not in {top_left[1], top_left[2]}
    # 同一地理点在各网格各自定位、各自回环，行列号各不相同。
    point = (-400000.0, 330000.0)
    expected = {
        "seed_30m": CellRef("seed_30m", 248, 160),
        "seed_250m": CellRef("seed_250m", 29, 19),
        "seed_900m": CellRef("seed_900m", 8, 5),
    }
    for gid, grid in grids.items():
        cell = grid.locate(*point)
        assert cell == expected[gid]
        assert grid.locate(*grid.cell_center(cell.row, cell.col)) == cell
    # 跨网格 CellRef 显式拒绝，不误判为越界或有效。
    with pytest.raises(ValueError, match="不符"):
        grids["seed_30m"].is_valid(CellRef("seed_250m", 29, 19))
    binding = GridBinding(grids["seed_30m"])
    with pytest.raises(ValueError, match="不符"):
        binding.bind("unit", [CellRef("seed_250m", 29, 19)])


# ---------------------------------------------------------------------------
# 六、空间单元 ↔ Cell 显式映射（与 SpatialIndex 协作，不复制移动图）
# ---------------------------------------------------------------------------


def _spatial_config() -> SpatialConfig:
    return SpatialConfig(
        nodes=[
            SpatialNode(id="well", name="水井", type=NodeType.RESOURCE,
                        travel_cost_from_well_tu=0.0),
            SpatialNode(id="shrine", name="祠堂", type=NodeType.SOCIAL,
                        travel_cost_from_well_tu=0.5),
            SpatialNode(id="east_field", name="东片田", type=NodeType.FIELD,
                        travel_cost_from_well_tu=1.5),
            SpatialNode(id="river_town", name="翠溪镇前段", type=NodeType.WATER,
                        travel_cost_from_well_tu=1.0),
        ],
        distance_edges=[
            DistanceEdge(from_id="well", to_id="shrine", one_way_tu=0.5),
            DistanceEdge(from_id="well", to_id="east_field", one_way_tu=1.5),
            DistanceEdge(from_id="well", to_id="river_town", one_way_tu=1.0),
        ],
    )


def test_spatial_units_bind_to_cells_without_touching_travel_graph() -> None:
    config = _spatial_config()
    index = SpatialIndex(config)
    grid = GridSpace(SPEC_SMALL)
    binding = GridBinding(grid)
    gid = "small"
    # 河段 → 覆盖范围；田块 → 覆盖范围；聚落节点（祠堂/水井）→ 单像元引用。
    binding.bind("river_town", [CellRef(gid, 2, 2), CellRef(gid, 2, 3), CellRef(gid, 3, 2)])
    binding.bind("east_field", [CellRef(gid, 3, 4), CellRef(gid, 3, 5)])
    binding.bind("well", [CellRef(gid, 1, 1)])
    binding.bind("shrine", [CellRef(gid, 1, 2)])

    assert binding.unit_ids == {"river_town", "east_field", "well", "shrine"}
    assert binding.grid is grid
    assert binding.cells_of("river_town") == {
        CellRef(gid, 2, 2), CellRef(gid, 2, 3), CellRef(gid, 3, 2),
    }
    assert binding.units_at(CellRef(gid, 2, 2)) == {"river_town"}
    assert binding.units_at(CellRef(gid, 1, 1)) == {"well"}
    assert binding.units_at(CellRef(gid, 0, 0)) == frozenset()  # 未覆盖像元
    assert binding.cells_of("ghost") == frozenset()             # 未绑定单元

    # DistanceEdge / Dijkstra 语义不变：移动耗时仍只由节点图给出。
    assert index.travel_tu("well", "well") == 0.0
    assert index.travel_tu("well", "east_field") == 1.5
    assert index.travel_tu("well", "river_town") == 1.0
    assert index.travel_tu("east_field", "river_town") == 2.5
    assert index.travel_tu("shrine", "east_field") == 2.0
    # Cell 不是 SpatialNode：像元不进入移动图，按节点 id 查询不可达。
    assert math.isinf(index.travel_tu("small:2:2", "well"))
    assert math.isinf(index.travel_tu("seed_30m:0:0", "shrine"))
    # 绑定不产生节点或第二套图：节点清单仍是配置中的 4 个。
    assert len(config.nodes) == 4


def test_binding_rejects_invalid_input_atomically() -> None:
    grid = GridSpace(SPEC_SMALL, valid_cells=MASK)
    binding = GridBinding(grid)
    gid = "small"
    double = GridBinding(GridSpace(SPEC_SMALL))
    double.bind("river_town", [CellRef(gid, 1, 1)])
    with pytest.raises(ValueError, match="已绑定"):
        double.bind("river_town", [CellRef(gid, 2, 2)])
    with pytest.raises(ValueError, match="不能为空"):
        binding.bind("empty_unit", [])
    with pytest.raises(ValueError, match="unit_id"):
        binding.bind("  ", [CellRef(gid, 1, 1)])
    with pytest.raises(ValueError, match="越界像元"):
        binding.bind("far_unit", [CellRef(gid, 1, 1), CellRef(gid, 9, 9)])
    with pytest.raises(ValueError, match="CellRef"):
        binding.bind("weird_unit", [(1, 1)])  # type: ignore[list-item]
    # 原子性：失败绑定不留下半更新状态。
    assert binding.cells_of("far_unit") == frozenset()
    assert binding.unit_ids == frozenset()


def test_queries_are_reproducible_across_instances() -> None:
    cells = [CellRef("small", 2, 2)]
    first = GridBinding(GridSpace(SPEC_SMALL, valid_cells=MASK))
    second = GridBinding(GridSpace(SPEC_SMALL, valid_cells=MASK))
    first.bind("river_town", cells)
    second.bind("river_town", cells)
    point = (15.0, 35.0)
    assert first.grid.locate(*point) == second.grid.locate(*point)
    assert first.cells_of("river_town") == second.cells_of("river_town")
    assert first.units_at(CellRef("small", 2, 2)) == second.units_at(CellRef("small", 2, 2))
