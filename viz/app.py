"""Tkinter 本地桌面入口：python -m viz.app。"""
from __future__ import annotations

import argparse
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
for _path in (str(SRC_ROOT), str(REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from viz.data import (  # noqa: E402
    DEFAULT_SPAN_GAP,
    UNKNOWN,
    EventGroup,
    EventSource,
    activity_spans,
    agent_profile,
    biography,
    build_person_index,
    person_keys,
    calendar_label,
    event_details,
    event_households,
    event_locations,
    event_people,
    event_summary,
    filter_events,
    focus_category,
    focus_events,
    group_events,
    household_profile,
    location_names,
    person_label,
    turning_point,
    world_config,
)
from viz.simulation import SimulationController  # noqa: E402

ALL = "全部"
GRANULARITIES = {"逐事件": "event", "按天": "day", "按事件簇": "cluster", "按活动聚合": "activity"}
SPEEDS = {"0.5×": 2.0, "1×": 1.0, "2×": 0.5, "4×": 0.25, "全速": 0.0}
DEFAULT_RENDER_CAP = 2000
FOCUS_TITLES = {"work": "劳作", "social": "关系与生命", "economy": "经济"}
PINNED_HINT = "已暂停跟随 · 点「回到最新」恢复"


def _iid_safe(key: str) -> str:
    """Treeview iid 只去除花括号，其余字符保留以保持稳定（跨刷新恢复展开态用）。"""
    return str(key).replace("{", "").replace("}", "")


class ValeApp:
    def __init__(self, root: tk.Tk, source: EventSource, controller_factory=SimulationController) -> None:
        self.root = root
        self.source = source
        self.controller_factory = controller_factory
        self.controller = None
        self.events: list[dict[str, Any]] = []
        self.filtered: list[dict[str, Any]] = []
        self.groups = []
        self.event_by_id: dict[int, dict[str, Any]] = {}
        self.selected_event_id: Optional[int] = None
        self.pending_event_id: Optional[int] = None
        self.user_pinned = False  # 运行中用户点击非最新事件 → 暂停跟随，直至点回最新/重启模拟
        self.cfg = world_config()
        self.names = location_names(self.cfg)
        self.messages: queue.Queue = queue.Queue()
        self.closing = False
        self.loading = False
        self.refresh_pending = False
        self.load_generation = 0
        self.filter_generation = 0
        self.profile_generation = 0
        self.sim_starting = False
        self.sim_state = "stopped"
        self.last_event_id: Optional[int] = None  # 增量加载水位
        self.stream_new_hint = False  # 非流式视图下有新事件未刷
        self.favorite_people: set[str] = set()
        self.favorite_households: set[str] = set()
        self.favorite_events: set[int] = set()
        self.agent_options: dict[str, str] = {ALL: ""}
        self.location_options: dict[str, str] = {ALL: ""}
        self._people_map: dict[str, str] = {}
        self._location_map: dict[str, str] = {}
        self._type_values: set[str] = set()
        self._household_values: set[str] = set()
        self._focus_type_rows: dict[str, dict[str, str]] = {key: {} for key in FOCUS_TITLES}
        self._focus_counts: dict[str, dict[str, int]] = {key: {} for key in FOCUS_TITLES}
        self.main_row_event: dict[str, int] = {}
        self.event_rows: dict[int, str] = {}
        self.profile_row_event: dict[str, dict[str, int]] = {"agent": {}, "household": {}}
        self.focus_row_event: dict[str, dict[str, int]] = {key: {} for key in FOCUS_TITLES}
        self.favorite_row_target: dict[str, tuple[str, Any]] = {}
        # 人物事件索引：载入后后台构建，角色档案查询免全库逐事件匹配（见 _start_index_build）
        self.person_index: Optional[dict[str, list]] = None
        self.index_generation = 0
        self._index_lock = threading.Lock()
        self._index_builder: Optional[threading.Thread] = None

        self._make_variables()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(50, self._poll_messages)
        self.root.after(1000, self._auto_refresh)
        self.load_source(source)

    def _make_variables(self) -> None:
        self.source_var = tk.StringVar(value=self.source.label)
        self.status_var = tk.StringVar(value="正在加载事件…")
        self.sim_status_var = tk.StringVar(value="模拟未启动")
        self.tick_var = tk.StringVar(value="当前 tick：—")
        self.speed_var = tk.StringVar(value="1×")
        self.auto_refresh_var = tk.BooleanVar(value=True)
        self.follow_latest_var = tk.BooleanVar(value=True)
        self.type_var = tk.StringVar(value=ALL)
        self.agent_filter_var = tk.StringVar(value=ALL)
        self.household_filter_var = tk.StringVar(value=ALL)
        self.location_filter_var = tk.StringVar(value=ALL)
        self.from_var = tk.StringVar()
        self.to_var = tk.StringVar()
        self.granularity_var = tk.StringVar(value="逐事件")
        self.span_gap_var = tk.IntVar(value=DEFAULT_SPAN_GAP)
        self.render_cap_var = tk.IntVar(value=DEFAULT_RENDER_CAP)
        self.jump_var = tk.StringVar()
        self.agent_view_var = tk.StringVar()
        self.household_view_var = tk.StringVar()
        self.focus_count_vars = {key: tk.StringVar(value="尚未加载") for key in FOCUS_TITLES}

    def _build_ui(self) -> None:
        self.root.title("Vale Chronicle · 溪谷镇人生档案")
        self.root.geometry("1440x900")
        self.root.minsize(1100, 700)
        style = ttk.Style()
        style.configure("Treeview", rowheight=25)
        style.configure("Title.TLabel", font=("TkDefaultFont", 11, "bold"))

        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        run_frame = ttk.LabelFrame(outer, text="世界运行控制", padding=6)
        run_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.start_button = ttk.Button(run_frame, text="启动新模拟", command=self.start_simulation)
        self.start_button.pack(side="left")
        self.run_button = ttk.Button(run_frame, text="运行", command=self.run_simulation, state="disabled")
        self.run_button.pack(side="left", padx=(6, 0))
        self.pause_button = ttk.Button(run_frame, text="暂停", command=self.pause_simulation, state="disabled")
        self.pause_button.pack(side="left", padx=(6, 0))
        self.step_button = ttk.Button(run_frame, text="单步", command=self.step_simulation, state="disabled")
        self.step_button.pack(side="left", padx=(6, 0))
        self.stop_button = ttk.Button(run_frame, text="停止", command=self.stop_simulation, state="disabled")
        self.stop_button.pack(side="left", padx=(6, 0))
        ttk.Label(run_frame, text="速度").pack(side="left", padx=(14, 3))
        speed = ttk.Combobox(run_frame, textvariable=self.speed_var, values=list(SPEEDS), width=6, state="readonly")
        speed.pack(side="left")
        speed.bind("<<ComboboxSelected>>", lambda _event: self.change_speed())
        ttk.Checkbutton(run_frame, text="自动刷新", variable=self.auto_refresh_var).pack(side="left", padx=12)
        ttk.Checkbutton(
            run_frame, text="跟随最新", variable=self.follow_latest_var, command=self._on_follow_toggled
        ).pack(side="left")
        self.follow_button = ttk.Button(run_frame, text="回到最新", command=self.back_to_latest)
        self.follow_button.pack(side="left", padx=(6, 0))
        ttk.Label(run_frame, textvariable=self.tick_var).pack(side="left", padx=6)
        ttk.Label(run_frame, textvariable=self.sim_status_var).pack(side="left", padx=6)

        filter_frame = ttk.LabelFrame(outer, text="筛选与显示", padding=6)
        filter_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self.type_combo = self._filter_combo(filter_frame, "事件类型", self.type_var, 0, 0, 20)
        self.agent_filter_combo = self._filter_combo(filter_frame, "角色", self.agent_filter_var, 0, 2, 18)
        self.household_combo = self._filter_combo(filter_frame, "家庭", self.household_filter_var, 0, 4, 18)
        self.location_combo = self._filter_combo(filter_frame, "地点", self.location_filter_var, 0, 6, 18)
        self._filter_entry(filter_frame, "Tick 从", self.from_var, 1, 0)
        self._filter_entry(filter_frame, "到", self.to_var, 1, 2)
        ttk.Label(filter_frame, text="时间粒度").grid(row=1, column=4, sticky="w", padx=(8, 3), pady=3)
        ttk.Combobox(
            filter_frame, textvariable=self.granularity_var, values=list(GRANULARITIES), width=10, state="readonly"
        ).grid(row=1, column=5, sticky="w", pady=3)
        ttk.Label(filter_frame, text="聚合间隔").grid(row=1, column=6, sticky="w", padx=(6, 3), pady=3)
        gap_spin = ttk.Spinbox(filter_frame, from_=1, to=360, width=5, textvariable=self.span_gap_var)
        gap_spin.grid(row=1, column=7, sticky="w", pady=3)
        gap_spin.bind("<Return>", lambda _e: self.apply_filters())
        ttk.Label(filter_frame, text="显示条数").grid(row=1, column=8, sticky="w", padx=(6, 3), pady=3)
        cap_spin = ttk.Spinbox(
            filter_frame, from_=100, to=100000, increment=100, width=7, textvariable=self.render_cap_var
        )
        cap_spin.grid(row=1, column=9, sticky="w", pady=3)
        cap_spin.bind("<Return>", lambda _e: self.apply_filters())
        ttk.Button(filter_frame, text="应用筛选", command=self.apply_filters).grid(row=1, column=10, padx=4, pady=3)
        ttk.Button(filter_frame, text="清空", command=self.clear_filters).grid(row=1, column=11, padx=4, pady=3)
        ttk.Label(filter_frame, text="跳转 tick").grid(row=1, column=12, sticky="e", padx=(8, 3), pady=3)
        ttk.Entry(filter_frame, textvariable=self.jump_var, width=8).grid(row=1, column=13, sticky="w", pady=3)
        ttk.Button(filter_frame, text="跳转", command=self.jump_to_tick).grid(row=1, column=14, padx=4, pady=3)
        ttk.Button(filter_frame, text="打开事件库", command=self.open_database).grid(row=1, column=15, padx=4, pady=3)
        ttk.Button(filter_frame, text="刷新", command=self.refresh).grid(row=1, column=16, padx=4, pady=3)

        self.main_paned = ttk.PanedWindow(outer, orient="vertical")
        self.main_paned.grid(row=2, column=0, sticky="nsew")
        upper = ttk.PanedWindow(self.main_paned, orient="horizontal")
        self.main_paned.add(upper, weight=5)

        event_frame = ttk.Frame(upper)
        upper.add(event_frame, weight=3)
        columns = ("tick", "type", "people", "summary", "count")
        self.event_tree = ttk.Treeview(event_frame, columns=columns, show="tree headings", selectmode="browse")
        self.event_tree.heading("#0", text="时间 / 分组")
        self.event_tree.heading("tick", text="Tick")
        self.event_tree.heading("type", text="类型")
        self.event_tree.heading("people", text="参与者")
        self.event_tree.heading("summary", text="事件摘要")
        self.event_tree.heading("count", text="条数")
        self.event_tree.column("#0", width=210, stretch=False)
        self.event_tree.column("tick", width=65, anchor="center", stretch=False)
        self.event_tree.column("type", width=155, stretch=False)
        self.event_tree.column("people", width=180, stretch=False)
        self.event_tree.column("summary", width=520)
        self.event_tree.column("count", width=55, anchor="center", stretch=False)
        self.event_tree.tag_configure("turning", background="#fff0bf")
        self.event_tree.tag_configure("favorite", foreground="#075ea8")
        yscroll = ttk.Scrollbar(event_frame, orient="vertical", command=self.event_tree.yview)
        xscroll = ttk.Scrollbar(event_frame, orient="horizontal", command=self.event_tree.xview)
        self.event_tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.event_tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        event_frame.rowconfigure(0, weight=1)
        event_frame.columnconfigure(0, weight=1)
        self.event_tree.bind("<<TreeviewSelect>>", self._on_event_select)

        self.detail_notebook = ttk.Notebook(upper)
        upper.add(self.detail_notebook, weight=2)
        self._build_detail_tabs()

        self.focus_notebook = ttk.Notebook(self.main_paned)
        self.main_paned.add(self.focus_notebook, weight=2)
        self.focus_trees: dict[str, ttk.Treeview] = {}
        for category, title in FOCUS_TITLES.items():
            self._build_focus_tab(category, title)
        self._build_favorites_tab()
        # 底部面板首次布局时给足高度，避免被上方面板挤成一条缝
        self._pane_layout_done = False
        self.main_paned.bind("<Configure>", self._on_paned_configure)

        status = ttk.Frame(outer)
        status.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(status, textvariable=self.source_var).pack(side="left")
        ttk.Label(status, textvariable=self.status_var).pack(side="right")

    def _filter_combo(self, parent, label, variable, row, column, width):
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=(6, 3), pady=3)
        combo = ttk.Combobox(parent, textvariable=variable, width=width)
        combo.grid(row=row, column=column + 1, sticky="w", pady=3)
        return combo

    def _filter_entry(self, parent, label, variable, row, column):
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=(6, 3), pady=3)
        ttk.Entry(parent, textvariable=variable, width=8).grid(row=row, column=column + 1, sticky="w", pady=3)

    def _build_detail_tabs(self) -> None:
        summary_frame = ttk.Frame(self.detail_notebook, padding=5)
        self.detail_notebook.add(summary_frame, text="事件摘要")
        self.summary_text = tk.Text(summary_frame, wrap="word", state="disabled", width=50, height=16)
        self.summary_text.pack(fill="both", expand=True)
        buttons = ttk.Frame(summary_frame)
        buttons.pack(fill="x", pady=(5, 0))
        ttk.Button(buttons, text="收藏事件", command=self.favorite_selected_event).pack(side="left")
        ttk.Button(buttons, text="查看角色", command=self.open_selected_agent).pack(side="left", padx=5)
        ttk.Button(buttons, text="查看家庭", command=self.open_selected_household).pack(side="left")

        json_frame = ttk.Frame(self.detail_notebook, padding=5)
        self.detail_notebook.add(json_frame, text="完整字段 JSON")
        self.json_text = tk.Text(json_frame, wrap="none", state="disabled")
        self.json_text.pack(fill="both", expand=True)

        self.agent_text, self.agent_timeline, agent_combo = self._build_profile_tab(
            "agent", "角色档案", self.agent_view_var, self.show_agent_profile, self.favorite_current_agent
        )
        self.agent_view_combo = agent_combo
        self.household_text, self.household_timeline, household_combo = self._build_profile_tab(
            "household", "家庭档案", self.household_view_var, self.show_household_profile,
            self.favorite_current_household,
        )
        self.household_view_combo = household_combo

    def _build_profile_tab(self, kind, title, variable, view_command, favorite_command):
        frame = ttk.Frame(self.detail_notebook, padding=5)
        self.detail_notebook.add(frame, text=title)
        controls = ttk.Frame(frame)
        controls.pack(fill="x")
        combo = ttk.Combobox(controls, textvariable=variable, width=24)
        combo.pack(side="left", fill="x", expand=True)
        ttk.Button(controls, text="查看", command=view_command).pack(side="left", padx=4)
        ttk.Button(controls, text="收藏", command=favorite_command).pack(side="left")
        text = tk.Text(frame, wrap="word", state="disabled", height=12)
        text.pack(fill="x", pady=(5, 5))
        tree = self._small_event_tree(frame)
        tree._viz_scroll.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        tree.bind("<<TreeviewSelect>>", lambda _event, k=kind: self._on_profile_event(k))
        return text, tree, combo

    def _small_event_tree(self, parent, height=6):
        tree = ttk.Treeview(
            parent, columns=("tick", "type", "summary"), show="headings", selectmode="browse", height=height
        )
        for column, title, width in (("tick", "Tick", 60), ("type", "类型", 145), ("summary", "摘要", 330)):
            tree.heading(column, text=title)
            tree.column(column, width=width, stretch=column == "summary")
        scroll = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree._viz_scroll = scroll
        return tree

    def _on_paned_configure(self, _event) -> None:
        if self._pane_layout_done:
            return
        height = self.main_paned.winfo_height()
        if height <= 100:
            return
        try:
            self.main_paned.sashpos(0, int(height * 0.60))
        except tk.TclError:
            return
        self._pane_layout_done = True

    def _build_focus_tab(self, category, title) -> None:
        frame = ttk.Frame(self.focus_notebook, padding=4)
        self.focus_notebook.add(frame, text=f"{title}关注点")
        controls = ttk.Frame(frame)
        controls.pack(fill="x")
        ttk.Label(controls, textvariable=self.focus_count_vars[category]).pack(side="left", fill="x", expand=True)
        ttk.Button(controls, text="刷新此面板", command=lambda: self.refresh_focus(category)).pack(side="right")
        tree = self._small_event_tree(frame)
        tree.configure(show="tree headings")
        tree.heading("#0", text="事件类别")
        tree.column("#0", width=155, stretch=False)
        tree._viz_scroll.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True, pady=(4, 0))
        tree.bind("<<TreeviewSelect>>", lambda _event, c=category: self._on_focus_event(c))
        self.focus_trees[category] = tree

    def _build_favorites_tab(self) -> None:
        frame = ttk.Frame(self.focus_notebook, padding=4)
        self.focus_notebook.add(frame, text="收藏与快速跳转")
        controls = ttk.Frame(frame)
        controls.pack(fill="x")
        ttk.Button(controls, text="跳转所选", command=self.jump_to_favorite).pack(side="left")
        ttk.Button(controls, text="移除收藏", command=self.remove_favorite).pack(side="left", padx=5)
        self.favorite_tree = ttk.Treeview(
            frame, columns=("kind", "target", "detail"), show="headings", selectmode="browse"
        )
        for column, title, width in (("kind", "类别", 80), ("target", "对象", 220), ("detail", "说明", 650)):
            self.favorite_tree.heading(column, text=title)
            self.favorite_tree.column(column, width=width, stretch=column == "detail")
        self.favorite_tree.pack(fill="both", expand=True, pady=(4, 0))

    def _set_text(self, widget, content) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    def load_source(self, source: EventSource, incremental: bool = False) -> None:
        if self.loading:
            if not incremental:
                self.refresh_pending = True
            return
        if (
            incremental
            and source is self.source
            and source.kind == "db"
            and self.last_event_id is not None
        ):
            # 增量：只取水位之后的新事件，避免大库每秒全量重载
            generation = self.load_generation

            def increment_worker():
                try:
                    new_events = source.load(since_id=self.last_event_id)
                    self.messages.put(("data_appended", generation, new_events))
                except Exception as exc:
                    self.messages.put(("data_error", generation, str(exc)))

            threading.Thread(target=increment_worker, name="viz-data-increment", daemon=True).start()
            return
        self.source = source
        self.source_var.set(source.label)
        self.loading = True
        self.load_generation += 1
        generation = self.load_generation
        self.status_var.set("正在只读加载…")

        def worker():
            try:
                events = source.load()
                self.messages.put(("data_loaded", generation, events))
            except Exception as exc:
                self.messages.put(("data_error", generation, str(exc)))

        threading.Thread(target=worker, name="viz-data-load", daemon=True).start()

    def refresh(self) -> None:
        self.load_source(self.source)

    def _source_is_live_sim(self) -> bool:
        """自动刷新只针对本 GUI 启动的模拟库；外部静态库不刷，避免无谓重载。"""
        return (
            self.controller is not None
            and self.controller.db_path is not None
            and self.source.kind == "db"
            and str(self.source.path) == str(self.controller.db_path)
        )

    def _auto_refresh(self) -> None:
        if self.closing:
            return
        if self.auto_refresh_var.get() and self.source.kind == "db" and self._source_is_live_sim():
            self.load_source(self.source, incremental=True)
        self.root.after(1000, self._auto_refresh)

    def apply_filters(self) -> None:
        try:
            tick_from = int(self.from_var.get()) if self.from_var.get().strip() else None
            tick_to = int(self.to_var.get()) if self.to_var.get().strip() else None
        except ValueError:
            self.status_var.set("Tick 范围必须是整数")
            return
        if tick_from is not None and tick_to is not None and tick_from > tick_to:
            self.status_var.set("Tick 下界不能大于上界")
            return
        criteria = {
            "agent": self.agent_options.get(self.agent_filter_var.get(), self.agent_filter_var.get()),
            "event_types": None if self.type_var.get() == ALL else [self.type_var.get()],
            "household": None if self.household_filter_var.get() == ALL else self.household_filter_var.get(),
            "location": self.location_options.get(self.location_filter_var.get(), self.location_filter_var.get()),
            "tick_from": tick_from,
            "tick_to": tick_to,
        }
        for key in ("agent", "household", "location"):
            criteria[key] = criteria[key] or None
        granularity = GRANULARITIES.get(self.granularity_var.get(), "event")
        gap = self.span_gap_var.get()
        events = list(self.events)
        cfg = self.cfg
        self.filter_generation += 1
        generation = self.filter_generation
        self.status_var.set("正在筛选…")

        def worker():
            try:
                filtered = filter_events(events, **criteria)
                groups = group_events(filtered, granularity, cfg, gap=gap)
                self.messages.put(("filtered", generation, filtered, groups))
            except Exception as exc:
                self.messages.put(("filter_error", generation, str(exc)))

        threading.Thread(target=worker, name="viz-filter", daemon=True).start()

    def clear_filters(self) -> None:
        for variable in (self.type_var, self.agent_filter_var, self.household_filter_var, self.location_filter_var):
            variable.set(ALL)
        self.from_var.set("")
        self.to_var.set("")
        self.apply_filters()

    def _poll_messages(self) -> None:
        if self.closing:
            return
        try:
            while True:
                message = self.messages.get_nowait()
                kind = message[0]
                if kind == "data_loaded" and message[1] == self.load_generation:
                    self._data_loaded(message[2])
                elif kind == "data_appended" and message[1] == self.load_generation:
                    self._data_appended(message[2])
                elif kind == "data_error" and message[1] == self.load_generation:
                    self.loading = False
                    self.status_var.set(f"读取失败，保留当前数据：{message[2]}")
                elif kind == "filtered" and message[1] == self.filter_generation:
                    self.filtered, self.groups = message[2], message[3]
                    self.stream_new_hint = False
                    self._populate_event_tree()
                    self._update_stream_status()
                elif kind == "filter_error" and message[1] == self.filter_generation:
                    self.status_var.set(f"筛选失败：{message[2]}")
                elif kind == "profile_ready" and message[1] == self.profile_generation:
                    if message[2] == "agent":
                        self._render_agent_profile(*message[3])
                    else:
                        self._render_household_profile(*message[3])
                elif kind == "profile_error" and message[1] == self.profile_generation:
                    self.status_var.set(f"档案汇总失败：{message[2]}")
                elif kind == "index_ready" and message[1] == self.index_generation:
                    self._update_stream_status()
                elif kind == "index_error" and message[1] == self.index_generation:
                    self.status_var.set(f"人物索引构建失败，档案走全库扫描：{message[2]}")
                elif kind == "sim_started":
                    self._simulation_started(message[1], message[2])
                elif kind == "sim_status":
                    self._simulation_status(message[1], message[2])
                elif kind == "sim_error":
                    self.sim_starting = False
                    self.sim_status_var.set(f"模拟错误：{message[1]}")
                    self._update_sim_buttons()
        except queue.Empty:
            pass
        self.root.after(50, self._poll_messages)

    def _update_stream_status(self, extra: str = "") -> None:
        shown = len(self.event_rows)
        base = f"显示 {shown} / 共 {len(self.events)} 条事件"
        cap = self.render_cap_var.get()
        if len(self.groups) > cap:
            base += f"（已截断，仅渲染最近 {cap} 条/组）"
        if self.stream_new_hint:
            base += " · 有新事件，点「应用筛选」并入"
        if self.person_index is None:
            base += " · 人物索引构建中，角色档案稍慢"
        if extra:
            base += f" · {extra}"
        self.status_var.set(base)

    def _data_loaded(self, events) -> None:
        self.loading = False
        self.events = events
        self.event_by_id = {int(event["id"]): event for event in events}
        self.last_event_id = max(self.event_by_id, default=None)
        self.stream_new_hint = False
        self._refresh_options()
        for category in FOCUS_TITLES:
            self.refresh_focus(category)
        self.refresh_favorites()
        self.apply_filters()
        self._start_index_build()
        if self.refresh_pending:
            self.refresh_pending = False
            self.root.after_idle(self.refresh)

    def _start_index_build(self) -> None:
        """后台构建人物索引；构建中的档案查询回退全库扫描路径，就绪后走索引。"""
        if self._index_builder is not None and self._index_builder.is_alive():
            self.index_generation += 1  # 旧构建作废，收尾时不落库
        self.index_generation += 1
        generation = self.index_generation
        snapshot = list(self.events)

        def builder():
            try:
                index = build_person_index(snapshot)
                with self._index_lock:
                    if generation == self.index_generation:
                        # 补上构建期间增量到达的事件，随后增量路径接管
                        for event in self.events[len(snapshot):]:
                            for key in person_keys(event):
                                bucket = index.get(key)
                                if bucket is None:
                                    index[key] = [event]
                                else:
                                    bucket.append(event)
                        self.person_index = index
                self.messages.put(("index_ready", generation))
            except Exception as exc:  # noqa: BLE001 - 索引失败不致命，档案回退全库扫描
                self.messages.put(("index_error", generation, str(exc)))

        self._index_builder = threading.Thread(target=builder, name="viz-person-index", daemon=True)
        self._index_builder.start()

    def _view_matches_stream(self) -> bool:
        """当前视图是否为「无筛选 + 逐事件」的完整事件流（可增量追加）。"""
        return (
            self.granularity_var.get() == "逐事件"
            and self.type_var.get() == ALL
            and self.agent_filter_var.get() == ALL
            and self.household_filter_var.get() == ALL
            and self.location_filter_var.get() == ALL
            and not self.from_var.get().strip()
            and not self.to_var.get().strip()
        )

    def _data_appended(self, new_events) -> None:
        """增量新事件：不重建界面，只追加行并保留用户全部交互状态。"""
        if not new_events:
            return
        for event in new_events:
            event_id = int(event["id"])
            self.events.append(event)
            self.event_by_id[event_id] = event
            self.last_event_id = max(self.last_event_id or 0, event_id)
        with self._index_lock:
            if self.person_index is not None:
                # 索引已就绪：增量追加；构建中则跳过（构建线程收尾时会补齐快照之后的事件）
                for event in new_events:
                    for key in person_keys(event):
                        bucket = self.person_index.get(key)
                        if bucket is None:
                            self.person_index[key] = [event]
                        else:
                            bucket.append(event)
        self._refresh_options(new_events)
        for category in FOCUS_TITLES:
            self._append_focus_events(category, new_events)
        if self._view_matches_stream():
            self._append_stream_rows(new_events)
            if self._should_follow_latest():
                last_id = self._last_visible_event_id()
                if last_id is not None:
                    self._select_main_event(last_id)
            self._update_stream_status()
        elif self.sim_state in {"running", "ready", "paused"}:
            self.stream_new_hint = True
            self._update_stream_status()

    def _refresh_options(self, new_events=None) -> None:
        """全量重建（new_events=None）或只用新事件更新筛选下拉的缓存。"""
        if new_events is None:
            self._people_map = {}
            self._location_map = {}
            self._type_values = set()
            self._household_values = set()
            scan_events = self.events
        else:
            scan_events = new_events
        for event in scan_events:
            self._type_values.add(str(event.get("event_type", "")))
            for person in event_people(event):
                selector = person.get("id") or person.get("name")
                if selector:
                    self._people_map[person_label(person)] = selector
            self._household_values.update(event_households(event))
            for location in event_locations(event):
                label = f"{self.names[location]}（{location}）" if location in self.names else location
                self._location_map[label] = location
        self.type_combo.configure(values=[ALL] + sorted(self._type_values))
        self.agent_options = {ALL: "", **dict(sorted(self._people_map.items()))}
        self.location_options = {ALL: "", **dict(sorted(self._location_map.items()))}
        household_values = [ALL] + sorted(self._household_values)
        self.agent_filter_combo.configure(values=list(self.agent_options))
        self.agent_view_combo.configure(values=[value for value in self.agent_options if value != ALL])
        self.household_combo.configure(values=household_values)
        self.household_view_combo.configure(values=sorted(self._household_values))
        self.location_combo.configure(values=list(self.location_options))

    def _event_tags(self, event) -> tuple[str, ...]:
        tags = []
        if turning_point(event):
            tags.append("turning")
        if int(event["id"]) in self.favorite_events:
            tags.append("favorite")
        return tuple(tags)

    def _event_values(self, event):
        people = "、".join(person_label(person) for person in event_people(event)[:3])
        return (event.get("tick", ""), event.get("event_type", ""), people, event_summary(event, self.names), 1)

    def _last_visible_event_id(self):
        """树中最后一个可见事件 id（分组模式取末组的末行）。"""
        children = self.event_tree.get_children()
        if not children:
            return None
        last_row = children[-1]
        sub = self.event_tree.get_children(last_row)
        if sub:
            last_row = sub[-1]
        return self.main_row_event.get(last_row)

    def _should_follow_latest(self) -> bool:
        """模拟运行中是否跟随最新事件（用户查看历史时不打扰）。

        条件：跟随开关开 + sim 处于 running + 用户未固定历史事件 + 视图在底部附近。
        跟随自动选中的最新事件不算固定，刷新后继续跟随新到的事件。
        """
        if self.sim_state != "running" or not self.follow_latest_var.get():
            return False
        if self.user_pinned:
            return False  # 用户点击了较旧事件，正在查阅历史
        children = self.event_tree.get_children()
        if children and self.root.winfo_viewable():
            yview = self.event_tree.yview()
            if yview[1] < 0.98:
                return False  # 用户上滚翻历史
        return True

    def _populate_event_tree(self) -> None:
        follow = self._should_follow_latest()
        # 重建前捕获用户状态：分组展开、滚动位置、面板分隔条，重建后原样恢复
        open_iids = [
            iid for iid in self.event_tree.get_children("")
            if str(iid).startswith("group:") and self.event_tree.item(iid, "open")
        ]
        yview = self.event_tree.yview()
        try:
            sash = self.main_paned.sashpos(0)
        except (tk.TclError, IndexError):
            sash = None
        self.event_tree.delete(*self.event_tree.get_children())
        self.main_row_event.clear()
        self.event_rows.clear()
        cap = max(1, self.render_cap_var.get())
        groups = self.groups
        trimmed = max(0, len(groups) - cap)
        if trimmed:
            self.event_tree.insert(
                "", "end", iid="cap:info", text=f"…更早 {trimmed} 条/组未渲染（调大显示条数或用筛选）",
                values=("", "", "", "", trimmed),
            )
            groups = groups[-cap:]
        grouped = GRANULARITIES.get(self.granularity_var.get(), "event") != "event"
        activity_mode = GRANULARITIES.get(self.granularity_var.get()) == "activity"
        for group in groups:
            first = group.events[0]
            if not grouped:
                event_id = int(first["id"])
                iid = f"event:{event_id}"
                self.event_tree.insert(
                    "", "end", iid=iid, text=group.label, values=self._event_values(first), tags=self._event_tags(first)
                )
                self.main_row_event[iid] = event_id
                self.event_rows[event_id] = iid
                continue
            parent = f"group:{_iid_safe(group.key)}"
            types = {event.get("event_type", "") for event in group.events}
            values = (group.tick, types.pop() if len(types) == 1 else "混合", "", event_summary(first, self.names), len(group.events))
            self.event_tree.insert("", "end", iid=parent, text=group.label, values=values, open=False)
            self.main_row_event[parent] = int(first["id"])
            if activity_mode:
                continue  # 活动区间可能包含数千事件，不展开子行，选中行显示首事件详情
            for event in group.events:
                event_id = int(event["id"])
                iid = f"event:{event_id}"
                self.event_tree.insert(
                    parent, "end", iid=iid, text=f"#{event_id}", values=self._event_values(event),
                    tags=self._event_tags(event),
                )
                self.main_row_event[iid] = event_id
                self.event_rows[event_id] = iid
        for iid in open_iids:
            if self.event_tree.exists(iid):
                self.event_tree.item(iid, open=True)
        if sash is not None:
            try:
                self.main_paned.sashpos(0, sash)
            except (tk.TclError, IndexError):
                pass
        if follow:
            last_id = self._last_visible_event_id()
            if last_id is not None:
                self.pending_event_id = None
                self._select_main_event(last_id)
                return
        target = self.pending_event_id if self.pending_event_id is not None else self.selected_event_id
        self.pending_event_id = None
        if target not in self.event_rows:
            target = next(iter(self.event_rows), None)
        # 运行中用户在查阅历史（固定事件/上滚）时刷新不回滚视图；其余保持原选中行为
        scroll = not (self.sim_state == "running" and self.follow_latest_var.get())
        if target is not None:
            self._select_main_event(int(target), scroll=scroll)
        else:
            self.selected_event_id = None
            self._set_text(self.summary_text, "当前筛选没有事件。")
            self._set_text(self.json_text, "")
        if not scroll and yview[1] < 1.0:
            self.event_tree.yview_moveto(yview[0])

    def _append_stream_rows(self, new_events) -> None:
        """流式视图增量追加：不重建、不触碰已有行，超限从头裁剪。"""
        cap = max(1, self.render_cap_var.get())
        for event in new_events:
            event_id = int(event["id"])
            if event_id in self.event_rows:
                continue
            tick = int(event.get("tick", 0))
            group = EventGroup(
                f"event:{event_id}", f"#{event_id} · {calendar_label(tick, self.cfg)}", tick, [event]
            )
            self.groups.append(group)
            self.filtered.append(event)
            iid = f"event:{event_id}"
            self.event_tree.insert(
                "", "end", iid=iid, text=group.label, values=self._event_values(event), tags=self._event_tags(event)
            )
            self.main_row_event[iid] = event_id
            self.event_rows[event_id] = iid
        children = self.event_tree.get_children("")
        excess = len(children) - cap
        if excess <= 0:
            return
        removed = 0
        for iid in children:
            if removed >= excess:
                break
            if iid == "cap:info":
                continue
            event_id = self.main_row_event.pop(iid, None)
            if event_id is not None:
                self.event_rows.pop(event_id, None)
            self.event_tree.delete(iid)
            removed += 1
        if not self.event_tree.exists("cap:info"):
            self.event_tree.insert(
                "", 0, iid="cap:info", text="…更早事件未渲染（调大显示条数或用筛选）", values=("", "", "", "", "")
            )

    def _on_event_select(self, _event=None) -> None:
        selection = self.event_tree.selection()
        if not selection:
            return
        event_id = self.main_row_event.get(selection[0])
        if event_id is not None:
            self.selected_event_id = event_id
            if self.sim_state == "running":
                self.user_pinned = event_id != self._last_visible_event_id()
                if self.user_pinned:
                    self.status_var.set(PINNED_HINT)
            self._show_event(event_id)

    def _on_follow_toggled(self) -> None:
        if self.follow_latest_var.get() and self.user_pinned:
            self.user_pinned = False
            self._resume_follow()

    def back_to_latest(self) -> None:
        """回到最新：清固定、恢复跟随并滚到最新事件。"""
        self.follow_latest_var.set(True)
        self.user_pinned = False
        self._resume_follow()

    def _resume_follow(self) -> None:
        last_id = self._last_visible_event_id()
        if last_id is not None:
            self._select_main_event(last_id)
        self._update_stream_status()

    def _select_main_event(self, event_id: int, scroll: bool = True) -> None:
        iid = self.event_rows.get(event_id)
        if not iid:
            return
        self.event_tree.selection_set(iid)
        self.event_tree.focus(iid)
        if scroll:
            self.event_tree.see(iid)
        self.selected_event_id = event_id
        self._show_event(event_id)

    def _show_event(self, event_id: int) -> None:
        event = self.event_by_id.get(event_id)
        if event is None:
            return
        people = event_people(event)
        households = event_households(event)
        locations = event_locations(event)
        location_text = "、".join(f"{self.names.get(node, node)}（{node}）" for node in locations) or UNKNOWN
        turn = turning_point(event)
        lines = [
            f"事件 #{event_id} · Tick {event.get('tick')} · {calendar_label(int(event.get('tick', 0)), self.cfg)}",
            f"类型：{event.get('event_type')}" + (f"    关键转折：{turn}" if turn else ""),
            "",
            event_summary(event, self.names),
            "",
            "参与者：" + ("、".join(person_label(person) for person in people) or UNKNOWN),
            "家庭：" + ("、".join(households) or UNKNOWN),
            "地点：" + location_text,
        ]
        self._set_text(self.summary_text, "\n".join(lines))
        self._set_text(self.json_text, event_details(event))

    def open_selected_agent(self) -> None:
        event = self.event_by_id.get(self.selected_event_id)
        people = event_people(event) if event else []
        if not people:
            self.status_var.set("该事件没有记录人物")
            return
        selector = people[0].get("id") or people[0].get("name")
        self.agent_view_var.set(self._agent_display(selector))
        self.show_agent_profile()
        self.detail_notebook.select(2)

    def open_selected_household(self) -> None:
        event = self.event_by_id.get(self.selected_event_id)
        households = event_households(event) if event else []
        if not households:
            self.status_var.set("该事件没有记录家庭")
            return
        self.household_view_var.set(households[0])
        self.show_household_profile()
        self.detail_notebook.select(3)

    def _agent_display(self, selector) -> str:
        return next((label for label, value in self.agent_options.items() if value == selector), selector)

    def show_agent_profile(self) -> None:
        selector = self.agent_options.get(self.agent_view_var.get(), self.agent_view_var.get()).strip()
        if not selector:
            self.status_var.set("请先选择角色")
            return
        self.status_var.set("正在汇总角色档案…")
        self.profile_generation += 1
        generation = self.profile_generation
        events = list(self.events)
        gap = self.span_gap_var.get()

        def worker():
            try:
                # 局部引用快照：构建完成则免全库逐事件人物匹配；未就绪则回退旧路径
                index = self.person_index
                profile = agent_profile(events, selector, index=index)
                # 聚合直接吃已过滤的本人时间线，省一遍全库人物匹配
                spans = activity_spans(profile.timeline, gap=gap)
                self.messages.put(("profile_ready", generation, "agent", (selector, profile, spans)))
            except Exception as exc:  # noqa: BLE001 - 后台线程边界转可读错误
                self.messages.put(("profile_error", generation, str(exc)))

        threading.Thread(target=worker, name="viz-agent-profile", daemon=True).start()

    def _render_agent_profile(self, selector, profile, spans) -> None:
        spouse = profile.spouse_name or profile.spouse_id or UNKNOWN
        birth = calendar_label(profile.birth_tick, self.cfg) if profile.birth_tick is not None else UNKNOWN
        death = calendar_label(profile.death_tick, self.cfg) if profile.death_tick is not None else UNKNOWN
        gap = self.span_gap_var.get()
        lines = [
            f"{profile.name}（{profile.agent_id or selector}）",
            f"出生：{birth}    死亡：{death}",
            f"配偶：{spouse}    最近家庭：{profile.household_id or UNKNOWN}",
            f"完整时间线：{len(profile.timeline)} 条；下方按事件顺序排列。",
            "",
            "近期事件：",
        ]
        lines.extend(f"#{e['id']} · {event_summary(e, self.names)}" for e in profile.recent_events)
        bio = biography(profile, self.names)
        if bio:
            lines.extend(["", f"一生大事记（{len(bio)} 件，按时间序）："])
            lines.extend(
                f"{calendar_label(entry.tick, self.cfg)} · {entry.label} · {entry.text}"
                for entry in bio
            )
        if spans:
            by_label: dict[str, list] = {}
            for span in spans:
                by_label.setdefault(span.label, []).append(span)
            lines.extend(["", f"生平阶段（同一活动间隔 ≤{gap} tick 合并为一段）："])
            ranked = sorted(by_label.items(), key=lambda item: -sum(s.count for s in item[1]))
            for label, items in ranked:
                total = sum(span.count for span in items)
                first, last = items[0], items[-1]
                span_note = "" if len(items) == 1 else f" · {len(items)} 段"
                lines.append(
                    f"{label}：{calendar_label(first.from_tick, self.cfg)} → "
                    f"{calendar_label(last.to_tick, self.cfg)} · {total} 次{span_note}"
                )
        self._set_text(self.agent_text, "\n".join(lines))
        self._populate_profile_timeline("agent", self.agent_timeline, profile.timeline)
        self._update_stream_status()

    def show_household_profile(self) -> None:
        household_id = self.household_view_var.get().strip()
        if not household_id or household_id == ALL:
            self.status_var.set("请先选择家庭")
            return
        self.status_var.set("正在汇总家庭档案…")
        self.profile_generation += 1
        generation = self.profile_generation
        events = list(self.events)

        def worker():
            try:
                profile = household_profile(events, household_id)
                self.messages.put(("profile_ready", generation, "household", (household_id, profile)))
            except Exception as exc:  # noqa: BLE001 - 后台线程边界转可读错误
                self.messages.put(("profile_error", generation, str(exc)))

        threading.Thread(target=worker, name="viz-household-profile", daemon=True).start()

    def _render_household_profile(self, household_id, profile) -> None:
        members = "、".join(person_label(member) for member in profile.members) or UNKNOWN
        head = profile.head_name or profile.head_id or UNKNOWN
        lines = [
            f"家庭：{household_id}",
            f"户主：{head}    住所：{self.names.get(profile.home_node, profile.home_node) or UNKNOWN}",
            f"劳作地点：{self.names.get(profile.work_node, profile.work_node) or UNKNOWN}",
            f"事件记录成员（聚合）：{members}",
            f"家庭事件时间线：{len(profile.timeline)} 条。",
            "",
            "近期事件：",
        ]
        lines.extend(f"#{e['id']} · {event_summary(e, self.names)}" for e in profile.recent_events)
        self._set_text(self.household_text, "\n".join(lines))
        self._populate_profile_timeline("household", self.household_timeline, profile.timeline)
        self._update_stream_status()

    def _populate_profile_timeline(self, kind, tree, events) -> None:
        tree.delete(*tree.get_children())
        self.profile_row_event[kind].clear()
        for event in events:
            event_id = int(event["id"])
            iid = f"{kind}:{event_id}"
            tree.insert("", "end", iid=iid, values=(event.get("tick"), event.get("event_type"), event_summary(event, self.names)))
            self.profile_row_event[kind][iid] = event_id

    def _on_profile_event(self, kind) -> None:
        tree = self.agent_timeline if kind == "agent" else self.household_timeline
        selection = tree.selection()
        if selection and selection[0] in self.profile_row_event[kind]:
            self.jump_to_event(self.profile_row_event[kind][selection[0]])

    def refresh_focus(self, category) -> None:
        """全量重建关注点面板（仅在整库加载后调用；运行期走增量追加）。"""
        tree = self.focus_trees[category]
        tree.delete(*tree.get_children())
        self.focus_row_event[category].clear()
        self._focus_type_rows[category].clear()
        events = focus_events(self.events, category)
        by_type: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            by_type.setdefault(str(event.get("event_type", "")), []).append(event)
        self._focus_counts[category] = {event_type: len(items) for event_type, items in by_type.items()}
        for type_index, (event_type, items) in enumerate(sorted(by_type.items())):
            parent = f"{category}:type:{type_index}"
            tree.insert("", "end", iid=parent, text=f"{event_type}（{len(items)}）", values=("", "", ""))
            self._focus_type_rows[category][event_type] = parent
            for event in items:
                event_id = int(event["id"])
                iid = f"{category}:event:{event_id}"
                tree.insert(
                    parent, "end", iid=iid, text=f"#{event_id}",
                    values=(event.get("tick"), event_type, event_summary(event, self.names)), tags=self._event_tags(event),
                )
                self.focus_row_event[category][iid] = event_id
        self._update_focus_counts_label(category)

    def _append_focus_events(self, category, new_events) -> None:
        """增量追加关注点行，不重建树（保留展开与滚动）。"""
        tree = self.focus_trees[category]
        counts = self._focus_counts.setdefault(category, {})
        type_rows = self._focus_type_rows[category]
        for event in new_events:
            if focus_category(event) != category:
                continue
            event_type = str(event.get("event_type", ""))
            counts[event_type] = counts.get(event_type, 0) + 1
            parent = type_rows.get(event_type)
            if parent is None or not tree.exists(parent):
                parent = f"{category}:type:{len(type_rows)}"
                tree.insert("", "end", iid=parent, text=f"{event_type}（1）", values=("", "", ""))
                type_rows[event_type] = parent
            else:
                tree.item(parent, text=f"{event_type}（{counts[event_type]}）")
            event_id = int(event["id"])
            iid = f"{category}:event:{event_id}"
            tree.insert(
                parent, "end", iid=iid, text=f"#{event_id}",
                values=(event.get("tick"), event_type, event_summary(event, self.names)),
                tags=self._event_tags(event),
            )
            self.focus_row_event[category][iid] = event_id
        self._update_focus_counts_label(category)

    def _update_focus_counts_label(self, category) -> None:
        counts = self._focus_counts.get(category, {})
        summary = " · ".join(f"{event_type} {count}" for event_type, count in sorted(counts.items()))
        self.focus_count_vars[category].set(f"共 {sum(counts.values())} 条" + (f" · {summary}" if summary else ""))

    def _on_focus_event(self, category) -> None:
        selection = self.focus_trees[category].selection()
        if selection:
            event_id = self.focus_row_event[category].get(selection[0])
            if event_id is not None:
                self.jump_to_event(event_id)

    def favorite_selected_event(self) -> None:
        if self.selected_event_id is None:
            return
        self.favorite_events.add(self.selected_event_id)
        self.refresh_favorites()
        self._populate_event_tree()

    def favorite_current_agent(self) -> None:
        selector = self.agent_options.get(self.agent_view_var.get(), self.agent_view_var.get()).strip()
        if selector:
            self.favorite_people.add(selector)
            self.refresh_favorites()

    def favorite_current_household(self) -> None:
        household_id = self.household_view_var.get().strip()
        if household_id and household_id != ALL:
            self.favorite_households.add(household_id)
            self.refresh_favorites()

    def refresh_favorites(self) -> None:
        self.favorite_tree.delete(*self.favorite_tree.get_children())
        self.favorite_row_target.clear()
        index = 0
        for selector in sorted(self.favorite_people):
            iid = f"favorite:{index}"
            index += 1
            self.favorite_tree.insert("", "end", iid=iid, values=("角色", self._agent_display(selector), "打开角色档案"))
            self.favorite_row_target[iid] = ("agent", selector)
        for household_id in sorted(self.favorite_households):
            iid = f"favorite:{index}"
            index += 1
            self.favorite_tree.insert("", "end", iid=iid, values=("家庭", household_id, "打开家庭档案"))
            self.favorite_row_target[iid] = ("household", household_id)
        for event_id in sorted(self.favorite_events):
            event = self.event_by_id.get(event_id)
            if event is None:
                continue
            iid = f"favorite:{index}"
            index += 1
            self.favorite_tree.insert("", "end", iid=iid, values=("事件", f"#{event_id}", event_summary(event, self.names)))
            self.favorite_row_target[iid] = ("event", event_id)

    def _selected_favorite(self):
        selection = self.favorite_tree.selection()
        return self.favorite_row_target.get(selection[0]) if selection else None

    def jump_to_favorite(self) -> None:
        target = self._selected_favorite()
        if not target:
            return
        kind, value = target
        if kind == "event":
            self.jump_to_event(value)
        elif kind == "agent":
            self.agent_view_var.set(self._agent_display(value))
            self.show_agent_profile()
            self.detail_notebook.select(2)
        else:
            self.household_view_var.set(value)
            self.show_household_profile()
            self.detail_notebook.select(3)

    def remove_favorite(self) -> None:
        target = self._selected_favorite()
        if not target:
            return
        kind, value = target
        if kind == "event":
            self.favorite_events.discard(value)
            self._populate_event_tree()
        elif kind == "agent":
            self.favorite_people.discard(value)
        else:
            self.favorite_households.discard(value)
        self.refresh_favorites()

    def jump_to_event(self, event_id: int) -> None:
        if event_id not in self.event_by_id:
            return
        if event_id in self.event_rows:
            self._select_main_event(event_id)
            return
        self.pending_event_id = event_id
        for variable in (self.type_var, self.agent_filter_var, self.household_filter_var, self.location_filter_var):
            variable.set(ALL)
        self.from_var.set("")
        self.to_var.set("")
        self.apply_filters()

    def jump_to_tick(self) -> None:
        try:
            tick = int(self.jump_var.get())
        except ValueError:
            self.status_var.set("跳转 tick 必须是整数")
            return
        candidates = [int(event["id"]) for event in self.events if int(event.get("tick", -1)) == tick]
        if not candidates:
            self.status_var.set(f"Tick {tick} 没有事件")
            return
        self.from_var.set(str(tick))
        self.to_var.set(str(tick))
        self.pending_event_id = min(candidates)
        self.apply_filters()

    def open_database(self) -> None:
        path = filedialog.askopenfilename(
            title="只读打开 SQLite 事件库", filetypes=[("SQLite 事件库", "*.db *.sqlite *.sqlite3"), ("所有文件", "*.*")]
        )
        if path:
            self.load_source(EventSource.database(path))

    def start_simulation(self) -> None:
        if self.sim_starting or self.sim_state in {"ready", "running", "paused"}:
            self.status_var.set("请先停止当前模拟")
            return
        self.sim_starting = True
        self.sim_status_var.set("正在启动独立模拟进程…")
        controller = None

        def on_status(status):
            self.messages.put(("sim_status", controller, status))

        controller = self.controller_factory(on_status=on_status)
        self.controller = controller
        self._update_sim_buttons()

        def worker():
            try:
                controller.start(seed=0)
                db_path = controller.db_path
                self.messages.put(("sim_started", controller, db_path))
            except Exception as exc:
                try:
                    controller.close()
                except Exception:
                    pass
                self.messages.put(("sim_error", str(exc)))

        threading.Thread(target=worker, name="viz-sim-start", daemon=True).start()

    def _simulation_started(self, controller, db_path) -> None:
        if controller is not self.controller:
            return
        self.sim_starting = False
        self.sim_state = "ready"
        self.user_pinned = False  # 新模拟从最新时间线开始跟随
        self.sim_status_var.set("模拟已就绪（暂停）")
        self.load_source(EventSource.database(db_path))
        self.change_speed()
        self._update_sim_buttons()

    def _simulation_status(self, controller, status) -> None:
        if controller is not self.controller or not isinstance(status, dict):
            return
        self.sim_starting = False
        previous_state = self.sim_state
        self.sim_state = str(status.get("state", self.sim_state))
        if previous_state in {"running"} and self.sim_state in {"paused", "stopped"} and self._source_is_live_sim():
            # 暂停/停止时补一次增量刷新，把最后一批写入并入（不等下一秒的轮询）
            self.load_source(self.source, incremental=True)
        if "current_tick" in status:
            label = f"当前 tick：{status['current_tick']}"
            if self.sim_state == "running":
                rate = status.get("rate")
                if isinstance(rate, (int, float)) and rate > 0:
                    label += f" · {rate:g} tick/s"
            self.tick_var.set(label)
        if status.get("error"):
            self.sim_status_var.set(f"模拟错误：{status['error']}")
        else:
            labels = {"ready": "模拟已就绪（暂停）", "running": "模拟运行中", "paused": "模拟已暂停", "stopped": "模拟已停止"}
            self.sim_status_var.set(labels.get(self.sim_state, self.sim_state))
        self._update_sim_buttons()

    def _update_sim_buttons(self) -> None:
        active = self.sim_state in {"ready", "running", "paused"}
        self.start_button.configure(state="disabled" if self.sim_starting or active else "normal")
        self.run_button.configure(state="normal" if self.sim_state in {"ready", "paused"} and not self.sim_starting else "disabled")
        self.pause_button.configure(state="normal" if self.sim_state == "running" else "disabled")
        self.step_button.configure(state="normal" if self.sim_state in {"ready", "paused"} and not self.sim_starting else "disabled")
        self.stop_button.configure(state="normal" if active else "disabled")

    def _controller_call(self, method, *args) -> None:
        if self.controller is None:
            return
        try:
            getattr(self.controller, method)(*args)
        except Exception as exc:
            self.sim_status_var.set(f"模拟控制失败：{exc}")

    def run_simulation(self) -> None:
        self._controller_call("run")

    def pause_simulation(self) -> None:
        self._controller_call("pause")

    def step_simulation(self) -> None:
        self._controller_call("step")

    def change_speed(self) -> None:
        if self.controller is not None:
            self._controller_call("set_speed", SPEEDS.get(self.speed_var.get(), 1.0))

    def stop_simulation(self) -> None:
        controller = self.controller
        if controller is None:
            return
        self.sim_status_var.set("正在停止模拟…")
        self.stop_button.configure(state="disabled")

        def worker():
            try:
                controller.stop()
            except Exception as exc:
                self.messages.put(("sim_error", str(exc)))

        threading.Thread(target=worker, name="viz-sim-stop", daemon=True).start()

    def close(self) -> None:
        if self.closing:
            return
        self.closing = True
        if self.controller is not None:
            try:
                self.controller.close()
            except Exception:
                pass
        self.root.destroy()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Vale Chronicle 本地人生档案查看器")
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument("--db", help="只读打开 SQLite 事件库")
    source_group.add_argument("--fixture", help="打开 JSON 事件数组样本")
    args = parser.parse_args(argv)
    source = EventSource.database(args.db) if args.db else EventSource.fixture(args.fixture)
    root = tk.Tk()
    ValeApp(root, source)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
