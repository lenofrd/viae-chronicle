"""家庭访问器（任务 12 家庭模型迁移第 1 步）。

经济单位是 Household：资产/债务/住所/默认工作节点归家庭。
所有模块必须经由本模块访问家庭，禁止散落读取（且不得在 AgentState 保留资产镜像）。
"""
from __future__ import annotations

from vale.core.state import AgentState, HouseholdState


def household_of(world, agent: AgentState) -> HouseholdState:
    """返回 agent 所属家庭；家庭缺失视为状态损坏，直接抛错（不静默兜底）。"""
    household = world.state.households.get(agent.household_id)
    if household is None:
        raise KeyError(f"household not found for agent {agent.agent_id}: {agent.household_id}")
    return household


def household_members(world, household: HouseholdState) -> list[AgentState]:
    """家庭成员（按 member_ids 顺序；缺失成员跳过，便于重放容错）。"""
    return [
        world.state.agents[aid]
        for aid in household.member_ids
        if aid in world.state.agents
    ]


def living_households(world) -> list[HouseholdState]:
    """经济池统一入口：家庭仍有存活成员即参与经济（A2 扩展）。"""
    return [
        h for h in world.state.households.values()
        if any(
            world.state.agents[aid].alive
            for aid in h.member_ids
            if aid in world.state.agents
        )
    ]


def work_node_of(world, agent: AgentState) -> str:
    """个人劳作点偏好优先；None 取家庭默认工作节点。"""
    if agent.work_node:
        return agent.work_node
    return household_of(world, agent).work_node


def home_node_of(world, agent: AgentState) -> str:
    return household_of(world, agent).home_node


def inventory_of(world, agent: AgentState, items: list[str] | None = None) -> dict[str, float]:
    """家庭库存快照（默认取集市物品集合的键；只读）。"""
    household = household_of(world, agent)
    if items is None:
        items = ["grain", "meat", "fish", "vegetable", "cloth"]
    return {i: round(getattr(household, i, 0.0), 2) for i in items}
