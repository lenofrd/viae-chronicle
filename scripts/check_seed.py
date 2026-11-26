"""静态校验 Environment Seed 数据包（ADR 011 · P0 的命令行入口）。

校验逻辑在 ``vale.world.seed_contract``（可复用模块，P2 Loader 复用）；
本文件只做参数解析、契约获取与报告输出，不承载校验实现。

用法（仓库根）：

  python scripts/check_seed.py --world brookvale-town-001 [--cache-root <dir>]
  python scripts/check_seed.py --contract <environment_seed 节 YAML> --cache-root <dir>

缓存根缺省取环境变量 ``VALE_SEED_CACHE``，否则 ``<仓库根>/data/seed-cache``
（数据包由部署环境下载/挂载，Viae 不做下载）。

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

from vale.config.schema.environment_seed import EnvironmentSeedConfig  # noqa: E402
from vale.core.config_loader import load_config  # noqa: E402
from vale.world.seed_contract import (  # noqa: E402
    SeedValidationReport,
    resolve_cache_root,
    seed_world_binding_errors,
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="静态校验 Environment Seed 数据包（失败关闭）")
    parser.add_argument("--world", default="brookvale-town-001", help="从该世界配置读取 environment_seed 契约")
    parser.add_argument("--contract", help="直接指定 environment_seed 节的 YAML 文件（无需整世界配置）")
    parser.add_argument("--cache-root", help="缓存根目录（覆盖 VALE_SEED_CACHE 与默认值）")
    args = parser.parse_args(argv)

    if args.contract:
        try:
            data = yaml.safe_load(Path(args.contract).read_text(encoding="utf-8"))
            seed = EnvironmentSeedConfig(**data)
        except (OSError, yaml.YAMLError, TypeError, ValueError) as exc:
            print(f"契约文件加载失败：{exc}")
            return 2
    else:
        try:
            config = load_config(args.world)
        except (OSError, yaml.YAMLError, ValueError) as exc:
            print(f"世界配置加载失败（{args.world}）：{exc}")
            return 2
        seed = config.world.environment_seed
        if seed is None:
            print(f"世界 {args.world} 未配置 environment_seed 节（该世界不接外部地理数据）")
            return 2
        world_id = config.world.world_id
        binding_errors = seed_world_binding_errors(world_id, seed)
        if binding_errors:
            for message in binding_errors:
                print(message)
            return 1
        print(f"世界身份绑定：anchor.world_ref={world_id}（唯一 world/location identity）")

    cache_root = Path(args.cache_root) if args.cache_root else resolve_cache_root(Path(ROOT))
    print(f"缓存根：{cache_root}")
    report = validate_seed_package(seed, cache_root)
    _print_report(report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
