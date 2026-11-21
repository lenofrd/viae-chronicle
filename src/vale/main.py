"""阶段四验收脚本：加载真实配置，落盘数据库，跑 10 个 Tick，打印每日气候摘要。

运行：python src/vale/main.py
"""
from __future__ import annotations

import os
import sys

# 让脚本直接 `python src/vale/main.py` 也能找到 vale / config 包
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, _ROOT)

from vale.core.config_loader import load_config  # noqa: E402
from vale.core.event_log import EventLog  # noqa: E402
from vale.core.scheduler import run_tick  # noqa: E402
from vale.core.world import World  # noqa: E402
from vale.domains.environment.climate import ClimateModule  # noqa: E402


def main() -> None:
    cfg = load_config("brookvale-town-001")

    db_dir = os.path.join(_ROOT, "data", "worlds", cfg.world.world_id)
    os.makedirs(db_dir, exist_ok=True)
    db_path = os.path.join(db_dir, "events.db")
    if os.path.exists(db_path):
        os.remove(db_path)  # 每次验收用空库

    log = EventLog(db_path)
    world = World(
        world_id=cfg.world.world_id,
        event_log=log,
        start_tick=cfg.world.start_tick,
        config=cfg,
    )
    world.register(ClimateModule())

    print(f"世界 {cfg.world.name}（{cfg.world.world_id}）启动，start_tick={cfg.world.start_tick}")
    print(f"数据库落盘：{db_path}")
    print("-" * 100)

    for _ in range(10):
        t = world.current_tick
        run_tick(world)
        s = world.state.environment.climate
        print(
            f"Tick {t:>2}: {s.year}年{s.month}月{s.day}日 {s.solar_term:<2} "
            f"season={s.season.value:>6} progress={s.season_progress:.3f} "
            f"weather={s.current_weather.value:>13} temp={s.temperature_c:>5.1f}C "
            f"rain={s.precipitation_mm:>4.1f}mm humidity={s.humidity_pct:>4.1f}% "
            f"drought_acc={s.drought_accumulation:>5.1f} [{s.drought_state.value}]"
        )

    events = log.all()
    type_counts: dict[str, int] = {}
    for e in events:
        type_counts[e["event_type"]] = type_counts.get(e["event_type"], 0) + 1
    print("-" * 100)
    print(f"共写入 {len(events)} 条事件：{type_counts}")
    print(f"落盘文件：{db_path}")


if __name__ == "__main__":
    main()
