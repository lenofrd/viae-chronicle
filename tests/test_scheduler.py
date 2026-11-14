"""阶段三测试：Tick 调度器与错误隔离。"""
from __future__ import annotations

from vale.core.event_log import EventLog
from vale.core.scheduler import run_tick
from vale.core.world import World


class GoodModule:
    name = "good"

    def __init__(self) -> None:
        self.ran = False

    def step(self, world: World) -> None:
        self.ran = True


class BadModule:
    name = "bad"

    def step(self, world: World) -> None:
        raise RuntimeError("boom")


class LateGoodModule:
    """注册在坏模块之后，用来验证坏模块崩溃后后续模块仍会执行。"""

    name = "late_good"

    def __init__(self) -> None:
        self.ran = False

    def step(self, world: World) -> None:
        self.ran = True


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
