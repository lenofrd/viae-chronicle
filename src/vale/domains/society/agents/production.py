"""生产口径：动作目标节点、作物类型、预期收成与记账小工具。"""

from __future__ import annotations

import math

from vale.config.schema.agents import AgentTuning
from vale.contracts.queries import EnvironmentQuery, SpatialQuery
from vale.domains.society.households import home_node_of, work_node_of
from vale.domains.society.state import AgentState, HouseholdState
from vale.domains.society.agents.perception import _food_lender_node, _lender_node

# crops.md §4.5 产量公式的中性因子：病虫害/灾害尚未接入，取值等价既有产出。
# moisture 已由灌溉档派生（任务30，见 EnvironmentQuery.moisture_factor）。
YIELD_GROWTH_HEALTH = 1.0
YIELD_DISASTER_DAMAGE = 0.0

def _target_node(action: str, agent: AgentState, world, spatial=None) -> str:
    """动作 → 目标节点（内容映射）。eat 在家；rest 就地（人物当前位置）；
    farm/harvest/weave 在个人劳作点；collect_water 在水井；borrow 去债主家。"""
    if action == "eat":
        return home_node_of(world, agent)
    if action == "rest":
        # 004：「rest = 1 TU 就地回满」——休息不需要先走回家，否则力竭者在家外无法恢复
        return agent.location or home_node_of(world, agent)
    if action in ("farm", "harvest", "weave"):
        return work_node_of(world, agent)
    if action == "collect_water":
        return "well"
    if action in ("court", "try_for_child"):
        # 婚育是"表达意愿"，就地完成；距离只用于评分惩罚，不要求走到对方家。
        return agent.location or home_node_of(world, agent)
    if action == "borrow_grain":
        return _lender_node(world, agent, spatial)
    if action == "borrow_food":
        return _food_lender_node(world, agent, spatial)
    if action == "construct":
        project = next((
            item for item in world.state.human.construction_projects.values()
            if item.household_id == agent.household_id
            and item.status == "under_construction"
        ), None)
        if project is None:
            return ""
        parcel = world.state.human.land_parcels.get(project.parcel_id)
        if parcel is None:
            return ""
        node_id = parcel.spatial_node_id
        valid_nodes = {node.id for node in world.config.spatial.nodes}
        return node_id if node_id in valid_nodes else ""
    gathering = world.config.agents.tuning.gathering.actions
    if action in gathering:
        return gathering[action].target_node
    return home_node_of(world, agent)

def _node_crop_type(world, node_id: str) -> str:
    """田块作物类型（配置层 crop_type）；未知节点按 grain 兜底。"""
    for n in world.config.spatial.nodes:
        if n.id == node_id:
            return getattr(n, "crop_type", "grain") or "grain"
    return "grain"

def expected_yield(world, node_id: str, crop: str, tuning: AgentTuning) -> float:
    """预期收成（crops.md §4.5）：

    base_yield × area × fertility × moisture × growth_health × (1 − disaster_damage)。

    阶段二：moisture 由灌溉档派生（任务30），其余因子取中性值。
    """
    return (
        tuning.agriculture.base_yield.get(crop, 0.0)
        * SpatialQuery.area(world, node_id)
        * EnvironmentQuery.fertility_factor(world, node_id)
        * EnvironmentQuery.moisture_factor(world)
        * YIELD_GROWTH_HEALTH
        * (1.0 - YIELD_DISASTER_DAMAGE)
    )

def _floor_to_step(value: float, step: float) -> float:
    """向下取整到步长（浮点容差 1e-9，避免 6.000000001 被判成 5.5）。"""
    if step <= 0:
        return 0.0
    return math.floor(value / step + 1e-9) * step

def _inventory(household: HouseholdState, items: list[str]) -> dict[str, float]:
    """交易事件载荷用的家庭库存快照（只含给定物品集合）。"""
    return {i: round(getattr(household, i, 0.0), 2) for i in items}
