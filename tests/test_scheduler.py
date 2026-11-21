"""阶段三/七测试：Tick 调度器、显式阶段排序与配置错误失败。"""
from __future__ import annotations

import pytest

from vale.core.event_log import EventLog
from vale.core.scheduler import resolve_order, run_tick
from vale.core.world import PHASE_ECOLOGY, PHASE_NATURAL, World


class GoodModule:
    name = "good"
    phase = PHASE_NATURAL
    depends_on: list[str] = []

    def __init__(self) -> None:
        self.ran = False

    def step(self, world: World) -> None:
        self.ran = True


class BadModule:
    name = "bad"
    phase = PHASE_NATURAL
    depends_on: list[str] = []

    def step(self, world: World) -> None:
        raise RuntimeError("boom")


class LateGoodModule:
    """注册在坏模块之后，用来验证坏模块崩溃后后续模块仍会执行。"""

    name = "late_good"
    phase = PHASE_NATURAL
    depends_on: list[str] = []

    def __init__(self) -> None:
        self.ran = False

    def step(self, world: World) -> None:
        self.ran = True


class _Recorder:
    """只记录名字的轻量模块，用于排序断言。"""

    depends_on: list[str] = []

    def __init__(self, name: str, phase: int, depends_on: list[str] | None = None) -> None:
        self.name = name
        self.phase = phase
        if depends_on is not None:
            self.depends_on = depends_on

    def step(self, world: World) -> None:  # pragma: no cover - 排序测试不跑 step
        pass


def test_error_isolation_keeps_world_running() -> None:
    log = EventLog(":memory:")
    world = World(world_id="test", event_log=log, start_tick=1)

    good = GoodModule()
    bad = BadModule()
    late = LateGoodModule()

    world.register(good)
    world.register(bad)
    world.register(late)

    # 调度器不应抛出异常
    run_tick(world)

    # 好模块都执行了（坏模块夹在中间也没阻断后续）
    assert good.ran is True
    assert late.ran is True

    # 数据库里生成了 module_error 事件，含模块名与错误信息
    errors = log.by_type("module_error")
    assert len(errors) == 1
    assert errors[0]["tick"] == 1
    payload = errors[0]["payload"]
    assert payload["module"] == "bad"
    assert "boom" in payload["error"]
    assert "Traceback" in payload["traceback"]

    # tick 正常推进
    assert world.current_tick == 2


def test_all_good_modules_run_and_advance_tick() -> None:
    log = EventLog(":memory:")
    world = World(world_id="test", event_log=log, start_tick=10)
    world.register(GoodModule())
    run_tick(world)
    assert world.current_tick == 11
    assert log.by_type("module_error") == []


def test_duplicate_module_name_fails_at_registration() -> None:
    log = EventLog(":memory:")
    world = World(world_id="test", event_log=log, start_tick=0)
    world.register(_Recorder("dup", PHASE_NATURAL))
    with pytest.raises(ValueError, match="模块名重复"):
        world.register(_Recorder("dup", PHASE_NATURAL))


def test_missing_dependency_fails() -> None:
    modules = [_Recorder("a", PHASE_NATURAL), _Recorder("b", PHASE_NATURAL, ["ghost"])]
    with pytest.raises(ValueError, match="未注册的模块"):
        resolve_order(modules)


def test_world_is_strict_by_default() -> None:
    """depends_on 是模块契约：默认 World 缺依赖即失败，不因手工组装静默忽略。"""
    world = World(world_id="test", event_log=EventLog(":memory:"), start_tick=1)
    world.register(GoodModule())
    world.register(_Recorder("needs_ghost", PHASE_NATURAL, ["ghost"]))
    with pytest.raises(ValueError, match="未注册的模块 'ghost'"):
        run_tick(world)


def test_isolated_fixture_can_declare_missing_dependencies_allowed() -> None:
    """孤立模块夹具必须显式声明例外，才允许缺失依赖。"""
    world = World(
        world_id="test",
        event_log=EventLog(":memory:"),
        start_tick=1,
        allow_missing_dependencies=True,
    )
    world.register(GoodModule())
    world.register(_Recorder("needs_ghost", PHASE_NATURAL, ["ghost"]))
    run_tick(world)
    assert world.current_tick == 2


def test_dependency_cycle_fails() -> None:
    modules = [
        _Recorder("a", PHASE_NATURAL, ["b"]),
        _Recorder("b", PHASE_NATURAL, ["a"]),
    ]
    with pytest.raises(ValueError, match="依赖环"):
        resolve_order(modules)


def test_self_dependency_fails() -> None:
    with pytest.raises(ValueError, match="依赖自身"):
        resolve_order([_Recorder("a", PHASE_NATURAL, ["a"])])


def test_module_without_phase_fails() -> None:
    class NoPhase:
        name = "no_phase"
        depends_on: list[str] = []

        def step(self, world: World) -> None:  # pragma: no cover
            pass

    with pytest.raises(ValueError, match="未声明 phase"):
        resolve_order([NoPhase()])


def test_phase_overrides_registration_order() -> None:
    """阶段显式：先注册人物阶段也会排在自然阶段之后，不靠注册顺序。"""
    modules = [
        _Recorder("agents", 4, ["climate", "ecology"]),
        _Recorder("climate", PHASE_NATURAL),
        _Recorder("ecology", PHASE_ECOLOGY, ["climate"]),
    ]
    assert [m.name for m in resolve_order(modules)] == ["climate", "ecology", "agents"]


def test_dependency_overrides_phase() -> None:
    """依赖优先于阶段：被依赖模块先执行，即便它声明了更晚的阶段。"""
    modules = [
        _Recorder("society", 4, ["natural"]),
        _Recorder("natural", 5),
    ]
    assert [m.name for m in resolve_order(modules)] == ["natural", "society"]
