from __future__ import annotations

import json
import time
import tkinter as tk

import pytest

from viz.app import ValeApp
from viz.data import EventSource


def make_fixture(tmp_path):
    events = [
        {"id": 1, "tick": 0, "event_type": "weather_changed",
         "payload": {"weather": "sunny", "temperature_c": 22}},
        {"id": 2, "tick": 0, "event_type": "agent_action_taken",
         "payload": {"agent_id": "a", "agent_name": "阿远", "action": "farm", "target_node": "field_west"}},
        {"id": 3, "tick": 1, "event_type": "agent_action_taken",
         "payload": {"agent_id": "b", "agent_name": "阿秀", "action": "rest", "target_node": "home"}},
    ]
    path = tmp_path / "events.json"
    path.write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")
    return path


def pump(app, predicate, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.root.update()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("等待界面异步更新超时")


def make_app(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"当前环境无法创建 Tk 窗口：{exc}")
    root.withdraw()
    app = ValeApp(root, EventSource.fixture(make_fixture(tmp_path)))
    app.auto_refresh_var.set(False)
    return app


def test_app_load_filter_group_and_select(tmp_path):
    app = make_app(tmp_path)
    try:
        pump(app, lambda: len(app.filtered) == 3 and len(app.event_rows) == 3)
        assert app.event_tree.get_children()

        app.type_var.set("agent_action_taken")
        app.from_var.set("0")
        app.to_var.set("0")
        app.apply_filters()
        pump(app, lambda: len(app.filtered) == 1 and len(app.event_rows) == 1)
        assert app.filtered[0]["id"] == 2

        app._select_main_event(2)
        app.root.update()
        assert "阿远" in app.summary_text.get("1.0", "end")
        assert '"agent_id": "a"' in app.json_text.get("1.0", "end")

        app.type_var.set("全部")
        app.from_var.set("")
        app.to_var.set("")
        app.granularity_var.set("按天")
        app.apply_filters()
        pump(app, lambda: len(app.groups) == 2 and len(app.event_rows) == 3)
        assert len(app.event_tree.get_children()) == 2
    finally:
        app.close()


def test_app_profile_focus_and_favorite_navigation(tmp_path):
    app = make_app(tmp_path)
    try:
        pump(app, lambda: len(app.event_rows) == 3)
        app._select_main_event(2)
        app.open_selected_agent()
        assert "阿远" in app.agent_text.get("1.0", "end")
        assert len(app.profile_row_event["agent"]) == 1

        app.favorite_current_agent()
        app.favorite_selected_event()
        assert app.favorite_people == {"a"}
        assert app.favorite_events == {2}
        assert len(app.favorite_tree.get_children()) == 2
        assert "共 1 条" in app.focus_count_vars["work"].get()

        app.type_var.set("weather_changed")
        app.apply_filters()
        pump(app, lambda: len(app.event_rows) == 1)
        app.jump_to_event(2)
        pump(app, lambda: app.selected_event_id == 2 and len(app.event_rows) == 3)
        assert app.type_var.get() == "全部"
    finally:
        app.close()


def test_app_follow_latest_while_running(tmp_path):
    """运行中跟随最新：自动选中最新事件；用户固定历史事件时不打扰、点回最新后恢复。"""
    app = make_app(tmp_path)
    try:
        pump(app, lambda: len(app.event_rows) == 3)

        # 非运行状态：刷新保持用户选中，不自动跳最新
        app._select_main_event(1)
        app.apply_filters()
        pump(app, lambda: not app.loading and app.selected_event_id == 1)

        # 运行中 + 跟随开：刷新自动选中并显示最新事件
        app.sim_state = "running"
        app.apply_filters()
        pump(app, lambda: app.selected_event_id == 3)
        assert app.user_pinned is False

        # 用户点击历史事件：跟随让位，选中保留
        app._select_main_event(1)
        app.root.update()
        assert app.user_pinned is True
        app.apply_filters()
        pump(app, lambda: not app.loading and app.selected_event_id == 1)

        # 点回最新事件：恢复跟随
        app._select_main_event(3)
        app.root.update()
        app.apply_filters()
        pump(app, lambda: app.selected_event_id == 3 and not app.loading)

        # 关闭跟随开关：刷新不再跳最新
        app.follow_latest_var.set(False)
        app._select_main_event(1)
        app.root.update()
        app.apply_filters()
        pump(app, lambda: not app.loading and app.selected_event_id == 1)
    finally:
        app.close()


def test_app_real_simulation_controls_and_auto_refresh(tmp_path):
    app = make_app(tmp_path)
    db_path = None
    try:
        pump(app, lambda: len(app.event_rows) == 3)
        app.auto_refresh_var.set(True)
        app.start_simulation()
        pump(
            app,
            lambda: (
                app.controller is not None
                and app.controller.state == "paused"
                and not app.sim_starting
                and app.source.kind == "db"
            ),
            timeout=30,
        )
        controller = app.controller
        db_path = app.source.path
        initial_tick = controller.current_tick

        app.run_simulation()
        pump(app, lambda: controller.current_tick >= initial_tick + 2, timeout=15)
        assert app.sim_state == "running"

        app.pause_simulation()
        pump(app, lambda: app.sim_state == "paused" and controller.state == "paused")
        paused_tick = controller.current_tick
        time.sleep(0.3)
        assert controller.current_tick == paused_tick

        app.step_simulation()
        expected_label = f"当前 tick：{paused_tick + 1}"
        pump(
            app,
            lambda: controller.current_tick == paused_tick + 1 and app.tick_var.get() == expected_label,
        )
        time.sleep(0.3)
        app.root.update()
        assert controller.current_tick == paused_tick + 1
        assert app.tick_var.get() == expected_label

        app.speed_var.set("4×")
        app.change_speed()
        time.sleep(0.3)
        assert controller.current_tick == paused_tick + 1
        assert "失败" not in app.sim_status_var.get()

        process = controller._process
        pump(app, lambda: len(app.events) > 0 and not app.loading, timeout=15)
        app.stop_simulation()
        pump(app, lambda: app.sim_state == "stopped" and controller.state == "stopped", timeout=15)
        # worker 的最后一条 stopped 消息可能早于进程完全退出到达：显式等待进程退出
        assert process is not None
        deadline = time.monotonic() + 10
        while process.poll() is None and time.monotonic() < deadline:
            app.root.update()
            time.sleep(0.01)
        assert process.poll() is not None
        assert db_path.is_file()
    finally:
        app.close()
        if db_path is not None:
            db_path.unlink(missing_ok=True)
