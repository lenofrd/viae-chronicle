"""家庭访问器（任务 12 家庭模型迁移第 1 步）。

经济单位是 Household：资产/债务/住所/默认工作节点归家庭。
所有模块必须经由本模块访问家庭，禁止散落读取（且不得在 AgentState 保留资产镜像）。
"""
from __future__ import annotations

from vale.core.calendar import DAYS_PER_YEAR
from vale.core.state import AgentState, HouseholdState


def household_of(world, agent: AgentState) -> HouseholdState:
    """返回 agent 所属家庭；家庭缺失视为状态损坏，直接抛错（不静默兜底）。"""
    household = world.state.human.households.get(agent.household_id)
    if household is None:
        raise KeyError(f"household not found for agent {agent.agent_id}: {agent.household_id}")
    return household


def household_members(world, household: HouseholdState) -> list[AgentState]:
    """家庭成员（按 member_ids 顺序；缺失成员跳过，便于重放容错）。"""
    return [
        world.state.human.agents[aid]
        for aid in household.member_ids
        if aid in world.state.human.agents
    ]


def living_households(world) -> list[HouseholdState]:
    """经济池统一入口：家庭仍有存活成员即参与经济（A2 扩展）。"""
    return [
        h for h in world.state.human.households.values()
        if any(
            world.state.human.agents[aid].alive
            for aid in h.member_ids
            if aid in world.state.human.agents
        )
    ]


def work_node_of(world, agent: AgentState) -> str:
    """劳作点解析（阶段二 C）：个人偏好 → 家庭可分配田块 → 家庭默认。

    个人偏好由 AgentModule 对账保证有效（失效时置 None）；家庭 ``work_nodes`` 为空
    （无田、非田默认点）时退回家庭默认 ``work_node``，与既有语义一致。

    田块按「可劳作成员在 member_ids 中的顺序」对位分配：第 k 个可劳作成员取
    第 k 块田（列表长度即按可劳作人数截断，见 AgentModule._desired_work_nodes）。
    不可劳作成员（未成年/高龄）不占劳作位，取默认田 nodes[0]——若用原始
    member_ids 下标取模，未成年穿插在中间时两个劳力会撞到同一块田、另一块闲置。
    """
    if agent.work_node:
        return agent.work_node
    household = household_of(world, agent)
    nodes = household.work_nodes
    if nodes:
        tuning = world.config.agents.tuning

        def capable(member: AgentState) -> bool:
            age = (world.current_tick - member.birth_tick) // DAYS_PER_YEAR
            return tuning.aging.stage_for(age).work_allowed

        if not agent.alive or not capable(agent):
            return nodes[0]
        rank = 0
        for member_id in household.member_ids:
            if member_id == agent.agent_id:
                break
            member = world.state.human.agents.get(member_id)
            if member is not None and member.alive and capable(member):
                rank += 1
        return nodes[rank % len(nodes)]
    return household.work_node


def home_node_of(world, agent: AgentState) -> str:
    return household_of(world, agent).home_node


def inventory_of(world, agent: AgentState, items: list[str] | None = None) -> dict[str, float]:
    """家庭库存快照（默认取集市物品集合的键；只读）。"""
    household = household_of(world, agent)
    if items is None:
        items = ["grain", "meat", "fish", "vegetable", "cloth", "firewood", "herbs", "hardwood", "coin"]
    return {i: round(getattr(household, i, 0.0), 2) for i in items}
