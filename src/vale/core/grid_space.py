"""Kernel 栅格空间（GridSpace）：规则网格的定位、查询与单元映射机制。

ADR 011 · P1 最小闭环，契约见
docs/design/systems/kernel/spatial-skeleton/04-grid-space.md。

域中立边界：本模块只管理 GridSpec、CellRef、坐标变换、邻域与单元映射；
不读取领域语义、不访问数据文件、不使用环境变量、不解释 NoData 的领域
数值含义（环境栅格值归 Environment，动物状态归 Wildlife）。

与离散拓扑空间的关系（02-distance-and-time.md §8）：

- DistanceEdge / SpatialIndex 继续独占「可通行关系 + 移动耗时」语义；
  栅格邻接只表示空间邻近，不表示可通行，不能由 Cell 直线距离推断可达。
- Cell 不是 SpatialNode：``GridBinding`` 只登记空间单元与 Cell 的显式
  映射，不为像元创建节点/实体，不复制第二套移动图。

坐标约定（仿射系数序与冻结的 ``world.yaml`` seed 网格契约一致）：

- ``transform`` 为仿射系数 ``(a, b, c, d, e, f)``：像元 (row, col) 的
  坐标满足 ``x = a*col + b*row + c``、``y = d*col + e*row + f``；
  ``(c, f)`` 是像元 (0, 0) 的左上角（地图坐标），不是像元中心。
- 北向上（north-up）：要求 ``a > 0、e < 0``；行 0 为最北行，列 0 为
  最西列；地图单位与轴序（东向 x、北向 y）由 ``crs`` 字符串声明。
- 旋转项 ``b、d`` 首版**显式拒绝**（契约 §3 允许「完整仿射逆变换」或
  「明确拒绝」二选一）；非北向上网格同样显式拒绝，不在 Kernel 换算。
- 像元边界半开约定：列 col 覆盖 ``x ∈ [c + a*col, c + a*(col+1))``、
  行 row 覆盖 ``y ∈ (f + e*(row+1), f + e*row]``，即坐标恰落内部边界
  时归属行/列号较大的一侧；网格外沿（x ≥ x_max 或 y ≤ y_min）越界。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class CellValidity(str, Enum):
    """像元有效性三态：越界、Mask 外与有效必须可明确区分，不静默夹取。"""

    VALID = "valid"                    # 网格界内，且（若定义了 Mask）在 Mask 内
    MASKED = "masked"                  # 网格界内但在 Mask 外
    OUT_OF_BOUNDS = "out_of_bounds"    # 网格范围之外


def _as_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} 必须是数值，实际为 {value!r}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} 必须是有限数值，实际为 {value!r}")
    return result


def _require_non_empty_str(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空字符串，实际为 {value!r}")


def _require_positive_int(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} 必须是正整数，实际为 {value!r}")


@dataclass(frozen=True)
class GridSpec:
    """单个规则网格的身份与几何契约（04-grid-space.md §2）。

    网格身份与数据集身份不同：同一 GridSpec 可被多个数据资产引用；
    同一地区不同分辨率（如 30/250/900 m）是不同 GridSpec（grid_id 不同，
    CellRef 身份随之独立）。``crs`` / ``nodata`` / ``version`` 只登记
    不解释：Kernel 不解析 CRS，不把 NoData 当作任何领域数值。
    """

    grid_id: str
    crs: str
    transform: tuple[float, ...]
    width: int
    height: int
    pixel_size: float
    nodata: float
    version: str

    def __post_init__(self) -> None:
        _require_non_empty_str(self.grid_id, "GridSpec.grid_id")
        _require_non_empty_str(self.crs, "GridSpec.crs")
        _require_non_empty_str(self.version, "GridSpec.version")
        _require_positive_int(self.width, "GridSpec.width")
        _require_positive_int(self.height, "GridSpec.height")
        if not isinstance(self.transform, (tuple, list)):
            raise ValueError(
                f"GridSpec.transform 必须是 6 元仿射序列 [a, b, c, d, e, f]，"
                f"实际为 {self.transform!r}"
            )
        if len(self.transform) != 6:
            raise ValueError(
                f"GridSpec.transform 必须是 6 元仿射 [a, b, c, d, e, f]，"
                f"实际 {len(self.transform)} 元：{self.transform!r}"
            )
        coeffs = tuple(_as_float(v, "GridSpec.transform 系数") for v in self.transform)
        pixel = _as_float(self.pixel_size, "GridSpec.pixel_size")
        nodata = _as_float(self.nodata, "GridSpec.nodata")
        if pixel <= 0:
            raise ValueError(f"GridSpec.pixel_size 必须为正（地图单位），实际为 {pixel!r}")
        a, b, _c, d, e, _f = coeffs
        if b != 0.0 or d != 0.0:
            raise ValueError(
                f"GridSpec.transform 含非零旋转项（b={b!r}, d={d!r}）：旋转网格"
                "首版显式不支持（04-grid-space.md §3），需要完整仿射逆变换时另行裁决"
            )
        if a <= 0 or e >= 0:
            raise ValueError(
                f"GridSpec.transform 必须北向上（a>0 且 e<0），实际 a={a!r}、e={e!r}；"
                "非北向上网格需在数据入栈侧翻转，不在 Kernel 换算"
            )
        if not (
            math.isclose(a, pixel, rel_tol=1e-9, abs_tol=1e-12)
            and math.isclose(-e, pixel, rel_tol=1e-9, abs_tol=1e-12)
        ):
            raise ValueError(
                f"GridSpec.pixel_size={pixel!r} 与 transform 像元尺寸不一致"
                f"（a={a!r}、-e={-e!r}）：首版假定方形像元，非方形需另行裁决"
            )
        object.__setattr__(self, "transform", coeffs)
        object.__setattr__(self, "pixel_size", pixel)
        object.__setattr__(self, "nodata", nodata)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """网格外接范围 ``(x_min, y_min, x_max, y_max)``；y_max 为行 0 上边界。"""
        a, _b, c, _d, e, f = self.transform
        return (c, f + e * self.height, c + a * self.width, f)


@dataclass(frozen=True)
class CellRef:
    """栅格像元的稳定位置引用（04-grid-space.md §3）。

    身份 = ``(grid_id, row, col)``：不同 GridSpec 即使 row/col 相同也是
    不同 Cell。CellRef 只承载位置，不承载地形、土壤、植被或动物状态；
    界内与否由所属 GridSpace 判定（本类只保证行列非负）。
    """

    grid_id: str
    row: int
    col: int

    def __post_init__(self) -> None:
        _require_non_empty_str(self.grid_id, "CellRef.grid_id")
        for name in ("row", "col"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"CellRef.{name} 行列从零起算，必须是非负整数，实际为 {value!r}"
                )


class GridSpace:
    """单个 GridSpec 的定位与查询面（04-grid-space.md §3–§4）。

    - ``locate`` 对网格外坐标返回 ``None``（明确越界，不静默夹取）；
      界内但 Mask 外的位置照常返回 CellRef，由 ``validity`` 区分
      ``MASKED`` 与 ``OUT_OF_BOUNDS``。
    - ``valid_cells=None`` 表示未定义 Mask：一切界内像元按 ``VALID``
      对待（与「全网格有效」语义不同，是否定义 Mask 由调用方保证口径）。
    - 邻域 / 窗口只表达**空间邻近**，不代表可通行；结果按 (row, col)
      行主序排序，确定性可复现。
    """

    _NEIGHBOR_OFFSETS_4 = ((-1, 0), (0, -1), (0, 1), (1, 0))
    _NEIGHBOR_OFFSETS_8 = (
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1), (0, 1),
        (1, -1), (1, 0), (1, 1),
    )

    def __init__(
        self, spec: GridSpec, valid_cells: Iterable[tuple[int, int]] | None = None
    ) -> None:
        self._spec = spec
        self._mask: frozenset[tuple[int, int]] | None = None
        if valid_cells is None:
            return
        cells: set[tuple[int, int]] = set()
        for item in valid_cells:
            try:
                row, col = item  # type: ignore[misc]
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"valid_cells 的元素必须是 (row, col) 二元组，实际为 {item!r}"
                ) from exc
            if (
                isinstance(row, bool) or isinstance(col, bool)
                or not isinstance(row, int) or not isinstance(col, int)
            ):
                raise ValueError(
                    f"valid_cells 的元素必须是 (row, col) 整数二元组，实际为 {(row, col)!r}"
                )
            cells.add((row, col))
        out_of_bounds = sorted(
            (row, col)
            for row, col in cells
            if not (0 <= row < spec.height and 0 <= col < spec.width)
        )
        if out_of_bounds:
            raise ValueError(
                f"valid_cells 含越界像元（网格 {spec.grid_id} 为 "
                f"{spec.height} 行 × {spec.width} 列）：{out_of_bounds[:5]}"
                + ("…" if len(out_of_bounds) > 5 else "")
            )
        self._mask = frozenset(cells)

    @property
    def spec(self) -> GridSpec:
        return self._spec

    @property
    def grid_id(self) -> str:
        return self._spec.grid_id

    @property
    def mask_defined(self) -> bool:
        return self._mask is not None

    def _cell_grid_or_raise(self, cell: CellRef) -> None:
        if cell.grid_id != self._spec.grid_id:
            raise ValueError(
                f"CellRef 属于网格 {cell.grid_id!r}，与本网格 {self._spec.grid_id!r} 不符："
                "不同 GridSpec 的 Cell 不可混用（多分辨率网格身份独立）"
            )

    def _indices_or_raise(self, row: int, col: int, what: str) -> None:
        if 0 <= row < self._spec.height and 0 <= col < self._spec.width:
            return
        raise ValueError(
            f"{what} 越界：(row={row}, col={col}) 不在网格 {self._spec.grid_id}"
            f"（{self._spec.height} 行 × {self._spec.width} 列）内；不静默夹取"
        )

    def locate(self, x: float, y: float) -> CellRef | None:
        """单点坐标定位（04-grid-space.md §4.1）；网格外返回 ``None``。

        同一 GridSpec 下同一坐标的映射确定且可复现；边界归属约定见
        模块 docstring（内部边界归行/列号较大的一侧，网格外沿越界）。
        """
        spec = self._spec
        a, _b, c, _d, e, f = spec.transform
        col = math.floor((x - c) / a)
        row = math.floor((f - y) / -e)
        if 0 <= row < spec.height and 0 <= col < spec.width:
            return CellRef(grid_id=spec.grid_id, row=row, col=col)
        return None

    def cell_center(self, row: int, col: int) -> tuple[float, float]:
        """像元中心的地图坐标 ``(x, y)``。"""
        self._indices_or_raise(row, col, "cell_center")
        a, _b, c, _d, e, f = self._spec.transform
        return (c + a * (col + 0.5), f + e * (row + 0.5))

    def cell_bounds(self, row: int, col: int) -> tuple[float, float, float, float]:
        """像元外接范围 ``(x_min, y_min, x_max, y_max)``。"""
        self._indices_or_raise(row, col, "cell_bounds")
        a, _b, c, _d, e, f = self._spec.transform
        return (c + a * col, f + e * (row + 1), c + a * (col + 1), f + e * row)

    def validity(self, row: int, col: int) -> CellValidity:
        """像元有效性三态判定（越界 / Mask 外 / 有效）。"""
        if not (0 <= row < self._spec.height and 0 <= col < self._spec.width):
            return CellValidity.OUT_OF_BOUNDS
        if self._mask is not None and (row, col) not in self._mask:
            return CellValidity.MASKED
        return CellValidity.VALID

    def is_valid(self, cell: CellRef) -> bool:
        """``CellRef`` 是否有效（要求属于本网格；跨网格显式报错）。"""
        self._cell_grid_or_raise(cell)
        return self.validity(cell.row, cell.col) is CellValidity.VALID

    def neighbors(self, cell: CellRef, connectivity: int = 8) -> list[CellRef]:
        """四/八邻域（04-grid-space.md §4.2）；界内几何邻接，行主序。

        只表达空间邻近不代表可通行；Mask 外像元照常返回（几何事实），
        调用方按需用 ``validity`` / ``is_valid`` 过滤。中心像元必须界内。
        """
        self._cell_grid_or_raise(cell)
        if connectivity == 4:
            offsets = self._NEIGHBOR_OFFSETS_4
        elif connectivity == 8:
            offsets = self._NEIGHBOR_OFFSETS_8
        else:
            raise ValueError(f"connectivity 只支持 4 或 8，实际为 {connectivity!r}")
        if self.validity(cell.row, cell.col) is CellValidity.OUT_OF_BOUNDS:
            raise ValueError(f"邻域中心越界：{cell}")
        spec = self._spec
        return [
            CellRef(grid_id=spec.grid_id, row=cell.row + dr, col=cell.col + dc)
            for dr, dc in offsets
            if 0 <= cell.row + dr < spec.height and 0 <= cell.col + dc < spec.width
        ]

    def window(self, center: CellRef, radius: int) -> list[CellRef]:
        """以 center 为中心、切比雪夫半径 radius 的矩形窗口（行主序）。

        越出网格边界的部分按边界裁剪——这是集合枚举语义，不是对查询
        位置的静默夹取；``locate`` / ``validity`` 的越界判定不受影响。
        中心像元必须界内；radius 为非负整数。
        """
        self._cell_grid_or_raise(center)
        if isinstance(radius, bool) or not isinstance(radius, int) or radius < 0:
            raise ValueError(f"window radius 必须是非负整数，实际为 {radius!r}")
        if self.validity(center.row, center.col) is CellValidity.OUT_OF_BOUNDS:
            raise ValueError(f"window 中心越界：{center}")
        spec = self._spec
        row_lo = max(0, center.row - radius)
        row_hi = min(spec.height - 1, center.row + radius)
        col_lo = max(0, center.col - radius)
        col_hi = min(spec.width - 1, center.col + radius)
        return [
            CellRef(grid_id=spec.grid_id, row=row, col=col)
            for row in range(row_lo, row_hi + 1)
            for col in range(col_lo, col_hi + 1)
        ]


class GridBinding:
    """空间单元 ↔ Cell 集合的显式映射（04-grid-space.md §4.4）。

    - ``unit_id`` 由调用方解释（通常是 ``SpatialConfig.nodes`` 的节点 id
      或空间单元 id）；Kernel 只登记字符串身份，不校验其在离散拓扑中
      存在。与 ``SpatialIndex`` 协作而非耦合：移动耗时仍全部走
      DistanceEdge / SpatialIndex，本映射不产生任何节点、边或可达性。
    - 绑定只要求像元在网格界内；是否要求处于 Mask 内由调用方决定。
    - 同一 unit_id 重复绑定显式报错（不覆盖、不合并）；绑定是原子操作，
      任一像元不合法时整体失败，不留下半更新状态。
    """

    def __init__(self, grid: GridSpace) -> None:
        self._grid = grid
        self._unit_cells: dict[str, frozenset[CellRef]] = {}
        self._cell_units: dict[tuple[int, int], set[str]] = {}

    @property
    def grid(self) -> GridSpace:
        return self._grid

    @property
    def unit_ids(self) -> frozenset[str]:
        return frozenset(self._unit_cells)

    def bind(self, unit_id: str, cells: Iterable[CellRef]) -> None:
        """把一个空间单元绑定到一组 Cell（单个像元传单元素即可）。"""
        _require_non_empty_str(unit_id, "GridBinding.bind 的 unit_id")
        if unit_id in self._unit_cells:
            raise ValueError(
                f"unit_id {unit_id!r} 已绑定：重复绑定显式拒绝（不覆盖、不合并）"
            )
        collected = list(cells)
        if not collected:
            raise ValueError(f"unit_id {unit_id!r} 的 cells 不能为空")
        for cell in collected:
            if not isinstance(cell, CellRef):
                raise ValueError(f"cells 的元素必须是 CellRef，实际为 {cell!r}")
            self._grid._cell_grid_or_raise(cell)
            if self._grid.validity(cell.row, cell.col) is CellValidity.OUT_OF_BOUNDS:
                raise ValueError(f"unit_id {unit_id!r} 绑定越界像元：{cell}")
        self._unit_cells[unit_id] = frozenset(collected)
        for cell in collected:
            self._cell_units.setdefault((cell.row, cell.col), set()).add(unit_id)

    def cells_of(self, unit_id: str) -> frozenset[CellRef]:
        """单元覆盖的 Cell 集合；未绑定的单元返回空集（查询语义）。"""
        return self._unit_cells.get(unit_id, frozenset())

    def units_at(self, cell: CellRef) -> frozenset[str]:
        """覆盖某 Cell 的单元集合；跨网格 CellRef 显式报错。"""
        self._grid._cell_grid_or_raise(cell)
        return frozenset(self._cell_units.get((cell.row, cell.col), ()))
