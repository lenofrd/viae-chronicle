"""P7 世界协调验收：统一组装、显式阶段顺序、入口不得各自维护模块清单。"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from vale.core.config_loader import LoadedConfig, load_config
from vale.core.event_log import EventLog
from vale.core.scheduler import resolve_order, run_tick
from vale.world.assembly import base_town_modules, build_world, full_modules, viz_modules
from vale.world.replay import rebuild_state
from vale.world.xigu import XiguGenerationConfig, build_xigu_agents_config, generate_xigu_town

ROOT = Path(__file__).resolve().parents[1]


def _xigu_config(seed: int = 20261118) -> LoadedConfig:
    base = load_config("brookvale-town-001")
    generated = generate_xigu_town(
        XiguGenerationConfig(seed=seed), base_spatial=base.spatial
    )
    return LoadedConfig(
        world=base.world,
        natural_params=base.natural_params,
        spatial=generated.spatial,
        agents=build_xigu_agents_config(generated, base.agents.tuning, base.agents),
        terrain=generated.terrain,
        resources=generated.resources,
    )


def test_full_profile_order_is_natural_then_ecology_then_wildlife_then_society_then_impact() -> None:
    world = build_world(_xigu_config(), EventLog(":memory:"), modules=full_modules(20261118))
    assert [m.name for m in resolve_order(world.modules)] == [
        "climate", "ecology", "wildlife", "agents", "tenancy_economy", "xigu_events",
    ]


def test_all_profiles_declare_phase_and_resolve() -> None:
    for modules in (full_modules(1), base_town_modules(), viz_modules(1)):
        for module in modules:
            assert isinstance(module.phase, int), module.name
        resolve_order(modules)


def test_build_world_is_strict_about_declared_dependencies() -> None:
    """统一组装入口缺依赖即失败；World 默认严格，局部夹具须显式声明例外。"""
    from vale.domains.environment.climate import ClimateModule
    from vale.domains.society.agents import AgentModule

    with pytest.raises(ValueError, match="未注册的模块 'ecology'"):
        build_world(
            _xigu_config(), EventLog(":memory:"), modules=[ClimateModule(), AgentModule()]
        )

    world = build_world(_xigu_config(), EventLog(":memory:"), modules=full_modules(1))
    assert world.allow_missing_dependencies is False


def test_entry_points_use_unified_assembly() -> None:
    """三个运行入口只选择 profile，不得各自 world.register(...) 维护业务模块清单。"""
    for name in ("scripts/run_xigu.py", "src/vale/cli.py", "viz/sim_worker.py"):
        source = (ROOT / name).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "vale.world.assembly"
            for alias in node.names
        }
        assert {"build_world"} <= imported, f"{name} 未使用统一组装入口"
        assert ".register(" not in source, f"{name} 仍在自行注册业务模块"


def test_replay_restores_all_three_domain_containers() -> None:
    config = _xigu_config()
    log = EventLog(":memory:")
    world = build_world(config, log, modules=full_modules(20261118))
    for _ in range(3):
        run_tick(world)
    events = log.all()

    first = rebuild_state(events, config).state
    second = rebuild_state(events, config).state

    assert first.human.agents and first.human.households
    assert first.environment.water_sources
    assert first.wildlife.pools
    assert first.model_dump() == second.model_dump()
