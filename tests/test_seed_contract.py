"""Environment Seed 静态契约校验专项测试（ADR 011 · P0）。

fixture 策略：真实资产哈希冻结已完成（本机实际文件复算核验），但仓库
不含数据二进制，故 CI 口径用合成数据包驱动全部校验分支（老板 2026-11-26
答复②的「校验器以 fixture 测试」）；真实包校验由
``python scripts/check_seed.py`` 以 ``--cache-root`` 指向部署缓存执行。

覆盖：合法包通过；版本/哈希/CRS/Transform/Mask/必需资产缺失/NoData 语义
各项明确拒绝（失败关闭）；确定性；坏配置加载即报错；CLI 入口退出码。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from vale.config.schema.environment_seed import (
    EnvironmentSeedConfig,
    SeedAnchor,
    SeedAsset,
    SeedGrid,
    SeedLocation,
    SeedScope,
    SeedSource,
    SeedWatershed,
)
from vale.core.config_loader import load_config
from vale.world.seed_contract import (
    resolve_cache_root,
    seed_world_binding_errors,
    validate_seed_package,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FAKE_WKT = (
    'PROJCS["fixture",GEOGCS["fixture",DATUM["WGS_1984",SPHEROID["WGS 84",6378137]]],'
    'PROJECTION["Fake_Equal_Area"],PARAMETER["latitude_of_center",33],'
    'PARAMETER["longitude_of_center",108.5],UNIT["metre",1]]'
)
FILE_NAMES = {
    "dem": "fixture_dem.tif",
    "sim_extent_mask": "fixture_mask.tif",
    "watershed": "fixture_watershed.tif",
    "rivers": "fixture_rivers.gpkg",
}


def _fixture_files() -> dict[str, bytes]:
    return {
        "dem": b"dem-payload-" * 8,
        "sim_extent_mask": b"10" * 6,
        "watershed": b"w" * 11,
        "rivers": b"GPKG" * 9,
    }


def _fixture_kwargs() -> dict:
    files = _fixture_files()

    def _asset(asset_id: str, **overrides) -> dict:
        blob = files[asset_id]
        base = dict(
            asset_id=asset_id,
            file=f"processed/fixture_seed/{FILE_NAMES[asset_id]}",
            format="GeoPackage" if asset_id == "rivers" else "GeoTIFF",
            status="active",
            size_bytes=len(blob),
            sha256=hashlib.sha256(blob).hexdigest(),
            lineage=f"fixture-upstream-{asset_id}",
        )
        if asset_id == "dem":
            base.update(dtype="float32", nodata=-9999.0)
        elif asset_id == "sim_extent_mask":
            base.update(dtype="uint8", nodata=None)
        elif asset_id == "watershed":
            base.update(dtype="uint8", nodata=0.0)
        else:
            base.update(
                layer="rivers",
                geometry_types=["LineString"],
                feature_count=3,
                bounds_albers_m=[-5.0, -6.0, 7.0, 8.0],
            )
        base.update(overrides)
        return base

    return dict(
        seed_id="fixture-seed-v2",
        manifest_file="seed_manifest_fixture.json",
        manifest_package_dir="processed/fixture_seed/",
        data_root_name="Xigu-Fixture-Data",
        anchor=dict(world_ref="fixture-world-001", lon=1.25, lat=2.5, albers_xy=[7.5, 17.5]),
        grid=dict(
            crs="+proj=fake +units=m",
            wkt_fragments=['PROJECTION["Fake_Equal_Area"]', 'PARAMETER["latitude_of_center",33]'],
            resolution_m=10.0,
            nodata=-9999.0,
            width=4,
            height=3,
            transform=[10.0, 0.0, 5.0, 0.0, -10.0, 35.0],
        ),
        scope=dict(shape="circle", radius_m=100.0, area_km2=0.0314, pixel_count=11,
                   mask_asset="sim_extent_mask"),
        core_watershed=dict(asset="watershed", area_km2=0.0021, share_of_scope_pct=6.7),
        source=dict(repository="git@example:fixture.git", revision="abc123def",
                    channel="fixture-channel", license="fixture upstream"),
        location=dict(package_dir="fixture_seed"),
        required_assets=[_asset("dem"), _asset("sim_extent_mask"),
                         _asset("watershed"), _asset("rivers")],
    )


def _fixture_contract() -> EnvironmentSeedConfig:
    return EnvironmentSeedConfig(**_fixture_kwargs())


def _manifest_from(contract: EnvironmentSeedConfig, files: dict[str, bytes],
                   mutate=None) -> dict:
    assets = []
    for asset in contract.required_assets:
        blob = files[asset.asset_id]
        entry = {
            "asset_id": asset.asset_id,
            "file": asset.file,
            "role": "fixture",
            "description": "fixture asset",
            "lineage": asset.lineage,
            "format": asset.format,
            "status": asset.status,
            "size_bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
        }
        if asset.format == "GeoTIFF":
            entry.update({
                "driver": "GTiff", "dtype": asset.dtype, "count": 1,
                "crs": FAKE_WKT,
                "width": contract.grid.width,
                "height": contract.grid.height,
                "nodata": asset.nodata,
                "bounds_albers_m": [0.0, 0.0, 40.0, 30.0],
                "transform": contract.grid.transform,
                "resolution_m": [contract.grid.resolution_m, contract.grid.resolution_m],
            })
        else:
            # 惯例对齐真实 manifest：矢量资产（rivers）不写 status 键。
            entry.pop("status")
            entry.update({
                "driver": "GPKG", "layer": asset.layer,
                "geometry_types": asset.geometry_types,
                "feature_count": asset.feature_count,
                "bounds_albers_m": asset.bounds_albers_m,
            })
        assets.append(entry)
    manifest = {
        "seed": contract.seed_id,
        "revision": {"supersedes": "fixture-seed-v1", "reason": "fixture revision"},
        "generated_at": "2026-11-26T00:00:00",
        "data_root": contract.data_root_name,
        "anchor": {
            "name": "fixture anchor", "lon": contract.anchor.lon,
            "lat": contract.anchor.lat, "albers_xy": contract.anchor.albers_xy,
        },
        "grid": {
            "crs": contract.grid.crs,
            "resolution_m": contract.grid.resolution_m,
            "nodata": contract.grid.nodata,
            "width": contract.grid.width,
            "height": contract.grid.height,
            "transform": contract.grid.transform,
        },
        "scope": {
            "shape": contract.scope.shape, "radius_m": contract.scope.radius_m,
            "area_km2": contract.scope.area_km2, "pixel_count": contract.scope.pixel_count,
            "mask_asset": contract.scope.mask_asset,
        },
        "core_watershed": {
            "asset": contract.core_watershed.asset,
            "area_km2": contract.core_watershed.area_km2,
            "share_of_scope_pct": contract.core_watershed.share_of_scope_pct,
        },
        "assets": assets,
        "acceptance": {"status": "pass"},
        "notes": [],
        "published": {
            "package_dir": contract.manifest_package_dir,
            "manifest": contract.manifest_package_dir + contract.manifest_file,
        },
    }
    if mutate is not None:
        mutate(manifest)
    return manifest


def _write_package(tmp_path: Path, contract: EnvironmentSeedConfig,
                   files: dict[str, bytes], mutate_manifest=None,
                   skip_assets: set[str] = frozenset()) -> Path:
    cache_root = tmp_path / "cache"
    package_dir = cache_root / contract.location.package_dir
    package_dir.mkdir(parents=True, exist_ok=True)
    manifest = _manifest_from(contract, files, mutate_manifest)
    (package_dir / contract.manifest_file).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for asset in contract.required_assets:
        if asset.asset_id in skip_assets:
            continue
        (package_dir / Path(asset.file).name).write_bytes(files[asset.asset_id])
    return cache_root


# ---------------------------------------------------------------------------
# 合法包通过 + 确定性
# ---------------------------------------------------------------------------

def test_valid_package_passes(tmp_path):
    contract = _fixture_contract()
    cache_root = _write_package(tmp_path, contract, _fixture_files())
    report = validate_seed_package(contract, cache_root)
    assert report.ok, report.issues
    assert report.assets_checked == 4
    assert report.files_hashed == 4
    # 矢量资产无 status 键 → 显式说明（按 manifest 惯例视作 active），不是问题。
    assert any("rivers" in note and "status" in note for note in report.notes)


def test_validation_is_deterministic(tmp_path):
    contract = _fixture_contract()
    files = _fixture_files()

    def _tamper(manifest):
        manifest["seed"] = "other-seed"
        manifest["assets"][0]["sha256"] = "0" * 64

    cache_root = _write_package(tmp_path, contract, files, mutate_manifest=_tamper)
    first = validate_seed_package(contract, cache_root)
    second = validate_seed_package(contract, cache_root)
    assert [(i.code, i.message) for i in first.issues] == [(i.code, i.message) for i in second.issues]
    assert first.notes == second.notes
    assert first.issue_codes() == ["seed_id", "manifest_hash"]


# ---------------------------------------------------------------------------
# 失败关闭：逐项拒绝
# ---------------------------------------------------------------------------

def _rejected(tmp_path, mutate_manifest=None, mutate_files=None,
              skip_assets=frozenset(), code=None) -> list[str]:
    contract = _fixture_contract()
    files = _fixture_files()
    if mutate_files is not None:
        mutate_files(files)
    cache_root = _write_package(
        tmp_path, contract, files,
        mutate_manifest=mutate_manifest, skip_assets=skip_assets,
    )
    report = validate_seed_package(contract, cache_root)
    assert not report.ok, f"应当拒绝，实际通过；notes={report.notes}"
    if code is not None:
        assert code in report.issue_codes(), report.issue_codes()
    return report.issue_codes()


def test_manifest_missing(tmp_path):
    contract = _fixture_contract()
    cache_root = _write_package(tmp_path, contract, _fixture_files())
    (cache_root / contract.location.package_dir / contract.manifest_file).unlink()
    report = validate_seed_package(contract, cache_root)
    assert report.issue_codes() == ["manifest_missing"]


def test_manifest_invalid_json(tmp_path):
    contract = _fixture_contract()
    cache_root = _write_package(tmp_path, contract, _fixture_files())
    manifest_path = cache_root / contract.location.package_dir / contract.manifest_file
    manifest_path.write_text("{not-json", encoding="utf-8")
    report = validate_seed_package(contract, cache_root)
    assert report.issue_codes() == ["manifest_parse"]


def test_wrong_seed_version_rejected(tmp_path):
    codes = _rejected(
        tmp_path,
        mutate_manifest=lambda m: m.__setitem__("seed", "environment-seed-v2"),
        code="seed_id",
    )
    assert "seed_id" in codes


def test_wrong_grid_contract_rejected(tmp_path):
    _rejected(tmp_path, mutate_manifest=lambda m: m["grid"].__setitem__(
        "transform", [30.0, 0.0, -404820.0, 0.0, -30.0, 337440.0]), code="grid")
    _rejected(tmp_path, mutate_manifest=lambda m: m["grid"].__setitem__(
        "crs", "+proj=aea +lat_1=30 +lat_2=36 +lat_0=33 +lon_0=108.5"), code="grid")
    _rejected(tmp_path, mutate_manifest=lambda m: m["grid"].__setitem__("width", 668), code="grid")
    _rejected(tmp_path, mutate_manifest=lambda m: m["grid"].__setitem__("resolution_m", 250.0), code="grid")


def test_wrong_anchor_rejected(tmp_path):
    _rejected(tmp_path, mutate_manifest=lambda m: m["anchor"].__setitem__("lon", 104.126366), code="anchor")


def test_wrong_scope_or_mask_rejected(tmp_path):
    _rejected(tmp_path, mutate_manifest=lambda m: m["scope"].__setitem__("radius_m", 5000.0), code="scope")
    # Mask 契约：范围掩膜资产被顶替（watershed 冒充模拟范围）必须拒绝。
    _rejected(tmp_path, mutate_manifest=lambda m: m["scope"].__setitem__("mask_asset", "watershed"), code="scope")


def test_wrong_watershed_rejected(tmp_path):
    _rejected(tmp_path, mutate_manifest=lambda m: m["core_watershed"].__setitem__("area_km2", 2.70), code="watershed")


def test_wrong_data_root_or_package_dir_rejected(tmp_path):
    _rejected(tmp_path, mutate_manifest=lambda m: m.__setitem__("data_root", "Other-Root"), code="data_root")
    _rejected(tmp_path, mutate_manifest=lambda m: m["published"].__setitem__(
        "package_dir", "work/pilot/"), code="package_dir")


def test_required_asset_missing_rejected(tmp_path):
    # Mask 资产缺失 = 模拟范围无法判定，必须失败关闭。
    _rejected(tmp_path, mutate_manifest=lambda m: m["assets"].pop(1), code="asset_missing")


def test_superseded_asset_rejected(tmp_path):
    _rejected(tmp_path, mutate_manifest=lambda m: m["assets"][1].__setitem__(
        "status", "superseded"), code="asset_status")


def test_manifest_hash_mismatch_rejected(tmp_path):
    _rejected(tmp_path, mutate_manifest=lambda m: m["assets"][0].__setitem__(
        "sha256", "f" * 64), code="manifest_hash")


def test_tampered_local_file_rejected(tmp_path):
    def _tamper(files):
        files["dem"] = files["dem"] + b"X"

    codes = _rejected(tmp_path, mutate_files=_tamper, code="file_hash")
    assert "file_size" in codes


def test_missing_local_file_rejected(tmp_path):
    contract = _fixture_contract()
    cache_root = _write_package(tmp_path, contract, _fixture_files())
    (cache_root / contract.location.package_dir / FILE_NAMES["dem"]).unlink()
    report = validate_seed_package(contract, cache_root)
    assert "file_missing" in report.issue_codes()


def test_asset_semantics_mismatch_rejected(tmp_path):
    # NoData 语义被改动（掩膜的 null → 0 会把圆外当缺失）必须拒绝。
    _rejected(tmp_path, mutate_manifest=lambda m: m["assets"][1].__setitem__("nodata", 0), code="asset_field")
    _rejected(tmp_path, mutate_manifest=lambda m: m["assets"][0].__setitem__("dtype", "uint8"), code="asset_field")
    _rejected(tmp_path, mutate_manifest=lambda m: m["assets"][0].__setitem__(
        "file", "work/pilot/fixture_dem.tif"), code="asset_path_prefix")
    _rejected(tmp_path, mutate_manifest=lambda m: m["assets"][0].__setitem__(
        "lineage", "unknown-source"), code="asset_field")


def test_wkt_missing_frozen_fragments_rejected(tmp_path):
    _rejected(tmp_path, mutate_manifest=lambda m: m["assets"][0].__setitem__(
        "crs", 'PROJCS["other",PROJECTION["Mercator"]]'), code="wkt_params")


def test_raster_grid_misalignment_rejected(tmp_path):
    # manifest 自身不一致：资产网格 ≠ manifest 网格（冻结网格整核对）。
    _rejected(tmp_path, mutate_manifest=lambda m: m["assets"][0].__setitem__(
        "transform", [20.0, 0.0, 5.0, 0.0, -20.0, 35.0]), code="asset_field")


def test_vector_contract_mismatch_rejected(tmp_path):
    _rejected(tmp_path, mutate_manifest=lambda m: m["assets"][3].__setitem__("feature_count", 25), code="asset_field")
    _rejected(tmp_path, mutate_manifest=lambda m: m["assets"][3].__setitem__(
        "bounds_albers_m", [0.0, 0.0, 1.0, 1.0]), code="asset_field")


def test_extra_manifest_assets_are_reported_not_fatal(tmp_path):
    def _add_extra(manifest):
        manifest["assets"].append({
            "asset_id": "future_asset", "file": "processed/fixture_seed/extra.tif",
            "format": "GeoTIFF", "status": "active",
        })

    contract = _fixture_contract()
    cache_root = _write_package(tmp_path, contract, _fixture_files(), mutate_manifest=_add_extra)
    report = validate_seed_package(contract, cache_root)
    assert report.ok, report.issues
    assert any("future_asset" in note for note in report.notes)


# ---------------------------------------------------------------------------
# 坏配置：加载即报错（结构层，pydantic）
# ---------------------------------------------------------------------------

def _kwargs_with(**overrides) -> dict:
    kwargs = _fixture_kwargs()
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(kwargs.get(key), dict):
            kwargs[key].update(value)
        else:
            kwargs[key] = value
    return kwargs


@pytest.mark.parametrize("overrides", [
    # sha256 必须是 64 位十六进制
    {"required_assets": [_fixture_kwargs()["required_assets"][0] | {"sha256": "zz"}]},
    # GeoTIFF 资产缺 dtype
    {"required_assets": [_fixture_kwargs()["required_assets"][0] | {"dtype": None}]},
    # 未知格式
    {"required_assets": [_fixture_kwargs()["required_assets"][0] | {"format": "Shapefile"}]},
    # GeoPackage 缺矢量契约字段
    {"required_assets": [_fixture_kwargs()["required_assets"][3] | {"feature_count": None}]},
    # 重复 asset_id
    {"required_assets": _fixture_kwargs()["required_assets"][:2]
     + [_fixture_kwargs()["required_assets"][0]]},
    # mask_asset 未登记
    {"scope": {"mask_asset": "unregistered_mask"}},
    # transform 长度错
    {"grid": {"transform": [10.0, 0.0, 5.0, 0.0, -10.0]}},
    # 锚点平面坐标长度错
    {"anchor": {"albers_xy": [1.0, 2.0, 3.0]}},
    # 非法尺寸
    {"grid": {"width": 0}},
])
def test_bad_seed_config_fails_at_load(overrides):
    with pytest.raises(ValidationError):
        EnvironmentSeedConfig(**_kwargs_with(**overrides))


def test_seed_config_requires_all_top_level_sections():
    incomplete = _fixture_kwargs()
    del incomplete["anchor"]
    with pytest.raises(ValidationError):
        EnvironmentSeedConfig(**incomplete)


# ---------------------------------------------------------------------------
# 世界身份绑定 + 缓存根解析
# ---------------------------------------------------------------------------

def test_world_binding_must_match_world_id():
    contract = _fixture_contract()
    assert seed_world_binding_errors("fixture-world-001", contract) == []
    errors = seed_world_binding_errors("other-world-001", contract)
    assert errors and "world_ref" in errors[0] and "other-world-001" in errors[0]


def test_resolve_cache_root_env_overrides_default(tmp_path, monkeypatch):
    monkeypatch.delenv("VALE_SEED_CACHE", raising=False)
    assert resolve_cache_root(tmp_path) == tmp_path / "data" / "seed-cache"
    monkeypatch.setenv("VALE_SEED_CACHE", str(tmp_path / "env-cache"))
    assert resolve_cache_root(tmp_path) == tmp_path / "env-cache"
    monkeypatch.setenv("VALE_SEED_CACHE", "relative-cache")
    assert resolve_cache_root(tmp_path) == tmp_path / "relative-cache"


# ---------------------------------------------------------------------------
# 在库真实契约（config/worlds/brookvale-town-001/world.yaml）
# ---------------------------------------------------------------------------

def test_real_world_seed_contract_is_frozen():
    config = load_config("brookvale-town-001")
    seed = config.world.environment_seed
    assert seed is not None, "brookvale-town-001 应已冻结 environment_seed 契约"
    assert seed_world_binding_errors(config.world.world_id, seed) == []

    assert seed.seed_id == "environment-seed-v3"
    assert seed.manifest_file == "seed_manifest_v3.json"
    assert seed.source.revision == "52e0d5517ea7d3d83c5641b9cf714d26fefe2944"
    assert seed.source.repository == "git@github.com:lenofrd/Xigu-Ecology-Data.git"
    assert seed.anchor.lon == 104.126366 and seed.anchor.lat == 35.875187
    assert seed.anchor.albers_xy == [-394804.54, 327448.73]

    assert (seed.grid.width, seed.grid.height) == (668, 666)
    assert seed.grid.transform == [30.0, 0.0, -404820.0, 0.0, -30.0, 337440.0]
    assert seed.grid.resolution_m == 30.0
    assert seed.scope.mask_asset == "sim_extent_mask"
    assert seed.scope.pixel_count == 349046
    assert seed.location.package_dir == "environment_seed_v2"

    ids = [asset.asset_id for asset in seed.required_assets]
    assert ids == ["dem", "slope", "aspect", "tpi_300m", "tpi_1000m", "tpi_3000m",
                   "worldcover", "sim_extent_mask", "watershed", "rivers"]
    by_id = {asset.asset_id: asset for asset in seed.required_assets}
    # NoData 语义冻结：掩膜无 NoData（圆外=0 是有效值）；类别/流域 0 为无数据或界外。
    assert by_id["sim_extent_mask"].nodata is None
    assert by_id["worldcover"].nodata == 0
    assert by_id["watershed"].nodata == 0
    assert by_id["dem"].nodata == -9999
    assert by_id["rivers"].feature_count == 25
    assert by_id["rivers"].geometry_types == ["LineString"]
    # 所有冻结哈希均为 64 位十六进制。
    assert all(len(asset.sha256) == 64 for asset in seed.required_assets)


# ---------------------------------------------------------------------------
# CLI 入口（仅命令行入口，校验逻辑在模块内）
# ---------------------------------------------------------------------------

def _run_cli(contract: EnvironmentSeedConfig, cache_root: Path, *extra: str) -> subprocess.CompletedProcess:
    contract_yaml = cache_root.parent / "contract.yaml"
    contract_yaml.write_text(yaml.safe_dump(contract.model_dump()), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "scripts/check_seed.py",
         "--contract", str(contract_yaml), "--cache-root", str(cache_root), *extra],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
        stdin=subprocess.DEVNULL,
    )


def test_cli_passes_valid_package(tmp_path):
    contract = _fixture_contract()
    cache_root = _write_package(tmp_path, contract, _fixture_files())
    result = _run_cli(contract, cache_root)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "通过" in result.stdout


def test_cli_rejects_tampered_package(tmp_path):
    contract = _fixture_contract()
    cache_root = _write_package(tmp_path, contract, _fixture_files())
    (cache_root / contract.location.package_dir / FILE_NAMES["dem"]).write_bytes(b"tampered")
    result = _run_cli(contract, cache_root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "file_hash" in result.stdout


def test_cli_rejects_missing_manifest(tmp_path):
    contract = _fixture_contract()
    cache_root = _write_package(tmp_path, contract, _fixture_files())
    (cache_root / contract.location.package_dir / contract.manifest_file).unlink()
    result = _run_cli(contract, cache_root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "manifest_missing" in result.stdout


def test_cli_reports_bad_contract_file(tmp_path):
    contract = _fixture_contract()
    cache_root = _write_package(tmp_path, contract, _fixture_files())
    contract_yaml = cache_root.parent / "bad_contract.yaml"
    contract_yaml.write_text("seed_id: broken\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "scripts/check_seed.py",
         "--contract", str(contract_yaml), "--cache-root", str(cache_root)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 2, result.stdout + result.stderr


def test_cli_world_path_uses_frozen_brookvale_contract(tmp_path):
    # --world 路径读取在库契约；指向空缓存根应因 manifest 缺失而失败关闭（非崩溃）。
    result = subprocess.run(
        [sys.executable, "scripts/check_seed.py",
         "--world", "brookvale-town-001", "--cache-root", str(tmp_path / "empty")],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "world_ref=brookvale-town-001" in result.stdout
    assert "manifest_missing" in result.stdout
