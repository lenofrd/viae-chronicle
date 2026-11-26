"""Environment Seed 契约的 Pydantic Schema（ADR 011 · P0）。

本文件只承载**冻结的内容**：`config/worlds/<world>/world.yaml` 的
`environment_seed` 节，声明 Viae 侧认可的外部数据包契约（Xigu
Environment Seed v2 / manifest v3，来源与数值见该节注释）。机制
（静态契约校验）在 `src/vale/world/seed_contract.py`，二者分离。

结构约束（缺键、错型、格式非法）在配置加载时即抛 ValidationError
（坏配置启动即报错）；与 manifest 实物的比对在数据集成边界校验。
"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class SeedAnchor(BaseModel):
    """锚点身份：P0 核验后的 Brookvale ↔ brookvale-town-001 映射契约。"""

    world_ref: str = Field(min_length=1, description="锚点对应的 Viae world_id；须与 world_id 一致（校验器核对）")
    lon: float = Field(ge=-180, le=180, description="锚点经度（WGS84，度）")
    lat: float = Field(ge=-90, le=90, description="锚点纬度（WGS84，度）")
    albers_xy: list[float] = Field(min_length=2, max_length=2, description="锚点在种子 CRS 下的平面坐标（米，[x, y]）")


class SeedGrid(BaseModel):
    """种子网格契约：本 Seed 的输入契约，不是 Kernel 全局默认网格参数。"""

    crs: str = Field(min_length=1, description="完整 CRS 的 PROJ 字符串；与 manifest grid.crs 严格相等")
    wkt_fragments: list[str] = Field(min_length=1, description="每个栅格资产 WKT 必须包含的参数片段（冻结 Albers 关键参数，不引入 CRS 库）")
    resolution_m: float = Field(gt=0, description="像元尺寸（地图单位，米）")
    nodata: float = Field(description="数值栅格基线 NoData；类别/掩膜资产的 NoData 冻结在资产级")
    width: int = Field(gt=0, description="列数")
    height: int = Field(gt=0, description="行数")
    transform: list[float] = Field(min_length=6, max_length=6, description="GDAL 仿射变换 [a, b, c, d, e, f]（含原点、像元尺寸、旋转项）")


class SeedScope(BaseModel):
    """模拟范围契约：圆形缓冲，非 bbox、非流域；判定必须用 mask 资产。"""

    shape: str = Field(min_length=1)
    radius_m: float = Field(gt=0)
    area_km2: float = Field(gt=0)
    pixel_count: int = Field(gt=0)
    mask_asset: str = Field(min_length=1, description="模拟范围掩膜资产 id（圆内=1，圆外=0）")


class SeedWatershed(BaseModel):
    """核心水文单元契约：占模拟范围的一部分，不得当全域 Mask 使用。"""

    asset: str = Field(min_length=1)
    area_km2: float = Field(gt=0)
    share_of_scope_pct: float = Field(ge=0, le=100)


class SeedAsset(BaseModel):
    """单个必需资产的身份与完整性契约（冻结自 manifest v3）。

    栅格资产的网格契约（width/height/transform）不逐资产冻结：所有
    GeoTIFF 资产必须与 SeedGrid 严格对齐（Xigu 数据契约 §2），由校验器
    按冻结网格整体核对 manifest 的每资产网格值。
    """

    asset_id: str = Field(min_length=1)
    file: str = Field(min_length=1, description="manifest 内相对 Xigu 数据根的资产路径")
    format: str = Field(min_length=1, description="GeoTIFF / GeoPackage")
    status: str = Field(default="active")
    dtype: str | None = Field(default=None, description="栅格数据类型（矢量资产为空）")
    nodata: float | None = Field(default=None, description="资产自身 NoData 语义（None = 无 NoData 定义，如模拟范围掩膜）")
    layer: str | None = Field(default=None, description="GeoPackage 图层名（矢量资产）")
    geometry_types: list[str] | None = Field(default=None, min_length=1)
    feature_count: int | None = Field(default=None, gt=0)
    bounds_albers_m: list[float] | None = Field(default=None, min_length=4, max_length=4)
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="冻结的 SHA-256（与 manifest 及实际文件三方一致）")
    lineage: str = Field(min_length=1, description="上游来源链（冻结自 manifest，溯源即内容）")

    @model_validator(mode="after")
    def _format_fields_present(self) -> "SeedAsset":
        if self.format == "GeoTIFF":
            if self.dtype is None:
                raise ValueError(f"GeoTIFF 资产 {self.asset_id} 缺少栅格契约字段：dtype")
        elif self.format == "GeoPackage":
            missing = [
                name for name, value in (
                    ("layer", self.layer), ("geometry_types", self.geometry_types),
                    ("feature_count", self.feature_count), ("bounds_albers_m", self.bounds_albers_m),
                ) if value is None
            ]
            if missing:
                raise ValueError(f"GeoPackage 资产 {self.asset_id} 缺少矢量契约字段：{missing}")
        else:
            raise ValueError(f"资产 {self.asset_id} 的 format 必须是 GeoTIFF 或 GeoPackage，实际为 {self.format!r}")
        return self


class SeedSource(BaseModel):
    """数据包来源与升级策略（B 机制：Xigu 发布版本化数据包；Viae 零网络逻辑）。"""

    repository: str = Field(min_length=1)
    revision: str = Field(min_length=1, description="溯源基准提交（数据包对应的 Xigu 仓库提交）")
    channel: str = Field(min_length=1, description="正式分发渠道")
    release: str | None = Field(default=None, description="Release 标签；Xigu 侧正式发布后回填")
    license: str = Field(min_length=1, description="许可与来源说明（指向上游数据方许可，不复制再分发条款）")
    upgrade_policy: str = Field(default="版本显式切换，旧版本可追溯，不原地覆盖")


class SeedLocation(BaseModel):
    """本地缓存定位（C 机制）：不写开发机绝对路径。"""

    package_dir: str = Field(min_length=1, description="数据包目录，相对缓存根（缓存根解析见 seed_contract.resolve_cache_root）")


class EnvironmentSeedConfig(BaseModel):
    """世界可选的 Environment Seed 冻结契约（world.yaml `environment_seed` 节）。"""

    seed_id: str = Field(min_length=1, description="期望的 manifest seed 身份（版本钉死；升级即显式换值）")
    manifest_file: str = Field(min_length=1, description="manifest 文件名（包目录内）")
    manifest_package_dir: str = Field(min_length=1, description="manifest 声明的发布目录（active 资产路径必须以其为前缀）")
    data_root_name: str = Field(min_length=1, description="期望的 manifest data_root（Xigu 数据根目录名）")
    anchor: SeedAnchor
    grid: SeedGrid
    scope: SeedScope
    core_watershed: SeedWatershed
    source: SeedSource
    location: SeedLocation
    required_assets: list[SeedAsset] = Field(min_length=1, description="必需资产清单；缺失任一即拒绝")

    @model_validator(mode="after")
    def _assets_consistent(self) -> "EnvironmentSeedConfig":
        ids = [asset.asset_id for asset in self.required_assets]
        if len(ids) != len(set(ids)):
            duplicates = sorted({asset_id for asset_id in ids if ids.count(asset_id) > 1})
            raise ValueError(f"required_assets 存在重复 asset_id：{duplicates}")
        known = set(ids)
        for field_name, value in (
            ("scope.mask_asset", self.scope.mask_asset),
            ("core_watershed.asset", self.core_watershed.asset),
        ):
            if value not in known:
                raise ValueError(f"{field_name}={value!r} 未在 required_assets 中登记")
        return self
