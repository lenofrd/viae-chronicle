"""溪谷镇命令行入口。

用法：
  python src/vale/cli.py run 30          跑 30 天，打印故事流，并落盘事件库
  python src/vale/cli.py agent 林远       查询某人物当前状态与最近行动

事件库落盘路径：data/worlds/<world_id>/cli_run.db（每次 run 覆盖重建）。
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
from vale.modules.agents import AgentModule  # noqa: E402
from vale.modules.climate import ClimateModule  # noqa: E402

WORLD_ID = "brookvale-town-001"
DB_PATH = os.path.join(_ROOT, "data", "worlds", WORLD_ID, "cli_run.db")

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


def _date_str(tick: int, cfg) -> str:
    """把事件 tick 换算成「X年M月D日 节气」字符串（与气候模块同源）。"""
    init = cfg.natural_params.climate_initial
    start_doy = start_day_of_year(init.season, init.season_progress or 0.0)
    year, month, day, solar_term, _ = calendar_from_tick(
        tick, cfg.world.start_tick, start_doy, cfg.world.start_year
    )
    return f"{year}年{month}月{day}日 {solar_term}"


def _bootstrap(run_db: bool = True) -> World:
    cfg = load_config(WORLD_ID)
    if run_db:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
    event_log = EventLog(DB_PATH if run_db else ":memory:")
    world = World(
        world_id=cfg.world.world_id,
        event_log=event_log,
        start_tick=cfg.world.start_tick,
        config=cfg,
    )
    world.register(ClimateModule())
    world.register(AgentModule())
    return world


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
    world = _bootstrap(run_db=True)
    names = _node_names(world.config.spatial)
    start_tick = world.current_tick  # run_tick 内部会自增，记录起点以便把 tick 映射回“第几天”

    climate_by_day: dict[int, dict] = {}
    for day in range(1, args.days + 1):
        run_tick(world)
        climate_by_day[day] = (
            world.state.climate.model_dump() if world.state.climate else {}
        )

    # 事件溯源：先按 tick 分组，再映射到第几天（day = tick - start_tick + 1）
    events_by_tick: dict[int, list[dict]] = {}
    for ev in world.event_log.all():
        events_by_tick.setdefault(ev["tick"], []).append(ev)

    print(f"世界 溪谷镇（{WORLD_ID}）启动，连跑 {args.days} 天。")
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
    print(f"  性别：{agent_cfg.sex.value}  年龄：{agent_cfg.age}")
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


def main() -> None:
    parser = argparse.ArgumentParser(description="溪谷镇模拟器 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="连跑 N 天并打印故事流")
    p_run.add_argument("days", type=int, help="天数（Tick 数）")
    p_run.set_defaults(func=cmd_run)

    p_agent = sub.add_parser("agent", help="查询人物状态与最近行动")
    p_agent.add_argument("name", help="人物姓名，如 林远")
    p_agent.set_defaults(func=cmd_agent)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
