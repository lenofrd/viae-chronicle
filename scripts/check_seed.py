"""静态校验 Environment / Ecology Seed 数据包（命令行入口）。

校验逻辑在 ``vale.world.seed_contract``（可复用模块，P2 Loader 复用）；
本文件只做参数解析、契约获取与报告输出，不承载校验实现。

用法（仓库根）：

  python scripts/check_seed.py --world brookvale-town-001 [--seed environment|ecology|all] [--cache-root <dir>]
  python scripts/check_seed.py --contract <seed 节 YAML> --seed ecology --cache-root <dir>

``--seed`` 选择数据线：``environment``（缺省，P0 地理环境包）、``ecology``
（EX-0 生态/群落数据包）、``all``（逐条校验世界配置中存在的 seed 节）。
两线共用缓存根（``VALE_SEED_CACHE`` 或缺省 ``<仓库根>/data/seed-cache``），
包目录隔离（environment_seed_v2 / ecology_seed_v1）；数据包由部署环境
下载/挂载，Viae 不做下载。

退出码：0 = 校验通过；1 = 契约不符（失败关闭）；2 = 用法/配置错误。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from vale.config.schema.ecology_seed import EcologySeedConfig  # noqa: E402
from vale.config.schema.environment_seed import EnvironmentSeedConfig  # noqa: E402
from vale.core.config_loader import load_config  # noqa: E402
from vale.world.seed_contract import (  # noqa: E402
    EcologySeedValidationReport,
    SeedValidationReport,
    ecology_seed_world_binding_errors,
    resolve_cache_root,
    seed_world_binding_errors,
    validate_ecology_seed_package,
    validate_seed_package,
)


def _print_report(report: SeedValidationReport) -> None:
    print(f"manifest：{report.manifest_path}")
    print(f"seed：{report.seed_id}；必需资产核对 {report.assets_checked} 项；本地文件哈希复算 {report.files_hashed} 件")
    for note in report.notes:
        print(f"  说明：{note}")
    if report.issues:
        print("契约不符（失败关闭）：")
        for issue in report.issues:
            print(f"  [{issue.code}] {issue.message}")
        print("结论：拒绝")
    else:
        print("结论：通过")


def _print_ecology_report(report: EcologySeedValidationReport) -> None:
    print(f"manifest：{report.manifest_path}")
    print(
        f"package：{report.seed_id}；文件核对 {report.files_checked} 件"
        f"（哈希复算 {report.files_hashed}）；表比对 {report.tables_compared} 张、"
        f"按主键逐行比对 {report.rows_compared} 行（全表逻辑等价）"
    )
    for note in report.notes:
        print(f"  说明：{note}")
    if report.issues:
        print("契约不符（失败关闭）：")
        for issue in report.issues:
            print(f"  [{issue.code}] {issue.message}")
        print("结论：拒绝")
    else:
        print("结论：通过")


def _load_contract_node(path: str) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"契约文件顶层必须是映射，实际为 {type(data).__name__}")
    return data


def _run_contract_file(contract_path: str, seed_kind: str, cache_root: Path) -> int:
    try:
        data = _load_contract_node(contract_path)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        print(f"契约文件加载失败：{exc}")
        return 2
    if seed_kind == "environment":
        try:
            seed = EnvironmentSeedConfig(**data)
        except (TypeError, ValueError) as exc:
            print(f"environment_seed 契约非法：{exc}")
            return 2
        report = validate_seed_package(seed, cache_root)
        _print_report(report)
        return 0 if report.ok else 1
    try:
        seed = EcologySeedConfig(**data)
    except (TypeError, ValueError) as exc:
        print(f"ecology_seed 契约非法：{exc}")
        return 2
    report = validate_ecology_seed_package(seed, cache_root)
    _print_ecology_report(report)
    return 0 if report.ok else 1


def _run_environment_world(config, cache_root: Path, single: bool) -> int:
    seed = config.world.environment_seed
    if seed is None:
        print(f"世界 {config.world.world_id} 未配置 environment_seed 节（该世界不接外部地理数据）")
        return 2 if single else 0
    binding_errors = seed_world_binding_errors(config.world.world_id, seed)
    if binding_errors:
        for message in binding_errors:
            print(message)
        return 1
    print(f"世界身份绑定：environment_seed.anchor.world_ref={config.world.world_id}（唯一 world/location identity）")
    report = validate_seed_package(seed, cache_root)
    _print_report(report)
    return 0 if report.ok else 1


def _run_ecology_world(config, cache_root: Path, single: bool) -> int:
    seed = config.world.ecology_seed
    if seed is None:
        print(f"世界 {config.world.world_id} 未配置 ecology_seed 节（该世界不接生态/群落数据线）")
        return 2 if single else 0
    binding_errors = ecology_seed_world_binding_errors(config.world.world_id, seed)
    if binding_errors:
        for message in binding_errors:
            print(message)
        return 1
    print(f"世界身份绑定：ecology_seed.world_ref={config.world.world_id}（唯一 world/location identity）")
    report = validate_ecology_seed_package(seed, cache_root)
    _print_ecology_report(report)
    return 0 if report.ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="静态校验 Environment / Ecology Seed 数据包（失败关闭）")
    parser.add_argument("--world", default="brookvale-town-001", help="从该世界配置读取 seed 契约")
    parser.add_argument("--contract", help="直接指定单个 seed 节的 YAML 文件（无需整世界配置）")
    parser.add_argument("--cache-root", help="缓存根目录（覆盖 VALE_SEED_CACHE 与默认值）")
    parser.add_argument(
        "--seed", choices=("environment", "ecology", "all"), default="environment",
        help="校验哪条数据线（all = 逐条校验世界配置中存在的 seed 节）",
    )
    args = parser.parse_args(argv)

    if args.contract and args.seed == "all":
        print("--contract 只承载单个 seed 节，与 --seed all 不兼容")
        return 2

    if args.contract:
        cache_root = Path(args.cache_root) if args.cache_root else resolve_cache_root(Path(ROOT))
        print(f"缓存根：{cache_root}")
        return _run_contract_file(args.contract, args.seed, cache_root)

    try:
        config = load_config(args.world)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        print(f"世界配置加载失败（{args.world}）：{exc}")
        return 2

    cache_root = Path(args.cache_root) if args.cache_root else resolve_cache_root(Path(ROOT))
    print(f"缓存根：{cache_root}")
    targets = ["environment", "ecology"] if args.seed == "all" else [args.seed]
    exit_code = 0
    for kind in targets:
        if kind == "environment":
            code = _run_environment_world(config, cache_root, single=len(targets) == 1)
        else:
            code = _run_ecology_world(config, cache_root, single=len(targets) == 1)
        exit_code = max(exit_code, code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
