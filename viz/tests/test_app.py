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
        pump(app, lambda: "阿远" in app.agent_text.get("1.0", "end"))
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


def test_agent_profile_renders_biography_section(tmp_path):
    """角色档案在近期事件与生平阶段之间渲染「一生大事记」。"""
    events = [
        {"id": 1, "tick": 0, "event_type": "agent_born",
         "payload": {"agent_id": "a", "agent_name": "阿远", "child_id": "a",
                     "child_name": "阿远", "birth_tick": 0, "household_id": "hh_a"}},
        {"id": 2, "tick": 10, "event_type": "agent_married",
         "payload": {"agent_id": "a", "agent_name": "阿远", "spouse_id": "b",
                     "spouse_name": "阿秀", "household_id": "hh_a"}},
        {"id": 3, "tick": 20, "event_type": "agent_action_taken",
         "payload": {"agent_id": "a", "agent_name": "阿远", "action": "farm"}},
    ]
    path = tmp_path / "bio_events.json"
    path.write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"当前环境无法创建 Tk 窗口：{exc}")
    root.withdraw()
    app = ValeApp(root, EventSource.fixture(path))
    try:
        pump(app, lambda: len(app.event_rows) == 3)  # 先等后台载入完成，档案入口才放开
        app.agent_view_var.set("阿远")
        app.show_agent_profile()
        text = ""
        pump(app, lambda: "一生大事记" in app.agent_text.get("1.0", "end"))
        text = app.agent_text.get("1.0", "end")
        lines = text.splitlines()
        bio_start = next(i for i, line in enumerate(lines) if "一生大事记" in line)
        assert "2 件" in lines[bio_start]
        assert any("出生" in line for line in lines[bio_start:])
        assert any("婚配" in line for line in lines[bio_start:])
        # 传记条目只有大事记两件；劳作事件在「近期事件」段而非传记
        bio_lines = [line for line in lines[bio_start:] if line.startswith("1年") or "·" in line]
        assert sum(1 for line in bio_lines if "· 出生 ·" in line or "· 婚配 ·" in line) == 2
        assert any("生平阶段" in line for line in lines[bio_start:])
    finally:
        app.close()


def test_person_index_builds_serves_profiles_and_appends(tmp_path):
    """载入后后台建人物索引；就绪前档案走扫描、就绪后增量事件自动入索引。"""
    app = make_app(tmp_path)
    try:
        # 索引就绪（后台构建完成且通过消息回主线程）
        pump(app, lambda: app.person_index is not None)
        assert set(app.person_index) == {"a", "阿远", "b", "阿秀"}

        # 就绪后打开档案仍渲染正确
        app.agent_view_var.set("阿远")
        app.show_agent_profile()
        pump(app, lambda: "完整时间线：1 条" in app.agent_text.get("1.0", "end"))
        assert "阿远（a）" in app.agent_text.get("1.0", "end")

        # 增量新事件：事件列表与索引同步追加
        new_event = {"id": 4, "tick": 2, "event_type": "agent_action_taken",
                     "payload": {"agent_id": "c", "agent_name": "阿贵", "action": "fish"}}
        app._data_appended([new_event])
        assert app.person_index["c"][0]["id"] == 4
        assert app.person_index["阿贵"][0]["id"] == 4
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

        # 用户点击历史事件：跟随让位，选中保留，状态栏给出恢复提示
        app._select_main_event(1)
        app.root.update()
        assert app.user_pinned is True
        assert "回到最新" in app.status_var.get()
        app.apply_filters()
        pump(app, lambda: not app.loading and app.selected_event_id == 1)

        # 「回到最新」按钮：清固定、恢复跟随并选中最新
        app.back_to_latest()
        app.root.update()
        assert app.user_pinned is False
        assert app.selected_event_id == 3

        # 再次固定后，重新勾选跟随开关也能恢复
        app._select_main_event(1)
        app.root.update()
        assert app.user_pinned is True
        app.follow_latest_var.set(False)
        app.follow_latest_var.set(True)
        app._on_follow_toggled()
        app.root.update()
        assert app.user_pinned is False

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


def test_app_render_cap_trims_to_recent_rows(tmp_path):
    app = make_app(tmp_path)
    try:
        pump(app, lambda: len(app.event_rows) == 3)
        app.render_cap_var.set(2)
        app.apply_filters()
        pump(app, lambda: not app.loading and len(app.event_rows) == 2)
        children = app.event_tree.get_children("")
        assert app.event_tree.exists("cap:info")
        assert children[0] == "cap:info"
        # 只保留最近 2 条（id 2、3），最旧的 1 条被裁掉
        assert sorted(app.event_rows) == [2, 3]
        assert "截断" in app.status_var.get()
    finally:
        app.close()


def test_app_incremental_append_preserves_ui_state(tmp_path):
    """增量追加：不重建树，展开态/选中/水位保持，行被追加。"""
    app = make_app(tmp_path)
    try:
        pump(app, lambda: len(app.event_rows) == 3)
        app.sim_state = "running"
        app._select_main_event(1)
        app.root.update()
        assert app.user_pinned is True

        new_event = {
            "id": 4, "tick": 2, "event_type": "agent_action_taken",
            "payload": {"agent_id": "a", "agent_name": "阿远", "action": "farm"},
        }
        first_row_iid = app.event_tree.get_children("")[0]
        app._data_appended([new_event])
        app.root.update()

        assert app.last_event_id == 4
        assert 4 in app.event_rows and len(app.event_rows) == 4
        assert app.event_tree.index(first_row_iid) == 0  # 旧行未被动过
        # 用户固定在历史事件上：追加不打扰选中
        assert app.selected_event_id == 1 and app.user_pinned is True
        assert 4 in app.event_by_id and len(app.events) == 4
    finally:
        app.close()


def test_app_incremental_append_follows_latest_when_not_pinned(tmp_path):
    app = make_app(tmp_path)
    try:
        pump(app, lambda: len(app.event_rows) == 3)
        app.sim_state = "running"
        new_event = {
            "id": 4, "tick": 2, "event_type": "agent_action_taken",
            "payload": {"agent_id": "b", "agent_name": "阿秀", "action": "rest"},
        }
        app._data_appended([new_event])
        app.root.update()
        assert app.selected_event_id == 4  # 跟随最新
    finally:
        app.close()


def test_app_group_expansion_survives_rebuild(tmp_path):
    """按天分组重建后，用户展开的组保持展开（修复「点开即收」）。"""
    app = make_app(tmp_path)
    try:
        pump(app, lambda: len(app.event_rows) == 3)
        app.granularity_var.set("按天")
        app.apply_filters()
        pump(app, lambda: len(app.event_tree.get_children("")) == 2)
        first_group = app.event_tree.get_children("")[0]
        app.event_tree.item(first_group, open=True)
        app.root.update()

        app.apply_filters()  # 模拟一次刷新重建
        pump(app, lambda: not app.loading)
        groups_after = [
            iid for iid in app.event_tree.get_children("") if str(iid).startswith("group:")
        ]
        assert len(groups_after) == 2
        assert app.event_tree.item(groups_after[0], "open") in (1, True)
    finally:
        app.close()


def test_app_activity_granularity_and_profile_spans(tmp_path):
    app = make_app(tmp_path)
    try:
        pump(app, lambda: len(app.event_rows) == 3)
        # 主时间线「按活动聚合」：每段一行，无子行
        app.granularity_var.set("按活动聚合")
        app.apply_filters()
        pump(app, lambda: not app.loading and any("劳作" in g.label for g in app.groups))
        work_row = next(g for g in app.groups if "劳作" in g.label)
        assert "阿远" in work_row.label
        iid = next(i for i in app.event_tree.get_children("") if app.main_row_event.get(i) == 2)
        assert app.event_tree.get_children(iid) == ()  # 不展开子行

        # 角色档案「生平阶段」：劳作 1 段 1 次
        app.agent_view_var.set("阿远（a）")
        app.show_agent_profile()
        pump(app, lambda: "生平阶段" in app.agent_text.get("1.0", "end"))
        text = app.agent_text.get("1.0", "end")
        assert "劳作" in text
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
