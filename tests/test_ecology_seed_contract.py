"""Ecology Seed 静态契约校验专项测试（EX-0，老板 2026-11-26 裁决有条件批准）。

fixture 策略与 P0 一致：仓库不含数据二进制，CI 口径用合成数据包驱动全部
校验分支；真实包校验由 ``python scripts/check_seed.py --seed ecology
--cache-root <部署缓存>`` 执行（EX-0 验收已对本机真实包跑通：8 文件哈希
复算、7 表 1394 行全表逻辑等价全部通过）。

覆盖：合法包通过（含全表逻辑等价与清单外表报告）；包身份/manifest 自身
哈希/文件哈希/文件缺失/行数契约各项明确拒绝（失败关闭）；CSV↔SQLite
逻辑等价的全部拒绝分支（缺行/多行/改值/重复主键/列集不一致/给 NULL 填值）；
逻辑等价口径单测（NULL↔空串、数值按值、文本精确含尾随空格）；确定性；
坏配置加载即报错；世界绑定；在库契约（world.yaml 冻结值）；CLI 退出码
（--seed ecology 分支与缺省 environment 分支回归）。
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from vale.config.schema.ecology_seed import EcologySeedConfig
from vale.core.config_loader import load_config
from vale.world.seed_contract import (
    _csv_sqlite_value_equal,
    ecology_seed_world_binding_errors,
    resolve_cache_root,
    validate_ecology_seed_package,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR_NAME = "ecology_seed_v1"
SQLITE_NAME = "ecology_seed_v1.sqlite"
MANIFEST_NAME = "manifest.json"

# CSV 文件名 ↔ SQLite 表名映射（与真实包一致：occurrences.csv ↔ species_records）。
FILE_FOR_TABLE = {
    "taxa": "taxa.csv",
    "species_records": "occurrences.csv",
    "functional_groups": "functional_groups.csv",
    "traits": "traits.csv",
    "ecological_interactions": "interactions.csv",
    "habitat_associations": "habitat_associations.csv",
    "initial_state": "initial_states.csv",
}

# 与真实包同构的最小 7 表（单列主键；列含 TEXT/INTEGER/REAL/NULL，模拟
# 证据字段与全 NULL 的 initial_state.quantity_value）。
TABLES: dict[str, tuple[str, list[tuple]]] = {
    "taxa": (
        "CREATE TABLE taxa (taxon_id TEXT PRIMARY KEY, scientific_name TEXT NOT NULL, "
        "rank TEXT, quality_status TEXT)",
        [
            ("TX_A", "Picea wilsonii", "species", "accepted"),
            ("TX_B", "Lanius cristatus", "species", "accepted"),
            ("TX_C", "Passer montanus", None, "accepted"),
        ],
    ),
    "species_records": (
        "CREATE TABLE species_records (record_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "taxon_id TEXT NOT NULL, latitude REAL, longitude REAL, evidence_grade TEXT, "
        "abundance_value REAL)",
        [
            (1, "TX_A", 35.947326, 104.140419, "B", None),
            (2, "TX_B", 35.800278, 104.066667, "B", 18.0),
            (3, "TX_C", 35.9, 104.1, "A2", 2.0),
        ],
    ),
    "functional_groups": (
        "CREATE TABLE functional_groups (functional_group_id TEXT PRIMARY KEY, "
        "name TEXT NOT NULL, role TEXT, evidence_grade TEXT)",
        [
            ("FG_PLANT_SEED", "植物种子与果实（聚合）", "producer", "C"),
            ("FG_SOIL_DECOMPOSER", "土壤分解者（聚合）", "decomposer", "D"),
        ],
    ),
    "traits": (
        "CREATE TABLE traits (trait_id TEXT PRIMARY KEY, taxon_id TEXT, "
        "trait_name TEXT NOT NULL, trait_value TEXT, value_num REAL)",
        [
            ("TR_TX_A_growth", "TX_A", "growth_form", "tree", None),
            ("TR_TX_B_diet", "TX_B", "diet", "carnivore", None),
        ],
    ),
    "ecological_interactions": (
        "CREATE TABLE ecological_interactions (interaction_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "source_taxon_id TEXT, object_group_id TEXT, interaction_type TEXT NOT NULL, "
        "evidence_grade TEXT, notes TEXT)",
        [
            (1, "TX_B", "FG_PLANT_SEED", "eats", "C", "GloBI; "),
            (2, "TX_C", "FG_PLANT_SEED", "preysOn", "C", "GloBI; "),
        ],
    ),
    "habitat_associations": (
        "CREATE TABLE habitat_associations (association_id TEXT PRIMARY KEY, taxon_id TEXT, "
        "habitat_ref TEXT NOT NULL, habitat_share REAL, confidence TEXT)",
        [
            ("HA_TX_B_LC50", "TX_B", "simulation_circle+LC50", 0.841743119266055, "low"),
            ("HA_TX_C_LC30", "TX_C", "simulation_circle+LC30", 0.262, "share=0.262"),
        ],
    ),
    "initial_state": (
        "CREATE TABLE initial_state (state_id TEXT PRIMARY KEY, taxon_id TEXT, "
        "spatial_ref TEXT NOT NULL, quantity_value REAL, unknown_reason TEXT)",
        [
            ("IS_simulation_circle_TX_A", "TX_A", "simulation_circle", None, "无本地实测"),
            ("IS_core_watershed_TX_B", "TX_B", "core_watershed", None, "无本地实测"),
            ("IS_L1_FG_SOIL_DECOMPOSER", None, "simulation_circle", None, "以功能组占位"),
        ],
    ),
}
TOTAL_ROWS = sum(len(rows) for _, rows in TABLES.values())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _csv_cell(value) -> str:
    """SQLite 值 → CSV 单元格（逻辑等价口径的逆映射）。"""
    if value is None:
        return ""
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _build_package(cache_root: Path) -> dict:
    """在 cache_root 下建合成生态包，返回自洽的冻结契约 dict（值取自实际文件）。"""
    package_dir = cache_root / PACKAGE_DIR_NAME
    package_dir.mkdir(parents=True, exist_ok=True)
    db_path = package_dir / SQLITE_NAME
    conn = sqlite3.connect(db_path)
    try:
        columns: dict[str, list[str]] = {}
        for table, (ddl, rows) in TABLES.items():
            conn.execute(ddl)
            placeholders = ",".join("?" for _ in rows[0])
            conn.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', rows)
            cursor = conn.execute(f'SELECT * FROM "{table}"')
            columns[table] = [description[0] for description in cursor.description]
        # 契约外过程表（驱动「清单外表报告，不作通过条件」）。
        conn.execute("CREATE TABLE datasets (dataset_id TEXT PRIMARY KEY, title TEXT)")
        conn.execute("INSERT INTO datasets VALUES ('DS_1', 'fixture dataset')")
        conn.commit()
    finally:
        conn.close()

    # CSV 导出：行序打乱（真实包两载体行序不同，校验必须按主键而非行位置）；
    # utf-8-sig 带发布侧 BOM。
    for table, (_, rows) in TABLES.items():
        shuffled = list(rows)
        random.Random(f"csv-order-{table}").shuffle(shuffled)
        csv_path = package_dir / FILE_FOR_TABLE[table]
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns[table])
            for row in shuffled:
                writer.writerow([_csv_cell(value) for value in row])

    file_entries = []
    for table in TABLES:
        path = package_dir / FILE_FOR_TABLE[table]
        file_entries.append({
            "file": FILE_FOR_TABLE[table], "table": table, "rows": len(TABLES[table][1]),
            "bytes": path.stat().st_size, "sha256": _sha256(path),
        })
    sqlite_entry = {
        "file": SQLITE_NAME, "table": "*", "rows": None,
        "bytes": db_path.stat().st_size, "sha256": _sha256(db_path),
    }
    manifest = {
        "package": PACKAGE_DIR_NAME, "version": "1.0",
        "contract": "Ecology_Seed_v1_数据契约 v1.1",
        "schema_version": "xigu_ecology_schema_2026-11-26",
        "counts": {table: len(rows) for table, (_, rows) in TABLES.items()},
        "files": [dict(entry) for entry in file_entries] + [dict(sqlite_entry)],
        "qc": {"verdict": "PASS"},
    }
    manifest_path = package_dir / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "seed_id": PACKAGE_DIR_NAME,
        "version": "1.0",
        "contract": "Ecology_Seed_v1_数据契约 v1.1",
        "schema_version": "xigu_ecology_schema_2026-11-26",
        "world_ref": "brookvale-town-001",
        "manifest": {
            "file": MANIFEST_NAME,
            "bytes": manifest_path.stat().st_size,
            "sha256": _sha256(manifest_path),
        },
        "source": {
            "repository": "git@github.com:example/Xigu-Ecology-Data.git",
            "revision": "0" * 40,
            "channel": "github-release",
            "release": "ecology-seed-v1.0",
            "license": "fixture license",
        },
        "location": {"package_dir": PACKAGE_DIR_NAME},
        "files": file_entries + [sqlite_entry],
        "table_rows": dict(manifest["counts"]),
    }


def _contract(config: dict) -> EcologySeedConfig:
    data = {key: value for key, value in config.items() if not key.startswith("_")}
    return EcologySeedConfig(**data)


def _load_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    return rows[0], rows[1:]


def _save_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _package_file(config: dict, name: str) -> Path:
    return Path(config["_cache_root"]) / PACKAGE_DIR_NAME / name


def _refresh_file_entry(config: dict, name: str) -> None:
    """按当前文件实际值刷新契约的文件条目（隔离逻辑等价分支，绕开哈希拒绝）。"""
    path = _package_file(config, name)
    for entry in config["files"]:
        if entry["file"] == name:
            entry["bytes"] = path.stat().st_size
            entry["sha256"] = _sha256(path)
            if entry["table"] != "*":
                _, rows = _load_csv(path)
                entry["rows"] = len(rows)
                config["table_rows"][entry["table"]] = len(rows)


def _resync_manifest(config: dict) -> None:
    """把契约的 files/table_rows 回写进 manifest 并刷新其自身哈希（隔离测试用）。"""
    manifest_path = _package_file(config, MANIFEST_NAME)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = [dict(entry) for entry in config["files"]]
    manifest["counts"] = dict(config["table_rows"])
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    config["manifest"]["bytes"] = manifest_path.stat().st_size
    config["manifest"]["sha256"] = _sha256(manifest_path)


@pytest.fixture()
def package(tmp_path) -> dict:
    config = _build_package(tmp_path)
    config["_cache_root"] = tmp_path
    return config


# ---------------------------------------------------------------------------
# 合法包：全表逻辑等价通过 + 报告口径
# ---------------------------------------------------------------------------

def test_valid_package_passes_full_table_equivalence(package):
    report = validate_ecology_seed_package(_contract(package), Path(package["_cache_root"]))
    assert report.ok, report.issue_codes()
    assert report.files_checked == 8
    assert report.files_hashed == 8
    assert report.tables_compared == 7
    assert report.rows_compared == TOTAL_ROWS  # 7 表全部行按主键逐一比对
    assert report.issue_codes() == []
    # 清单外表显式报告（不作通过条件）。
    assert any("datasets" in note for note in report.notes)
    assert any("quantity_value" in note and "NULL" in note for note in report.notes)
    assert any("qc.verdict" in note for note in report.notes)


def test_world_binding_matches(package):
    assert ecology_seed_world_binding_errors("brookvale-town-001", _contract(package)) == []


def test_world_binding_mismatch_rejected(package):
    seed = _contract(package)
    errors = ecology_seed_world_binding_errors("another-world-001", seed)
    assert errors and "another-world-001" in errors[0]


# ---------------------------------------------------------------------------
# 失败关闭：包身份 / manifest / 文件层
# ---------------------------------------------------------------------------

def test_missing_manifest_rejected(package):
    _package_file(package, MANIFEST_NAME).unlink()
    report = validate_ecology_seed_package(_contract(package), Path(package["_cache_root"]))
    assert not report.ok
    assert "manifest_missing" in report.issue_codes()


def test_manifest_self_hash_rejected(package):
    # manifest 被追加字节（内容仍可解析）→ 我方实测冻结的自身哈希拒绝。
    path = _package_file(package, MANIFEST_NAME)
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    report = validate_ecology_seed_package(_contract(package), Path(package["_cache_root"]))
    assert not report.ok
    assert "manifest_hash" in report.issue_codes()


def test_package_identity_rejected(package):
    manifest_path = _package_file(package, MANIFEST_NAME)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = "1.1"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    package["manifest"]["bytes"] = manifest_path.stat().st_size
    package["manifest"]["sha256"] = _sha256(manifest_path)
    report = validate_ecology_seed_package(_contract(package), Path(package["_cache_root"]))
    assert not report.ok
    assert "seed_version" in report.issue_codes()


def test_missing_file_rejected(package):
    _package_file(package, "occurrences.csv").unlink()
    report = validate_ecology_seed_package(_contract(package), Path(package["_cache_root"]))
    assert not report.ok
    assert "file_missing" in report.issue_codes()


def test_tampered_file_hash_rejected(package):
    _package_file(package, "taxa.csv").write_bytes(b"tampered")
    report = validate_ecology_seed_package(_contract(package), Path(package["_cache_root"]))
    assert not report.ok
    assert "file_hash" in report.issue_codes()


def test_corrupt_sqlite_rejected(package):
    _package_file(package, SQLITE_NAME).write_bytes(b"not a sqlite file")
    report = validate_ecology_seed_package(_contract(package), Path(package["_cache_root"]))
    assert not report.ok
    assert "file_hash" in report.issue_codes()
    assert "sqlite_read" in report.issue_codes()


def test_manifest_rows_contract_rejected(package):
    manifest_path = _package_file(package, MANIFEST_NAME)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["counts"]["taxa"] = 13
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    package["manifest"]["bytes"] = manifest_path.stat().st_size
    package["manifest"]["sha256"] = _sha256(manifest_path)
    report = validate_ecology_seed_package(_contract(package), Path(package["_cache_root"]))
    assert not report.ok
    assert "table_rows" in report.issue_codes()


# ---------------------------------------------------------------------------
# 失败关闭：SQLite↔CSV 全表逻辑等价（隔离分支：刷新哈希后纯逻辑比对）
# ---------------------------------------------------------------------------

def _isolated_csv_mutation(package, mutate):
    """改 CSV → 刷新契约与 manifest（绕开哈希/行数入口拒绝），只留逻辑等价差异。"""
    path = _package_file(package, "taxa.csv")
    header, rows = _load_csv(path)
    rows = mutate(rows)
    _save_csv(path, header, rows)
    _refresh_file_entry(package, "taxa.csv")
    _resync_manifest(package)
    return validate_ecology_seed_package(_contract(package), Path(package["_cache_root"]))


def test_csv_row_missing_rejected(package):
    report = _isolated_csv_mutation(package, lambda rows: rows[1:])
    assert not report.ok
    assert "csv_row_missing" in report.issue_codes()


def test_csv_row_extra_rejected(package):
    report = _isolated_csv_mutation(
        package, lambda rows: rows + [["TX_D", "Pinus tabuliformis", "species", "accepted"]],
    )
    assert not report.ok
    assert "csv_row_extra" in report.issue_codes()


def test_csv_value_mismatch_rejected(package):
    def mutate(rows):
        mutated = [list(row) for row in rows]
        mutated[0][1] = "Pinus tabuliformis"  # 改科学名
        return mutated

    report = _isolated_csv_mutation(package, mutate)
    assert not report.ok
    assert "csv_value_mismatch" in report.issue_codes()


def test_csv_duplicate_pk_rejected(package):
    def mutate(rows):
        duplicated = [list(row) for row in rows]
        return duplicated + [list(duplicated[0])]  # 同主键再出现一次

    report = _isolated_csv_mutation(package, mutate)
    assert not report.ok
    assert "csv_duplicate_pk" in report.issue_codes()


def test_csv_columns_mismatch_rejected(package):
    path = _package_file(package, "taxa.csv")
    header, rows = _load_csv(path)
    header = ["taxon_id", "scientific_name", "rank_x", "quality_status"]
    _save_csv(path, header, rows)
    _refresh_file_entry(package, "taxa.csv")
    _resync_manifest(package)
    report = validate_ecology_seed_package(_contract(package), Path(package["_cache_root"]))
    assert not report.ok
    assert "csv_columns" in report.issue_codes()


def test_filled_initial_state_value_rejected(package):
    # 裁决否决项的守门：给 quantity_value（SQLite 侧 NULL）填入推测值 → 拒绝。
    path = _package_file(package, "initial_states.csv")
    header, rows = _load_csv(path)
    for row in rows:
        row[header.index("quantity_value")] = "0.5"
    _save_csv(path, header, rows)
    _refresh_file_entry(package, "initial_states.csv")
    _resync_manifest(package)
    report = validate_ecology_seed_package(_contract(package), Path(package["_cache_root"]))
    assert not report.ok
    assert "csv_value_mismatch" in report.issue_codes()


# ---------------------------------------------------------------------------
# 逻辑等价口径单测（NULL↔空串；数值按值；文本精确含尾随空格）
# ---------------------------------------------------------------------------

def test_value_equivalence_rules():
    assert _csv_sqlite_value_equal(None, "")
    assert not _csv_sqlite_value_equal(None, "0")
    assert not _csv_sqlite_value_equal(None, "NULL")
    assert _csv_sqlite_value_equal(18.0, "18.0")
    assert _csv_sqlite_value_equal(18.0, "18")  # 数值相等即等价（"18" ↔ 18.0）
    assert _csv_sqlite_value_equal(18.0, "18.00")
    assert not _csv_sqlite_value_equal(18.0, "")
    assert not _csv_sqlite_value_equal(18.0, "abc")
    assert _csv_sqlite_value_equal(1158, "1158")
    assert _csv_sqlite_value_equal(0.841743119266055, "0.841743119266055")
    assert _csv_sqlite_value_equal("GloBI; ", "GloBI; ")  # 尾随空格保留
    assert not _csv_sqlite_value_equal("GloBI; ", "GloBI;")
    assert _csv_sqlite_value_equal("", "")
    assert _csv_sqlite_value_equal("CC_BY_4_0", "CC_BY_4_0")


# ---------------------------------------------------------------------------
# 确定性
# ---------------------------------------------------------------------------

def test_validation_is_deterministic(package):
    first = validate_ecology_seed_package(_contract(package), Path(package["_cache_root"]))
    second = validate_ecology_seed_package(_contract(package), Path(package["_cache_root"]))
    assert first.ok and second.ok
    assert first.issue_codes() == second.issue_codes()
    assert first.notes == second.notes
    assert (first.files_checked, first.tables_compared, first.rows_compared) == (
        second.files_checked, second.tables_compared, second.rows_compared,
    )


# ---------------------------------------------------------------------------
# 坏配置加载即报错
# ---------------------------------------------------------------------------

def _valid_contract_kwargs(package) -> dict:
    data = {key: value for key, value in package.items() if not key.startswith("_")}
    return json.loads(json.dumps(data))  # 深拷贝


def test_bad_config_missing_table_rows_entry_rejected(package):
    kwargs = _valid_contract_kwargs(package)
    del kwargs["table_rows"]["traits"]
    with pytest.raises(ValidationError):
        EcologySeedConfig(**kwargs)


def test_bad_config_duplicate_file_rejected(package):
    kwargs = _valid_contract_kwargs(package)
    kwargs["files"] = kwargs["files"] + [dict(kwargs["files"][0])]
    with pytest.raises(ValidationError):
        EcologySeedConfig(**kwargs)


def test_bad_config_two_sqlite_carriers_rejected(package):
    kwargs = _valid_contract_kwargs(package)
    extra = dict(kwargs["files"][-1])
    extra["file"] = "second.sqlite"
    kwargs["files"] = kwargs["files"] + [extra]
    with pytest.raises(ValidationError):
        EcologySeedConfig(**kwargs)


def test_bad_config_rows_inconsistency_rejected(package):
    kwargs = _valid_contract_kwargs(package)
    kwargs["files"][0]["rows"] = 99  # taxa.csv 行数与 table_rows 不一致
    with pytest.raises(ValidationError):
        EcologySeedConfig(**kwargs)


def test_bad_config_sqlite_carrier_rows_not_null_rejected(package):
    kwargs = _valid_contract_kwargs(package)
    kwargs["files"][-1]["rows"] = 1394
    with pytest.raises(ValidationError):
        EcologySeedConfig(**kwargs)


# ---------------------------------------------------------------------------
# 在库契约（world.yaml 冻结值）
# ---------------------------------------------------------------------------

def test_in_repo_world_contract_is_wellformed():
    config = load_config("brookvale-town-001")
    seed = config.world.ecology_seed
    assert seed is not None
    assert seed.seed_id == "ecology_seed_v1"
    assert seed.version == "1.0"
    assert seed.world_ref == "brookvale-town-001"
    assert seed.manifest.sha256 == "27d30b76bf53450d6b7db0ba64b46f5a1246dec005b9c4fb120b41d0dd1f5b44"
    assert seed.source.release == "ecology-seed-v1.0"
    assert seed.source.revision == "034384412dacf3ea5289a32c01af6088aa2c7bfa"
    assert seed.location.package_dir == "ecology_seed_v1"
    assert len(seed.files) == 8
    assert sum(1 for entry in seed.files if entry.table == "*") == 1
    assert seed.table_rows == {
        "taxa": 14, "species_records": 1254, "functional_groups": 5,
        "traits": 14, "ecological_interactions": 30,
        "habitat_associations": 24, "initial_state": 53,
    }
    assert ecology_seed_world_binding_errors(config.world.world_id, seed) == []


def test_in_repo_world_uses_shared_cache_root_default():
    # 两线共用缓存根（裁决③④）：同一 resolve_cache_root，包目录隔离。
    root = resolve_cache_root(REPO_ROOT)
    config = load_config("brookvale-town-001")
    assert config.world.environment_seed is not None
    assert config.world.environment_seed.location.package_dir != config.world.ecology_seed.location.package_dir


# ---------------------------------------------------------------------------
# CLI 入口（仅命令行入口，校验逻辑在模块内）
# ---------------------------------------------------------------------------

def _run_cli(package: dict, *extra: str) -> subprocess.CompletedProcess:
    contract_yaml = Path(package["_cache_root"]) / "contract.yaml"
    contract_yaml.write_text(
        yaml.safe_dump({k: v for k, v in package.items() if not k.startswith("_")}, allow_unicode=True),
        encoding="utf-8",
    )
    return subprocess.run(
        [sys.executable, "scripts/check_seed.py",
         "--contract", str(contract_yaml), "--seed", "ecology",
         "--cache-root", str(package["_cache_root"]), *extra],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
        stdin=subprocess.DEVNULL,
    )


def test_cli_passes_valid_ecology_package(package):
    result = _run_cli(package)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "通过" in result.stdout
    assert "全表逻辑等价" in result.stdout


def test_cli_rejects_tampered_ecology_package(package):
    _package_file(package, "taxa.csv").write_bytes(b"tampered")
    result = _run_cli(package)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "file_hash" in result.stdout


def test_cli_rejects_missing_manifest_ecology_package(package):
    _package_file(package, MANIFEST_NAME).unlink()
    result = _run_cli(package)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "manifest_missing" in result.stdout


def test_cli_rejects_bad_contract_file(package):
    contract_yaml = Path(package["_cache_root"]) / "bad_contract.yaml"
    contract_yaml.write_text("seed_id: broken\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "scripts/check_seed.py",
         "--contract", str(contract_yaml), "--seed", "ecology",
         "--cache-root", str(package["_cache_root"])],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 2, result.stdout + result.stderr


def test_cli_contract_with_seed_all_rejected(package):
    result = _run_cli(package, "--seed", "all")
    assert result.returncode == 2, result.stdout + result.stderr


def test_cli_world_path_validates_ecology_seed(tmp_path):
    # --world 路径读取在库契约；指向空缓存根应因 manifest 缺失而失败关闭（非崩溃）。
    result = subprocess.run(
        [sys.executable, "scripts/check_seed.py",
         "--world", "brookvale-town-001", "--seed", "ecology",
         "--cache-root", str(tmp_path / "empty")],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "ecology_seed.world_ref=brookvale-town-001" in result.stdout
    assert "manifest_missing" in result.stdout


def test_cli_world_path_validates_all_seeds(tmp_path):
    # --seed all：两线都读在库契约、共用缓存根；空缓存根下双双失败关闭。
    result = subprocess.run(
        [sys.executable, "scripts/check_seed.py",
         "--world", "brookvale-town-001", "--seed", "all",
         "--cache-root", str(tmp_path / "empty")],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "environment_seed" in result.stdout
    assert "ecology_seed" in result.stdout
    assert result.stdout.count("manifest_missing") == 2


def test_cli_default_seed_remains_environment(tmp_path):
    # 缺省 --seed 回归：与 P0 行为一致（默认校验 environment_seed）。
    result = subprocess.run(
        [sys.executable, "scripts/check_seed.py",
         "--world", "brookvale-town-001", "--cache-root", str(tmp_path / "empty")],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "world_ref=brookvale-town-001" in result.stdout
    assert "manifest_missing" in result.stdout
    assert "ecology" not in result.stdout
