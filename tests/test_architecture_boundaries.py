"""架构边界测试（TASK-02 P0）。

目的：把 ADR 009 的状态所有权与依赖方向变成会失败的测试，而不是靠代码评审。
P0 只加测试、不改运行时行为；因此现有越界以「已知债务」显式登记，
债务修完后必须同步删除条目（测试会检查条目是否仍然存在，防止台账变假）。

静态扫描的已知盲区（人工复核补记，见审计文档 state-ownership.md）：
- 经工厂函数（如 ``household_of``）跨函数传递后再写字段的路径追踪不到；
- ``getattr(world.state, "...")`` 等动态访问；
- ``SpatialNode.attributes`` 内嵌的资源副本。
"""
from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

from vale.core.config_loader import LoadedConfig, load_config
from vale.core.event_log import EventLog
from vale.core.scheduler import run_tick
from vale.core.state import (
    EnvironmentState,
    HumanState,
    WildlifeState,
    WorldState,
)
from vale.core.world import World
from vale.modules.agents import AgentModule
from vale.modules.climate import ClimateModule
from vale.modules.ecology import EcologyModule
from vale.worldgen.xigu import (
    XiguGenerationConfig,
    build_xigu_agents_config,
    generate_xigu_town,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "vale"

# ---------------------------------------------------------------------------
# 一、状态所有权：谁可以写 WorldState 的哪个字段
# ---------------------------------------------------------------------------

# 字段 -> 允许写入的模块。投影模块（core.replay）单独豁免：它按事件重建状态，
# 是投影而非领域写入。未登记的字段会在 test_world_state_fields_have_declared_owner 失败。
STATE_OWNERS: dict[str, set[str]] = {
    # Environment（自然）
    "climate": {"modules.climate"},
    "water_level_ratio": {"modules.climate"},
    "irrigation_gear": {"modules.climate"},
    "ecological_resources": {"modules.ecology"},
    # P3a 水源库存：环境域状态，由取水契约（ResourceService 切片）结算写入。
    "water_sources": {"contracts.water"},
    # 农作物：按 ADR 2.3 归人文农业管理；灾害写长势属待收敛的跨域写
    "field_growth": {"modules.agents"},
    "fertility_factor": {"modules.agents"},
    "soil_quality": {"modules.agents"},
    "field_season_labor": {"modules.agents"},
    # 静态生成副本（P4 世界生成分段后归 Environment）
    "terrain_cells": {"modules.land"},
    # Human
    "agents": {"modules.agents", "modules.land", "modules.social"},
    "households": {"modules.agents", "modules.land", "modules.construction"},
    "land_parcels": {"modules.land", "modules.tenancy_economy"},
    "buildings": {"modules.land", "modules.construction"},
    "construction_projects": {"modules.construction"},
    "building_needs": {"modules.community", "modules.construction"},
    "land_leases": {"modules.tenancy_economy"},
    "resource_loans": {"modules.tenancy_economy"},
    "public_treasury": {"modules.tenancy_economy"},
    "community_reserves": {"modules.community"},
    "service_queues": {"modules.community", "modules.tenancy_economy"},
    "representatives": {"modules.governance"},
    "elections": {"modules.governance"},
    "headman_id": {"modules.governance"},
    "acting_headman_id": {"modules.governance"},
    "council_decisions": {"modules.governance"},
    "appeals": {"modules.governance"},
}

# 子容器归属（P1）：显式写死，字段被搬到错误的容器会在这里失败。
ENVIRONMENT_FIELDS = {
    "climate", "terrain_cells", "water_level_ratio", "irrigation_gear",
    "ecological_resources", "water_sources", "field_growth", "field_season_labor",
    "fertility_factor", "soil_quality",
}
HUMAN_FIELDS = {
    "agents", "households", "land_parcels", "buildings", "construction_projects",
    "land_leases", "resource_loans", "service_queues", "public_treasury",
    "community_reserves", "building_needs", "representatives", "elections",
    "headman_id", "acting_headman_id", "council_decisions", "appeals",
}
WILDLIFE_FIELDS: set[str] = set()

FIELD_CONTAINERS = {
    "environment": ENVIRONMENT_FIELDS,
    "human": HUMAN_FIELDS,
    "wildlife": WILDLIFE_FIELDS,
}
CONTAINER_OF: dict[str, str] = {
    field: container for container, fields in FIELD_CONTAINERS.items() for field in fields
}

# 已知跨域写：模块 -> 字段 -> 计划收敛阶段。修掉后必须删条目（见 test_no_untracked_cross_domain_writes）。
KNOWN_CROSS_DOMAIN_WRITES: dict[tuple[str, str], str] = {
    ("modules.agents", "ecological_resources"): "P3b：采集改走 ResourceService",
    ("modules.xigu_events", "field_growth"): "P3b：洪涝/旱灾改走 EcologicalImpact",
    ("modules.xigu_events", "fertility_factor"): "P3b：滑坡改走 EcologicalImpact",
    ("modules.xigu_events", "agents"): "P3b：野生动物伤害改走 WildlifeQuery/EcologicalImpact",
}

PROJECTION_MODULES = {"core.replay"}

# P2 读侧收口：人类模块只能经 EnvironmentQuery 读环境。
# 农事四字段按 ADR 2.3 归人类农业管理，允许直读直写。
HUMAN_OWNED_ENV_FIELDS = {
    "field_growth", "fertility_factor", "soil_quality", "field_season_labor",
}
# 尚未收敛的环境访问（修掉后必须删条目，测试会检查台账是否变假）。
HUMAN_ENV_ACCESS_EXCEPTIONS: dict[tuple[str, str], str] = {
    ("modules.agents", "ecological_resources"): "P3b：采集改走 ResourceService",
    ("modules.land", "terrain_cells"): "P4：世界生成分段后归 Environment",
}


_MUTATING_METHODS = {"append", "extend", "update", "pop", "remove", "clear", "setdefault", "add"}


def _state_field(node: ast.AST) -> str | None:
    """若表达式里出现 ``<...>.state.<container>.<field>``，返回 field。"""
    for sub in ast.walk(node):
        if not (isinstance(sub, ast.Attribute) and sub.attr in CONTAINER_OF):
            continue
        container = sub.value
        if not (isinstance(container, ast.Attribute)
                and container.attr == CONTAINER_OF[sub.attr]):
            continue
        root = container.value
        if isinstance(root, ast.Attribute) and root.attr == "state":
            return sub.attr
        if isinstance(root, ast.Name) and root.id == "state":
            return sub.attr
    return None


def _base_name(node: ast.AST) -> str | None:
    while isinstance(node, (ast.Subscript, ast.Attribute)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _scope_writes(body: list[ast.stmt]) -> set[str]:
    """返回该作用域内被写入的 WorldState 字段（含 ``pool = state.x[...]`` 式别名）。"""
    aliases: dict[str, str] = {}
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Assign):
                field = _state_field(node.value)
                if field:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            aliases[target.id] = field
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                field = _state_field(node.value)
                if field and isinstance(node.target, ast.Name):
                    aliases[node.target.id] = field

    written: set[str] = set()
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    field = _state_field(target)
                    if field:
                        written.add(field)
                    base = _base_name(target)
                    if isinstance(target, (ast.Attribute, ast.Subscript)) and base in aliases:
                        written.add(aliases[base])
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in _MUTATING_METHODS:
                    field = _state_field(node.func.value)
                    if field:
                        written.add(field)
                    base = _base_name(node.func.value)
                    if base in aliases:
                        written.add(aliases[base])
    return written


def state_writers() -> dict[str, set[str]]:
    """扫描 src/vale，返回 字段 -> 真实写入模块集合。"""
    writers: dict[str, set[str]] = {field: set() for field in STATE_OWNERS}
    for path in sorted(SRC.rglob("*.py")):
        module = path.relative_to(SRC).with_suffix("").as_posix().replace("/", ".")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        scopes: list[list[ast.stmt]] = [tree.body]
        scopes += [n.body for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for scope in scopes:
            for field in _scope_writes(scope):
                writers.setdefault(field, set()).add(module)
    return writers


def cross_domain_writes() -> set[tuple[str, str]]:
    """返回 (写入模块, 字段) 形式的跨域写集合（投影模块豁免）。"""
    return {
        (module, field)
        for field, modules in state_writers().items()
        for module in modules
        if module not in PROJECTION_MODULES and module not in STATE_OWNERS.get(field, set())
    }


def test_world_state_fields_have_declared_owner():
    """WorldState 只做组合根；每个字段必须落在登记的子容器里并声明所有者。"""
    assert set(WorldState.model_fields) == set(FIELD_CONTAINERS), (
        "WorldState 只允许 environment/human/wildlife 三个子容器："
        f"{sorted(WorldState.model_fields)}"
    )
    actual = {
        "environment": set(EnvironmentState.model_fields),
        "human": set(HumanState.model_fields),
        "wildlife": set(WildlifeState.model_fields),
    }
    for container, expected in FIELD_CONTAINERS.items():
        assert actual[container] == expected, (
            f"{container} 容器字段与登记不一致：多 {sorted(actual[container] - expected)}，"
            f"少 {sorted(expected - actual[container])}"
        )
    declared = set(STATE_OWNERS)
    actual_fields = set(CONTAINER_OF)
    assert actual_fields - declared == set(), f"未声明所有者的状态字段：{sorted(actual_fields - declared)}"
    assert declared - actual_fields == set(), f"已不存在的状态字段仍登记：{sorted(declared - actual_fields)}"


def test_no_untracked_cross_domain_writes():
    """出现新的跨域写即失败；修完债务必须同步删台账条目。"""
    detected = set(cross_domain_writes())
    known = set(KNOWN_CROSS_DOMAIN_WRITES)
    untracked = detected - known
    stale = known - detected
    assert untracked == set(), (
        "发现未登记的跨域写（先确认所有权，再决定修代码或补台账）：\n"
        + "\n".join(f"  {m} -> {f}" for m, f in sorted(untracked))
    )
    assert stale == set(), (
        "台账里的跨域写已不存在，请删除条目：\n"
        + "\n".join(f"  {m} -> {f}（{KNOWN_CROSS_DOMAIN_WRITES[(m, f)]}）" for m, f in sorted(stale))
    )


def _environment_attribute_accesses(path: Path) -> set[str]:
    """该文件里出现的 ``<...>.state.environment.<field>`` 字段集合（读或写）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fields: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Attribute) and node.attr in ENVIRONMENT_FIELDS):
            continue
        owner = node.value
        if isinstance(owner, ast.Attribute) and owner.attr == "environment":
            fields.add(node.attr)
    return fields


def test_human_modules_read_environment_through_query_only():
    """P2：人类模块读环境须经 EnvironmentQuery，不得直取环境内部字段。"""
    present: set[tuple[str, str]] = set()
    for module in sorted(HUMAN_MODULES):
        path = SRC / (module.replace(".", "/") + ".py")
        if not path.exists():
            continue
        for field in _environment_attribute_accesses(path):
            present.add((module, field))
    allowed = {(m, f) for m, f in present if f in HUMAN_OWNED_ENV_FIELDS}
    allowed |= set(HUMAN_ENV_ACCESS_EXCEPTIONS)
    offenders = present - allowed
    assert offenders == set(), (
        "人类模块直接读取环境内部字段（改用 EnvironmentQuery）：\n"
        + "\n".join(f"  {m} -> {f}" for m, f in sorted(offenders))
    )
    stale = set(HUMAN_ENV_ACCESS_EXCEPTIONS) - present
    assert stale == set(), (
        "环境访问例外已不存在，请删除台账：\n"
        + "\n".join(f"  {m} -> {f}（{HUMAN_ENV_ACCESS_EXCEPTIONS[(m, f)]}）" for m, f in sorted(stale))
    )


# ---------------------------------------------------------------------------
# 二、模块依赖方向
# ---------------------------------------------------------------------------

ENVIRONMENT_MODULES = {"modules.climate", "modules.ecology", "modules.xigu_events"}
HUMAN_MODULES = {
    "modules.agents", "modules.land", "modules.construction", "modules.governance",
    "modules.tenancy_economy", "modules.social", "modules.community",
}
ENTRY_MODULES = {"vale.cli", "vale.main", "vale.api.main"}

# 已知越界：core 依赖领域、领域互相依赖。修掉后必须删条目。
KNOWN_IMPORT_VIOLATIONS: dict[tuple[str, str], str] = {
    ("core.replay", "modules.social"): "D3：基础设施依赖人类领域（P1 消除）",
    ("modules.construction", "modules.agents"): "D1：施工依赖人类主模块（P6 抽取公共派生函数）",
    ("modules.governance", "modules.agents"): "D2：治理依赖人类主模块（P6 抽取公共派生函数）",
}


def _resolve_relative(module: str, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    parts = module.split(".")[:-1]
    keep = len(parts) - (node.level - 1)
    base = parts[:max(keep, 0)]
    return ".".join(base + ([node.module] if node.module else []))


def internal_import_edges() -> set[tuple[str, str]]:
    files = sorted(SRC.rglob("*.py"))
    known_modules = {
        path.relative_to(SRC).with_suffix("").as_posix().replace("/", ".") for path in files
    }
    edges: set[tuple[str, str]] = set()
    for path in files:
        module = path.relative_to(SRC).with_suffix("").as_posix().replace("/", ".")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                target = _resolve_relative(module, node)
                if not target.startswith(("vale.", "config.")):
                    continue
                short = target.removeprefix("vale.").removeprefix("config.")
                edges.add((module, short))
                # ``from vale.modules import social`` 的别名可能指模块，只在确为模块时计入。
                for alias in node.names:
                    candidate = f"{short}.{alias.name}"
                    if candidate in known_modules:
                        edges.add((module, candidate))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(("vale.", "config.")):
                        edges.add((module, alias.name.removeprefix("vale.").removeprefix("config.")))
    return edges


def _is_entry(target: str) -> bool:
    return target in ENTRY_MODULES or target.startswith(("vale.cli.", "vale.main.", "vale.api."))


def test_import_direction_rules():
    """基础设施不得依赖领域；自然域与人文域不得互相导入；生成/领域不得依赖入口。"""
    violations: set[tuple[str, str]] = set()
    for importer, imported in internal_import_edges():
        if _is_entry(imported) or imported == "scripts":
            violations.add((importer, imported))
        if importer.startswith("core.") and imported.startswith("modules."):
            violations.add((importer, imported))
        if importer in ENVIRONMENT_MODULES | HUMAN_MODULES:
            if importer in ENVIRONMENT_MODULES and imported in HUMAN_MODULES:
                violations.add((importer, imported))
            if importer in HUMAN_MODULES and imported in ENVIRONMENT_MODULES:
                violations.add((importer, imported))
        # 人类主模块不得被其他人文子系统反向依赖（D1/D2）。
        if importer in HUMAN_MODULES - {"modules.agents"} and imported == "modules.agents":
            violations.add((importer, imported))
        if importer.startswith("worldgen.") and imported.startswith(
            ("modules.", "observability.", "cli.", "main.")
        ):
            violations.add((importer, imported))
    known = set(KNOWN_IMPORT_VIOLATIONS)
    untracked = {edge for edge in violations if edge not in known}
    stale = {edge for edge in known if edge not in violations}
    assert untracked == set(), (
        "发现未登记的依赖越界：\n"
        + "\n".join(f"  {a} -> {b}" for a, b in sorted(untracked))
    )
    assert stale == set(), (
        "台账里的依赖越界已不存在，请删除条目：\n"
        + "\n".join(f"  {a} -> {b}（{KNOWN_IMPORT_VIOLATIONS[(a, b)]}）" for a, b in sorted(stale))
    )


# ---------------------------------------------------------------------------
# 三、配置与生成结果的一致性
# ---------------------------------------------------------------------------

# 采集产出的物品必须来自有对应语义的资源池；meat 必须来自猎物池而非林地池。
GATHERING_OUTPUT_SOURCES: dict[str, set[str]] = {
    "meat": {"game"},
    "fish": {"fish"},
    "firewood": {"firewood"},
    "herbs": {"herbs_and_hardwood"},
    "hardwood": {"herbs_and_hardwood"},
}

# 已知未消费资源池：生成后再生但没有任何采集动作指向它。
KNOWN_UNCONSUMED_POOLS = {"game_trail"}

# 已知产出与资源池语义错配（任务号 + 计划修正阶段）。
KNOWN_OUTPUT_SOURCE_MISMATCH = {
    ("hunt", "meat", "low_mountain", "herbs_and_hardwood"): "P4：猎物应绑定 game_trail",
}


@lru_cache(maxsize=1)
def _generated_config():
    base = load_config("brookvale-town-001")
    generated = generate_xigu_town(
        XiguGenerationConfig(seed=20261118), base_spatial=base.spatial
    )
    config = LoadedConfig(
        world=base.world,
        natural_params=base.natural_params,
        spatial=generated.spatial,
        agents=build_xigu_agents_config(generated, base.agents.tuning, base.agents),
        terrain=generated.terrain,
    )
    return generated, config


def test_gathering_targets_are_live_resource_nodes():
    generated, config = _generated_config()
    nodes = {node.id: node for node in generated.spatial.nodes}
    for action, cfg in config.agents.tuning.gathering.actions.items():
        assert cfg.target_node in nodes, f"{action} 的目标节点 {cfg.target_node} 不存在"
        attrs = nodes[cfg.target_node].attributes
        assert "resource_stock" in attrs, f"{action} 的目标节点 {cfg.target_node} 没有资源池"
        if not attrs.get("restricted"):
            assert attrs["resource_max_stock"] > 0, f"{action} 的目标节点池上限非法"


def test_output_source_mismatch_is_tracked():
    generated, config = _generated_config()
    resources = generated.resources
    mismatches = set()
    for action, cfg in config.agents.tuning.gathering.actions.items():
        expected = GATHERING_OUTPUT_SOURCES.get(cfg.output_field)
        pool = resources.get(cfg.target_node)
        if expected is None or pool is None:
            continue
        if pool.resource_type not in expected:
            mismatches.add((action, cfg.output_field, cfg.target_node, pool.resource_type))
    known = set(KNOWN_OUTPUT_SOURCE_MISMATCH)
    assert mismatches - known == set(), f"新增产出/资源池语义错配：{sorted(mismatches - known)}"
    assert known - mismatches == set(), f"错配已修正，请删除台账：{sorted(known - mismatches)}"


def test_unconsumed_resource_pools_are_tracked():
    """每个非禁区资源池都应有采集动作消费；新增死池会在这里失败。"""
    generated, config = _generated_config()
    consumed = {cfg.target_node for cfg in config.agents.tuning.gathering.actions.values()}
    unconsumed = {
        node_id
        for node_id, pool in generated.resources.items()
        if not pool.restricted and node_id not in consumed
    }
    assert unconsumed - KNOWN_UNCONSUMED_POOLS == set(), (
        f"新增未被任何采集动作消费的资源池：{sorted(unconsumed - KNOWN_UNCONSUMED_POOLS)}"
    )
    assert KNOWN_UNCONSUMED_POOLS - unconsumed == set(), (
        f"资源池已被消费，请删除台账：{sorted(KNOWN_UNCONSUMED_POOLS - unconsumed)}"
    )


def test_resource_pools_are_not_empty_at_generation():
    generated, _ = _generated_config()
    empty = [
        node_id for node_id, pool in generated.resources.items()
        if not pool.restricted and pool.current_stock <= 0
    ]
    assert empty == [], f"非禁区资源池库存为 0：{empty}"


def test_fertility_runtime_and_static_sources_are_separated():
    """运行期产量只读 fertility_factor；soil_quality / terrain_cells 是生成静态副本。"""
    generated, config = _generated_config()
    log = EventLog(":memory:")
    world = World(config.world.world_id, log, config.world.start_tick, config)
    world.register(ClimateModule())
    world.register(EcologyModule())
    world.register(AgentModule())
    try:
        run_tick(world)
        field_ids = {
            node.id for node in config.spatial.nodes
            if getattr(node.type, "value", node.type) == "field"
            and not node.attributes.get("abstract_zone")
        }
        assert set(world.state.environment.fertility_factor) == field_ids
        assert all(value == 1.0 for value in world.state.environment.fertility_factor.values())
        # 静态地力与生成输入逐田一致，且不进入产量计算。
        assert set(world.state.environment.soil_quality) == field_ids
        for node in config.spatial.nodes:
            if node.id in field_ids:
                assert world.state.environment.soil_quality[node.id] == float(
                    node.attributes["soil_fertility"]
                )
        # 生成输入与静态副本一致，说明 terrain_cells 只承载生成结果，不参与产量。
        source_cells = {(cell.x, cell.y): cell for cell in config.terrain}
        assert len(world.state.environment.terrain_cells) == len(source_cells)
        for cell in world.state.environment.terrain_cells.values():
            assert cell.soil_fertility == source_cells[(cell.x, cell.y)].soil_fertility
    finally:
        log.close()
