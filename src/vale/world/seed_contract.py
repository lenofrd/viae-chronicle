"""Seed 静态契约校验（数据集成边界：Environment Seed ADR 011 · P0；Ecology Seed EX-0）。

可复用校验模块：全部校验逻辑在本文件，P2 Seed Loader 在同一装配边界
复用；CLI 仅是命令行入口（``scripts/check_seed.py``），不承载校验实现
（老板 2026-11-26 答复③）。本模块位于 ``world/``（装配/集成边界），
不进 Environment / Wildlife 领域内部（ADR 011 §2.6），不依赖 GDAL/Rasterio。

契约来源：world.yaml ``environment_seed`` / ``ecology_seed`` 节（冻结值，
schema 见 ``vale.config.schema.environment_seed`` /
``vale.config.schema.ecology_seed``）。校验全部**失败关闭**：任一项
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

import csv
import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from vale.config.schema.ecology_seed import EcologySeedConfig
from vale.config.schema.environment_seed import EnvironmentSeedConfig, SeedAsset

CACHE_ENV_VAR = "VALE_SEED_CACHE"
DEFAULT_CACHE_SUBDIR = ("data", "seed-cache")
# SQLite 自身簿记表，不计入「契约外表」报告。
SQLITE_INTERNAL_TABLES = {"sqlite_sequence"}


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


# ---------------------------------------------------------------------------
# Ecology Seed（EX-0，老板 2026-11-26 裁决：批准契约冻结/静态校验/完整性
# 验证，暂缓 E3/E4/E5 运行时消费）。
#
# 生态/群落数据线（Xigu Ecology Seed v1：7 CSV + 1 SQLite）的静态契约校验。
# 与 Environment Seed **共用缓存根**（resolve_cache_root）、**包目录隔离**
# （location.package_dir，裁决③④）。失败关闭。
#
# SQLite↔CSV **全表逻辑等价**（老板裁决：抽样不足以保证两种载体一致），
# 口径按本包实测冻结：
# - 行匹配按表主键（契约 7 表均为单列主键），与行序无关（实测两载体行序不同）；
# - 字段等价：SQLite NULL ↔ CSV 空串（实测逐列计数吻合且 SQLite 侧无空串值，
#   两载体均无 "NULL" 字面量）；数值字段按数值相等（整型/浮点统一按 float
#   比较，发布侧为全精度 repr 可精确往返）；文本字段按字符串精确相等；
# - 列集按表头名字集合一致；行数三方一致（冻结 table_rows、manifest rows/counts、
#   SQLite 行数、CSV 数据行数）。
# SQLite 中契约外的表（registry/过程表）显式报告，不作为通过条件。
# ---------------------------------------------------------------------------


@dataclass
class EcologySeedValidationReport:
    """生态数据包校验报告：code 稳定（供测试断言），notes 为非门禁信息项。"""

    manifest_path: str
    seed_id: str | None = None
    files_checked: int = 0
    files_hashed: int = 0
    tables_compared: int = 0
    rows_compared: int = 0
    issues: list[SeedIssue] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def issue_codes(self) -> list[str]:
        return [issue.code for issue in self.issues]


def ecology_seed_world_binding_errors(world_id: str, seed: EcologySeedConfig) -> list[str]:
    """世界身份绑定核对：world_ref 必须与 world_id 一致（同 P0 模式）。"""
    if seed.world_ref != world_id:
        return [
            f"ecology_seed.world_ref={seed.world_ref!r} 与 world_id={world_id!r} 不一致：世界身份绑定失败"
        ]
    return []


def _csv_sqlite_value_equal(sqlite_value, csv_value: str) -> bool:
    """单字段逻辑等价（口径见本节注释：NULL↔空串、数值按值、文本精确）。"""
    if sqlite_value is None:
        return csv_value == ""
    if isinstance(sqlite_value, (int, float)):
        if csv_value == "":
            return False
        try:
            return float(csv_value) == float(sqlite_value)
        except ValueError:
            return False
    return str(sqlite_value) == csv_value


def _read_csv_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    """读 CSV（utf-8-sig 兼容发布侧 BOM），返回（表头, 数据行）。"""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None) or []
        rows = [row for row in reader]
    return header, rows


def _sqlite_pk_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """主键列（按 PRAGMA table_info 的 pk 序号排序；无主键为空）。"""
    info = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    pk = sorted((row[5], row[1]) for row in info if row[5])
    return [name for _, name in pk]


def _compare_csv_sqlite_table(
    conn: sqlite3.Connection, table: str, frozen_rows: int, csv_path: Path,
    issues: list[SeedIssue],
) -> int:
    """单表全表逻辑等价比对；返回比对过的行数（按主键交集计）。"""
    cursor = conn.execute(f'SELECT * FROM "{table}"')
    sqlite_cols = [description[0] for description in cursor.description]
    sqlite_rows = cursor.fetchall()

    pk_columns = _sqlite_pk_columns(conn, table)
    if len(pk_columns) != 1:
        issues.append(SeedIssue(
            "table_pk",
            f"表 {table} 主键非单列（{pk_columns}），无法按稳定 ID 逐行匹配",
        ))
        return 0
    pk = pk_columns[0]

    if not csv_path.is_file():
        return 0  # 文件缺失已在文件层报 file_missing
    header, csv_rows = _read_csv_rows(csv_path)

    if len(sqlite_rows) != frozen_rows:
        issues.append(SeedIssue(
            "row_count",
            f"表 {table} SQLite 行数：实际={len(sqlite_rows)}，冻结契约={frozen_rows}",
        ))
    if len(csv_rows) != frozen_rows:
        issues.append(SeedIssue(
            "row_count",
            f"表 {table} CSV 数据行数：实际={len(csv_rows)}，冻结契约={frozen_rows}",
        ))

    if set(header) != set(sqlite_cols):
        only_csv = sorted(set(header) - set(sqlite_cols))
        only_sqlite = sorted(set(sqlite_cols) - set(header))
        issues.append(SeedIssue(
            "csv_columns",
            f"表 {table} 列集不一致：仅 CSV 有 {only_csv}，仅 SQLite 有 {only_sqlite}",
        ))
        return 0

    csv_by_pk: dict[str, list[str]] = {}
    for row in csv_rows:
        if len(row) != len(header):
            issues.append(SeedIssue(
                "csv_row_shape",
                f"表 {table} 存在字段数与表头不一致的 CSV 行（{len(row)} != {len(header)}）",
            ))
            continue
        key = row[header.index(pk)]
        if key in csv_by_pk:
            issues.append(SeedIssue(
                "csv_duplicate_pk",
                f"表 {table} CSV 主键 {pk}={key!r} 重复（两载体按主键匹配的前提被破坏）",
            ))
            continue
        csv_by_pk[key] = row

    sqlite_by_pk: dict[str, tuple] = {}
    for row in sqlite_rows:
        sqlite_by_pk[str(row[sqlite_cols.index(pk)])] = row

    sqlite_keys, csv_keys = set(sqlite_by_pk), set(csv_by_pk)
    missing = sorted(sqlite_keys - csv_keys)
    if missing:
        shown = ", ".join(missing[:5]) + ("…" if len(missing) > 5 else "")
        issues.append(SeedIssue(
            "csv_row_missing",
            f"表 {table} CSV 缺少 {len(missing)} 行（主键 {pk}：{shown}）",
        ))
    extra = sorted(csv_keys - sqlite_keys)
    if extra:
        shown = ", ".join(extra[:5]) + ("…" if len(extra) > 5 else "")
        issues.append(SeedIssue(
            "csv_row_extra",
            f"表 {table} CSV 多出 {len(extra)} 行（主键 {pk}：{shown}）",
        ))

    mismatches = 0
    common = sqlite_keys & csv_keys
    for key in sorted(common):
        sqlite_row = sqlite_by_pk[key]
        csv_row_map = dict(zip(header, csv_by_pk[key]))
        for column, sqlite_value in zip(sqlite_cols, sqlite_row):
            if not _csv_sqlite_value_equal(sqlite_value, csv_row_map[column]):
                mismatches += 1
                if mismatches <= 5:
                    issues.append(SeedIssue(
                        "csv_value_mismatch",
                        f"表 {table}[{pk}={key}].{column}："
                        f"SQLite={sqlite_value!r}，CSV={csv_row_map[column]!r}",
                    ))
    if mismatches > 5:
        issues.append(SeedIssue(
            "csv_value_mismatch",
            f"表 {table} 另有 {mismatches - 5} 处字段逻辑不等价（输出截断）",
        ))
    return len(common)


def validate_ecology_seed_package(
    seed: EcologySeedConfig, cache_root: Path,
) -> EcologySeedValidationReport:
    """按冻结契约静态校验生态数据包；不修改任何被检文件（只读）。

    校验项：manifest 存在/可解析；manifest 自身 size+sha256（我方实测冻结）；
    包身份四元组（package/version/contract/schema_version）；manifest files
    条目与冻结清单逐字段一致；manifest counts 与行数契约一致；8 个本地文件
    存在 + 字节数 + SHA-256 复算；7 个导出表 SQLite↔CSV **全表逻辑等价**。
    """
    report = EcologySeedValidationReport(
        manifest_path=str(cache_root / seed.location.package_dir / seed.manifest.file)
    )
    issues, notes = report.issues, report.notes
    package_dir = Path(report.manifest_path).parent
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

    report.seed_id = manifest.get("package") if isinstance(manifest.get("package"), str) else None

    # manifest 自身完整性（我方实测冻结：Xigu 侧文档曾误标该哈希）。
    actual_bytes = manifest_path.stat().st_size
    if actual_bytes != seed.manifest.bytes:
        issues.append(SeedIssue(
            "manifest_hash",
            f"manifest 字节数：实际={actual_bytes}，冻结契约={seed.manifest.bytes}",
        ))
    actual_hash = _sha256(manifest_path)
    if actual_hash != seed.manifest.sha256:
        issues.append(SeedIssue(
            "manifest_hash",
            f"manifest SHA-256：实际={actual_hash}，冻结契约={seed.manifest.sha256}",
        ))

    # 包身份四元组。
    _check_scalar(manifest.get("package"), seed.seed_id, "manifest.package", "package_id", issues)
    _check_scalar(manifest.get("version"), seed.version, "manifest.version", "seed_version", issues)
    _check_scalar(manifest.get("contract"), seed.contract, "manifest.contract", "seed_contract", issues)
    _check_scalar(
        manifest.get("schema_version"), seed.schema_version,
        "manifest.schema_version", "schema_version", issues,
    )

    # manifest files 条目与冻结清单逐字段一致。
    raw_files = manifest.get("files")
    entries: dict[str, dict] = {}
    if isinstance(raw_files, list):
        for entry in raw_files:
            if isinstance(entry, dict) and isinstance(entry.get("file"), str):
                entries[entry["file"]] = entry
    for frozen in seed.files:
        entry = entries.get(frozen.file)
        if entry is None:
            issues.append(SeedIssue(
                "file_entry", f"必需文件 {frozen.file} 不在 manifest files 中"
            ))
            continue
        for key, expected, code in (
            ("table", frozen.table, "file_entry"),
            ("rows", frozen.rows, "file_entry"),
            ("bytes", frozen.bytes, "file_entry"),
            ("sha256", frozen.sha256, "file_entry"),
        ):
            _check_scalar(entry.get(key), expected, f"files[{frozen.file}].{key}", code, issues)
    frozen_files = {frozen.file for frozen in seed.files}
    for name in sorted(set(entries) - frozen_files):
        notes.append(
            f"manifest 含冻结清单之外的文件 {name}（table={entries[name].get('table')}），"
            "显式报告：未接入，不作为通过条件"
        )

    # manifest counts 与行数契约一致。
    counts = manifest.get("counts")
    counts = counts if isinstance(counts, dict) else {}
    for table in sorted(seed.table_rows):
        _check_scalar(
            counts.get(table), seed.table_rows[table],
            f"manifest.counts[{table}]", "table_rows", issues,
        )

    # 本地文件存在 + 字节数 + SHA-256 复算。
    for frozen in seed.files:
        report.files_checked += 1
        local_path = package_dir / frozen.file
        if not local_path.is_file():
            issues.append(SeedIssue(
                "file_missing", f"文件 {frozen.file} 不存在：{local_path}"
            ))
            continue
        actual_size = local_path.stat().st_size
        if actual_size != frozen.bytes:
            issues.append(SeedIssue(
                "file_size",
                f"文件 {frozen.file} 字节数：实际={actual_size}，冻结契约={frozen.bytes}",
            ))
        report.files_hashed += 1
        actual_hash = _sha256(local_path)
        if actual_hash != frozen.sha256:
            issues.append(SeedIssue(
                "file_hash",
                f"文件 {frozen.file} 的 SHA-256：实际={actual_hash}，冻结契约={frozen.sha256}",
            ))

    # SQLite↔CSV 全表逻辑等价。
    sqlite_file = package_dir / next(f.file for f in seed.files if f.table == "*")
    csv_files = {f.table: package_dir / f.file for f in seed.files if f.table != "*"}
    if not sqlite_file.is_file():
        return report  # 文件缺失已在文件层失败关闭
    conn = None
    try:
        conn = sqlite3.connect(f"{sqlite_file.resolve().as_uri()}?mode=ro", uri=True)
        db_tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table in sorted(seed.table_rows):
            if table not in db_tables:
                issues.append(SeedIssue("table_missing", f"SQLite 缺少契约表：{table}"))
                continue
            report.rows_compared += _compare_csv_sqlite_table(
                conn, table, seed.table_rows[table], csv_files[table], issues,
            )
            report.tables_compared += 1
        extra_tables = sorted(db_tables - set(seed.table_rows) - SQLITE_INTERNAL_TABLES)
        if extra_tables:
            notes.append(
                "SQLite 含契约之外的表（registry/过程表，未导出）："
                + ", ".join(extra_tables)
                + "；显式报告：未接入，不作为通过条件"
            )
    except sqlite3.Error as exc:
        issues.append(SeedIssue("sqlite_read", f"SQLite 只读读取失败：{exc}"))
    finally:
        if conn is not None:
            conn.close()

    qc = manifest.get("qc")
    qc_verdict = qc.get("verdict") if isinstance(qc, dict) else None
    notes.append(
        f"Xigu 侧自检 qc.verdict={qc_verdict!r}（信息项，非 Viae 通过条件；"
        "Viae 侧以哈希复算与全表逻辑等价为准）"
    )
    notes.append(
        "initial_state.quantity_value 在本冻结版本全部为 NULL（2026-11-26 裁决："
        "不得用推测值填充；数值提供须走 Xigu 新版本 + Viae 显式升级）"
    )
    return report
