"""溪谷镇命令行入口。

用法：
  python src/vale/cli.py run 30          跑 30 天，打印故事流，并落盘事件库
  python src/vale/cli.py run 30 --seed 1 指定随机种子（同种子事件流一致）
  python src/vale/cli.py agent 林远       查询某人物当前状态与最近行动

事件库落盘路径：data/worlds/brookvale-town-001/cli_run.db（每次 run 覆盖重建）。
"""
from __future__ import annotations

import argparse
import os
import sys

# 让 `python src/vale/cli.py` 能直接找到 vale 包与 config 包
_HERE = os.path.dirname(os.path.abspath(__file__))  # src/vale
_SRC = os.path.dirname(_HERE)  # src
_ROOT = os.path.dirname(_SRC)  # 项目根
for _p in (_SRC, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from vale.core.calendar import calendar_from_tick, start_day_of_year  # noqa: E402
from vale.core.config_loader import load_config  # noqa: E402
from vale.core.event_log import EventLog  # noqa: E402
from vale.core.scheduler import run_tick  # noqa: E402
from vale.core.world import World  # noqa: E402
from vale.world.assembly import DEFAULT_SEED, base_town_modules, build_world  # noqa: E402
from vale.observability.export import EXPORT_FORMATS  # noqa: E402
from vale.observability.query import EventFilter, apply_filter  # noqa: E402
from vale.observability.render import payload_preview, render_event  # noqa: E402
from vale.observability.viewer import (  # noqa: E402
    ReadonlyEventStore,
    date_str,
    day_tick_range,
    expr_to_tick,
)

WORLD_ID = "brookvale-town-001"
DB_PATH = os.path.join(_ROOT, "data", "worlds", WORLD_ID, "cli_run.db")
# 默认库说明（events 顶层与各子命令的 --help 共用同一份文本，保持一致）
_DB_DEFAULT_REL = f"data/worlds/{WORLD_ID}/cli_run.db"
DB_HELP = (
    f"事件库路径；默认 {_DB_DEFAULT_REL}（由 `cli run <days>` 生成，每次覆盖重建）；"
    "可放在子命令前或后"
)
DEBUG_HELP = "出错时打印完整异常堆栈（默认关闭，面向日常查看保持可读）"

WEATHER_DESC = {
    "sunny": "天气晴朗",
    "cloudy": "多云",
    "light_rain": "下起了小雨",
    "moderate_rain": "下雨了",
    "heavy_rain": "下起了大雨",
    "other": "天气变幻",
}


def _node_names(spatial) -> dict[str, str]:
    return {n.id: n.name for n in spatial.nodes}


# 任务17 裁决 4.2：从事件 payload 收集 agent_id → 姓名，供渲染层显示姓名（如债争 round=1 主语）。
_AGENT_ID_NAME_PREFIXES = (
    "agent", "spouse", "observer", "target", "creditor", "debtor",
    "head", "old_head", "new_head", "mother", "father", "child",
)


def _agent_names(events: list) -> dict[str, str]:
    names: dict[str, str] = {}
    for evt in events:
        payload = evt.get("payload")
        if not isinstance(payload, dict):
            continue
        for prefix in _AGENT_ID_NAME_PREFIXES:
            agent_id = payload.get(f"{prefix}_id")
            name = payload.get(f"{prefix}_name")
            if agent_id and name:
                names.setdefault(str(agent_id), str(name))
    return names


def _date_str(tick: int, cfg) -> str:
    """把事件 tick 换算成「X年M月D日 节气」字符串（与气候模块同源）。"""
    init = cfg.natural_params.climate_initial
    start_doy = start_day_of_year(init.season, init.season_progress or 0.0)
    year, month, day, solar_term, _ = calendar_from_tick(
        tick, cfg.world.start_tick, start_doy, cfg.world.start_year
    )
    return f"{year}年{month}月{day}日 {solar_term}"


def _bootstrap(run_db: bool = True, seed: int = DEFAULT_SEED) -> World:
    cfg = load_config(WORLD_ID)
    if run_db:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
    event_log = EventLog(DB_PATH if run_db else ":memory:")
    return build_world(cfg, event_log, modules=base_town_modules(seed))


def _narrate(ev: dict, names: dict[str, str]) -> str:
    name = ev["agent_name"]
    action = ev["action"]
    hb = ev["hunger_before"]
    sa = ev["stamina_after"]
    target = ev["target_node"]
    tname = names.get(target, target)

    if hb >= 85:
        prefix = "饿得发慌，"
    elif hb >= 60:
        prefix = "觉得有点饿，"
    else:
        prefix = ""

    if action == "eat":
        body = f"吃了些存粮垫肚子（存粮剩 {ev['grain_after']:.0f} 石）。"
    elif action == "rest":
        if hb >= 60:
            body = f"在家歇了一天，只是肚里发空（饥饿 {ev['hunger_after']:.0f}）。"
        else:
            body = f"在家歇息了一天，缓了缓劲（体力 {sa:.0f}）。"
    elif action == "farm":
        tail = f"累得筋疲力尽，回家歇息（体力 {sa:.0f}）。" if sa < 30 else f"体力尚余 {sa:.0f}。"
        body = f"在{tname}劳作了一天，{tail}"
    elif action == "collect_water":
        body = f"去{tname}打了水，歇了歇脚。"
    elif action == "harvest":
        gain = ev["grain_after"] - ev["grain_before"]
        repaid = ev["debt_before"] - ev["debt_after"]
        body = f"在{tname}秋收了，打下 {gain:.0f} 石粮食（存粮剩 {ev['grain_after']:.0f} 石）"
        if repaid > 0:
            body += f"，还了 {repaid:.0f} 石债"
        body += "。"
    elif action == "borrow_grain":
        amount = ev["grain_after"] - ev["grain_before"]
        body = (f"去{tname}借了 {amount:.0f} 石粮应急（存粮剩 {ev['grain_after']:.0f} 石，"
                f"欠债 {ev['debt_after']:.0f} 石）。")
    else:
        body = f"做了些事（{action}）。"
    return f"[{name}] {prefix}{body}"


def cmd_run(args: argparse.Namespace) -> None:
    world = _bootstrap(run_db=True, seed=args.seed)
    names = _node_names(world.config.spatial)
    start_tick = world.current_tick  # run_tick 内部会自增，记录起点以便把 tick 映射回“第几天”

    climate_by_day: dict[int, dict] = {}
    for day in range(1, args.days + 1):
        run_tick(world)
        climate_by_day[day] = (
            world.state.environment.climate.model_dump() if world.state.environment.climate else {}
        )

    # 事件溯源：先按 tick 分组，再映射到第几天（day = tick - start_tick + 1）
    events_by_tick: dict[int, list[dict]] = {}
    for ev in world.event_log.all():
        events_by_tick.setdefault(ev["tick"], []).append(ev)

    print(f"世界 溪谷镇（{WORLD_ID}）启动，连跑 {args.days} 天，seed={args.seed}。")
    print(f"事件库落盘：{DB_PATH}")
    print("-" * 80)
    for day in range(1, args.days + 1):
        step_tick = start_tick + day - 1
        snap = climate_by_day.get(day) or {}
        w = snap.get("current_weather", "other")
        temp = snap.get("temperature_c", 0.0)
        y = snap.get("year", 1)
        mo = snap.get("month", 1)
        d = snap.get("day", 1)
        st = snap.get("solar_term", "")
        print(f"[第{y}年 {mo}月{d}日 {st}] 溪谷镇{WEATHER_DESC.get(w, w)}，气温 {temp:.0f} 度。")
        for ev in events_by_tick.get(step_tick, []):
            if ev["event_type"] == "agent_action_taken":
                print("  " + _narrate(ev["payload"], names))
    print("-" * 80)
    counts: dict[str, int] = {}
    for ev in world.event_log.all():
        counts[ev["event_type"]] = counts.get(ev["event_type"], 0) + 1
    print("共写入事件：", counts)


def cmd_agent(args: argparse.Namespace) -> None:
    cfg = load_config(WORLD_ID)
    names = _node_names(cfg.spatial)
    target = args.name
    agent_cfg = next((a for a in cfg.agents.agents if a.name == target), None)
    if agent_cfg is None:
        print(f"未找到人物：{target}")
        return

    print(f"== {agent_cfg.name}（{agent_cfg.id}）==")
    print(f"  性别：{agent_cfg.sex.value}  开局年龄：{agent_cfg.age}")
    print(f"  住所：{names.get(agent_cfg.home_node, agent_cfg.home_node)}")
    print(f"  田地：{names.get(agent_cfg.work_node, agent_cfg.work_node)}")
    print(f"  初始存粮：{agent_cfg.assets.grain:.0f} 石")

    if not os.path.exists(DB_PATH):
        print("  （暂无运行记录，请先执行：cli.py run N）")
        return
    el = EventLog(DB_PATH)
    actions = [e for e in el.all() if e["event_type"] == "agent_action_taken" and e["payload"]["agent_name"] == target]
    if not actions:
        print("  （该人物暂无行动记录）")
        el.close()
        return
    last = actions[-1]["payload"]
    print(f"  最近状态：存粮 {last['grain_after']:.0f} 石，欠债 {last['debt_after']:.0f} 石，"
          f"饥饿 {last['hunger_after']:.0f}，体力 {last['stamina_after']:.0f}，"
          f"田地长势 {last['field_growth_after']:.0f}")
    print("  最近 5 次行动：")
    for e in actions[-5:]:
        p = e["payload"]
        print(f"    {_date_str(e['tick'], cfg)} → {p['action']}（目标：{names.get(p['target_node'], p['target_node'])}，天气：{WEATHER_DESC.get(p['weather'], p['weather'])}）")
    el.close()


# ----------------------------------------------------------------------
# 观察层：events 子命令族（只读事件流查看器，任务 07）
# ----------------------------------------------------------------------
def _add_common_args(p: argparse.ArgumentParser) -> None:
    """子解析器共享 --db/--debug。default 用 SUPPRESS：子命令未传时不覆盖 events 级别的值，
    因此 --db/--debug 放在子命令前或后都生效；help 显示说明文本，便于子命令 --help 自查。"""
    p.add_argument("--db", default=argparse.SUPPRESS, help=DB_HELP)
    p.add_argument("--debug", action="store_true", default=argparse.SUPPRESS, help=DEBUG_HELP)


def _add_filter_args(p: argparse.ArgumentParser, default_limit: Optional[int] = 50,
                     match_participants: bool = False) -> None:
    p.add_argument("--agent", help="按人物姓名筛选（payload.agent_name）")
    p.add_argument("--type", action="append", default=[],
                   help="按事件类型筛选，可重复传或逗号分隔，如 --type weather_changed --type agent_action_taken")
    p.add_argument("--from", dest="from_", help="范围下界：纯数字=tick，或「1年7月1日」")
    p.add_argument("--to", help="范围上界：纯数字=tick，或「1年9月30日」（含）")
    p.add_argument("--limit", type=int, default=default_limit,
                   help=f"最多返回条数（默认 {default_limit if default_limit is not None else '全量'}）")
    p.add_argument("--all", action="store_true", help="全量，忽略 --limit")
    p.add_argument("--reverse", action="store_true", help="倒序（最新在前）")
    p.set_defaults(match_participants=match_participants)


def _build_filter(args, cfg) -> EventFilter:
    types: list[str] = []
    for t in getattr(args, "type", []) or []:
        types.extend(x.strip() for x in t.split(",") if x.strip())
    tick_from = expr_to_tick(args.from_, cfg) if getattr(args, "from_", None) else None
    tick_to = expr_to_tick(args.to, cfg) if getattr(args, "to", None) else None
    limit = None if getattr(args, "all", False) else getattr(args, "limit", 50)
    return EventFilter(
        agent=getattr(args, "agent", None),
        event_types=types or None,
        tick_from=tick_from,
        tick_to=tick_to,
        limit=limit,
        reverse=getattr(args, "reverse", False),
        match_participants=getattr(args, "match_participants", False),
    )


def _filter_desc(args) -> str:
    parts = []
    if getattr(args, "agent", None):
        parts.append(f"agent={args.agent}")
    if getattr(args, "type", None):
        parts.append(f"type={','.join(args.type)}")
    if getattr(args, "from_", None):
        parts.append(f"from={args.from_}")
    if getattr(args, "to", None):
        parts.append(f"to={args.to}")
    if getattr(args, "name", None) and getattr(args, "command", None) == "events" \
            and getattr(args, "ev_command", None) == "timeline":
        parts.append(f"timeline={args.name}")
    return ", ".join(parts)


def _print_events(events: list, cfg, names) -> int:
    # 任务17 裁决 4.2：并入人名映射（id→姓名），地名映射优先保既有键
    names = {**_agent_names(events), **(names or {})}
    degraded = 0
    for evt in events:
        r = render_event(evt, names)
        if r.degraded:
            degraded += 1
        tag = " [降级]" if r.degraded else ""
        print(f"  #{evt['id']:<6} [{date_str(evt['tick'], cfg)}] "
              f"{evt['event_type']:<20} {r.text}{tag}")
    print(f"共 {len(events)} 条，其中降级 {degraded} 条。")
    return degraded


def _query(args, cfg):
    store = ReadonlyEventStore(args.db)
    try:
        return apply_filter(store.all(), _build_filter(args, cfg))
    finally:
        store.close()


def cmd_events_list(args) -> None:
    cfg = load_config(WORLD_ID)
    names = _node_names(cfg.spatial)
    events = _query(args, cfg)
    print(f"事件库：{args.db}  |  筛选：{_filter_desc(args) or '无'}")
    _print_events(events, cfg, names)


def cmd_events_timeline(args) -> None:
    cfg = load_config(WORLD_ID)
    names = _node_names(cfg.spatial)
    args.agent = args.name  # 位置参数覆盖 --agent
    events = _query(args, cfg)
    print(f"人物时间线：{args.name}  |  事件库：{args.db}")
    _print_events(events, cfg, names)


def cmd_events_day(args) -> None:
    cfg = load_config(WORLD_ID)
    names = _node_names(cfg.spatial)
    tick_lo, tick_hi = day_tick_range(cfg, args.date)
    args.from_ = str(tick_lo)
    args.to = str(tick_hi)
    events = _query(args, cfg)
    print(f"{date_str(tick_lo, cfg)} 的事件  |  事件库：{args.db}")
    _print_events(events, cfg, names)


def cmd_events_show(args) -> None:
    cfg = load_config(WORLD_ID)
    names = _node_names(cfg.spatial)
    store = ReadonlyEventStore(args.db)
    try:
        evt = store.get(args.event_id)
    finally:
        store.close()
    if evt is None:
        print(f"未找到事件 id={args.event_id}")
        return
    r = render_event(evt, names)
    print(f"事件 #{evt['id']}  tick={evt['tick']}  [{date_str(evt['tick'], cfg)}]  "
          f"类型={evt['event_type']}  降级={'是' if r.degraded else '否'}")
    print(f"摘要：{r.text}")
    if r.degraded:
        print(f"降级原因：{r.reason}")
    print("完整 payload：")
    print(payload_preview(evt))


def cmd_events_export(args) -> None:
    cfg = load_config(WORLD_ID)
    names = _node_names(cfg.spatial)
    fmt = args.format.lower()
    if fmt not in EXPORT_FORMATS:
        raise SystemExit(f"不支持的导出格式：{fmt}（可选：md / csv / jsonl）")
    events = _query(args, cfg)
    if not args.output:
        raise SystemExit("导出需要 -o/--output 指定输出文件")
    text = EXPORT_FORMATS[fmt](
        events, names=names,
        date_of=lambda t: date_str(t, cfg),
        filter_desc=_filter_desc(args),
    )
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(text)
    degraded = sum(1 for e in events if render_event(e, names).degraded)
    print(f"已导出 {len(events)} 条（降级 {degraded} 条）→ {args.output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="溪谷镇模拟器 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="连跑 N 天并打印故事流")
    p_run.add_argument("days", type=int, help="天数（Tick 数）")
    p_run.add_argument(
        "--seed", type=int, default=DEFAULT_SEED,
        help=f"随机种子（默认 {DEFAULT_SEED}；同种子产生一致事件流）",
    )
    p_run.set_defaults(func=cmd_run)

    p_agent = sub.add_parser("agent", help="查询人物状态与最近行动")
    p_agent.add_argument("name", help="人物姓名，如 林远")
    p_agent.set_defaults(func=cmd_agent)

    # events 只读事件流查看器（任务 07）
    p_events = sub.add_parser("events", help="只读事件流查看器")
    p_events.add_argument("--db", default=DB_PATH, help=DB_HELP)
    p_events.add_argument("--debug", action="store_true", help=DEBUG_HELP)
    ev_sub = p_events.add_subparsers(dest="ev_command", required=True)

    p_list = ev_sub.add_parser("list", help="事件列表（可筛选）")
    _add_common_args(p_list)
    _add_filter_args(p_list)
    p_list.set_defaults(func=cmd_events_list)

    p_tl = ev_sub.add_parser("timeline", help="某人物的时间线")
    p_tl.add_argument("name", help="人物姓名，如 林远")
    _add_common_args(p_tl)
    # D14：timeline 默认全量、并匹配 participants；events list 保持旧默认（50 条、仅 agent_name）
    _add_filter_args(p_tl, default_limit=None, match_participants=True)
    p_tl.set_defaults(func=cmd_events_timeline)

    p_day = ev_sub.add_parser("day", help="某一天的全部事件")
    p_day.add_argument("date", help="日期「1年7月1日」或纯 tick 数字")
    _add_common_args(p_day)
    _add_filter_args(p_day)
    p_day.set_defaults(func=cmd_events_day)

    p_show = ev_sub.add_parser("show", help="单事件详情")
    p_show.add_argument("event_id", type=int, help="事件 id")
    _add_common_args(p_show)
    p_show.set_defaults(func=cmd_events_show)

    p_exp = ev_sub.add_parser("export", help="导出事件流（md/csv/jsonl）")
    p_exp.add_argument("format", help="导出格式：md / csv / jsonl")
    p_exp.add_argument("-o", "--output", required=True, help="输出文件路径")
    _add_common_args(p_exp)
    _add_filter_args(p_exp)
    p_exp.set_defaults(func=cmd_events_export)

    args = parser.parse_args()
    try:
        args.func(args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — 面向老板给可读提示，不抛裸堆栈
        print(f"错误：{exc}", file=sys.stderr)
        if getattr(args, "debug", False):
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
