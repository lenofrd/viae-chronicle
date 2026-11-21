"""决策感知层：Perception 快照与债权家庭选择（只读世界，不写状态）。"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Optional

from vale.config.schema.natural_params import Season, WeatherType
from vale.core.household import home_node_of, living_households
from vale.core.state import AgentState, HouseholdState

@dataclass
class Perception:
    agent: AgentState
    weather: WeatherType
    temperature_c: float
    is_raining: bool
    season: Season
    work_field_growth: float
    work_field_season_labor_remaining: Optional[float] = None
    lender_node: str = ""
    # 可选债权家庭（存粮 ≥ 借出量的最富其他家庭）；None 表示无人可借 → borrow 不可行
    creditor_household_id: Optional[str] = None
    food_creditor_household_id: Optional[str] = None
    food_creditor_resource: Optional[str] = None
    food_lender_node: str = ""
    # 004：当前位置 → 各候选目标的单程 TU（日内 location 真实化，计距基点由家改为当前位置）；
    # 打分/执行时往返 = 2 × 单程（C1 往返语义保留）。
    distance_from_location: dict[str, float] = field(default_factory=dict)
    # 自己的 work_node 是否为田地：非田地节点（如集市）不允许 farm/harvest，避免"在广场种粮"
    work_node_is_field: bool = True
    # 能否进食（任务12 D9）：家庭有任一可食食物
    can_eat: bool = True
    # 可依赖的监护人 id（叙事字段，无经济语义）；None = 无
    feeder_id: Optional[str] = None
    # 家庭维度快照（决策只依赖 Perception，不直接读 WorldState）
    home_node: str = ""
    work_node: str = ""
    household_grain: float = 0.0
    household_food_days: float = float("inf")
    # 任务30：家庭水缸存量（烹饪需水；不足以做饭时先去打水）
    household_water: float = 0.0
    household_daily_water_need: float = 0.0
    well_distance_from_home: float = float("inf")
    season_progress: float = 0.0
    has_overdue_debt: bool = False
    construction_project_id: Optional[str] = None
    construction_progress: float = 0.0
    construction_target_node: str = ""
    production_efficiency: float = 1.0
    fatigue_efficiency: float = 1.0
    water_service_available: bool = True
    weave_available: bool = False
    # 婚育动作（court / try_for_child）：候选配偶与生育可行性快照。
    # 决策只依赖 Perception，故把"最近适婚对象"与"当前能否生育"在感知层算好。
    courtship_target_id: Optional[str] = None
    courtship_target_name: str = ""
    courtship_distance: float = 0.0
    can_conceive: bool = False
    birth_resource_factor: float = 0.0

def select_creditor(
    world,
    debtor_household_id: str,
    amount: float,
    *,
    spatial=None,
    debtor_home_node: Optional[str] = None,
) -> Optional[HouseholdState]:
    """选择可借出足额粮食的存活家庭。

    有空间索引时优先选最近的可达债主，同距离再选存粮较多者；不提供空间索引
    时保留旧的「最富者优先」纯函数语义，兼容离线调用。
    """
    candidates = [
        h for h in living_households(world)
        if h.household_id != debtor_household_id and h.grain >= amount
    ]
    if not candidates:
        return None
    if spatial is not None and debtor_home_node:
        reachable = [
            (spatial.travel_tu(debtor_home_node, h.home_node), h)
            for h in candidates
        ]
        reachable = [(distance, h) for distance, h in reachable if math.isfinite(distance)]
        if not reachable:
            return None
        return min(reachable, key=lambda item: (item[0], -item[1].grain, item[1].household_id))[1]
    return max(candidates, key=lambda h: (h.grain, h.household_id))

def select_food_creditor(
    world,
    debtor_household_id: str,
    amount: float,
    surplus_threshold: float,
    resources: list[str],
    *,
    spatial=None,
    debtor_home_node: Optional[str] = None,
) -> Optional[tuple[HouseholdState, str]]:
    """选择最近且能在保留自家余粮后借出指定食物的家庭。"""
    candidates = []
    for household in living_households(world):
        if household.household_id == debtor_household_id:
            continue
        for order, resource in enumerate(resources):
            stock = float(getattr(household, resource, 0.0))
            lendable = stock - surplus_threshold
            if lendable + 1e-9 < amount:
                continue
            distance = (
                spatial.travel_tu(debtor_home_node, household.home_node)
                if spatial is not None and debtor_home_node
                else 0.0
            )
            if not math.isfinite(distance):
                continue
            candidates.append((distance, order, -lendable, household.household_id, household, resource))
    if not candidates:
        return None
    chosen = min(candidates, key=lambda item: item[:4])
    return chosen[4], chosen[5]

def _food_lender_node(world, agent: AgentState, spatial=None) -> str:
    tuning = world.config.agents.tuning.borrow
    household = world.state.human.households.get(agent.household_id)
    debtor_home = household.home_node if household is not None else home_node_of(world, agent)
    creditor = select_food_creditor(
        world, agent.household_id, tuning.borrow_food_amount,
        tuning.food_lending_surplus_threshold, tuning.food_resources,
        spatial=spatial, debtor_home_node=debtor_home,
    )
    return creditor[0].home_node if creditor else debtor_home

def _lender_node(world, agent: AgentState, spatial=None) -> str:
    """借粮目标与可行性选择共用同一个最近足额债主。"""
    amount = world.config.agents.tuning.borrow.borrow_grain_amount
    household = world.state.human.households.get(agent.household_id)
    debtor_home = household.home_node if household is not None else home_node_of(world, agent)
    creditor = select_creditor(
        world, agent.household_id, amount,
        spatial=spatial, debtor_home_node=debtor_home,
    )
    return creditor.home_node if creditor is not None else debtor_home
