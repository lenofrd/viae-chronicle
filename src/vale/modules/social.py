"""社会认知与关系层 —— 机制层纯函数（任务 16 阶段二）。

设计要点（裁决 §1/§3/§五）：
- 认知：``AgentState.acquaintances`` dict，两级枚举（留五级扩展），TTL 查询时遗忘。
- 记忆：``AgentState.recent_interactions`` 容量 N 环形缓冲，纯由现有事件投影。
- 统一查询：``get_social_view(observer, target)``，决策只读不写事件。
- kin 默认 known 纯函数 ``apply_kin_defaults``，运行时与 replay 共用（裁决 §3.1）。
- 简化点（裁决 §3.3）：交互即互升 KNOWN，未来五级认知细化。
- 留接口（裁决 §五）：``decay_relation`` 签名返回 None，trust/grudge 本轮不实现。
- 印象沉淀层（任务 18 P1）：``AgentState.impressions`` 独立载体，counts 只从记忆
  窗口派生，label 由代码常量规则派生；只在 label 变化时写事件，不接决策。
- 不做：位置跟踪、进入/离开地点触发、多接入点、衰减曲线、印象参与决策。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from vale.core.state import (
    AcquaintanceEntry,
    AcquaintanceLevel,
    ImpressionEntry,
    MemoryEntry,
)

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
    返回 ``{"known": bool, "level": int, "memories": list[MemoryEntry],
    "impression": Optional[ImpressionEntry]}``（任务 18 P1 追加 impression 键，旧调用不读）。
    """
    observer = state.agents.get(observer_id)
    if observer is None:
        return {
            "known": False,
            "level": int(AcquaintanceLevel.UNKNOWN),
            "memories": [],
            "impression": None,
        }
    entry = observer.acquaintances.get(target_id)
    known = bool(
        entry is not None
        and entry.level >= int(AcquaintanceLevel.KNOWN)
        and not is_forgotten(entry, now, ttl)
    )
    level = entry.level if entry is not None else int(AcquaintanceLevel.UNKNOWN)
    # 任务 18 P1：附加印象（无印象为 None），旧调用方不读，向后兼容。
    return {
        "known": known,
        "level": level,
        "memories": recall(observer, target_id),
        "impression": observer.impressions.get(target_id),
    }


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


# --------------------------------------------------------------------------- #
# 印象沉淀层（任务 18 P1：进档案不接决策）
# --------------------------------------------------------------------------- #
# label 由 counts 确定性派生；规则是代码常量，不做配置、不调参（裁决 §3.1）。
IMPRESSION_UNKNOWN = "unknown"
IMPRESSION_DEFAULTING = "defaulting"
IMPRESSION_RELIABLE = "reliable"

# 合成门槛：记忆窗口 ≥2 次交互，或本次出现违约/守约（裁决 §3.3）。
IMPRESSION_MIN_INTERACTIONS = 2
IMPRESSION_DEFAULT_OUTCOMES = ("broken",)
IMPRESSION_HONOR_OUTCOMES = ("repaid", "partial_repaid")


def _impression_memories(agent, target_id: str, window: int) -> list[MemoryEntry]:
    """取对 target 的最近 ``window`` 条债争记忆（记忆窗口，非独立计数器）。"""
    memories = [m for m in recall(agent, target_id) if m.event_type == "debt_dispute"]
    return memories[-window:] if window > 0 else []


def _derive_counts(memories: list[MemoryEntry]) -> dict:
    """counts 只从记忆窗口派生（裁决 §3.5：不写独立累加计数器）。"""
    latest = max(memories, key=lambda m: m.tick) if memories else None
    return {
        "contracts": len(memories),
        "defaults": sum(1 for m in memories if m.outcome in IMPRESSION_DEFAULT_OUTCOMES),
        "repays": sum(1 for m in memories if m.outcome in IMPRESSION_HONOR_OUTCOMES),
        "last_outcome": latest.outcome if latest is not None else None,
        "last_tick": latest.tick if latest is not None else 0,
    }


def impression_label(counts: dict) -> str:
    """label 规则（裁决 §3.1）：违约优先，其次守约，其余 unknown。"""
    contracts = int(counts.get("contracts") or 0)
    defaults = int(counts.get("defaults") or 0)
    repays = int(counts.get("repays") or 0)
    if defaults >= 2 or (contracts > 0 and defaults / contracts >= 0.5):
        return IMPRESSION_DEFAULTING
    if repays >= 2 and defaults == 0:
        return IMPRESSION_RELIABLE
    return IMPRESSION_UNKNOWN


def synthesize_impression(
    state: "WorldState", observer_id: str, target_id: str, window: int,
) -> Optional[ImpressionEntry]:
    """从观察者的记忆窗口重算印象（纯函数、幂等，裁决 §3.3/§3.5）。

    只读记忆，不读已存 impressions，也不读任何独立计数器——即便有人注入
    不一致的 counts，重算结果也不受影响。门槛未达（窗口不足 2 次交互且
    无违约/守约）返回 None，表示「暂不形成印象」。

    快照口径（裁决 18-verdict §3.1）：写入 ``impressions`` 的 counts 是「最近一次
    label 变化时的窗口快照」，随记忆窗口推进会变旧——label 仍正确，但精确计数
    可能滞后。P1 不接决策，不影响行为；P2/trust 层若需精确 counts，应从事件流
    实时重算（只查特定 target 的事件，成本可控），不依赖存储值。
    """
    observer = state.agents.get(observer_id)
    if observer is None or observer_id == target_id:
        return None
    memories = _impression_memories(observer, target_id, window)
    if not memories:
        return None
    latest = max(memories, key=lambda m: m.tick)
    decisive = latest.outcome in IMPRESSION_DEFAULT_OUTCOMES + IMPRESSION_HONOR_OUTCOMES
    if len(memories) < IMPRESSION_MIN_INTERACTIONS and not decisive:
        return None
    counts = _derive_counts(memories)
    return ImpressionEntry(label=impression_label(counts), **counts)


def update_impression(
    world, observer_id: str, target_id: str, window: int,
) -> Optional[str]:
    """_remember_dispute 之后触发合成（裁决 §3.3），仅在 label 变化时写事件。

    首次形成写 ``impression_formed``，label 翻转写 ``impression_changed``；
    label 不变不写事件、也不改写条目——条目即「最近一次 label 变化时的窗口快照」，
    这样运行时与 replay 由同一份事件载荷重建，逐项相等（裁决 §5.2/§5.3）。
    代价（裁决 18-verdict §3.1）：存储 counts 会变旧，精确计数需从事件流重算。
    返回当前 label；门槛未达返回 None。
    """
    entry = synthesize_impression(world.state, observer_id, target_id, window)
    if entry is None:
        return None
    observer = world.state.agents[observer_id]
    old = observer.impressions.get(target_id)
    if old is not None and old.label == entry.label:
        return entry.label
    observer.impressions[target_id] = entry
    target = world.state.agents.get(target_id)
    payload = {
        "observer_id": observer_id,
        "observer_name": observer.name,
        "target_id": target_id,
        "target_name": target.name if target is not None else target_id,
        "label": entry.label,
        "contracts": entry.contracts,
        "defaults": entry.defaults,
        "repays": entry.repays,
        "last_outcome": entry.last_outcome,
        "last_tick": entry.last_tick,
    }
    if old is None:
        world.event_log.append(world.current_tick, "impression_formed", payload)
    else:
        payload["old_label"] = old.label
        world.event_log.append(world.current_tick, "impression_changed", payload)
    return entry.label


def get_impression(state: "WorldState", observer_id: str,
                   target_id: str) -> Optional[ImpressionEntry]:
    """只读查询印象（裁决 §4.1.6）。无印象返回 None，不写事件。"""
    observer = state.agents.get(observer_id)
    if observer is None:
        return None
    return observer.impressions.get(target_id)
