"""Environment Seed 静态契约校验（ADR 011 · P0，数据集成边界）。

可复用校验模块：全部校验逻辑在本文件，P2 Seed Loader 在同一装配边界
复用；CLI 仅是命令行入口（``scripts/check_seed.py``），不承载校验实现
（老板 2026-11-26 答复③）。本模块位于 ``world/``（装配/集成边界），
不进 Environment 领域内部（ADR 011 §2.6），不依赖 GDAL/Rasterio。

契约来源：world.yaml ``environment_seed`` 节（冻结值，schema 见
``vale.config.schema.environment_seed``）。校验全部**失败关闭**：任一项
不符即拒绝，不静默忽略资产、不隐式改 CRS/重采样、不把 NoData 当零。

本地缓存定位（C 机制，B+C 裁决 2026-11-26）：

- 缓存根 = 环境变量 ``VALE_SEED_CACHE``（若设置；绝对或相对 base 均可），
  否则 ``<base>/data/seed-cache``（base 缺省为当前工作目录）。
- 包目录 = 缓存根 / ``location.package_dir``；manifest = 包目录 / ``manifest_file``。
- 资产本地路径 = manifest 所在目录 / ``basename(manifest 路径)``；manifest
  的 active 资产路径必须以 ``manifest_package_dir`` 为前缀，因此该规则同时
  兼容「缓存根镜像整仓」与「缓存根只挂载包目录」两种部署布局。
- 【待裁决】缓存根解析规则为老板 2026-11-26「有条件采纳」的临时实现，
  条件明示前不改语义（见 DECISIONS 2026-11-26 ①）；世界配置不写绝对路径。
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from vale.config.schema.environment_seed import EnvironmentSeedConfig, SeedAsset

CACHE_ENV_VAR = "VALE_SEED_CACHE"
DEFAULT_CACHE_SUBDIR = ("data", "seed-cache")


@dataclass(frozen=True)
class SeedIssue:
    """一条契约不符：code 稳定（供测试断言），message 含具体差异。"""

    code: str
    message: str


@dataclass
class SeedValidationReport:
    manifest_path: str
    seed_id: str | None = None
    assets_checked: int = 0
    files_hashed: int = 0
    issues: list[SeedIssue] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def issue_codes(self) -> list[str]:
        return [issue.code for issue in self.issues]


def resolve_cache_root(base: Path | None = None) -> Path:
    """解析本地缓存根：环境变量优先，缺省 ``<base>/data/seed-cache``。

    环境变量值可为绝对路径或相对 base 的路径；本函数只解析路径，
    不创建目录、不做网络访问（Viae 运行时零网络逻辑）。
    """
    configured = os.environ.get(CACHE_ENV_VAR)
    if configured:
        root = Path(configured).expanduser()
        if not root.is_absolute():
            root = (base or Path.cwd()) / root
        return root
    return (base or Path.cwd()).joinpath(*DEFAULT_CACHE_SUBDIR)


def seed_world_binding_errors(world_id: str, seed: EnvironmentSeedConfig) -> list[str]:
    """世界身份绑定核对（P0 身份冻结）：锚点 world_ref 必须与 world_id 一致。"""
    if seed.anchor.world_ref != world_id:
        return [
            f"environment_seed.anchor.world_ref={seed.anchor.world_ref!r} "
            f"与 world_id={world_id!r} 不一致：世界身份绑定失败"
        ]
    return []


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_scalar(actual, expected: str, label: str, code: str,
                  issues: list[SeedIssue]) -> None:
    if actual != expected:
        issues.append(SeedIssue(
            code, f"{label}: manifest={actual!r}，冻结契约={expected!r}"
        ))


def _check_manifest_header(manifest: dict, seed: EnvironmentSeedConfig,
                           issues: list[SeedIssue]) -> None:
    _check_scalar(manifest.get("seed"), seed.seed_id, "seed（版本身份）", "seed_id", issues)
    _check_scalar(manifest.get("data_root"), seed.data_root_name, "data_root", "data_root", issues)
    published = manifest.get("published")
    package_dir = published.get("package_dir") if isinstance(published, dict) else None
    _check_scalar(package_dir, seed.manifest_package_dir, "published.package_dir", "package_dir", issues)

    anchor = manifest.get("anchor")
    anchor = anchor if isinstance(anchor, dict) else {}
    _check_scalar(anchor.get("lon"), seed.anchor.lon, "anchor.lon", "anchor", issues)
    _check_scalar(anchor.get("lat"), seed.anchor.lat, "anchor.lat", "anchor", issues)
    _check_scalar(anchor.get("albers_xy"), seed.anchor.albers_xy, "anchor.albers_xy", "anchor", issues)

    grid = manifest.get("grid")
    grid = grid if isinstance(grid, dict) else {}
    for key, expected in (
        ("crs", seed.grid.crs),
        ("resolution_m", seed.grid.resolution_m),
        ("nodata", seed.grid.nodata),
        ("width", seed.grid.width),
        ("height", seed.grid.height),
        ("transform", seed.grid.transform),
    ):
        _check_scalar(grid.get(key), expected, f"grid.{key}", "grid", issues)

    scope = manifest.get("scope")
    scope = scope if isinstance(scope, dict) else {}
    for key, expected in (
        ("shape", seed.scope.shape),
        ("radius_m", seed.scope.radius_m),
        ("area_km2", seed.scope.area_km2),
        ("pixel_count", seed.scope.pixel_count),
        ("mask_asset", seed.scope.mask_asset),
    ):
        _check_scalar(scope.get(key), expected, f"scope.{key}", "scope", issues)

    watershed = manifest.get("core_watershed")
    watershed = watershed if isinstance(watershed, dict) else {}
    for key, expected in (
        ("asset", seed.core_watershed.asset),
        ("area_km2", seed.core_watershed.area_km2),
        ("share_of_scope_pct", seed.core_watershed.share_of_scope_pct),
    ):
        _check_scalar(watershed.get(key), expected, f"core_watershed.{key}", "watershed", issues)


def _check_asset_entry(frozen: SeedAsset, entry: dict, seed: EnvironmentSeedConfig,
                       issues: list[SeedIssue], notes: list[str]) -> str | None:
    """核对单个资产的 manifest 条目；返回 manifest 声明的资产路径（无法核对时 None）。"""
    label = f"assets[{frozen.asset_id}]"
    status = entry.get("status")
    if status is None:
        notes.append(
            f"资产 {frozen.asset_id} 的 manifest 未声明 status，按 active 处理"
            "（manifest 惯例：仅非 active 资产显式标注 status）"
        )
        status = "active"
    _check_scalar(status, frozen.status, f"{label}.status", "asset_status", issues)

    manifest_file = entry.get("file")
    _check_scalar(manifest_file, frozen.file, f"{label}.file", "asset_field", issues)
    _check_scalar(entry.get("format"), frozen.format, f"{label}.format", "asset_field", issues)
    _check_scalar(entry.get("size_bytes"), frozen.size_bytes, f"{label}.size_bytes", "asset_field", issues)
    _check_scalar(entry.get("sha256"), frozen.sha256, f"{label}.sha256", "manifest_hash", issues)

    if not isinstance(manifest_file, str) or not manifest_file.startswith(seed.manifest_package_dir):
        issues.append(SeedIssue(
            "asset_path_prefix",
            f"{label}.file={manifest_file!r} 不以发布目录前缀 {seed.manifest_package_dir!r} 开头",
        ))

    if frozen.format == "GeoTIFF":
        # 所有栅格资产必须与冻结网格严格对齐（Xigu 数据契约 §2）。
        for key, expected in (
            ("dtype", frozen.dtype),
            ("nodata", frozen.nodata),
            ("width", seed.grid.width),
            ("height", seed.grid.height),
            ("transform", seed.grid.transform),
        ):
            _check_scalar(entry.get(key), expected, f"{label}.{key}", "asset_field", issues)
        wkt = entry.get("crs")
        if not isinstance(wkt, str):
            issues.append(SeedIssue(
                "wkt_params", f"{label}.crs（WKT）缺失或非字符串，无法核对投影参数"
            ))
        else:
            for fragment in seed.grid.wkt_fragments:
                if fragment not in wkt:
                    issues.append(SeedIssue(
                        "wkt_params",
                        f"{label}.crs（WKT）缺少冻结片段 {fragment!r}（自定义 Albers 投影参数）",
                    ))
    else:
        for key, expected in (
            ("layer", frozen.layer),
            ("geometry_types", frozen.geometry_types),
            ("feature_count", frozen.feature_count),
            ("bounds_albers_m", frozen.bounds_albers_m),
        ):
            _check_scalar(entry.get(key), expected, f"{label}.{key}", "asset_field", issues)

    _check_scalar(entry.get("lineage"), frozen.lineage, f"{label}.lineage", "asset_field", issues)
    return manifest_file if isinstance(manifest_file, str) else None


def validate_seed_package(seed: EnvironmentSeedConfig, cache_root: Path) -> SeedValidationReport:
    """按冻结契约静态校验本地数据包；不修改任何被检文件（只读）。"""
    report = SeedValidationReport(
        manifest_path=str(cache_root / seed.location.package_dir / seed.manifest_file)
    )
    issues, notes = report.issues, report.notes
    manifest_path = Path(report.manifest_path)

    if not manifest_path.is_file():
        issues.append(SeedIssue(
            "manifest_missing", f"manifest 不存在：{report.manifest_path}（缓存根={cache_root}）"
        ))
        return report
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(SeedIssue("manifest_parse", f"manifest 读取/解析失败：{exc}"))
        return report
    if not isinstance(manifest, dict):
        issues.append(SeedIssue("manifest_parse", f"manifest 顶层必须是对象，实际为 {type(manifest).__name__}"))
        return report

    report.seed_id = manifest.get("seed") if isinstance(manifest.get("seed"), str) else None
    _check_manifest_header(manifest, seed, issues)

    raw_assets = manifest.get("assets")
    entries: dict[str, dict] = {}
    if isinstance(raw_assets, list):
        for entry in raw_assets:
            if isinstance(entry, dict) and isinstance(entry.get("asset_id"), str):
                entries[entry["asset_id"]] = entry

    manifest_dir = manifest_path.parent
    for frozen in seed.required_assets:
        report.assets_checked += 1
        entry = entries.get(frozen.asset_id)
        if entry is None:
            issues.append(SeedIssue(
                "asset_missing", f"必需资产 {frozen.asset_id} 不在 manifest assets 中"
            ))
            continue
        manifest_file = _check_asset_entry(frozen, entry, seed, issues, notes)
        if manifest_file is None:
            continue
        local_path = manifest_dir / Path(manifest_file).name
        if not local_path.is_file():
            issues.append(SeedIssue(
                "file_missing", f"资产 {frozen.asset_id} 的本地文件不存在：{local_path}"
            ))
            continue
        actual_size = local_path.stat().st_size
        if actual_size != frozen.size_bytes:
            issues.append(SeedIssue(
                "file_size",
                f"资产 {frozen.asset_id} 字节数：实际={actual_size}，冻结契约={frozen.size_bytes}",
            ))
        report.files_hashed += 1
        actual_hash = _sha256(local_path)
        if actual_hash != frozen.sha256:
            issues.append(SeedIssue(
                "file_hash",
                f"资产 {frozen.asset_id} 的 SHA-256：实际={actual_hash}，冻结契约={frozen.sha256}",
            ))

    frozen_ids = {frozen.asset_id for frozen in seed.required_assets}
    for asset_id, entry in entries.items():
        if asset_id in frozen_ids:
            continue
        notes.append(
            f"manifest 含冻结清单之外的资产 {asset_id}（status={entry.get('status', 'active')}），"
            "显式报告：未接入，不作为通过条件（升级由 Xigu 发布新版本后显式换引用）"
        )
    revision = manifest.get("revision")
    if isinstance(revision, dict) and revision.get("supersedes"):
        notes.append(
            f"manifest 修订链：{manifest.get('seed')} 取代 {revision.get('supersedes')}"
            f"（{revision.get('reason', '无说明')}）"
        )
    return report
