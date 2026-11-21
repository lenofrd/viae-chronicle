"""配置 schema 与跨文件一致性检查（架构门禁 P8-11）。

检查内容：
1. 每个世界目录的四个必需 YAML 能按 Pydantic schema 校验通过；
2. YAML 顶层字段不得出现 schema 未定义的键（防拼写错误被静默忽略）；
3. 跨文件引用必须自洽：路网端点、人物家居/劳作点、采集目标、市场与作坊节点、
   田块作物都有对应节点或产量配置；水源键必须是已登记节点；
4. ``config/shared/`` 下的 YAML 必须可解析。

用法（仓库根）：``python scripts/check_schemas.py``；失败退出码 1。
"""
from __future__ import annotations

import os
import sys

import yaml

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_ROOT, "src"))

from pydantic import BaseModel, ValidationError  # noqa: E402

from vale.config.schema.agents import AgentsConfig  # noqa: E402
from vale.config.schema.natural_params import NaturalConfig  # noqa: E402
from vale.config.schema.spatial_units import SpatialConfig  # noqa: E402
from vale.config.schema.world_config import WorldConfig  # noqa: E402

CONFIG_ROOT = os.path.join(_ROOT, "config")
REQUIRED_FILES: dict[str, type[BaseModel]] = {
    "world.yaml": WorldConfig,
    "natural-params.yaml": NaturalConfig,
    "spatial-units.yaml": SpatialConfig,
    "agents.yaml": AgentsConfig,
}


def _load_yaml(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"顶层必须是映射，实际为 {type(data).__name__}")
    return data


def _unknown_top_level(data: dict, schema: type[BaseModel]) -> list[str]:
    return sorted(set(data) - set(schema.model_fields))


def _check_cross_references(
    spatial: SpatialConfig, natural: NaturalConfig, agents: AgentsConfig
) -> list[str]:
    problems: list[str] = []
    node_ids = {node.id for node in spatial.nodes}

    for edge in spatial.distance_edges:
        for endpoint in (edge.from_id, edge.to_id):
            if endpoint not in node_ids:
                problems.append(f"spatial-units: 距离边端点 '{endpoint}' 未在节点表中登记")

    for agent in agents.agents:
        for field_name in ("home_node", "work_node"):
            node = getattr(agent, field_name)
            if node not in node_ids:
                problems.append(f"agents: 人物 '{agent.id}' 的 {field_name}='{node}' 不存在")

    tuning = agents.tuning
    for action_name, action in tuning.gathering.actions.items():
        if action.target_node not in node_ids:
            problems.append(
                f"agents: 采集动作 '{action_name}' 的 target_node="
                f"'{action.target_node}' 不存在"
            )

    for node in spatial.nodes:
        if node.type.value == "field" and node.crop_type not in tuning.agriculture.base_yield:
            problems.append(
                f"agents: 田块 '{node.id}' 的作物 '{node.crop_type}' "
                f"未在 agriculture.base_yield 中配置产量"
            )

    for candidate in tuning.split.home_node_candidates or []:
        if candidate not in node_ids:
            problems.append(f"agents: split.home_node_candidates 中的 '{candidate}' 不存在")

    market_node = tuning.market.market_node
    if market_node not in node_ids:
        problems.append(f"agents: market.market_node='{market_node}' 不存在")

    for workshop in tuning.textile.workshop_nodes or []:
        if workshop not in node_ids:
            problems.append(f"agents: textile.workshop_nodes 中的 '{workshop}' 不存在")

    for source in natural.water_supply:
        if source not in node_ids:
            problems.append(f"natural-params: 水源 '{source}' 未在空间节点表中登记")

    return problems


def check_world(world_dir: str) -> list[str]:
    problems: list[str] = []
    loaded: dict[str, BaseModel] = {}
    for filename, schema in REQUIRED_FILES.items():
        path = os.path.join(world_dir, filename)
        if not os.path.exists(path):
            problems.append(f"缺少必需文件 {filename}")
            continue
        try:
            data = _load_yaml(path)
        except (OSError, yaml.YAMLError, ValueError) as exc:
            problems.append(f"{filename}: YAML 解析失败：{exc}")
            continue
        unknown = _unknown_top_level(data, schema)
        if unknown:
            problems.append(f"{filename}: schema 未定义的顶层字段 {unknown}")
        try:
            loaded[filename] = schema(**data)
        except ValidationError as exc:
            problems.append(f"{filename}: schema 校验失败：\n{exc}")

    if len(loaded) == len(REQUIRED_FILES):
        problems.extend(
            _check_cross_references(
                loaded["spatial-units.yaml"],  # type: ignore[arg-type]
                loaded["natural-params.yaml"],  # type: ignore[arg-type]
                loaded["agents.yaml"],  # type: ignore[arg-type]
            )
        )
    return problems


def check_shared_yaml() -> list[str]:
    problems: list[str] = []
    shared_root = os.path.join(CONFIG_ROOT, "shared")
    if not os.path.isdir(shared_root):
        return problems
    for dirpath, _, filenames in os.walk(shared_root):
        for filename in sorted(filenames):
            if not filename.endswith((".yaml", ".yml")):
                continue
            path = os.path.join(dirpath, filename)
            rel = os.path.relpath(path, _ROOT)
            try:
                with open(path, encoding="utf-8") as handle:
                    # 空文件 = 该组共享约束暂未启用，允许；非空则必须是映射。
                    data = yaml.safe_load(handle)
                if data is not None and not isinstance(data, dict):
                    raise ValueError(f"顶层必须是映射，实际为 {type(data).__name__}")
            except (OSError, yaml.YAMLError, ValueError) as exc:
                problems.append(f"{rel}: 解析失败：{exc}")
    return problems


def main() -> int:
    worlds_root = os.path.join(CONFIG_ROOT, "worlds")
    world_dirs = sorted(
        os.path.join(worlds_root, name)
        for name in os.listdir(worlds_root)
        if os.path.isdir(os.path.join(worlds_root, name))
    )
    failures: dict[str, list[str]] = {}
    for world_dir in world_dirs:
        problems = check_world(world_dir)
        if problems:
            failures[os.path.basename(world_dir)] = problems

    shared_problems = check_shared_yaml()
    if shared_problems:
        failures["config/shared"] = shared_problems

    if failures:
        print(f"schema 检查失败（{len(failures)} 组）：")
        for scope, problems in failures.items():
            print(f"\n[{scope}]")
            for problem in problems:
                print(f"  - {problem}")
        return 1

    print(f"schema 检查通过：{len(world_dirs)} 个世界目录 + shared YAML")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
