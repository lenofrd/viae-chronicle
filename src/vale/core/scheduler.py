"""Tick 调度器：按显式阶段 + 依赖拓扑调用各模块 step()，并做错误隔离。

核心要求（P7 世界协调）：
- 模块必须显式声明 ``phase``（见 ``core.world.PHASE_*``）与 ``depends_on``；
- 排序先按 phase，再按依赖拓扑，最后按注册顺序稳定；
- 重复模块名、依赖环、缺少 phase 一律明确报错，不静默回退注册顺序；
- 默认所有 World 都要求 depends_on 全部注册，缺依赖即失败（depends_on 是模块契约）；
  只有显式 ``World(allow_missing_dependencies=True)`` 的孤立模块夹具可缺失依赖；
- 某个模块内部崩溃不能让整个世界循环中断：
  捕获 Exception → 打印警告 → 写 module_error 事件 → 继续后续模块。
"""
from __future__ import annotations

import heapq
import traceback

from .world import World


def resolve_order(modules, *, require_dependencies: bool = True) -> list:
    """返回模块执行顺序；调度配置错误一律抛 ValueError。

    ``require_dependencies``：是否要求 ``depends_on`` 的模块必须已注册。默认严格；
    只有显式声明 ``World(allow_missing_dependencies=True)`` 的孤立模块夹具才置 False，
    此时缺失依赖不视为错误，顺序仍由 phase + 拓扑确定。
    """
    names = [getattr(m, "name", None) for m in modules]
    if any(not name for name in names):
        raise ValueError(f"模块缺少 name：{[type(m).__name__ for m in modules]}")
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"模块名重复：{duplicates}")

    missing_phase = [name for name, m in zip(names, modules) if not hasattr(m, "phase")]
    if missing_phase:
        raise ValueError(f"模块未声明 phase：{missing_phase}")

    name_to_mod = dict(zip(names, modules))
    order_index = {name: i for i, name in enumerate(names)}
    indeg = {name: 0 for name in names}
    edges: dict[str, list[str]] = {name: [] for name in names}

    for name, module in zip(names, modules):
        for dep in getattr(module, "depends_on", None) or []:
            if dep == name:
                raise ValueError(f"模块 '{name}' 依赖自身")
            if dep not in name_to_mod:
                if require_dependencies:
                    raise ValueError(f"模块 '{name}' 依赖未注册的模块 '{dep}'")
                continue
            edges[dep].append(name)
            indeg[name] += 1

    # 就绪队列按 (phase, 注册顺序) 取最小：阶段显式，同阶段保持注册顺序稳定。
    counter = 0
    ready: list[tuple[int, int, int, str]] = []
    for name in names:
        if indeg[name] == 0:
            module = name_to_mod[name]
            ready.append((module.phase, order_index[name], counter, name))
            counter += 1
    heapq.heapify(ready)

    result: list[str] = []
    while ready:
        _, _, _, name = heapq.heappop(ready)
        result.append(name)
        for nxt in edges[name]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                module = name_to_mod[nxt]
                heapq.heappush(ready, (module.phase, order_index[nxt], counter, nxt))
                counter += 1

    if len(result) != len(modules):
        remaining = sorted(name for name in names if name not in result)
        raise ValueError(f"模块存在依赖环：{remaining}")
    return [name_to_mod[name] for name in result]


def run_tick(world: World) -> None:
    strict = not bool(getattr(world, "allow_missing_dependencies", False))
    for module in resolve_order(world.modules, require_dependencies=strict):
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
