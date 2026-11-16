"""社会认知与关系层 —— 机制层纯函数（任务 16 阶段二）。

设计要点（裁决 §1/§3/§五）：
- 认知：``AgentState.acquaintances`` dict，两级枚举（留五级扩展），TTL 查询时遗忘。
- 记忆：``AgentState.recent_interactions`` 容量 N 环形缓冲，纯由现有事件投影。
- 统一查询：``get_social_view(observer, target)``，决策只读不写事件。
- kin 默认 known 纯函数 ``apply_kin_defaults``，运行时与 replay 共用（裁决 §3.1）。
- 简化点（裁决 §3.3）：交互即互升 KNOWN，未来五级认知细化。
- 留接口（裁决 §五）：``decay_relation`` 签名返回 None，trust/grudge 本轮不实现。
- 不做：位置跟踪、进入/离开地点触发、多接入点、衰减曲线。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from vale.core.state import AcquaintanceEntry, AcquaintanceLevel, MemoryEntry

if TYPE_CHECKING:
    from vale.core.state import WorldState


def _are_kin(a, b) -> bool:
    """两 agent 是否有亲缘关系（配偶 / 父母 / 子女）。"""
    if a.spouse_id == b.agent_id or b.spouse_id == a.agent_id:
        return True
    if a.mother_id == b.agent_id or a.father_id == b.agent_id:
        return True
    if b.mother_id == a.agent_id or b.father_id == a.agent_id:
        return True
    if b.agent_id in a.children_ids or a.agent_id in b.children_ids:
        return True
    return False


def apply_kin_defaults(state: WorldState, now: int) -> None:
    """同户/亲缘默认 known，并刷新 last_seen_tick=now（裁决 §3.1）。

    纯函数、幂等：运行时每 tick 调用 与 replay 结束调用 共用同一份逻辑，
    保证两者认知集合逐项相等。不写事件（避免开局刷屏）。
    刷新 last_seen_tick 使 kin 关系不受 TTL 遗忘——亲属不该互相遗忘。
    """
    agents = list(state.agents.values())
    for i, a in enumerate(agents):
        for b in agents[i + 1:]:
            if a.household_id == b.household_id or _are_kin(a, b):
                _set_known(a, b.agent_id, now)
                _set_known(b, a.agent_id, now)


def _set_known(agent, target_id: str, now: int) -> None:
    entry = agent.acquaintances.get(target_id)
    if entry is None:
        agent.acquaintances[target_id] = AcquaintanceEntry(
            level=int(AcquaintanceLevel.KNOWN), last_seen_tick=now
        )
    else:
        # 已是 known：仅刷新 last_seen_tick 保持不过期，不降级、不写事件
        entry.last_seen_tick = now


def upgrade_acquaintance(
    world, observer_id: str, target_id: str, tick: int,
    cause: str = "interaction", location_source: str = "home",
) -> bool:
    """交互即升级 observer 对 target 的认知到 KNOWN（裁决 §3.2/§3.3）。

    写 ``acquaintance_changed`` 事件。同一对同一级别只写一次（已知则跳过，
    返回 False，且不刷新 last_seen_tick —— 保持运行时与 replay 逐项一致）。
    观察者侧单向：被观察者默认无感。
    """
    observer = world.state.agents.get(observer_id)
    target = world.state.agents.get(target_id)
    if observer is None or target is None or observer_id == target_id:
        return False
    entry = observer.acquaintances.get(target_id)
    old_level = entry.level if entry else int(AcquaintanceLevel.UNKNOWN)
    if old_level >= int(AcquaintanceLevel.KNOWN):
        return False  # 同对同级别只写一次（裁决 §3.2）
    observer.acquaintances[target_id] = AcquaintanceEntry(
        level=int(AcquaintanceLevel.KNOWN), last_seen_tick=tick
    )
    world.event_log.append(tick, "acquaintance_changed", {
        "observer_id": observer_id,
        "observer_name": observer.name,
        "target_id": target_id,
        "target_name": target.name,
        "old_level": old_level,
        "new_level": int(AcquaintanceLevel.KNOWN),
        "location": observer.location,
        "location_source": location_source,
        "cause": cause,
    })
    return True


def record_interaction(
    world, observer_id: str, target_id: str, tick: int, capacity: int,
    event_type: str, outcome: Optional[str], location_source: str = "home",
) -> None:
    """交互发生的统一写入：升级认知（写事件）+ 写记忆（不写事件）。

    观察者侧单向；债争/催收结果处对双方各调一次。
    """
    upgrade_acquaintance(world, observer_id, target_id, tick,
                         cause="interaction", location_source=location_source)
    observer = world.state.agents.get(observer_id)
    if observer is not None:
        record_memory(observer, target_id, event_type, outcome, tick, capacity)


def record_memory(agent, target_id: str, event_type: str, outcome: Optional[str],
                  tick: int, capacity: int) -> None:
    """写一条交互记忆到环形缓冲（不写事件，裁决 §1.2/§3.4）。

    纯净性：只读参数，不读运行时中间态 —— 运行时与 replay 用相同参数调用
    即得逐项相等的结果。满了淘汰最旧（滑动窗口）。
    """
    agent.recent_interactions.append(MemoryEntry(
        tick=tick, target_id=target_id, event_type=event_type, outcome=outcome,
    ))
    if len(agent.recent_interactions) > capacity:
        agent.recent_interactions = agent.recent_interactions[-capacity:]


def recall(agent, target_id: str) -> list[MemoryEntry]:
    """召回对 target 的记忆（裁决 §1.2）。记忆靠容量淘汰，不过 TTL。"""
    return [m for m in agent.recent_interactions if m.target_id == target_id]


def is_forgotten(entry, now: int, ttl: int) -> bool:
    """认知遗忘判定（裁决 §1.4）：``now - last_seen_tick > ttl`` 视为遗忘。

    收口为单一函数，未来换事件驱动衰减曲线只改此函数，调用方不改。
    entry 需有 ``last_seen_tick`` 属性。
    """
    return (now - entry.last_seen_tick) > ttl


def get_social_view(state: WorldState, observer_id: str, target_id: str,
                    now: int, ttl: int) -> dict:
    """统一查询接口（裁决 §1.3/§1.5）：observer 对 target 的认知 + 记忆。

    决策只读，不写事件（裁决 §3.5）。认知过滤已遗忘条目。
    返回 ``{"known": bool, "level": int, "memories": list[MemoryEntry]}``。
    """
    observer = state.agents.get(observer_id)
    if observer is None:
        return {"known": False, "level": int(AcquaintanceLevel.UNKNOWN), "memories": []}
    entry = observer.acquaintances.get(target_id)
    known = bool(
        entry is not None
        and entry.level >= int(AcquaintanceLevel.KNOWN)
        and not is_forgotten(entry, now, ttl)
    )
    level = entry.level if entry is not None else int(AcquaintanceLevel.UNKNOWN)
    return {"known": known, "level": level, "memories": recall(observer, target_id)}


def last_memory_outcome(memories: list[MemoryEntry]) -> Optional[str]:
    """取最近一条记忆的 outcome（按 tick 降序）。供决策读取。"""
    if not memories:
        return None
    return max(memories, key=lambda m: m.tick).outcome


def cleanup_forgotten(world, now: int, ttl: int) -> int:
    """低频遗忘清理（裁决 §3.5）：批量删除已遗忘认知，写 forgot 事件。

    每 ``cleanup_interval`` tick 调一次（由 step 触发）。返回清理条目数。
    """
    count = 0
    for observer in world.state.agents.values():
        for target_id in list(observer.acquaintances.keys()):
            entry = observer.acquaintances[target_id]
            if not is_forgotten(entry, now, ttl):
                continue
            del observer.acquaintances[target_id]
            target = world.state.agents.get(target_id)
            world.event_log.append(now, "acquaintance_changed", {
                "observer_id": observer.agent_id,
                "observer_name": observer.name,
                "target_id": target_id,
                "target_name": target.name if target else target_id,
                "old_level": entry.level,
                "new_level": int(AcquaintanceLevel.UNKNOWN),
                "location": observer.location,
                "location_source": "home",
                "cause": "forgot",
            })
            count += 1
    return count


def decay_relation(entry, now: int) -> Optional[float]:
    """留接口（裁决 §五）：trust/grudge 事件驱动衰减。

    本轮返回 None，不实现。未来填充内部逻辑，调用方（经 get_social_view）不改。
    """
    return None
