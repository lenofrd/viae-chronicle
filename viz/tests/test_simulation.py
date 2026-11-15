from __future__ import annotations

from pathlib import Path
import re
import sqlite3
import time

import pytest

from viz.simulation import SimulationController


_WAIT_TIMEOUT = 10.0


def wait_for(predicate, description: str) -> None:
    deadline = time.monotonic() + _WAIT_TIMEOUT
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    pytest.fail(f"等待超时：{description}")


@pytest.fixture
def controller_factory():
    controllers: list[SimulationController] = []

    def factory(**kwargs) -> SimulationController:
        controller = SimulationController(**kwargs)
        controllers.append(controller)
        return controller

    yield factory

    for controller in controllers:
        controller.close()
    for controller in controllers:
        if controller.db_path:
            Path(controller.db_path).unlink(missing_ok=True)


def test_start_waits_for_ready_and_uses_new_timestamped_db(controller_factory):
    statuses = []
    controller = controller_factory(on_status=statuses.append)
    controller.start(seed=7)

    assert controller.state == "paused"
    assert controller.current_tick == 1
    assert controller.last_error is None
    assert any(status["type"] == "ready" for status in statuses)
    db_path = Path(controller.db_path)
    assert db_path.is_file()
    assert db_path.name != "cli_run.db"
    assert re.match(r"sim-\d{8}-\d{6}-\d{6}-\d+\.db$", db_path.name)

    initial_tick = controller.current_tick
    time.sleep(0.12)
    assert controller.current_tick == initial_tick

    second = controller_factory()
    second.start(seed=7)
    assert second.db_path != controller.db_path


def test_run_and_pause(controller_factory):
    controller = controller_factory()
    controller.start()
    controller.set_speed(0.03)
    initial_tick = controller.current_tick

    controller.run()
    wait_for(
        lambda: controller.current_tick >= initial_tick + 2,
        "running 状态推进至少两个 tick",
    )
    assert controller.state == "running"

    controller.pause()
    wait_for(lambda: controller.state == "paused", "pause 状态")
    paused_tick = controller.current_tick
    time.sleep(0.15)
    assert controller.current_tick == paused_tick


def test_step_advances_exactly_one_tick_while_paused(controller_factory):
    controller = controller_factory()
    controller.start()
    initial_tick = controller.current_tick

    controller.step()
    wait_for(
        lambda: controller.current_tick == initial_tick + 1,
        "单步推进一个 tick",
    )
    assert controller.state == "paused"
    time.sleep(0.12)
    assert controller.current_tick == initial_tick + 1


def test_speed_changes_tick_interval_without_advancing_paused_world(controller_factory):
    controller = controller_factory()
    controller.start()
    initial_tick = controller.current_tick
    controller.set_speed(0.15)
    time.sleep(0.05)
    assert controller.current_tick == initial_tick
    assert controller.state == "paused"

    started = time.monotonic()
    controller.run()
    wait_for(
        lambda: controller.current_tick == initial_tick + 1,
        "按 speed 间隔推进首个 tick",
    )
    assert time.monotonic() - started >= 0.10

    controller.pause()
    wait_for(lambda: controller.state == "paused", "speed 测试后的 pause 状态")


def test_stop_exits_process_preserves_db_and_close_is_idempotent(controller_factory):
    controller = controller_factory()
    controller.start()
    initial_tick = controller.current_tick
    controller.step()
    wait_for(lambda: controller.current_tick == initial_tick + 1, "stop 前单步")

    process = controller._process
    db_path = Path(controller.db_path)
    assert process is not None and process.poll() is None
    controller.stop()

    assert controller.state == "stopped"
    assert process.poll() is not None
    assert db_path.is_file()
    connection = sqlite3.connect(db_path)
    try:
        event_count = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    finally:
        connection.close()
    assert event_count > 0

    controller.close()
    with pytest.raises(RuntimeError, match="未运行"):
        controller.step()
