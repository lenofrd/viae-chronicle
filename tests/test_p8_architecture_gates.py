"""P8 架构最终验收门禁（任务书 §P8 十二条）。

前六条静态架构扫描复用 ``test_architecture_boundaries`` 的扫描器与台账，
避免两套判定口径；第七条起补充运行时行为门禁。任何一条失败即架构未收口。
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

from vale.core.event_log import EventLog
from vale.core.scheduler import resolve_order, run_tick
from vale.core.world import World
from vale.world.assembly import build_world, full_modules

from test_architecture_boundaries import (
    internal_import_edges,
    test_contracts_are_never_state_writers,
    test_human_modules_read_environment_through_query_only,
    test_import_direction_rules,
    test_no_untracked_cross_domain_writes,
    test_world_state_fields_have_declared_owner,
)
from test_p7_orchestration import (
    _xigu_config,
    test_entry_points_use_unified_assembly,
    test_replay_restores_all_three_domain_containers,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


class _Module:
    """测试用最小模块：只有调度声明与空 step。"""

    def __init__(self, name: str, phase: int = 1, depends_on: tuple[str, ...] = ()) -> None:
        self.name = name
        self.phase = phase
        self.depends_on = list(depends_on)

    def step(self, world: World) -> None:
        return None


class _NoPhaseModule:
    name = "no_phase"
    depends_on: list[str] = []

    def step(self, world: World) -> None:
        return None


# ---------------------------------------------------------------------------
# 一、静态架构门禁（1–6）
# ---------------------------------------------------------------------------


def test_gate_01_state_fields_have_declared_owner() -> None:
    """1. 状态字段与领域所有者一致。"""
    test_world_state_fields_have_declared_owner()


def test_gate_02_untracked_cross_domain_writes_fail() -> None:
    """2. 未授权模块不能写入领域状态。"""
    test_no_untracked_cross_domain_writes()


def test_gate_03_contracts_never_write_state() -> None:
    """3. 契约层不能写状态。"""
    test_contracts_are_never_state_writers()


def test_gate_04_cross_domain_reads_go_through_queries() -> None:
    """4. 跨领域内部状态访问受到限制。"""
    test_human_modules_read_environment_through_query_only()


def test_gate_05_import_direction_is_correct() -> None:
    """5. 领域依赖方向正确。"""
    test_import_direction_rules()


def test_gate_06_internal_import_graph_has_no_cycle() -> None:
    """6. 领域内部不存在循环依赖。"""
    graph: dict[str, set[str]] = {}
    for importer, imported in internal_import_edges():
        if not (importer.startswith("domains.") and imported.startswith("domains.")):
            continue
        graph.setdefault(importer, set()).add(imported)
        graph.setdefault(imported, set())

    state: dict[str, int] = {}

    def visit(node: str) -> bool:
        state[node] = 1
        for nxt in graph.get(node, ()):
            if state.get(nxt) == 1:
                return True
            if state.get(nxt, 0) == 0 and visit(nxt):
                return True
        state[node] = 2
        return False

    cycles = sorted(node for node in graph if state.get(node, 0) == 0 and visit(node))
    assert cycles == [], f"领域内部存在循环依赖：{cycles}"


# ---------------------------------------------------------------------------
# 二、运行时行为门禁（7–12）
# ---------------------------------------------------------------------------


def test_gate_07_scheduler_fails_loudly() -> None:
    """7. Scheduler 对缺失依赖、重复名称和依赖环明确失败。"""
    with pytest.raises(ValueError, match="重复"):
        resolve_order([_Module("dup"), _Module("dup")])
    with pytest.raises(ValueError, match="未注册的模块 'ghost'"):
        resolve_order([_Module("needs_ghost", depends_on=("ghost",))])
    with pytest.raises(ValueError, match="依赖自身"):
        resolve_order([_Module("selfish", depends_on=("selfish",))])
    with pytest.raises(ValueError, match="依赖环"):
        resolve_order([_Module("a", depends_on=("b",)), _Module("b", depends_on=("a",))])
    with pytest.raises(ValueError, match="未声明 phase"):
        resolve_order([_NoPhaseModule()])

    world = World(world_id="dup", event_log=EventLog(":memory:"))
    world.register(_Module("same"))
    with pytest.raises(ValueError, match="模块名重复"):
        world.register(_Module("same"))


def test_gate_08_all_entry_points_use_unified_assembly() -> None:
    """8. 所有运行入口使用统一组装。"""
    test_entry_points_use_unified_assembly()


def test_gate_09_replay_is_complete_and_deterministic() -> None:
    """9. 事件 Replay 完整且确定。"""
    test_replay_restores_all_three_domain_containers()


def _run_and_dump(ticks: int, seed: int = 20261118) -> list[dict]:
    config = _xigu_config(seed)
    log = EventLog(":memory:")
    world = build_world(config, log, modules=full_modules(seed))
    for _ in range(ticks):
        run_tick(world)
    # created_at 是落盘墙钟时间，不属于模拟语义；比较调度与载荷。
    return [
        {key: value for key, value in event.items() if key != "created_at"}
        for event in log.all()
    ]


def test_gate_10_same_seed_baseline_is_reproducible() -> None:
    """10. 同种子迁移前后基线一致（当前以同种子运行逐事件等价为运行时代理）。"""
    first = _run_and_dump(ticks=3)
    second = _run_and_dump(ticks=3)
    assert first == second, "同种子、同 tick 数的事件流不一致"
    assert first, "基线运行没有产生事件"


def test_gate_11_config_and_docs_checks_are_real() -> None:
    """11. 配置和文档检查脚本真实有效（脚本自身退出码 0 才算有效）。"""
    for name in ("check_schemas.py", "check_docs_config.py"):
        path = ROOT / "scripts" / name
        spec = importlib.util.spec_from_file_location(f"gate_{path.stem}", path)
        assert spec and spec.loader, f"无法加载 {name}"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.main() == 0, f"{name} 检查未通过"


def test_gate_12_no_legacy_modules_imports() -> None:
    """12. 不存在旧 ``modules.*`` 生产导入和兼容层。"""
    legacy_dir = SRC / "vale" / "modules"
    legacy_sources = sorted(legacy_dir.rglob("*.py")) if legacy_dir.exists() else []
    assert legacy_sources == [], f"旧兼容层源码仍然存在：{legacy_sources}"
    offenders: list[str] = []
    for pattern in ("src/vale/**/*.py", "tests/**/*.py", "scripts/*.py", "viz/**/*.py"):
        for path in ROOT.glob(pattern):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module == "modules" or module.startswith(("modules.", "vale.modules")):
                        offenders.append(f"{path.relative_to(ROOT)}: from {module}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "modules" or alias.name.startswith(
                            ("modules.", "vale.modules")
                        ):
                            offenders.append(f"{path.relative_to(ROOT)}: import {alias.name}")
    assert offenders == [], "发现旧 modules.* 导入：\n" + "\n".join(offenders)
