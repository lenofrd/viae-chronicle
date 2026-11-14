"""Tick 调度器：按依赖拓扑排序调用各模块 step()，并做错误隔离。

核心要求：
- 模块按 depends_on 做拓扑排序（无依赖则保持注册顺序，稳定）；
- 某个模块内部崩溃不能让整个世界循环中断：
  捕获 Exception → 打印警告 → 写 module_error 事件 → 继续后续模块。
"""
from __future__ import annotations

import traceback
from collections import deque

from .world import World


def _topo_sort(modules):
    """按 depends_on 拓扑排序；循环依赖时回退到注册顺序并告警。"""
    name_to_mod = {m.name: m for m in modules}
    order_index = {m.name: i for i, m in enumerate(modules)}

    indeg = {m.name: 0 for m in modules}
    edges: dict[str, list[str]] = {m.name: [] for m in modules}
    for m in modules:
        for dep in getattr(m, "depends_on", None) or []:
            if dep in name_to_mod and dep != m.name:
                edges[dep].append(m.name)
                indeg[m.name] += 1

    # 入度为 0 的按注册顺序入队，保证稳定
    ready = sorted(
        [m.name for m in modules if indeg[m.name] == 0],
        key=lambda n: order_index[n],
    )
    queue = deque(ready)
    result: list[str] = []
    while queue:
        n = queue.popleft()
        result.append(n)
        for nxt in edges[n]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                # 插入保持注册顺序
                queue.append(nxt)
                queue = deque(sorted(queue, key=lambda x: order_index[x]))

    if len(result) != len(modules):
        print("[WARN] module dependency cycle detected; falling back to registration order")
        return list(modules)
    return [name_to_mod[n] for n in result]


def run_tick(world: World) -> None:
    for module in _topo_sort(world.modules):
        try:
            module.step(world)
        except Exception as exc:  # noqa: BLE001 - 故意捕获所有异常以隔离
            print(
                f"[WARN] module '{module.name}' failed in tick "
                f"{world.current_tick}: {exc!r}"
            )
            world.event_log.append(
                tick=world.current_tick,
                event_type="module_error",
                payload={
                    "module": module.name,
                    "error": repr(exc),
                    "traceback": traceback.format_exc(),
                },
            )
    world.current_tick += 1
