"""人口学基础：年龄派生、存活人物入口、野遇伤害结算。"""

from __future__ import annotations

from vale.core.calendar import DAYS_PER_YEAR
from vale.domains.society.state import AgentState

def age_years(birth_tick: int, tick: int) -> int:
    """当前年龄（整年）。``birth_tick`` 允许为负（开局前出生），唯一真相源。"""
    return (tick - birth_tick) // DAYS_PER_YEAR

def living_agents(agents: dict[str, AgentState]) -> list[AgentState]:
    """存活人物统一入口（A2）：债权人、交易对手、婚配对象、继承候选人一律经此过滤。"""
    return [a for a in agents.values() if a.alive]

def apply_wildlife_attack(world, agent_id: str, damage: float, *, location: str = "") -> bool:
    """野生动物袭击：结算人类个体健康损失，返回是否命中（死亡/不存在直接拒绝）。"""
    agent = world.state.human.agents.get(agent_id)
    if agent is None or not agent.alive:
        return False
    before = agent.health
    agent.health = max(0.0, before - float(damage))
    agent.last_injury_tick = world.current_tick
    world.event_log.append(world.current_tick, "wildlife_attack", {
        "agent_id": agent.agent_id, "agent_name": agent.name,
        "health_before": round(before, 2), "health_after": round(agent.health, 2),
        "location": location, "injury": float(damage),
    })
    return True
