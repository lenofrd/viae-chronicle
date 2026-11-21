"""人物模块：感知隔离 + 效用驱动决策 + 动作执行。

设计约束（system-prompt）：
- 机制/内容分离：所有权重/消耗/阈值来自 world.config.agents（agents.yaml），代码不写死具体数值。
- 事件溯源：agent_action_taken 写入 EventLog（单一真相源），AgentState 是同步维护的快照投影。
- 感知隔离：决策只用 Perception（自身状态 + 天气 + 家到目标的距离），不直接读 WorldState 全貌。
- 模块隔离：单个人物处理异常被捕获、写 agent_error 事件，不影响其他人物与世界。
"""
from __future__ import annotations

import heapq
import math
import random
import traceback
from dataclasses import dataclass, field
from typing import Callable, Optional

from vale.config.schema.agents import AgentSex, AgentTuning
from vale.config.schema.natural_params import Season, WeatherType
from vale.core.calendar import DAYS_PER_YEAR
from vale.core.household import (
    home_node_of,
    household_members,
    household_of,
    inventory_of,
    living_households,
    work_node_of,
)
from vale.contracts.impacts import EcologicalImpact
from vale.contracts.queries import EnvironmentQuery, SpatialQuery
from vale.contracts.resources import ResourceService
from vale.core.state import AgentState, DebtRecord, HouseholdState
from vale.modules import social
from vale.modules.community import (
    environmental_injury_multiplier,
    fatigue_efficiency,
    production_efficiency_at_node,
    service_capacity_available,
    settle_building_maintenance,
    update_building_needs,
)

# 视为降雨的天气（B9：影响户外劳作）
RAIN_WEATHERS = {WeatherType.LIGHT_RAIN, WeatherType.MODERATE_RAIN, WeatherType.HEAVY_RAIN}
# 不可行动作的得分（体力不足 / 无粮等），保证不会被选中
IMPOSSIBLE = float("-inf")

# 候选动作集合（内容外置：动作→目标节点的映射在 _target_node）
CANDIDATE_ACTIONS = ["eat", "rest", "farm", "collect_water", "harvest", "borrow_grain", "borrow_food", "weave", "construct", "court", "try_for_child"]


def age_years(birth_tick: int, tick: int) -> int:
    """当前年龄（整年）。``birth_tick`` 允许为负（开局前出生），唯一真相源。"""
    return (tick - birth_tick) // DAYS_PER_YEAR


def living_agents(agents: dict[str, AgentState]) -> list[AgentState]:
    """存活人物统一入口（A2）：债权人、交易对手、婚配对象、继承候选人一律经此过滤。"""
    return [a for a in agents.values() if a.alive]


def _candidate_actions(tuning: AgentTuning) -> list[str]:
    """基础候选动作 + 配置声明的采集类动作（hunt / 未来 fish）。

    新增第二生计只需在 agents.yaml 的 gathering.actions 下加一项，此处自动纳入候选，
    核心决策循环不改、不出现 ``if action == "hunt"`` 式散落硬编码。
    """
    return CANDIDATE_ACTIONS + list(tuning.gathering.actions.keys())


# --------------------------------------------------------------------------- #
# 空间距离索引：由 SpatialConfig 构建全节点最短耗时（TU）
# --------------------------------------------------------------------------- #
class SpatialIndex:
    """全源最短路径。边来自 distance_edges（双向）+ 各节点 travel_cost_from_well_tu（连到 well）。"""

    def __init__(self, spatial) -> None:
        self._dist: dict[tuple[str, str], float] = {}
        self._build(spatial)

    def _build(self, spatial) -> None:
        nodes = {n.id for n in spatial.nodes}
        adj: dict[str, list[tuple[str, float]]] = {n: [] for n in nodes}
        for e in spatial.distance_edges:
            w = float(e.one_way_tu)
            adj.setdefault(e.from_id, []).append((e.to_id, w))
            adj.setdefault(e.to_id, []).append((e.from_id, w))
        well = "well"
        for n in spatial.nodes:
            cost = getattr(n, "travel_cost_from_well_tu", None)
            if cost is not None and n.id != well:
                adj.setdefault(n.id, []).append((well, float(cost)))
                adj.setdefault(well, []).append((n.id, float(cost)))
        for src in nodes:
            self._dijkstra(src, adj)

    def _dijkstra(self, src: str, adj: dict[str, list[tuple[str, float]]]) -> None:
        dist: dict[str, float] = {src: 0.0}
        pq: list[tuple[float, str]] = [(0.0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist.get(u, float("inf")):
                continue
            for v, w in adj.get(u, []):
                nd = d + w
                if nd < dist.get(v, float("inf")):
                    dist[v] = nd
                    heapq.heappush(pq, (nd, v))
        for v, d in dist.items():
            self._dist[(src, v)] = d

    def travel_tu(self, a: str, b: str) -> float:
        if a == b:
            return 0.0
        return self._dist.get((a, b), float("inf"))


# --------------------------------------------------------------------------- #
# 感知层：只暴露决策所需的最小信息（隔离层）
# --------------------------------------------------------------------------- #
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


# crops.md §4.5 产量公式的中性因子：病虫害/灾害尚未接入，取值等价既有产出。
# moisture 已由灌溉档派生（任务30，见 EnvironmentQuery.moisture_factor）。
YIELD_GROWTH_HEALTH = 1.0
YIELD_DISASTER_DAMAGE = 0.0


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


# --------------------------------------------------------------------------- #
# 个体健康结算（人类域所有者；田块生态结算已迁 modules.ecology，2026-11-21 裁决）
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# 人物模块
# --------------------------------------------------------------------------- #
class AgentModule:
    name = "agents"
    depends_on = ["climate", "ecology"]

    def __init__(self, rng=None) -> None:
        self._spatial: Optional[SpatialIndex] = None
        # 打猎成功率/受伤的随机源：默认独立 Random（故事流非确定），测试传 seeded 实例保证可复现
        self.rng = rng if rng is not None else random.Random()
        self._daily_task_assignments: dict[str, str] = {}
        # 当日结亲意向：agent_id -> target_id。日内由 court 动作写入，
        # 日末 _settle_courtship 结算互为目标的配对后清空。
        self._courtship_offers: dict[str, str] = {}

    # -- 生命周期 ----------------------------------------------------------- #
    def step(self, world) -> None:
        cfg = world.config.agents
        if self._spatial is None:
            self._spatial = SpatialIndex(world.config.spatial)
        self._ensure_agents(world, cfg)
        tuning = cfg.tuning
        # 任务16 阶段二：同户/亲缘默认 known（纯函数，运行时每 tick 与 replay 末尾共用，
        # 裁决 §3.1；不写事件避免开局刷屏）
        social.apply_kin_defaults(world.state, world.current_tick)
        # 阶段二 C：劳作点对账（家庭可分配田块 + 个人偏好失效回收），先于当日决策
        self._reconcile_work_nodes(world, tuning)
        # 家庭先协商当日分工，再由成员分别执行；生存动作仍可覆盖分工。
        self._daily_task_assignments = self._plan_household_work(world, tuning)
        # A1：主循环以 WorldState.agents 为唯一真相源；cfg.agents 只用于开局播种，
        # 运行时新增的新生儿下一 tick 即参与决策/结算/查询。
        for agent_id in list(world.state.human.agents.keys()):
            agent = world.state.human.agents[agent_id]
            try:
                self._process_one(world, agent, tuning)
            except Exception as exc:  # noqa: BLE001 — 模块隔离：单个人物失败不拖垮世界
                self._log_agent_error(world, agent, "daily_action", exc)
        # 共同居住/工作地点形成日常接触；双方各自记录认知，不写入短期互动记忆。
        self._record_shared_location_interactions(world, tuning)
        # 每日结算（任务 08/12）：死亡+继承 → 催收 → 集市 → 婚配 → 生育 → 回血
        self._settle(world, tuning)
        # 004 C1：日末回家——日内 location 已真实化（停在最后动作目标），结算后统一归位，
        # 使次日从家出发。集市结算先于归位，故仍能识别「当日是否在场 market」。
        for agent in living_agents(world.state.human.agents):
            agent.location = home_node_of(world, agent)
        self._settle_fatigue(world, tuning)
        settle_building_maintenance(world, tuning.environment)
        update_building_needs(world, tuning.environment)
        # 任务16 阶段二：低频遗忘清理（裁决 §3.5——批量删过期条目并写 forgot 事件；
        # 决策读取只过滤不写，保持诉求计算只读语义）
        soc = tuning.social
        if world.current_tick > 0 and world.current_tick % soc.cleanup_interval == 0:
            social.cleanup_forgotten(world, world.current_tick, soc.acquaintance_ttl)

    def _record_shared_location_interactions(self, world, tuning: AgentTuning) -> None:
        """共同居住或工作节点视为有日常接触；只更新双向认知，不污染短期互动记忆。"""
        groups: dict[str, list[AgentState]] = {}
        for agent in living_agents(world.state.human.agents):
            meeting_nodes = {
                node for node in (work_node_of(world, agent), home_node_of(world, agent))
                if node
            }
            for node in meeting_nodes:
                groups.setdefault(node, []).append(agent)

        seen_pairs: set[tuple[str, str]] = set()
        for node in sorted(groups):
            members = sorted(groups[node], key=lambda item: item.agent_id)
            if len(members) < 2:
                continue
            # 轮转配对：每 tick 只生成 O(n) 次接触，跨日轮换覆盖同一地点的人群。
            offset = 1 + ((world.current_tick - 1) % (len(members) - 1))
            for index, observer in enumerate(members):
                target = members[(index + offset) % len(members)]
                if observer.household_id == target.household_id:
                    continue
                pair = tuple(sorted((observer.agent_id, target.agent_id)))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                view_a = social.get_social_view(
                    world.state, observer.agent_id, target.agent_id,
                    world.current_tick, tuning.social.acquaintance_ttl,
                )
                view_b = social.get_social_view(
                    world.state, target.agent_id, observer.agent_id,
                    world.current_tick, tuning.social.acquaintance_ttl,
                )
                if view_a["known"] and view_b["known"]:
                    continue
                social.upgrade_acquaintance(
                    world, observer.agent_id, target.agent_id, world.current_tick,
                    cause="interaction", location_source=f"shared:{node}",
                )
                social.upgrade_acquaintance(
                    world, target.agent_id, observer.agent_id, world.current_tick,
                    cause="interaction", location_source=f"shared:{node}",
                )

    def _ensure_agents(self, world, cfg) -> None:
        """仅首次从配置初始化；之后状态快照为唯一真相源（A1）。

        家庭模型第 1 步：每个配置人物建单人家庭 `hh_{id}`，资产/债务/住所/工作节点搬入家庭；
        `AgentConfig.assets/home_node/work_node` 仅作开局输入。
        """
        if world.state.human.agents:
            return
        # 2026-11-21 裁决：无池目录不等于资源无限。有池目录→采集目标必须在目录登记；
        # 无目录但配置了采集动作→启动即报错；无目录且无采集动作→允许（基础世界可不编池）。
        catalog = getattr(world.config, "resources", None) or {}
        actions = cfg.tuning.gathering.actions
        if not catalog and actions:
            raise ValueError(
                "world configures gathering actions but has no resource pool catalog: "
                f"{sorted(g.target_node for g in actions.values())}"
            )
        unregistered = sorted({
            g.target_node for g in actions.values() if g.target_node not in catalog
        })
        if unregistered:
            raise ValueError(
                f"gathering actions target unregistered resource pools: {unregistered}"
            )
        phys = cfg.tuning.physiology
        aging = cfg.tuning.aging
        start_tick = world.current_tick
        node_ids = {n.id for n in world.config.spatial.nodes}
        registry_node = "elder_house" if "elder_house" in node_ids else ("village_head_house" if "village_head_house" in node_ids else None)
        for a in cfg.agents:
            household_id = a.household_id or f"hh_{a.id}"
            household = world.state.human.households.get(household_id)
            if household is None:
                household = HouseholdState(
                    household_id=household_id,
                    member_ids=[a.id],
                    head_id=a.id,
                    grain=a.assets.grain,
                    coin=a.assets.coin,
                    vegetable=a.assets.vegetable,
                    cloth=a.assets.cloth,
                    home_node=a.home_node,
                    work_node=a.work_node,
                    registry_node=registry_node,
                    registered_tick=start_tick if registry_node else None,
                    formed_tick=start_tick,
                )
                world.state.human.households[household_id] = household
                if registry_node:
                    world.event_log.append(start_tick, "household_registered", {
                        "household_id": household_id, "head_id": a.id,
                        "home_node": a.home_node, "work_node": a.work_node,
                        "registry_node": registry_node, "registered_tick": start_tick,
                        "assets": {k: getattr(household, k) for k in ("grain", "coin", "vegetable", "cloth")},
                    })
            else:
                if household.home_node != a.home_node:
                    raise ValueError(f"members of {household_id} must share one home_node")
                if a.id not in household.member_ids:
                    household.member_ids.append(a.id)
                    if registry_node:
                        world.event_log.append(start_tick, "household_member_registered", {
                            "household_id": household_id, "agent_id": a.id,
                            "home_node": household.home_node, "registry_node": registry_node,
                        })
            world.state.human.agents[a.id] = AgentState(
                agent_id=a.id,
                name=a.name,
                surname=a.surname or "",
                sex=a.sex,
                birth_tick=start_tick - a.age * DAYS_PER_YEAR,
                life_stage=aging.stage_for(a.age).name,
                household_id=household_id,
                location=a.home_node,
                work_node=a.work_node,
                health=a.initial_health if a.initial_health is not None else phys.initial_health,
                hunger=a.initial_hunger if a.initial_hunger is not None else phys.initial_hunger,
                stamina=a.initial_stamina if a.initial_stamina is not None else phys.initial_stamina,
                fatigue=phys.initial_fatigue,
            )
        # 初始化田块生态状态（长势 0 / 动态地力中性 / 静态地力抄生成输入）：
        # 环境域所有者执行（2026-11-21 裁决），此处仅按既有触发时序经契约调用，保持确定性。
        EcologicalImpact.ensure_field_states(world)
        # 阶段二 C：播种家庭可分配田块（单人户 = [默认田]，与既有 work_node_of 等价；不写事件）
        for household in world.state.human.households.values():
            household.work_nodes = self._desired_work_nodes(world, household, cfg.tuning)
        # Land parcels are projected only after households and their deterministic field rights exist.
        from vale.modules.land import initialize_land
        initialize_land(world)

    # -- 阶段二 C：劳作点对账（家庭可分配田块 + 个人偏好失效回收）------------- #
    def _work_capable_count(self, world, household: HouseholdState,
                            tuning: AgentTuning) -> int:
        """户内可劳作存活成员数（年龄分段 work_allowed；确定性计数，不依赖 life_stage 投影）。"""
        count = 0
        for member_id in household.member_ids:
            member = world.state.human.agents.get(member_id)
            if member is None or not member.alive:
                continue
            stage = tuning.aging.stage_for(age_years(member.birth_tick, world.current_tick))
            if stage.work_allowed:
                count += 1
        return count

    def _desired_work_nodes(self, world, household: HouseholdState,
                            tuning: AgentTuning) -> list[str]:
        """家庭可分配田块（labor.allocation_policy=deterministic_distance）。

        默认田排首位（保证单人户与既有 work_node_of 等价），其余可达田按
        「家→田距离升序、节点 id 升序」补足；列表长度取可劳作成员数（至少 1）。
        家庭默认劳作点不是田（如集市）时返回空表，保持既有语义、不做田块分配。
        """
        field_ids = list(SpatialQuery.field_ids(world))
        if household.work_node not in field_ids:
            return []
        if self._spatial is None:
            self._spatial = SpatialIndex(world.config.spatial)
        default = household.work_node
        others = sorted(
            (fid for fid in field_ids
             if fid != default
             and self._spatial.travel_tu(household.home_node, fid) != float("inf")),
            key=lambda fid: (self._spatial.travel_tu(household.home_node, fid), fid),
        )
        workers = max(1, self._work_capable_count(world, household, tuning))
        return ([default] + others)[:workers]

    def _reconcile_work_nodes(self, world, tuning: AgentTuning) -> None:
        """每 tick 对账：家庭可分配田块重算 + 个人偏好失效回收（确定性，无随机）。

        - 家庭列表变化写 ``household_work_nodes_changed``（before/after/reason）；
        - 个人偏好指向不存在或不可达节点时置 None，写 ``agent_work_node_changed``
          （reason=preference_invalid）。
        """
        if self._spatial is None:
            self._spatial = SpatialIndex(world.config.spatial)
        for household in living_households(world):
            desired = self._desired_work_nodes(world, household, tuning)
            if desired == household.work_nodes:
                continue
            before = list(household.work_nodes)
            household.work_nodes = desired
            world.event_log.append(
                world.current_tick,
                "household_work_nodes_changed",
                {
                    "household_id": household.household_id,
                    "home_node": household.home_node,
                "well_distance_tu": (
                    round(self._spatial.travel_tu(household.home_node, "well"), 3)
                    if self._spatial is not None else None
                ),
                    "before": before,
                    "after": list(desired),
                    "reason": "reassigned",
                    "work_capable_members": self._work_capable_count(
                        world, household, tuning
                    ),
                },
            )
        node_ids = {n.id for n in world.config.spatial.nodes}
        for agent in living_agents(world.state.human.agents):
            if not agent.work_node:
                continue
            if agent.work_node in node_ids and (
                self._spatial.travel_tu(home_node_of(world, agent), agent.work_node)
                != float("inf")
            ):
                continue
            before = agent.work_node
            agent.work_node = None
            world.event_log.append(
                world.current_tick,
                "agent_work_node_changed",
                {
                    "agent_id": agent.agent_id,
                    "agent_name": agent.name,
                    "household_id": agent.household_id,
                    "before": before,
                    "after": None,
                    "reason": "preference_invalid",
                },
            )

    def _plan_household_work(self, world, tuning: AgentTuning) -> dict[str, str]:
        """Allocate distinct feasible daily tasks across each household's capable members.

        Assignments are preferences, not locks: urgent eating, water and rest needs
        still override them. Extra workers reinforce the best remaining task.
        """
        assignments: dict[str, str] = {}
        excluded = {"eat", "rest", "borrow_grain", "borrow_food"}
        for household in living_households(world):
            workers = []
            for member_id in household.member_ids:
                member = world.state.human.agents.get(member_id)
                if member is None or not member.alive or member.incapacitated:
                    continue
                stage = tuning.aging.stage_for(age_years(member.birth_tick, world.current_tick))
                if stage.work_allowed:
                    workers.append(member)
            # Single-worker households have no division to coordinate; leave their
            # existing utility-driven behavior untouched.
            if len(workers) < 2:
                continue
            workers.sort(key=lambda item: item.agent_id)
            offset = (world.current_tick - 1) % len(workers)
            rotated = workers[offset:] + workers[:offset]
            rank = {member.agent_id: index for index, member in enumerate(rotated)}
            by_action: dict[str, list[tuple[float, int, str]]] = {}
            by_member: dict[str, list[tuple[float, str]]] = {}
            for member in workers:
                perception = self._perceive(world, member)
                options = []
                for action in self._candidate_actions_for(member, tuning):
                    if action in excluded:
                        continue
                    score = self.score_action(action, perception, tuning)
                    if score == IMPOSSIBLE or score <= 0:
                        continue
                    options.append((score, action))
                    by_action.setdefault(action, []).append((score, rank[member.agent_id], member.agent_id))
                by_member[member.agent_id] = options
            task_order = sorted(
                by_action,
                key=lambda action: (-max(item[0] for item in by_action[action]), action),
            )
            assigned_members: set[str] = set()
            for action in task_order:
                choices = sorted(by_action[action], key=lambda item: (-item[0], item[1], item[2]))
                choice = next((item for item in choices if item[2] not in assigned_members), None)
                if choice is None:
                    continue
                assignments[choice[2]] = action
                assigned_members.add(choice[2])
            for member in rotated:
                if member.agent_id in assigned_members:
                    continue
                options = sorted(by_member.get(member.agent_id, []), key=lambda item: (-item[0], item[1]))
                if options:
                    assignments[member.agent_id] = options[0][1]
            household_plan = {
                member_id: action for member_id, action in assignments.items()
                if member_id in household.member_ids
            }
            if household_plan:
                world.event_log.append(world.current_tick, "household_work_plan_created", {
                    "household_id": household.household_id,
                    "assignments": household_plan,
                    "worker_count": len(workers),
                    "distinct_task_count": len(set(household_plan.values())),
                })
        return assignments

    # -- 年龄与衰老（任务12）----------------------------------------------- #
    def _health_cap(self, age: int, tuning: AgentTuning) -> float:
        """健康上限 = 分段乘数 × 100 − 老年衰减，下限 min_health_cap（D3）。"""
        ag = tuning.aging
        base = 100.0 * ag.stage_for(age).health_max_mult
        decline = ag.health_cap_decline_per_year * max(0, age - ag.health_cap_decline_start_age)
        return max(ag.min_health_cap, base - decline)

    def _stamina_cap(self, agent: AgentState, tuning: AgentTuning) -> float:
        stage = tuning.aging.stage_by_name(agent.life_stage) or tuning.aging.stage_for(0)
        return 100.0 * stage.stamina_max_mult

    # -- 004 M5：日内 TU 预算与体力分级 ------------------------------------ #
    def _work_window_tu(self, world) -> float:
        """当日工作窗（TU），随季节取值（natural-params.seasons.*.work_window_tu）。"""
        season = EnvironmentQuery.season(world)
        sparams = world.config.natural_params.climate_evolution.seasons.get(season.value)
        if sparams is None:
            return 10.0
        return float(sparams.work_window_tu)

    def _tu_cost_of(self, action: str, act) -> float:
        """动作 TU 占用；缺省或小于 1 时按 1 计（防止零成本动作导致日内死循环）。"""
        return max(1.0, float(act.tu_cost.get(action, 1.0)))

    def _labor_stamina(self, action: str, act) -> float:
        """动作劳动体力消耗：重活 = heavy_stamina_per_tu × tu_cost；轻活 = 0。

        移动体力另按往返 TU × utility.move_stamina_per_tu 计（见 _score / _execute）。
        """
        if action in act.heavy_actions:
            return act.heavy_stamina_per_tu * self._tu_cost_of(action, act)
        return 0.0

    def _perceived_target(self, action: str, p: Perception, tuning: AgentTuning) -> str:
        """动作目标节点的纯感知版（与 ``_target_node`` 同口径，但不读 world）。

        004：rest 就地（当前位置）；eat 回家；其余到劳作点/水井/债主家/采集点。
        """
        if action == "eat":
            return p.home_node
        if action == "rest":
            return p.agent.location or p.home_node
        if action in ("farm", "harvest", "weave"):
            return p.work_node
        if action == "collect_water":
            return "well"
        if action in ("court", "try_for_child"):
            return p.agent.location or p.home_node
        if action == "borrow_grain":
            return p.lender_node
        if action == "borrow_food":
            return p.food_lender_node
        if action == "construct":
            return p.construction_target_node
        gathering = tuning.gathering.actions
        if action in gathering:
            return gathering[action].target_node
        return p.home_node

    def _tu_total(self, action: str, p: Perception, tuning: AgentTuning) -> float:
        """总 TU = 疲劳调整后的实际劳动时间 + 往返移动时间。

        疲劳不降低单次工作的产出；达到连续高疲劳宽限期后，同一工作
        需要更多 TU，因而挤占当日可完成的其他工作。
        """
        target = self._perceived_target(action, p, tuning)
        if action == "construct":
            one_way = p.distance_from_location.get(target, float("inf")) if target else float("inf")
            if not math.isfinite(one_way):
                return float("inf")
        else:
            one_way = p.distance_from_location.get(target, 0.0)
        base_labor_tu = self._tu_cost_of(action, tuning.action)
        if action in tuning.environment.fatigue_affected_actions:
            efficiency = max(1e-6, fatigue_efficiency(p.agent, tuning.environment))
            base_labor_tu /= efficiency
        return base_labor_tu + 2.0 * one_way

    def _apply_aging(self, world, agent: AgentState, tuning: AgentTuning) -> None:
        """生日结算（D2）：重算分段与上限、按上限截断，分段跨越或上限下降时写一次 agent_aged。

        每人每年至多一条：只有生日（年龄变化）且分段/健康上限变化才写事件。
        """
        tick = world.current_tick
        age = age_years(agent.birth_tick, tick)
        prev_age = age_years(agent.birth_tick, tick - 1)
        aging = tuning.aging
        stage = aging.stage_for(age)
        prev_stage = aging.stage_for(prev_age)
        health_cap = self._health_cap(age, tuning)
        prev_health_cap = self._health_cap(prev_age, tuning)
        stamina_cap = 100.0 * stage.stamina_max_mult
        health_before = agent.health
        stamina_before = agent.stamina

        agent.life_stage = stage.name
        agent.health = min(agent.health, health_cap)
        agent.stamina = min(agent.stamina, stamina_cap)

        if age == prev_age:
            return
        stage_changed = stage.name != prev_stage.name
        cap_declined = health_cap < prev_health_cap
        if not (stage_changed or cap_declined):
            return
        world.event_log.append(
            tick,
            "agent_aged",
            {
                "agent_id": agent.agent_id,
                "agent_name": agent.name,
                "age": age,
                "old_stage": prev_stage.name,
                "new_stage": stage.name,
                "stage_changed": stage_changed,
                "stamina_cap_before": round(100.0 * prev_stage.stamina_max_mult, 2),
                "stamina_cap_after": round(stamina_cap, 2),
                "health_cap_before": round(prev_health_cap, 2),
                "health_cap_after": round(health_cap, 2),
                "health_before": round(health_before, 2),
                "health_after": round(agent.health, 2),
                "stamina_before": round(stamina_before, 2),
                "stamina_after": round(agent.stamina, 2),
            },
        )

    def _check_natural_death(self, world, agent: AgentState, tuning: AgentTuning) -> None:
        """自然死亡判定（D4）：年龄 ≥ 阈值且健康 ≤ 阈值 → health=0、死因 aging。

        确定性触发，不替代饥饿/受伤死亡：置零后复用既有失能→宽限期→死亡链路。
        """
        ag = tuning.aging
        if agent.incapacitated or not agent.alive:
            return
        age = age_years(agent.birth_tick, world.current_tick)
        if age < ag.natural_death_min_age or agent.health > ag.natural_death_health_threshold:
            return
        agent.health = 0.0
        agent.death_cause = "aging"

    def _determine_death_cause(self, agent: AgentState, tuning: AgentTuning) -> str:
        """死因归类（失能时确定）：aging > starvation > injury > illness。"""
        if agent.death_cause is not None:
            return agent.death_cause
        phys = tuning.physiology
        if agent.hunger > phys.hunger_health_damage_threshold:
            return "starvation"
        window = tuning.aging.injury_cause_window_days
        if agent.last_injury_tick is not None and \
                agent.incapacitated_tick is not None and \
                agent.incapacitated_tick - agent.last_injury_tick <= window:
            return "injury"
        return "illness"

    # -- 依赖者进食（任务12 D9）------------------------------------------- #
    def _guardian(self, world, agent: AgentState, tuning: AgentTuning) -> Optional[AgentState]:
        """依赖者的监护人（D9）：在世父母中存粮多者优先（并列取母亲），避免只吃一方饿死另一方。"""
        dep = tuning.dependency
        if not dep.feed_from_parent:
            return None
        age = age_years(agent.birth_tick, world.current_tick)
        if age >= dep.max_age:
            return None
        parents: list[AgentState] = []
        for pid in (agent.mother_id, agent.father_id):
            if not pid:
                continue
            parent = world.state.human.agents.get(pid)
            if parent is not None and parent.alive:
                parents.append(parent)
        if not parents:
            return None
        fields = tuning.physiology.food_fields

        def _stock(p: AgentState) -> float:
            hh = household_of(world, p)
            return sum(getattr(hh, f, 0.0) for f in fields)

        # max() 在并列时返回第一个，父/母顺序保证并列取母亲
        return max(parents, key=_stock)

    def _has_food(self, world, agent: AgentState) -> bool:
        hh = household_of(world, agent)
        return any(getattr(hh, f, 0.0) > 0 for f in world.config.agents.tuning.physiology.food_fields)

    # -- 单个人物的一天 ----------------------------------------------------- #
    def _process_one(self, world, agent: AgentState, tuning: AgentTuning) -> None:
        phys = tuning.physiology

        # 已死亡：完全不参与当日任何处理（结算中的死亡判定已先于此处写好事件）
        if not agent.alive:
            return

        # 0. 生日结算/衰老（台账投影，事件至多 1 条/人/年）
        self._apply_aging(world, agent, tuning)
        # 0b. 自然死亡判定（D4）：健康置零后交由下面的失能链路
        self._check_natural_death(world, agent, tuning)

        # 1. 每日自然生理演化（A1 饥饿增长；A4 饥饿过高掉健康）—— 对失能者也发生（无法进食只会更糟）
        agent.hunger = min(100.0, agent.hunger + phys.hunger_gain_per_tick)
        if agent.hunger > phys.hunger_health_damage_threshold:
            agent.health = max(0.0, agent.health - phys.hunger_health_damage)

        # 1b. 冬季保暖（任务11）：无布御寒扣健康，每人每日至多一条 cold_exposure
        season = EnvironmentQuery.season(world)
        self._apply_cold_exposure(world, agent, tuning, season)

        # 2. 生命状态门控（任务10）：health 触底 → 失能，停止一切主动动作；事件只写一次
        if self._incapacitate_if_needed(world, agent, tuning):
            return  # 本 tick 刚进入失能，不再感知/决策/执行
        if agent.incapacitated:
            return  # 已失能，持续不行动

        # 3–5. 日内 TU 循环（004 M5）：逐动作贪心重规划，直到预算耗尽或无可行动作；
        # 剩余 TU 自动转恢复（闲时 1 TU 回满）。日末回家在 step 结算后统一执行（C1）。
        self._run_intraday(world, agent, tuning)

    def _run_intraday(self, world, agent: AgentState, tuning: AgentTuning) -> None:
        """日内循环：感知 → 打分 → 选动作 → 执行（扣 TU + 体力）→ 逐动作重规划。

        终止条件：TU 预算耗尽（< 1）或无可行动作（后者转闲时恢复）。
        生存门控（hunger 逼近伤害阈值必须 eat）在每次动作选择前检查。
        """
        tu_remaining = self._work_window_tu(world)
        slot = 0
        # 安全上限：预算 + 缓冲，防止浮点/配置异常导致死循环（正常远低于此）
        max_slots = int(tu_remaining) + 8
        while tu_remaining >= 1.0 - 1e-9 and slot < max_slots:
            p = self._perceive(world, agent)
            action = self._decide(
                p, tuning, tu_remaining=tu_remaining,
                preferred_action=self._daily_task_assignments.get(agent.agent_id),
            )
            # 闲时（体力已满仍无更优动作，或无可行动作）：剩余 TU 一次性转休整，
            # 不逐 TU 刷事件（004：闲时同样 1 TU 回满，消耗该 TU）
            if action is None or (
                action == "rest"
                and agent.stamina >= self._stamina_cap(agent, tuning) - 1e-9
            ):
                self._execute(
                    world, agent, "rest", p, tuning,
                    slot=slot + 1, tu_spent=tu_remaining,
                    tu_remaining=0.0, idle=True,
                )
                break
            # 004：单次动作占用 = 动作 TU + 往返移动 TU（老板裁决：移动扣工作窗）
            tu_cost = self._tu_total(action, p, tuning)
            self._execute(
                world, agent, action, p, tuning,
                slot=slot + 1, tu_spent=tu_cost,
                tu_remaining=round(tu_remaining - tu_cost, 3),
            )
            slot += 1
            tu_remaining -= tu_cost

    def _incapacitate_if_needed(self, world, agent: AgentState, tuning: AgentTuning) -> bool:
        """health 触底且尚未失能 → 标记失能、写一次 agent_incapacitated。返回是否本 tick 刚失能。

        纯状态机：已失能/已死亡直接返回 False，保证事件不重复。
        """
        if agent.incapacitated or not agent.alive:
            return False
        if agent.health > tuning.death.incapacitation_health_threshold:
            return False
        agent.incapacitated = True
        agent.incapacitated_tick = world.current_tick
        agent.death_cause = self._determine_death_cause(agent, tuning)
        household = household_of(world, agent)
        food_inventory = {
            field_name: round(float(getattr(household, field_name, 0.0)), 2)
            for field_name in tuning.physiology.food_fields
        }
        world.event_log.append(
            world.current_tick,
            "agent_incapacitated",
            {
                "agent_id": agent.agent_id,
                "agent_name": agent.name,
                "reason": "health_bottomed",
                "household_id": household.household_id,
                "cause": agent.death_cause,
                "health": round(agent.health, 2),
                "hunger": round(agent.hunger, 2),
                "stamina": round(agent.stamina, 2),
                "death_grace_ticks": tuning.death.death_grace_ticks,
                "household_food_inventory": food_inventory,
                "household_food_stock": round(sum(food_inventory.values()), 2),
                "household_water": round(float(household.water), 2),
                "household_member_count": len(household.member_ids),
                "home_node": household.home_node,
            },
        )
        return True

    def _apply_cold_exposure(self, world, agent: AgentState, tuning: AgentTuning, season: Season) -> None:
        """冬季保暖（任务11）：布量达门槛免惩罚，否则扣健康并写 cold_exposure。

        布是耐用品（不每日消耗）；每人每日至多一条事件（本函数每日每人只调用一次）。
        """
        if season != Season.WINTER:
            return
        tex = tuning.textile
        household = household_of(world, agent)
        if household.cloth >= tex.warmth_cloth_threshold:
            return
        # A sound dwelling is meaningful winter shelter, not merely a place to
        # recover fatigue. Clothing remains the strongest protection, while a
        # damaged/absent house exposes residents to progressively more cold.
        home_node = home_node_of(world, agent)
        dwelling = None
        has_home_dwelling = False
        for building in world.state.human.buildings.values():
            if building.building_type != "dwelling":
                continue
            parcel = world.state.human.land_parcels.get(building.parcel_id)
            if parcel is None or parcel.spatial_node_id != home_node:
                continue
            has_home_dwelling = True
            if building.status not in {"active", "occupied", "vacant"} or building.condition <= 0:
                continue
            if dwelling is None or building.condition > dwelling.condition:
                dwelling = building
        shelter_condition = float(dwelling.condition) if dwelling is not None else 0.0
        shelter_id = dwelling.building_id if dwelling is not None else None
        protection = (
            tuning.environment.dwelling_cold_protection * shelter_condition / 100.0
            if dwelling is not None else 0.0
        )
        # Legacy abstract home nodes remain sheltered even when the same world
        # contains non-residential buildings such as a market or shrine.
        if not has_home_dwelling:
            shelter_condition = 100.0
            shelter_id = "legacy_unmodeled_dwelling"
            protection = tuning.environment.dwelling_cold_protection
        base_loss = float(tex.cold_health_loss)
        actual_loss = base_loss * (1.0 - protection)
        if actual_loss <= 1e-9:
            return
        before = agent.health
        agent.health = max(0.0, before - actual_loss)
        world.event_log.append(
            world.current_tick,
            "cold_exposure",
            {
                "agent_id": agent.agent_id,
                "agent_name": agent.name,
                "household_id": household.household_id,
                "cloth": round(household.cloth, 2),
                "warmth_cloth_threshold": tex.warmth_cloth_threshold,
                "dwelling_id": shelter_id,
                "dwelling_condition": round(shelter_condition, 2),
                "dwelling_cold_protection": round(protection, 3),
                "base_loss": round(base_loss, 2),
                "health_before": round(before, 2),
                "health_after": round(agent.health, 2),
                "loss": round(before - agent.health, 2),
            },
        )

    def _candidate_actions_for(self, agent: AgentState, tuning: AgentTuning) -> list[str]:
        """按年龄分段裁剪候选动作：白名单优先，其次 work_allowed；eat/rest 始终保留。"""
        stage = tuning.aging.stage_by_name(agent.life_stage)
        if stage is not None:
            if stage.allowed_actions is not None:
                return ["eat", "rest", *stage.allowed_actions]
            if not stage.work_allowed:
                return ["eat", "rest"]
        return _candidate_actions(tuning)

    def _perceive(self, world, agent: AgentState) -> Perception:
        # _perceive is also a public testing/replay seam; do not require callers
        # to have entered the daily step() lifecycle first. Distance perception
        # must always use the same road-network TU index as production ticks.
        if self._spatial is None:
            self._spatial = SpatialIndex(world.config.spatial)
        tuning = world.config.agents.tuning
        weather = EnvironmentQuery.weather(world)
        temp = EnvironmentQuery.temperature_c(world)
        season = EnvironmentQuery.season(world)
        household = household_of(world, agent)
        work_node = work_node_of(world, agent)
        # 004：日内计距基点 = 人物当前位置（location 真实化），不再固定从家起算
        origin = agent.location
        dist: dict[str, float] = {}
        for act in self._candidate_actions_for(agent, tuning):
            target = _target_node(act, agent, world, self._spatial)
            if not target:
                continue
            dist[target] = self._spatial.travel_tu(origin, target)
        bor = tuning.borrow
        creditor = select_creditor(world, agent.household_id, bor.borrow_grain_amount, spatial=self._spatial, debtor_home_node=household.home_node)
        food_creditor = select_food_creditor(
            world, agent.household_id, bor.borrow_food_amount,
            bor.food_lending_surplus_threshold, bor.food_resources,
            spatial=self._spatial, debtor_home_node=household.home_node,
        )
        guardian = self._guardian(world, agent, tuning)
        construction_project = next(
            (
                p for p in world.state.human.construction_projects.values()
                if p.household_id == agent.household_id
                and p.status == "under_construction"
            ),
            None,
        )
        if construction_project is not None:
            parcel = world.state.human.land_parcels.get(construction_project.parcel_id)
            valid_nodes = {node.id for node in world.config.spatial.nodes}
            construction_target = (
                parcel.spatial_node_id
                if parcel is not None and parcel.spatial_node_id in valid_nodes
                else ""
            )
            if construction_target:
                dist[construction_target] = self._spatial.travel_tu(origin, construction_target)
        else:
            construction_target = ""
        # Food security is measured in household food-days, not grain alone.
        food_stock = sum(max(0.0, float(getattr(household, field_name, 0.0)))
                         for field_name in tuning.physiology.food_fields)
        daily_food_need = 0.0
        daily_water_need = 0.0
        for member_id in household.member_ids:
            member = world.state.human.agents.get(member_id)
            if member is None or not member.alive:
                continue
            member_age = age_years(member.birth_tick, world.current_tick)
            share = (tuning.consumption.minor_food_share
                     if member_age < tuning.dependency.max_age else 1.0)
            daily_food_need += (
                tuning.physiology.eat_grain_cost
                * tuning.physiology.daily_meals_per_member
                * share
            )
            daily_water_need += (
                tuning.water.daily_consumption_per_member
                + tuning.water.water_per_meal
                * tuning.physiology.daily_meals_per_member
                * share
            )
        household_food_days = food_stock / daily_food_need if daily_food_need > 0 else float("inf")
        weave_available = work_node in tuning.textile.workshop_nodes or any(
            building.building_type == "workshop"
            and building.status in {"active", "occupied"}
            and building.condition > 0
            and (parcel := world.state.human.land_parcels.get(building.parcel_id)) is not None
            and parcel.spatial_node_id == work_node
            for building in world.state.human.buildings.values()
        )
        season_key = season.value if hasattr(season, "value") else str(season)
        season_labor_required = tuning.agriculture.field_labor_required_by_season.get(season_key)
        season_year = EnvironmentQuery.year(world)
        labor_record = world.state.human.field_season_labor.get(work_node, {})
        labor_completed = (
            float(labor_record.get("labor_completed", 0.0))
            if labor_record.get("year") == season_year and labor_record.get("season") == season_key
            else 0.0
        )
        season_labor_remaining = (
            max(0.0, float(season_labor_required) - labor_completed)
            if season_labor_required is not None else None
        )
        # 婚育（court / try_for_child）：把候选配偶与生育可行性在感知层算好，
        # 决策阶段不再读 WorldState（感知隔离）。
        courtship_target = (
            self._find_courtship_target(world, agent, tuning)
            if self._marriage_eligible(world, agent, tuning) else None
        )
        spouse = world.state.human.agents.get(agent.spouse_id) if agent.spouse_id else None
        can_conceive = bool(
            agent.sex == AgentSex.FEMALE
            and spouse is not None and spouse.alive
            and spouse.spouse_id == agent.agent_id
            and self._birth_eligible(world, agent, spouse, tuning)
        )
        birth_factor = (
            self._birth_resource_factor(world, agent, tuning) if can_conceive else 0.0
        )
        return Perception(
            agent=agent,
            weather=weather,
            temperature_c=temp,
            is_raining=weather in RAIN_WEATHERS,
            season=season,
            work_field_growth=EnvironmentQuery.field_growth(world, work_node),
            work_field_season_labor_remaining=season_labor_remaining,
            lender_node=_lender_node(world, agent, self._spatial),
            creditor_household_id=creditor.household_id if creditor else None,
            food_creditor_household_id=food_creditor[0].household_id if food_creditor else None,
            food_creditor_resource=food_creditor[1] if food_creditor else None,
            food_lender_node=food_creditor[0].home_node if food_creditor else household.home_node,
            distance_from_location=dist,
            work_node_is_field=SpatialQuery.is_field(world, work_node),
            can_eat=self._has_food(world, agent),
            feeder_id=guardian.agent_id if guardian else None,
            home_node=household.home_node,
            work_node=work_node,
            household_grain=household.grain,
            household_food_days=household_food_days,
            household_water=household.water,
            household_daily_water_need=daily_water_need,
            well_distance_from_home=self._spatial.travel_tu(household.home_node, "well"),
            season_progress=(max(0, world.current_tick - 1) % (DAYS_PER_YEAR // 4)) / (DAYS_PER_YEAR // 4),
            has_overdue_debt=any(d.overdue for d in household.debts),
            construction_project_id=construction_project.project_id if construction_project else None,
            construction_progress=(construction_project.labor_completed / construction_project.labor_required) if construction_project else 0.0,
            construction_target_node=construction_target,
            production_efficiency=production_efficiency_at_node(world, work_node, "weave", tuning.environment),
            fatigue_efficiency=fatigue_efficiency(agent, tuning.environment),
            water_service_available=service_capacity_available(world, "well", "collect_water", tuning.environment),
            weave_available=weave_available,
            courtship_target_id=courtship_target.agent_id if courtship_target else None,
            courtship_target_name=courtship_target.name if courtship_target else "",
            courtship_distance=(
                self._spatial.travel_tu(household.home_node, home_node_of(world, courtship_target))
                if courtship_target else 0.0
            ),
            can_conceive=can_conceive,
            birth_resource_factor=birth_factor,
        )

    # -- 决策（只依赖 Perception + tuning）--------------------------------- #
    def _water_reserve_target(self, p: Perception, tuning: AgentTuning) -> float:
        """按季节可达性决定家庭应提前储备的水量。"""
        water = tuning.water
        daily_need = max(0.0, float(p.household_daily_water_need))
        season = p.season.value if hasattr(p.season, "value") else str(p.season)
        distance = float(p.well_distance_from_home)
        next_season = {"spring": "summer", "autumn": "winter"}.get(season)
        next_access_limit = water.seasonal_access_distance_tu.get(next_season)
        reserve_days = float(water.seasonal_reserve_days.get(season, 0.0))
        if (
            next_access_limit is not None
            and distance > float(next_access_limit)
            and reserve_days > 0
        ):
            # 目标随当前季节推进而增长，避免季初一次性强制囤满而挤占吃饭/生产。
            progress = min(1.0, max(0.0, float(p.season_progress)))
            return max(water.household_stock_target, daily_need * reserve_days * progress)
        return daily_need

    def _decide(
        self, p: Perception, tuning: AgentTuning, tu_remaining: Optional[float] = None,
        preferred_action: Optional[str] = None,
    ) -> Optional[str]:
        # 生存硬门控（任务11 修复）：若今天不进食，饥饿将在下一 tick 跨过伤害阈值，
        # 且自己有食物（或依赖者可由监护人供养），则必须进食。否则体力/做工的效用竞争会让
        # "抱着粮食饿伤"成为稳定循环——这正是移动体力校准后旧回归中全员饿死的根因。
        phys = tuning.physiology
        # Water is a prerequisite for eating and a daily survival requirement.
        # Do not let productive work indefinitely outrank a household water deficit:
        # otherwise a resident can retain food, farm repeatedly, and die dehydrated/
        # starved because the meal action remains unavailable.
        # Trigger only below one household-day of actual drinking + meal water.
        # Using the larger storage target here caused repeated collection after
        # every meal, consuming the whole work window and starving other actions.
        water_target = self._water_reserve_target(p, tuning)
        if water_target > 0 and p.household_water + 1e-9 < water_target:
            if (
                self.score_action("collect_water", p, tuning) != IMPOSSIBLE
                and (
                    tu_remaining is None
                    or self._tu_total("collect_water", p, tuning) <= tu_remaining + 1e-9
                )
            ):
                return "collect_water"
        # If the household has no edible stock, explicitly borrow from a
        # solvent creditor before ordinary production preferences can starve it.
        if (
            not p.can_eat
            and p.household_grain < tuning.borrow.borrow_grain_threshold
            and p.creditor_household_id is not None
            and not p.has_overdue_debt
            and self.score_action("borrow_grain", p, tuning) != IMPOSSIBLE
            and (
                tu_remaining is None
                or self._tu_total("borrow_grain", p, tuning) <= tu_remaining + 1e-9
            )
        ):
            return "borrow_grain"
        if (
            not p.can_eat
            and p.food_creditor_household_id is not None
            and not p.has_overdue_debt
            and self.score_action("borrow_food", p, tuning) != IMPOSSIBLE
            and (
                tu_remaining is None
                or self._tu_total("borrow_food", p, tuning) <= tu_remaining + 1e-9
            )
        ):
            return "borrow_food"
        if (
            p.agent.hunger + phys.hunger_gain_per_tick >= phys.hunger_health_damage_threshold
            and p.can_eat
        ):
            need_water = (
                tuning.water.water_per_meal > 0
                and p.household_water + 1e-9 < tuning.water.water_per_meal
            )
            if need_water:
                # 任务30：有粮无水 → 先去打水（水是做饭前置）；打水不可行时退回常规打分
                if (
                    self.score_action("collect_water", p, tuning) != IMPOSSIBLE
                    and (
                        tu_remaining is None
                        or self._tu_total("collect_water", p, tuning) <= tu_remaining + 1e-9
                    )
                ):
                    return "collect_water"
            elif (
                tu_remaining is None
                or self._tu_total("eat", p, tuning) <= tu_remaining + 1e-9
            ):
                return "eat"  # eat 动作 1 TU + 回家往返 TU，须装得进当日剩余预算
        # 004 M5：逐动作贪心——过滤掉不可行（IMPOSSIBLE）与 TU 装不下的动作，取最高分
        candidates = self._candidate_actions_for(p.agent, tuning)
        scored: list[tuple[float, str]] = []
        for cand in candidates:
            s = self.score_action(cand, p, tuning)
            if s == IMPOSSIBLE:
                continue
            if (
                tu_remaining is not None
                and self._tu_total(cand, p, tuning) > tu_remaining + 1e-9
            ):
                continue
            if cand == preferred_action:
                s += tuning.utility.household_task_priority_bonus
            scored.append((s, cand))
        if not scored:
            return None  # 无可行且装得下的动作 → 上层转闲时恢复
        # 最高分胜出；同分按候选顺序稳定取第一个（B10：本阶段不实现纠局）
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    def score_action(self, action: str, p: Perception, tuning: AgentTuning) -> float:
        """对单个动作打分。可独立测试（如对比雨天/晴天 farm 得分）。"""
        weights = tuning.utility.need_weights

        def urgency(need: str) -> float:
            if need == "survival":
                return p.agent.hunger / 100.0
            if need == "stamina":
                return 1.0 - p.agent.stamina / 100.0
            if need == "economy":
                return (
                    tuning.utility.economy_urgency_grain_zero
                    if p.household_grain <= 0
                    else tuning.utility.economy_urgency_grain_positive
                )
            if need == "food_security":
                target_days = tuning.utility.food_security_target_days
                return max(0.0, min(1.0, 1.0 - p.household_food_days / target_days))
            if need == "family":
                # 家族延续是持续动机，不随饥饿波动；能否行动由可行性闸（未婚/可生育）控制，
                # 生育强弱另由 try_for_child 的资源安全度乘子决定。
                return 1.0
            return 0.0

        return self._score(action, p, tuning, weights, urgency)

    def _score(
        self,
        action: str,
        p: Perception,
        tuning: AgentTuning,
        weights: dict[str, float],
        urgency: Callable[[str], float],
    ) -> float:
        agent = p.agent
        act = tuning.action
        util = tuning.utility
        agr = tuning.agriculture
        bor = tuning.borrow

        # 目标节点（决策只依赖 Perception，故用 p.lender_node 而非 world）
        target = self._perceived_target(action, p, tuning)

        # 可行性前置过滤（不可行 → -inf，不会被选中）
        stage = tuning.aging.stage_by_name(agent.life_stage)
        if stage is not None and not stage.work_allowed and action not in ("eat", "rest"):
            return IMPOSSIBLE  # 幼年不劳作（D3 work_allowed）
        if action == "eat" and not p.can_eat:
            return IMPOSSIBLE
        # Eating is a discrete survival action, not a free utility sink. Only
        # allow it when skipping the meal would cross the next-tick hunger
        # damage threshold; _decide() then gives it hard priority.
        if (
            action == "eat"
            and agent.hunger + tuning.physiology.hunger_gain_per_tick
            < tuning.physiology.hunger_health_damage_threshold
        ):
            return IMPOSSIBLE
        if action == "weave" and not p.weave_available:
            return IMPOSSIBLE
        if action == "collect_water" and not p.water_service_available:
            return IMPOSSIBLE
        # 任务30：烹饪/佐餐需水——水缸不足一餐用量时无法进食（先去 collect_water）
        if (
            action == "eat"
            and tuning.water.water_per_meal > 0
            and p.household_water + 1e-9 < tuning.water.water_per_meal
        ):
            return IMPOSSIBLE
        if action == "borrow_grain" and p.household_grain >= bor.borrow_grain_threshold:
            return IMPOSSIBLE
        # 婚育：无候选配偶 / 当前不可生育 → 不可行（是否"想"由效用决定）
        if action == "court" and p.courtship_target_id is None:
            return IMPOSSIBLE
        if action == "try_for_child" and not p.can_conceive:
            return IMPOSSIBLE
        # 生育粮闸：家庭存粮撑不到配置天数时，agent 主动不生育（内容外置的 [调参] 值）
        if action == "try_for_child" and p.household_food_days < tuning.birth.min_food_days:
            return IMPOSSIBLE
        if action == "construct" and (
            p.construction_project_id is None or not p.construction_target_node
        ):
            return IMPOSSIBLE
        if action == "construct" and p.construction_progress >= 1.0:
            return IMPOSSIBLE
        # 只有田地能 farm/harvest：work_node 是集市等非田地节点时禁止，避免"在广场种粮"
        if action in ("farm", "harvest") and not p.work_node_is_field:
            return IMPOSSIBLE
        if action == "harvest" and (
            p.season != Season.AUTUMN or p.work_field_growth < agr.harvest_growth_threshold
        ):
            return IMPOSSIBLE
        # farm 封顶：长势达上限后不可再选 farm，避免无效劳作与体力消耗（任务 08）
        if action == "farm" and p.work_field_growth >= agr.max_field_growth:
            return IMPOSSIBLE
        if action == "farm" and p.work_field_season_labor_remaining is not None and p.work_field_season_labor_remaining <= 1e-9:
            return IMPOSSIBLE
        # borrow 可行性：存粮 < 阈值（上已判） + 有存粮足够的债主 + 无逾期债务
        if action == "borrow_grain":
            if p.creditor_household_id is None or p.has_overdue_debt:
                return IMPOSSIBLE
        if action == "borrow_food":
            if p.food_creditor_household_id is None or p.has_overdue_debt or p.can_eat:
                return IMPOSSIBLE

        one_way = p.distance_from_location.get(target, 0.0)
        if action == "construct" and (not target or not math.isfinite(one_way)):
            return IMPOSSIBLE
        round_trip = one_way * 2.0  # C1：往返

        move_stamina = round_trip * util.move_stamina_per_tu
        # 004 M5：体力分级——重活按速率 × TU 结算劳动体力，轻活为 0
        labor_stamina = self._labor_stamina(action, act)
        if action == "construct":
            labor_stamina = 5.0
        total_stamina_cost = move_stamina + labor_stamina
        # 可行性闸（004「TU 够 + 体力够」双门槛）：移动体力须付得起；
        # 重活还需尚有余力（一次重活≈满格 100，结算后归零，必须 rest 回满才能再干——
        # 这正是「体力是小时级节奏器、防止连续重活」的实现口径；轻活 labor=0 不受此限）。
        if agent.stamina < move_stamina:
            return IMPOSSIBLE
        if labor_stamina > 0 and agent.stamina <= 0:
            return IMPOSSIBLE

        # 效用 = Σ weight(need) * 紧缺度(need) * fulfill(action, need)
        # [机制修正] 原 (1 + 紧缺度) 会给每个需求留 +1 地板，导致 rest 等即使不紧缺也有正分、
        # 压过一切；改为紧缺度为 0 时贡献为 0（标准效用 AI 形式）。权重/fulfill 已相应重平衡。
        fulfill = act.fulfill.get(action, {})
        gross = 0.0
        for need, w in weights.items():
            if w == 0:
                continue
            gross += w * urgency(need) * fulfill.get(need, 0.0)

        if action == "construct":
            construction_urgency = max(0.0, 1.0 - p.construction_progress)
            gross += weights.get("economy", 1.0) * urgency("economy") * 2.0 * construction_urgency
            season_key = p.season.value if hasattr(p.season, "value") else str(p.season)
            gross *= tuning.environment.construction_season_multiplier.get(season_key, 1.0)

        # 任务30：家庭存水低于目标 → 打水紧迫度上升（避免依赖者无水可炊）
        wcfg = tuning.water
        if action == "collect_water" and wcfg.household_stock_target > 0:
            shortage = max(0.0, 1.0 - p.household_water / wcfg.household_stock_target)
            gross += wcfg.scarcity_weight * shortage

        if action == "weave":
            gross *= p.production_efficiency

        if action == "try_for_child":
            # 生育意愿随家庭资源安全度连续下降：缺粮/缺水时 agent 主动放弃生育。
            # 负反馈内建在效用里，不再依赖系统按 resource_factor 抽签兜底。
            gross *= max(0.0, 1.0 - urgency("food_security")) * p.birth_resource_factor
            if gross <= 0.0:
                return IMPOSSIBLE

        # 减去体力惩罚（归一化到与 gross 同量级）与距离惩罚
        stamina_penalty = total_stamina_cost / util.stamina_score_divisor
        score = gross - stamina_penalty - round_trip * util.distance_penalty_per_tu

        # 天气影响（B9）：雨天户外动作得分 × 乘数
        if p.is_raining and action in act.outdoor:
            score *= util.rain_outdoor_score_multiplier

        return score

    # -- 执行（更新快照投影 + 写事件）-------------------------------------- #
    def _execute(
        self,
        world,
        agent: AgentState,
        action: str,
        p: Perception,
        tuning: AgentTuning,
        *,
        slot: int = 1,
        tu_spent: Optional[float] = None,
        tu_remaining: Optional[float] = None,
        idle: bool = False,
    ) -> None:
        phys = tuning.physiology
        util = tuning.utility
        act = tuning.action
        agr = tuning.agriculture
        bor = tuning.borrow

        # 004：直接调用（单测/外部）时补默认日内字段；日内循环会显式传入
        target = _target_node(action, agent, world, self._spatial)
        household = household_of(world, agent)
        work_node = work_node_of(world, agent)
        crop = _node_crop_type(world, work_node) if action == "harvest" else None
        one_way = p.distance_from_location.get(target, 0.0)
        if action == "construct":
            expected_target = p.construction_target_node
            if not expected_target or target != expected_target or not math.isfinite(one_way):
                raise ValueError("construction parcel must resolve to a reachable spatial node")
        round_trip = one_way * 2.0
        if tu_spent is None:
            # 直接调用与日内调度保持同一口径：疲劳延长劳动时间，不减少单次工作产出。
            labor_tu = self._tu_cost_of(action, act)
            if action in tuning.environment.fatigue_affected_actions:
                labor_tu /= max(1e-6, fatigue_efficiency(agent, tuning.environment))
            tu_spent = labor_tu + round_trip
        if tu_remaining is None:
            tu_remaining = max(0.0, self._work_window_tu(world) - tu_spent)

        move_stamina = round_trip * util.move_stamina_per_tu
        # 004 M5：体力分级——重活按速率 × TU，轻活为 0（不再读已废弃的 stamina_cost 平表）
        labor_stamina = self._labor_stamina(action, act)

        hunger_before = agent.hunger
        household_inv_before = inventory_of(world, agent, list(tuning.market.trade_values))
        grain_before = household.grain
        coin_before = household.coin
        meat_before = household.meat
        fish_before = household.fish
        vegetable_before = household.vegetable
        cloth_before = household.cloth
        water_before = household.water
        debt_before = household.debt
        field_growth_before = EnvironmentQuery.field_growth(world, work_node)
        harvest_detail: dict = {}

        # 扣体力（移动 + 分级劳动体力）
        agent.stamina = max(0.0, agent.stamina - move_stamina - labor_stamina)

        # 动作效果
        fed_by = "self"
        if action == "eat":
            # D9 改写：直接消费家庭库存（未成年人不再从父母个人账户转账）
            agent.hunger = max(0.0, agent.hunger - phys.eat_hunger_reduction)
            # 阶段三第2轮：未成年人单次进食按 consumption.minor_food_share 扣减库存；
            # 成年恒为 1.0（与既有行为一致）。饥饿降低量、评分、其他消费逻辑均不变。
            share = (
                tuning.consumption.minor_food_share
                if age_years(agent.birth_tick, world.current_tick) < tuning.dependency.max_age
                else 1.0
            )
            cost = phys.eat_grain_cost * share
            available = sum(getattr(household, f, 0.0) for f in phys.food_fields)
            if available >= cost:
                for f in phys.food_fields:
                    stock = getattr(household, f, 0.0)
                    if stock >= cost:
                        setattr(household, f, round(stock - cost, 2))
                        break
            else:
                # 存量不足：吃尽家庭现有食物（不产生负数，不跨家庭转账）
                for f in phys.food_fields:
                    setattr(household, f, 0.0)
            guardian = self._guardian(world, agent, tuning)
            if guardian is not None:
                fed_by = guardian.name  # 仅叙事：实际照料者
            # 任务30：烹饪/佐餐用水（可行性已保证够一餐，扣后不为负）
            per_meal = tuning.water.water_per_meal
            if per_meal > 0:
                household.water = round(max(0.0, household.water - per_meal), 2)
        elif action == "rest":
            # 004：rest 与闲时均 1 TU 回满（旧 rest_stamina_recovery 线性回复已废弃，劳逸比 4:1）
            agent.stamina = self._stamina_cap(agent, tuning)
        elif action == "farm":
            # 每季每块田有显式劳动预算；效率低的人仍完成相同工作单元，但占用更多 TU。
            season_key = p.season.value if hasattr(p.season, "value") else str(p.season)
            season_year = EnvironmentQuery.year(world)
            required_labor = agr.field_labor_required_by_season.get(season_key)
            if required_labor is not None:
                previous = world.state.human.field_season_labor.get(work_node, {})
                completed = (
                    float(previous.get("labor_completed", 0.0))
                    if previous.get("year") == season_year and previous.get("season") == season_key
                    else 0.0
                )
                after_labor = min(float(required_labor), completed + agr.field_labor_per_farm)
                world.state.human.field_season_labor[work_node] = {
                    "year": season_year, "season": season_key,
                    "labor_completed": round(after_labor, 3),
                }
                world.event_log.append(world.current_tick, "field_labor_progressed", {
                    "field_node": work_node, "year": season_year, "season": season_key,
                    "labor_before": round(completed, 3), "labor_after": round(after_labor, 3),
                    "labor_required": float(required_labor), "agent_id": agent.agent_id,
                    "household_id": household.household_id,
                })
            # 只提升长势，绝不直接产粮（农业周期：farm → 累积 → harvest）。
            # 意图携带增量（含 max_field_growth 截断），环境所有者校验边界并结算（2026-11-21 裁决）。
            delta = max(
                0.0, min(agr.field_growth_per_farm, agr.max_field_growth - field_growth_before)
            )
            EcologicalImpact.farm_growth(
                world, work_node, delta,
                agent_id=agent.agent_id, household_id=household.household_id,
            )
        elif action == "harvest":
            # 秋季且长势达标：长势经契约由环境所有者复位归零；
            # 按 crops.md §4.5 公式产出对应作物（grain / vegetable），产出进家庭库存。
            EcologicalImpact.harvest_reset(
                world, work_node, agent_id=agent.agent_id, household_id=household.household_id,
            )
            base_gain = expected_yield(world, work_node, crop, tuning)
            gain = base_gain
            harvest_detail = {
                "crop": crop,
                "base_yield": tuning.agriculture.base_yield.get(crop, 0.0),
                "field_area": SpatialQuery.area(world, work_node),
                "field_fertility": EnvironmentQuery.fertility_factor(world, work_node),
                # 任务30：moisture 由灌溉档派生（旧库缺失时观察层按 1.0 降级）
                "moisture": EnvironmentQuery.moisture_factor(world),
                "base_expected_yield": round(base_gain, 2),
                "expected_yield": round(gain, 2),
            }
            setattr(household, crop, round(getattr(household, crop, 0.0) + gain, 2))
            self._repay_debts(
                world, agent, tuning, source="harvest", max_repay=agr.harvest_debt_repayment
            )
        elif action == "borrow_grain":
            # 借粮闭合：从债权家庭扣粮、债务家庭加粮、创建家庭债务记录；无债主/不足则不借
            amount = bor.borrow_grain_amount
            creditor_hh = select_creditor(world, household.household_id, amount, spatial=self._spatial, debtor_home_node=household.home_node)
            if creditor_hh is not None and creditor_hh.grain >= amount:
                creditor_grain_before = creditor_hh.grain
                creditor_hh.grain = round(creditor_hh.grain - amount, 2)
                household.grain = round(household.grain + amount, 2)
                due_tick = world.current_tick + tuning.debt.due_days
                household.debts.append(
                    DebtRecord(
                        debtor_household_id=household.household_id,
                        creditor_household_id=creditor_hh.household_id,
                        amount=amount,
                        originated_tick=world.current_tick,
                        due_tick=due_tick,
                    )
                )
                creditor_head = world.state.human.agents.get(creditor_hh.head_id or "")
                creditor_name = creditor_head.name if creditor_head else creditor_hh.household_id
                world.event_log.append(
                    world.current_tick,
                    "debt_formed",
                    {
                        "creditor_id": creditor_head.agent_id if creditor_head else creditor_hh.household_id,
                        "creditor_name": creditor_name,
                        "debtor_id": agent.agent_id,
                        "debtor_name": agent.name,
                        "creditor_household_id": creditor_hh.household_id,
                        "debtor_household_id": household.household_id,
                        "household_id": household.household_id,
                        "debt_type": "grain",
                        "amount": round(amount, 2),
                        "due_tick": due_tick,
                        "originated_tick": world.current_tick,
                        "debtor_grain_before": round(grain_before, 2),
                        "debtor_grain_after": round(household.grain, 2),
                        "creditor_grain_before": round(creditor_grain_before, 2),
                        "creditor_grain_after": round(creditor_hh.grain, 2),
                        "debt_before": round(debt_before, 2),
                        "debt_after": round(household.debt, 2),
                    },
                )
            # 若 creditor 为 None 或存粮不足（理论上 _score 已过滤），不产粮不欠债，仅消耗往返体力
        elif action == "borrow_food":
            pair = select_food_creditor(
                world, household.household_id, bor.borrow_food_amount,
                bor.food_lending_surplus_threshold, bor.food_resources,
                spatial=self._spatial, debtor_home_node=household.home_node,
            )
            if pair is not None:
                creditor_hh, resource = pair
                creditor_before = float(getattr(creditor_hh, resource))
                debtor_before = float(getattr(household, resource))
                amount = min(bor.borrow_food_amount, max(0.0, creditor_before - bor.food_lending_surplus_threshold))
                if amount > 0:
                    setattr(creditor_hh, resource, round(creditor_before - amount, 2))
                    setattr(household, resource, round(debtor_before + amount, 2))
                    due_tick = world.current_tick + tuning.debt.due_days
                    household.debts.append(
                        DebtRecord(
                            debtor_household_id=household.household_id,
                            creditor_household_id=creditor_hh.household_id,
                            amount=amount,
                            originated_tick=world.current_tick,
                            due_tick=due_tick,
                            origin="food_loan",
                            resource=resource,
                        )
                    )
                    creditor_head = world.state.human.agents.get(creditor_hh.head_id or "")
                    world.event_log.append(
                        world.current_tick,
                        "debt_formed",
                        {
                            "creditor_id": creditor_head.agent_id if creditor_head else creditor_hh.household_id,
                            "creditor_name": creditor_head.name if creditor_head else creditor_hh.household_id,
                            "debtor_id": agent.agent_id,
                            "debtor_name": agent.name,
                            "creditor_household_id": creditor_hh.household_id,
                            "debtor_household_id": household.household_id,
                            "household_id": household.household_id,
                            "debt_type": resource,
                            "resource": resource,
                            "origin": "food_loan",
                            "amount": round(amount, 2),
                            "due_tick": due_tick,
                            "originated_tick": world.current_tick,
                            f"debtor_{resource}_before": round(debtor_before, 2),
                            f"debtor_{resource}_after": round(getattr(household, resource), 2),
                            f"creditor_{resource}_before": round(creditor_before, 2),
                            f"creditor_{resource}_after": round(getattr(creditor_hh, resource), 2),
                            "debt_before": round(debt_before, 2),
                            "debt_after": round(household.debt, 2),
                        },
                    )
        elif action == "weave":
            self._execute_weave(world, agent, p, tuning)
        elif action in tuning.gathering.actions:
            self._execute_gather(world, agent, action, p, tuning)
        elif action == "construct":
            from vale.modules.construction import advance_construction
            project_id = p.construction_project_id
            if project_id is None:
                raise ValueError("construction action selected without an active household project")
            advance_construction(world, project_id, worker_id=agent.agent_id)
        elif action == "collect_water":
            # 任务30：生活用水最小切片——取水按水源库存结算（P3a），日耗在结算扣减
            collected = ResourceService.withdraw_water(
                world, "well", tuning.water.collect_amount,
                requester_id=household.household_id,
            )
            household.water = round(household.water + collected, 2)
        elif action == "court":
            self._execute_court(world, agent, p, tuning)
        elif action == "try_for_child":
            self._execute_try_for_child(world, agent, p, tuning)

        field_growth_after = EnvironmentQuery.field_growth(world, work_node)

        # 004：日内位置真实化——动作结束停在目标节点；日末回家由 step 统一归位（C1）
        # 取水动作代表到井取水并把水带回家；往返 TU 已计入动作成本。
        agent.location = home_node_of(world, agent) if action == "collect_water" else target

        # 快照投影：最近动作（事件溯源的镜像，便于 CLI 查询）
        agent.last_action = action
        agent.recent_actions.insert(0, action)
        if len(agent.recent_actions) > 5:
            agent.recent_actions = agent.recent_actions[:5]

        # 事件溯源：写 agent_action_taken（C4 命名）
        world.event_log.append(
            world.current_tick,
            "agent_action_taken",
            {
                "agent_id": agent.agent_id,
                "agent_name": agent.name,
                "household_id": household.household_id,
                "action": action,
                "household_role": self._daily_task_assignments.get(agent.agent_id),
                "work_node": work_node,
                "target_node": target,
                # 004 日内字段：序号 1 起；旧库缺字段时观察层按默认 slot=1 降级
                "slot": slot,
                "tu_spent": round(tu_spent, 3),
                "tu_remaining": round(max(0.0, tu_remaining), 3),
                "round_trip_tu": round(round_trip, 3),
                "move_stamina": round(move_stamina, 3),
                "labor_stamina": round(labor_stamina, 3),
                "idle": idle,
                "hunger_before": round(hunger_before, 2),
                "hunger_after": round(agent.hunger, 2),
                "grain_before": round(grain_before, 2),
                "grain_after": round(household.grain, 2),
                "coin_before": round(coin_before, 2),
                "coin_after": round(household.coin, 2),
                "meat_before": round(meat_before, 2),
                "meat_after": round(household.meat, 2),
                "fish_before": round(fish_before, 2),
                "fish_after": round(household.fish, 2),
                "vegetable_before": round(vegetable_before, 2),
                "vegetable_after": round(household.vegetable, 2),
                "cloth_before": round(cloth_before, 2),
                "cloth_after": round(household.cloth, 2),
                # 任务30：产水/日耗可追溯（collect_water 产水时差值 = collect_amount）
                "water_before": round(water_before, 2),
                "water_after": round(household.water, 2),
                "household_inv_before": household_inv_before,
                "household_inv_after": inventory_of(world, agent, list(tuning.market.trade_values)),
                **harvest_detail,
                **({"fed_by": fed_by} if action == "eat" else {}),
                "debt_before": round(debt_before, 2),
                "debt_after": round(household.debt, 2),
                "field_growth_before": round(field_growth_before, 2),
                "field_growth_after": round(field_growth_after, 2),
                "stamina_after": round(agent.stamina, 2),
                "weather": p.weather.value,
            },
        )

    # -- 婚育动作（court / try_for_child）----------------------------------- #
    def _execute_court(self, world, agent: AgentState, p: Perception,
                       tuning: AgentTuning) -> None:
        """登记当日结亲意向；双向互选在日末 _settle_courtship 结算。"""
        target_id = p.courtship_target_id
        if not target_id:
            return
        self._courtship_offers[agent.agent_id] = target_id
        world.event_log.append(
            world.current_tick,
            "courtship_offer",
            {
                "agent_id": agent.agent_id,
                "agent_name": agent.name,
                "target_id": target_id,
                "target_name": p.courtship_target_name,
                "distance_tu": round(p.courtship_distance, 3),
            },
        )

    def _execute_try_for_child(self, world, agent: AgentState, p: Perception,
                               tuning: AgentTuning) -> None:
        """女方主动求子；是否怀上仍由 chance_per_day × 资源系数决定（生理不确定）。"""
        father = world.state.human.agents.get(agent.spouse_id or "")
        if father is None or not father.alive:
            raise ValueError("try_for_child selected without a living spouse")
        b = tuning.birth
        boost = self._fertility_boost(world, tuning)
        chance = min(1.0, b.chance_per_day * boost * p.birth_resource_factor)
        if self.rng.random() >= chance:
            return
        self._give_birth(world, agent, father, tuning,
                         resource_factor=p.birth_resource_factor)

    # -- 采集类动作（打猎 / 未来捕鱼，通用分支，不写死动作名）---------------- #
    def _execute_gather(self, world, agent, action, p: Perception, tuning) -> None:
        cfg = tuning.gathering.actions[action]
        out_field = cfg.output_field
        household = household_of(world, agent)
        out_before = getattr(household, out_field, 0.0)
        health_before = agent.health

        # 成功率 = 基础 × 季节修正 × 天气修正（全部来自配置，不硬编码数值）
        season_key = p.season.value if hasattr(p.season, "value") else str(p.season)
        season_mult = cfg.season_modifier.get(season_key, 1.0)
        weather_mult = cfg.bad_weather_success_mult if p.is_raining else 1.0
        success_rate = min(1.0, cfg.base_success_rate * season_mult * weather_mult)
        success = self.rng.random() < success_rate
        amount = cfg.output_amount
        if success:
            # P3b：采集改走 ResourceService（环境域校验额度与存量，先事件后投影）
            granted = ResourceService.harvest(
                world, cfg.target_node, amount,
                agent_id=agent.agent_id, household_id=household.household_id,
                action=action,
            )
            if granted <= 0:
                success = False
            else:
                amount = granted

        if success:
            setattr(household, out_field, round(out_before + amount, 2))
            world.event_log.append(
                world.current_tick,
                "gather_success",
                {
                    "agent_id": agent.agent_id,
                    "agent_name": agent.name,
                    "household_id": household.household_id,
                    "action": action,
                    "resource_node": cfg.target_node,
                    "output_field": out_field,
                    "output_before": round(out_before, 2),
                    "output_after": round(getattr(household, out_field), 2),
                    "amount": round(amount, 2),
                    "success_rate": round(success_rate, 3),
                },
            )
        else:
            world.event_log.append(
                world.current_tick,
                "gather_fail",
                {
                    "agent_id": agent.agent_id,
                    "agent_name": agent.name,
                    "household_id": household.household_id,
                    "action": action,
                    "resource_node": cfg.target_node,
                    "reason": (
                        "resource_depleted"
                        if ResourceService.is_resource_node(world, cfg.target_node)
                        else "未获猎物"
                    ),
                    "success_rate": round(success_rate, 3),
                },
            )

        # 受伤判定（独立于成败；坏天气风险加倍；年龄分段乘数；不致死）
        stage = tuning.aging.stage_by_name(agent.life_stage)
        stage_mult = stage.injury_risk_mult if stage is not None else 1.0
        injury_mult = cfg.bad_weather_injury_mult if p.is_raining else 1.0
        site_mult = environmental_injury_multiplier(world, cfg.target_node, p.is_raining, tuning.environment)
        fatigue_mult = 1.0 + (1.0 - p.fatigue_efficiency)
        injury_prob = min(1.0, cfg.injury_risk * injury_mult * stage_mult * site_mult * fatigue_mult)
        if self.rng.random() < injury_prob:
            agent.health = max(0.0, health_before - cfg.injury_health_loss)
            agent.last_injury_tick = world.current_tick
            world.event_log.append(
                world.current_tick,
                "gather_injury",
                {
                    "agent_id": agent.agent_id,
                    "agent_name": agent.name,
                    "household_id": household.household_id,
                    "action": action,
                    "resource_node": cfg.target_node,
                    "health_before": round(health_before, 2),
                    "health_after": round(agent.health, 2),
                    "site_risk_multiplier": round(site_mult, 3),
                    "loss": round(cfg.injury_health_loss, 2),
                },
            )

    # -- 纺织（任务11，配置驱动，仿 farm 结构）------------------------------ #
    def _execute_weave(self, world, agent, p: Perception, tuning) -> None:
        """织布：成功率 = 基础 × 季节修正；成功产布、失败无产出，各写一条事件。

        v1 布由劳动直接产出，不消耗麻/棉原料（原料链为后续接入点，见 06-actions.md）。
        """
        tex = tuning.textile
        season_key = p.season.value if hasattr(p.season, "value") else str(p.season)
        success_rate = min(1.0, tex.base_success_rate * tex.season_modifier.get(season_key, 1.0))
        household = household_of(world, agent)
        cloth_before = household.cloth
        work_node = work_node_of(world, agent)
        if self.rng.random() < success_rate:
            produced = tex.cloth_per_weave * p.production_efficiency
            household.cloth = round(cloth_before + produced, 2)
            world.event_log.append(
                world.current_tick,
                "weave_success",
                {
                    "agent_id": agent.agent_id,
                    "agent_name": agent.name,
                    "household_id": household.household_id,
                    "target_node": work_node,
                    "cloth_before": round(cloth_before, 2),
                    "cloth_after": round(household.cloth, 2),
                    "amount": round(produced, 2),
                    "base_amount": round(tex.cloth_per_weave, 2),
                    "production_efficiency": round(p.production_efficiency, 3),
                    "fatigue_efficiency": round(p.fatigue_efficiency, 3),
                    "success_rate": round(success_rate, 3),
                },
            )
        else:
            world.event_log.append(
                world.current_tick,
                "weave_fail",
                {
                    "agent_id": agent.agent_id,
                    "agent_name": agent.name,
                    "household_id": household.household_id,
                    "target_node": work_node,
                    "reason": "织机未成布",
                    "success_rate": round(success_rate, 3),
                },
            )

    # -- 债务还款（秋收 / 通用）-------------------------------------------- #
    def _repay_debts(
        self, world, agent: AgentState, tuning: AgentTuning, *, source: str, max_repay: float
    ) -> None:
        """按最早到期优先，从债务家庭扣粮还给各债权家庭，最多 max_repay 石；逐笔写 debt_repaid。

        粮守恒：债务家庭扣的每石都加到对应债权家庭，绝不凭空消债。不得扣成负粮。
        """
        household = household_of(world, agent)
        if max_repay <= 0 or not household.debts:
            return
        ordered = sorted(household.debts, key=lambda d: (d.due_tick, d.originated_tick))
        budget = max_repay
        for rec in ordered:
            if budget <= 0:
                break
            resource = getattr(rec, "resource", "grain") or "grain"
            debtor_stock = float(getattr(household, resource, 0.0))
            pay = min(rec.amount, budget, debtor_stock)
            if pay <= 0:
                continue
            creditor_hh = world.state.human.households.get(rec.creditor_household_id)
            if creditor_hh is None:
                continue
            creditor_stock = float(getattr(creditor_hh, resource, 0.0))
            setattr(household, resource, round(debtor_stock - pay, 2))
            setattr(creditor_hh, resource, round(creditor_stock + pay, 2))
            rec.amount = round(rec.amount - pay, 2)
            budget = budget - pay
            creditor_head = world.state.human.agents.get(creditor_hh.head_id or "")
            world.event_log.append(
                world.current_tick,
                "debt_repaid",
                {
                    "creditor_id": creditor_head.agent_id if creditor_head else creditor_hh.household_id,
                    "creditor_name": creditor_head.name if creditor_head else creditor_hh.household_id,
                    "debtor_id": agent.agent_id,
                    "debtor_name": agent.name,
                    "household_id": household.household_id,
                    "debtor_household_id": household.household_id,
                    "creditor_household_id": creditor_hh.household_id,
                    "amount": round(pay, 2),
                    "remaining": round(rec.amount, 2),
                    "source": source,
                    "resource": resource,
                    f"debtor_{resource}_after": round(getattr(household, resource), 2),
                    f"creditor_{resource}_after": round(getattr(creditor_hh, resource), 2),
                    "debtor_grain_after": round(household.grain, 2),
                    "creditor_grain_after": round(creditor_hh.grain, 2),
                },
            )
        # 清偿完毕（amount==0）的记录移出列表，保持债务列表干净
        household.debts = [d for d in household.debts if d.amount > 0]

    def _settle_fatigue(self, world, tuning: AgentTuning) -> None:
        """日末长期疲劳结算：劳动/通勤累积，住宅睡眠恢复；事件是 Replay 真相源。"""
        cfg = tuning.environment
        action_events = [
            event for event in world.event_log.by_type_at_tick("agent_action_taken", world.current_tick)
        ]
        by_agent: dict[str, tuple[float, float]] = {}
        for event in action_events:
            payload = event.get("payload") or {}
            agent_id = payload.get("agent_id")
            if not agent_id:
                continue
            action = payload.get("action", "")
            labor_tu, travel_tu = by_agent.get(agent_id, (0.0, 0.0))
            if action in cfg.fatigue_affected_actions:
                labor_tu += max(
                    0.0,
                    float(payload.get("tu_spent", 0.0))
                    - float(payload.get("round_trip_tu", 0.0)),
                )
            travel_tu += max(0.0, float(payload.get("round_trip_tu", 0.0)))
            by_agent[agent_id] = (labor_tu, travel_tu)

        for agent in living_agents(world.state.human.agents):
            labor_tu, travel_tu = by_agent.get(agent.agent_id, (0.0, 0.0))
            home_node = home_node_of(world, agent)
            dwelling = None
            has_home_dwelling = False
            for building in world.state.human.buildings.values():
                if building.building_type != "dwelling":
                    continue
                parcel = world.state.human.land_parcels.get(building.parcel_id)
                if parcel is None or parcel.spatial_node_id != home_node:
                    continue
                has_home_dwelling = True
                if building.status not in {"active", "occupied", "vacant"} or building.condition <= 0:
                    continue
                if dwelling is None or building.condition > dwelling.condition:
                    dwelling = building
            crowding_ratio = 0.0
            crowding_loss = 0.0
            if dwelling is not None and dwelling.condition > 0:
                recovery = cfg.dwelling_fatigue_recovery_per_day * dwelling.condition / 100.0
                household = household_of(world, agent)
                residents = sum(
                    1 for member_id in household.member_ids
                    if member_id in world.state.human.agents and world.state.human.agents[member_id].alive
                )
                capacity = max(1.0, float(dwelling.attributes.get(
                    "resident_capacity", cfg.dwelling_resident_capacity
                )))
                crowding_ratio = residents / capacity
                excess = max(0.0, crowding_ratio - cfg.dwelling_comfort_ratio)
                crowding_loss = min(1.0, excess * cfg.dwelling_crowding_recovery_loss_per_ratio)
                recovery *= 1.0 - crowding_loss
                shelter = "dwelling"
            elif not has_home_dwelling:
                # Legacy settlements may have non-residential buildings (market/shrine)
                # but no explicit dwelling entity for an abstract home node. That home
                # still represents shelter; do not mistake it for an unsheltered camp.
                recovery = cfg.dwelling_fatigue_recovery_per_day
                shelter = "legacy_unmodeled_dwelling"
            else:
                recovery = cfg.outdoor_fatigue_recovery_per_day
                shelter = "unsheltered"
            load = labor_tu * cfg.fatigue_per_labor_tu + travel_tu * cfg.fatigue_per_travel_tu
            before = agent.fatigue
            before_high_days = agent.fatigue_high_days
            after = round(min(100.0, max(0.0, before + load - recovery)), 2)
            after_high_days = before_high_days + 1 if after > cfg.fatigue_efficiency_threshold else 0
            if abs(after - before) < 1e-9 and after_high_days == before_high_days:
                continue
            agent.fatigue = after
            agent.fatigue_high_days = after_high_days
            world.event_log.append(world.current_tick, "agent_fatigue_settled", {
                "agent_id": agent.agent_id,
                "household_id": agent.household_id,
                "before": round(before, 2),
                "after": after,
                "high_days_before": before_high_days,
                "high_days_after": after_high_days,
                "efficiency_active": after_high_days >= cfg.fatigue_efficiency_grace_days,
                "labor_tu": round(labor_tu, 3),
                "travel_tu": round(travel_tu, 3),
                "fatigue_load": round(load, 3),
                "recovery": round(recovery, 3),
                "crowding_ratio": round(crowding_ratio, 3),
                "crowding_recovery_loss": round(crowding_loss, 3),
                "shelter": shelter,
            })

    # -- 每日结算：死亡+继承 → 催收会话 → 强制催收 → 集市 → 婚配 → 生育 → 回血 --- #
    def _settle(self, world, tuning: AgentTuning) -> None:
        """tick 末尾统一结算。逐人错误隔离：单人结算失败写 agent_error，不拖垮世界。

        顺序（任务12 A3 固定）：死亡判定 → 继承（资产转移+债务继承/核销）→ 催收会话
        → 强制催收 → 集市 → 婚配 → 生育 → 健康回血。继承必须先于债务处理，否则债务无处继承。
        催收会话先于强制扣粮（任务15 阶段三修正）：让「有粮赖账」窗口先被会话看到，
        否则库存会被 _collect_debts 先扣走。死者/失能者不参与催收、集市、婚配、生育与回血。
        """
        dead_now: list[AgentState] = []
        for agent in list(world.state.human.agents.values()):
            try:
                was_alive = agent.alive
                self._process_death(world, agent, tuning)
                if was_alive and not agent.alive:
                    dead_now.append(agent)
            except Exception as exc:  # noqa: BLE001 — 单人结算失败不拖垮世界
                self._log_agent_error(world, agent, "death_settlement", exc)

        # A3/P0：死亡后先处理家庭生命周期（接任/最后成员继承），再催收与债务核销
        for agent in dead_now:
            try:
                self._handle_death(world, agent, tuning)
            except Exception as exc:  # noqa: BLE001
                self._log_agent_error(world, agent, "inheritance", exc)

        # 任务15 阶段三：催收会话先于强制扣粮，看到「有粮赖账」窗口（只有 market_credit 债务参与）
        try:
            self._settle_debt_disputes(world, tuning)
        except Exception as exc:  # noqa: BLE001 — 冲突结算失败不拖垮集市/婚配/回血
            world.event_log.append(
                world.current_tick,
                "agent_error",
                {
                    "agent_id": "_conflict",
                    "agent_name": "债务催收",
                    "phase": "debt_dispute",
                    "error": repr(exc),
                    "traceback": traceback.format_exc(limit=2),
                },
            )

        for agent in list(world.state.human.agents.values()):
            try:
                if not agent.alive:
                    continue
                # 失能者无收入、无法进食：不催收（避免对垂死之人重复刷违约），也不回血
                if agent.incapacitated:
                    continue
                self._collect_debts(world, agent, tuning)
            except Exception as exc:  # noqa: BLE001 — 单人结算失败不拖垮世界
                self._log_agent_error(world, agent, "debt_collection", exc)

        if self._is_market_day(world.current_tick, tuning):
            try:
                self._settle_market(world, tuning)
            except Exception as exc:  # noqa: BLE001 — 集市结算失败不拖垮回血与后续 tick
                world.event_log.append(
                    world.current_tick,
                    "agent_error",
                    {
                        "agent_id": "_market",
                        "agent_name": "集市",
                        "phase": "market_settlement",
                        "error": repr(exc),
                        "traceback": traceback.format_exc(limit=2),
                    },
                )

        try:
            self._settle_water(world, tuning)
        except Exception as exc:  # noqa: BLE001 — 用水结算失败不拖垮婚配/生育/回血
            world.event_log.append(
                world.current_tick,
                "agent_error",
                {
                    "agent_id": "_water",
                    "agent_name": "生活用水",
                    "phase": "water_settlement",
                    "error": repr(exc),
                    "traceback": traceback.format_exc(limit=2),
                },
            )

        try:
            # 婚配与生育已下沉为 court / try_for_child 动作；日末只结算"双向互选"的结亲意向，
            # 不再做系统贪心配对或概率抽签。
            self._settle_courtship(world, tuning)
        except Exception as exc:  # noqa: BLE001
            world.event_log.append(
                world.current_tick,
                "agent_error",
                {
                    "agent_id": "_marriage",
                    "agent_name": "婚配",
                    "phase": "courtship_settlement",
                    "error": repr(exc),
                    "traceback": traceback.format_exc(limit=2),
                },
            )

        try:
            self._settle_split(world, tuning)
        except Exception as exc:  # noqa: BLE001
            world.event_log.append(
                world.current_tick,
                "agent_error",
                {
                    "agent_id": "_split",
                    "agent_name": "分家",
                    "phase": "split_settlement",
                    "error": repr(exc),
                    "traceback": traceback.format_exc(limit=2),
                },
            )

        for agent in list(world.state.human.agents.values()):
            try:
                if not agent.alive or agent.incapacitated:
                    continue
                self._recover_health(world, agent, tuning)
            except Exception as exc:  # noqa: BLE001
                self._log_agent_error(world, agent, "health_recovery", exc)

    def _log_agent_error(self, world, agent: AgentState, phase: str, exc: Exception) -> None:
        world.event_log.append(
            world.current_tick,
            "agent_error",
            {
                "agent_id": agent.agent_id,
                "agent_name": agent.name,
                "phase": phase,
                "error": repr(exc),
                "traceback": traceback.format_exc(limit=2),
            },
        )

    # -- 集市日：赶路扣体力 + 以物易物撮合（任务11）------------------------- #
    def _is_market_day(self, tick: int, tuning: AgentTuning) -> bool:
        mkt = tuning.market
        return tick % mkt.market_day_interval == mkt.market_day_offset

    def _market_executor(self, world, household: HouseholdState,
                         cost: float, tuning: AgentTuning) -> tuple[Optional[AgentState], str]:
        """户主优先 → 最长成年可行动成员；返回 (执行者, 失败原因)。"""
        min_age = tuning.marriage.min_age
        min_stamina = tuning.market.market_min_stamina
        members = [
            world.state.human.agents[mid]
            for mid in household.member_ids
            if mid in world.state.human.agents
            and world.state.human.agents[mid].alive
            and not world.state.human.agents[mid].incapacitated
            and age_years(world.state.human.agents[mid].birth_tick, world.current_tick) >= min_age
        ]
        if not members:
            return None, "dead_or_incap"
        members.sort(key=lambda a: (a.agent_id != household.head_id, a.birth_tick, a.agent_id))
        for member in members:
            if member.stamina - cost >= min_stamina:
                return member, ""
        return None, "too_weak"

    def _settle_water(self, world, tuning: AgentTuning) -> None:
        """按存活成员扣除日常饮水；缺口只记账，不在本版直接扣健康。"""
        per_member = tuning.water.daily_consumption_per_member
        if per_member <= 0:
            return
        for household in world.state.human.households.values():
            members = [
                m for m in household.member_ids
                if m in world.state.human.agents and world.state.human.agents[m].alive
            ]
            if not members:
                continue
            need = round(per_member * len(members), 2)
            before = max(0.0, float(household.water))
            consumed = min(before, need)
            after = round(max(0.0, before - need), 2)
            shortage = round(max(0.0, need - before), 2)
            household.water = after
            if consumed > 0:
                world.event_log.append(
                    world.current_tick,
                    "water_consumed",
                    {
                        "household_id": household.household_id,
                        "member_count": len(members),
                        "need": need,
                        "amount": round(consumed, 2),
                        "shortage": shortage,
                        "before": round(before, 2),
                        "after": after,
                    },
                )
            if shortage > 0:
                world.event_log.append(
                    world.current_tick,
                    "water_shortage",
                    {
                        "household_id": household.household_id,
                        "member_count": len(members),
                        "need": need,
                        "available": round(before, 2),
                        "shortage": shortage,
                        "health_penalty_applied": False,
                    },
                )

    def _settle_market(self, world, tuning: AgentTuning) -> None:
        """集市日结算（Q3）：每户每日最多一次行程，户主优先，体力记执行者。

        计距用 Household.home_node；撮合以家庭库存为单位，禁止同户自交易。
        """
        mkt = tuning.market
        move_rate = tuning.utility.move_stamina_per_tu
        skipped = {"dead_or_incap": 0, "too_far": 0, "too_weak": 0}
        participants: list[tuple[HouseholdState, AgentState]] = []
        travel: dict[str, float] = {}
        households = sorted(living_households(world), key=lambda h: h.household_id)
        visitor_limit = tuning.environment.service_capacity_by_node.get(mkt.market_node, {}).get("market_visitors")
        # Rotate the queue by day so a fixed household-id ordering does not permanently exclude the same families.
        if households and visitor_limit is not None and len(households) > int(visitor_limit):
            offset = world.current_tick % len(households)
            households = households[offset:] + households[:offset]
        for household in households:
            one_way = (
                self._spatial.travel_tu(household.home_node, mkt.market_node)
                if self._spatial is not None
                else float("inf")
            )
            if math.isinf(one_way) or one_way > mkt.market_max_distance_tu:
                skipped["too_far"] += 1
                continue
            cost = 2.0 * one_way * move_rate
            executor, reason = self._market_executor(world, household, cost, tuning)
            if executor is None:
                skipped[reason] += 1
                continue
            # 004 §3.2-6：当日已在集市（日内动作目标为 market）→ 免往返体力
            if executor.location == mkt.market_node:
                cost = 0.0
            if visitor_limit is not None and len(participants) >= int(visitor_limit):
                skipped["crowded"] = skipped.get("crowded", 0) + 1
                continue
            executor.stamina = max(0.0, executor.stamina - cost)
            travel[executor.agent_id] = round(cost, 2)
            participants.append((household, executor))

        trade_count = self._match_market(world, tuning, participants, travel)
        credit_count = self._settle_market_credit(world, tuning, participants)

        world.event_log.append(
            world.current_tick,
            "market_day_summary",
            {
                "market_node": mkt.market_node,
                "market_day": world.current_tick,
                "participants": [
                    {
                        "agent_id": executor.agent_id,
                        "agent_name": executor.name,
                        "participant_agent_id": executor.agent_id,
                        "participant_name": executor.name,
                        "household_id": household.household_id,
                        "member_count": len(household.member_ids),
                        "travel_stamina_cost": travel[executor.agent_id],
                    }
                    for household, executor in participants
                ],
                "participant_count": len(participants),
                "visitor_capacity": visitor_limit,
                "skipped": skipped,
                "trade_count": trade_count,
                "credit_count": credit_count,
            },
        )

    def _match_market(
        self,
        world,
        tuning: AgentTuning,
        participants: list[tuple[HouseholdState, AgentState]],
        travel: dict[str, float],
    ) -> int:
        """按家庭 id 稳定排序后两两撮合（每对只撮合一次），返回成交笔数。

        禁止同户自交易；约定：seller 给出 give_item、换回 take_item；各物品总量守恒、不得为负。
        """
        mkt = tuning.market
        items = list(mkt.trade_values.keys())
        # Generic market deficit thresholds are not enough for protective goods:
        # a household needs the configured winter-warmth stock, not merely the
        # ordinary "has at least a little cloth" threshold.
        deficit_target = dict(mkt.deficit_threshold)
        if "cloth" in deficit_target:
            deficit_target["cloth"] = max(
                float(deficit_target["cloth"]),
                float(tuning.textile.warmth_cloth_threshold),
            )
        count = 0
        for i, (seller_hh, seller) in enumerate(participants):
            for buyer_hh, buyer in participants[i + 1:]:
                if seller_hh.household_id == buyer_hh.household_id:
                    continue  # 同户禁自交易
                for give in items:
                    for take in items:
                        if give == take:
                            continue
                        if not (
                            getattr(seller_hh, give) > mkt.surplus_threshold[give]
                            and getattr(seller_hh, take) < deficit_target[take]
                        ):
                            continue
                        if not (
                            getattr(buyer_hh, take) > mkt.surplus_threshold[take]
                            and getattr(buyer_hh, give) < deficit_target[give]
                        ):
                            continue
                        ratio = mkt.trade_values[give] / mkt.trade_values[take]
                        avail_give = getattr(seller_hh, give) - mkt.surplus_threshold[give]
                        need_give = deficit_target[give] - getattr(buyer_hh, give)
                        avail_take = getattr(buyer_hh, take) - mkt.surplus_threshold[take]
                        need_take = deficit_target[take] - getattr(seller_hh, take)
                        give_max = min(
                            avail_give,
                            need_give,
                            avail_take / ratio,
                            need_take / ratio,
                            mkt.max_trade_units,
                        )
                        give_qty = _floor_to_step(give_max, mkt.trade_unit_step)
                        if give_qty < mkt.trade_unit_step:
                            continue
                        take_qty = give_qty * ratio
                        if take_qty > avail_take + 1e-9 or take_qty > need_take + 1e-9:
                            continue
                        v_give = mkt.trade_values[give] * give_qty
                        v_take = mkt.trade_values[take] * take_qty
                        if abs(v_give - v_take) / max(v_give, v_take, 1e-9) > mkt.trade_value_tolerance:
                            continue

                        seller_before = _inventory(seller_hh, items)
                        buyer_before = _inventory(buyer_hh, items)
                        setattr(seller_hh, give, round(getattr(seller_hh, give) - give_qty, 2))
                        setattr(seller_hh, take, round(getattr(seller_hh, take) + take_qty, 2))
                        setattr(buyer_hh, give, round(getattr(buyer_hh, give) + give_qty, 2))
                        setattr(buyer_hh, take, round(getattr(buyer_hh, take) - take_qty, 2))
                        count += 1
                        world.event_log.append(
                            world.current_tick,
                            "trade_executed",
                            {
                                "market_day": world.current_tick,
                                "market_node": mkt.market_node,
                                "seller_id": seller.agent_id,
                                "seller_name": seller.name,
                                "seller_agent_id": seller.agent_id,
                                "seller_household_id": seller_hh.household_id,
                                "buyer_id": buyer.agent_id,
                                "buyer_name": buyer.name,
                                "buyer_agent_id": buyer.agent_id,
                                "buyer_household_id": buyer_hh.household_id,
                                "give_item": give,
                                "give_qty": round(give_qty, 3),
                                "take_item": take,
                                "take_qty": round(take_qty, 3),
                                "seller_inv_before": seller_before,
                                "seller_inv_after": _inventory(seller_hh, items),
                                "buyer_inv_before": buyer_before,
                                "buyer_inv_after": _inventory(buyer_hh, items),
                                "trade_value_ratio": round(ratio, 3),
                                "travel_stamina_cost": {
                                    seller.agent_id: travel.get(seller.agent_id, 0.0),
                                    buyer.agent_id: travel.get(buyer.agent_id, 0.0),
                                },
                            },
                        )
        return count

    # -- 集市赊账（任务15 阶段二）：短缺家庭向富余家庭挂账 ------------------ #
    def _settle_market_credit(
        self,
        world,
        tuning: AgentTuning,
        participants: list[tuple[HouseholdState, AgentState]],
    ) -> int:
        """集市日赊账：买方短缺、卖方富余时当期交粮并生成 ``debt_formed(origin="market_credit")``。

        约束（裁决 §3.1/§3.3，全部来自配置）：
        - 仅 ``credit.eligible_items``；零利息；单户未清偿赊账 ≤ ``max_per_household``；
        - 已有赊账逾期未清时不再新增（防雪球）；
        - 粮当期从卖方家庭转买方家庭，逐笔事件记录双方库存，守恒且不为负。
        返回新增赊账笔数。仅参加集市的家庭可赊。
        """
        credit = tuning.market.credit
        if not credit.enabled or not participants:
            return 0
        step = tuning.market.trade_unit_step
        tick = world.current_tick
        count = 0
        for buyer_hh, _buyer in participants:  # participants 已按 household_id 稳定排序
            for item in credit.eligible_items:
                if item not in HouseholdState.model_fields:
                    continue
                outstanding = sum(
                    rec.amount for rec in buyer_hh.debts
                    if rec.origin == "market_credit" and getattr(rec, "resource", "grain") == item
                )
                overdue = any(
                    rec.origin == "market_credit" and rec.overdue
                    and getattr(rec, "resource", "grain") == item
                    for rec in buyer_hh.debts
                )
                if overdue:
                    continue  # 该物资已有逾期赊账：不再新增，避免雪球
                headroom = credit.max_per_household - outstanding
                if headroom <= 0:
                    continue
                stock = getattr(buyer_hh, item, 0.0)
                if stock >= credit.min_shortage:
                    continue
                need = credit.min_shortage - stock
                seller = self._pick_credit_seller(
                    participants, buyer_hh, item, credit.min_surplus
                )
                if seller is None:
                    continue
                amount = _floor_to_step(
                    min(need, getattr(seller, item, 0.0) - credit.min_surplus, headroom),
                    step,
                )
                if amount < step:
                    continue
                buyer_before = round(stock, 2)
                seller_before = round(getattr(seller, item, 0.0), 2)
                setattr(seller, item, round(seller_before - amount, 2))
                setattr(buyer_hh, item, round(buyer_before + amount, 2))
                due_tick = tick + credit.due_days
                buyer_hh.debts.append(
                    DebtRecord(
                        debtor_household_id=buyer_hh.household_id,
                        creditor_household_id=seller.household_id,
                        amount=round(amount, 2),
                        originated_tick=tick,
                        due_tick=due_tick,
                        origin="market_credit",
                        resource=item,
                    )
                )
                debtor_head = world.state.human.agents.get(buyer_hh.head_id or "")
                creditor_head = world.state.human.agents.get(seller.head_id or "")
                world.event_log.append(
                    tick,
                    "debt_formed",
                    {
                        "creditor_id": (
                            creditor_head.agent_id if creditor_head else seller.household_id
                        ),
                        "creditor_name": (
                            creditor_head.name if creditor_head else seller.household_id
                        ),
                        "debtor_id": (
                            debtor_head.agent_id if debtor_head else buyer_hh.household_id
                        ),
                        "debtor_name": (
                            debtor_head.name if debtor_head else buyer_hh.household_id
                        ),
                        "creditor_household_id": seller.household_id,
                        "debtor_household_id": buyer_hh.household_id,
                        "household_id": buyer_hh.household_id,
                        "debt_type": item,
                        "origin": "market_credit",
                        "resource": item,
                        "amount": round(amount, 2),
                        "due_tick": due_tick,
                        "originated_tick": tick,
                        f"debtor_{item}_before": buyer_before,
                        f"debtor_{item}_after": round(getattr(buyer_hh, item, 0.0), 2),
                        f"creditor_{item}_before": seller_before,
                        f"creditor_{item}_after": round(getattr(seller, item, 0.0), 2),
                        "debt_before": round(outstanding, 2),
                        "debt_after": round(outstanding + amount, 2),
                    },
                )
                count += 1
                break  # 单户单集市日只新增一笔赊账
        return count

    @staticmethod
    def _pick_credit_seller(
        participants: list[tuple[HouseholdState, AgentState]],
        buyer_hh: HouseholdState,
        item: str,
        min_surplus: float,
    ) -> Optional[HouseholdState]:
        """选富余最多的其他参加家庭（并列按 household_id 稳定）；无则 None。"""
        candidates = [
            hh
            for hh, _agent in participants
            if hh.household_id != buyer_hh.household_id
            and getattr(hh, item, 0.0) >= min_surplus
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda h: (getattr(h, item, 0.0), h.household_id))

    def _process_death(self, world, agent: AgentState, tuning: AgentTuning) -> None:
        """失能满 death_grace_ticks 仍未恢复 → 死亡；写一次 agent_died。

        债务不在此处核销：A3 规定「agent_died → 继承（资产+债务）→ 从经济池移除」，
        债务继承/核销统一由 ``_execute_inheritance`` 完成。幂等：已死亡直接返回。
        """
        if not agent.incapacitated or not agent.alive:
            return
        if agent.incapacitated_tick is None:
            return
        if world.current_tick - agent.incapacitated_tick < tuning.death.death_grace_ticks:
            return
        agent.alive = False
        agent.died_tick = world.current_tick
        cause = agent.death_cause or self._determine_death_cause(agent, tuning)
        agent.death_cause = cause
        household = household_of(world, agent)
        outstanding = round(household.debt, 2)
        food_inventory = {
            field_name: round(float(getattr(household, field_name, 0.0)), 2)
            for field_name in tuning.physiology.food_fields
        }
        world.event_log.append(
            world.current_tick,
            "agent_died",
            {
                "agent_id": agent.agent_id,
                "agent_name": agent.name,
                "household_id": household.household_id,
                "cause": cause,
                "incapacitated_tick": agent.incapacitated_tick,
                "died_tick": world.current_tick,
                "health": round(agent.health, 2),
                "hunger": round(agent.hunger, 2),
                "stamina": round(agent.stamina, 2),
                "fatigue": round(agent.fatigue, 2),
                "fatigue_high_days": agent.fatigue_high_days,
                "age_years": age_years(agent.birth_tick, world.current_tick),
                "life_stage": agent.life_stage,
                "outstanding_debt": outstanding,
                "household_food_inventory": food_inventory,
                "household_food_stock": round(sum(food_inventory.values()), 2),
                "household_water": round(float(household.water), 2),
                "household_member_count": len(household.member_ids),
                "home_node": household.home_node,
            },
        )

    # -- 继承（任务12 D10-D12 / A3；家庭模型第 1 步适配）-------------------- #
    def _inheritance_items(self, tuning: AgentTuning) -> list[str]:
        """可继承物品集合 = 集市物品键 ∩ HouseholdState 现有字段（内容驱动，不写死）。

        任务30：生活用水不参与集市交易，但也要随继承/分家转移，否则家庭消亡时水凭空消失。
        """
        items = [i for i in tuning.market.trade_values if i in HouseholdState.model_fields]
        if "water" not in items and "water" in HouseholdState.model_fields:
            items.append("water")
        if "coin" not in items and "coin" in HouseholdState.model_fields:
            items.append("coin")
        return items

    def _select_heir(self, world, deceased: AgentState, tuning: AgentTuning) -> Optional[AgentState]:
        """单继承人（D10）：按配置顺位取第一个仍存活的候选人。"""
        for kind in tuning.inheritance.priority:
            if kind == "spouse":
                if deceased.spouse_id:
                    spouse = world.state.human.agents.get(deceased.spouse_id)
                    if spouse is not None and spouse.alive:
                        return spouse
            elif kind == "children":
                alive_children = [
                    world.state.human.agents[cid]
                    for cid in deceased.children_ids
                    if cid in world.state.human.agents and world.state.human.agents[cid].alive
                ]
                if alive_children:
                    # 最长者（birth_tick 最小）优先
                    return min(alive_children, key=lambda a: (a.birth_tick, a.agent_id))
            elif kind == "parents":
                for pid in (deceased.mother_id, deceased.father_id):
                    if not pid:
                        continue
                    parent = world.state.human.agents.get(pid)
                    if parent is not None and parent.alive:
                        return parent
        return None

    def _execute_inheritance(self, world, deceased: AgentState,
                             tuning: AgentTuning) -> Optional[HouseholdState]:
        """家庭最后成员死亡：资产 → 家庭外继承人；债务按比例转移/核销（D10-D12）。

        返回继承人家庭（无继承人返回 None），供债权家庭消亡处理使用。
        守恒：转移量 + 归公量 = 死者家庭原存量；债务转移 + 核销 = 原债务。
        """
        inh = tuning.inheritance
        deceased_hh = household_of(world, deceased)
        heir = self._select_heir(world, deceased, tuning)
        heir_hh = household_of(world, heir) if heir is not None else None
        if heir_hh is not None and heir_hh.household_id == deceased_hh.household_id:
            return heir_hh  # 同一家庭：资产/债务不搬动（正常不会发生：最后成员已死）

        for item in self._inheritance_items(tuning):
            amount = round(getattr(deceased_hh, item, 0.0), 2)
            if amount <= 0:
                continue
            moved = 0.0
            if heir_hh is not None and inh.asset_ratio > 0:
                moved = round(amount * inh.asset_ratio, 2)
                if moved > 0:
                    heir_before = round(getattr(heir_hh, item, 0.0), 2)
                    setattr(heir_hh, item, round(heir_before + moved, 2))
                    world.event_log.append(
                        world.current_tick,
                        "inheritance_executed",
                        {
                            "deceased_id": deceased.agent_id,
                            "deceased_name": deceased.name,
                            "deceased_household_id": deceased_hh.household_id,
                            "heir_id": heir.agent_id,
                            "heir_name": heir.name,
                            "heir_household_id": heir_hh.household_id,
                            "item": item,
                            "amount": moved,
                            "deceased_before": amount,
                            "deceased_after": round(amount - moved, 2),
                            "heir_before": heir_before,
                            "heir_after": round(getattr(heir_hh, item, 0.0), 2),
                            "cause": "death",
                        },
                    )
            remainder = round(amount - moved, 2)
            if remainder > 0 and inh.escheat:
                world.event_log.append(
                    world.current_tick,
                    "inheritance_escheated",
                    {
                        "deceased_id": deceased.agent_id,
                        "deceased_name": deceased.name,
                        "deceased_household_id": deceased_hh.household_id,
                        "item": item,
                        "amount": remainder,
                        "reason": "no_heir" if heir_hh is None else "ratio_remainder",
                    },
                )
            setattr(deceased_hh, item, 0.0)

        if heir_hh is None:
            if deceased_hh.debts:
                self._write_off_debts(world, deceased_hh, reason="no_heir")
            from vale.modules.land import settle_household_land_inheritance
            settle_household_land_inheritance(
                world,
                deceased_household_id=deceased_hh.household_id,
                heir_household_id=None,
                deceased_agent_id=deceased.agent_id,
            )
            return None

        for rec in list(deceased_hh.debts):
            creditor_hh = world.state.human.households.get(rec.creditor_household_id)
            creditor_head = (
                world.state.human.agents.get(creditor_hh.head_id or "") if creditor_hh is not None else None
            )
            creditor_name = (
                creditor_head.name if creditor_head is not None else rec.creditor_household_id
            )
            creditor_agent_id = (
                creditor_head.agent_id if creditor_head is not None else rec.creditor_household_id
            )
            if heir_hh.household_id == rec.creditor_household_id:
                # 自己欠自己：直接核销，不转移
                world.event_log.append(
                    world.current_tick,
                    "debt_forgiven",
                    {
                        "creditor_id": creditor_agent_id,
                        "creditor_name": creditor_name,
                        "creditor_household_id": rec.creditor_household_id,
                        "debtor_id": deceased.agent_id,
                        "debtor_name": deceased.name,
                        "debtor_household_id": deceased_hh.household_id,
                        "household_id": deceased_hh.household_id,
                        "amount": round(rec.amount, 2),
                        "resource": rec.resource,
                        "cause": "heir_is_creditor",
                    },
                )
                continue
            moved = round(rec.amount * inh.debt_ratio, 2)
            remainder = round(rec.amount - moved, 2)
            if moved > 0:
                heir_hh.debts.append(
                    DebtRecord(
                        debtor_household_id=heir_hh.household_id,
                        creditor_household_id=rec.creditor_household_id,
                        amount=moved,
                        originated_tick=world.current_tick,
                        due_tick=rec.due_tick,
                        overdue=rec.overdue,
                        resource=rec.resource,
                    )
                )
                world.event_log.append(
                    world.current_tick,
                    "debt_transferred",
                    {
                        "from_id": deceased.agent_id,
                        "from_name": deceased.name,
                        "from_household_id": deceased_hh.household_id,
                        "to_id": heir.agent_id,
                        "to_name": heir.name,
                        "to_household_id": heir_hh.household_id,
                        "creditor_id": creditor_agent_id,
                        "creditor_name": creditor_name,
                        "creditor_household_id": rec.creditor_household_id,
                        "amount": moved,
                        "due_tick": rec.due_tick,
                        "resource": rec.resource,
                    },
                )
            if remainder > 0:
                world.event_log.append(
                    world.current_tick,
                    "debt_written_off",
                    {
                        "creditor_id": creditor_agent_id,
                        "creditor_name": creditor_name,
                        "creditor_household_id": rec.creditor_household_id,
                        "debtor_id": deceased.agent_id,
                        "debtor_name": deceased.name,
                        "debtor_household_id": deceased_hh.household_id,
                        "household_id": deceased_hh.household_id,
                        "amount": remainder,
                        "resource": rec.resource,
                        "reason": "inheritance_remainder",
                    },
                )
        deceased_hh.debts = []
        from vale.modules.land import settle_household_land_inheritance
        settle_household_land_inheritance(
            world,
            deceased_household_id=deceased_hh.household_id,
            heir_household_id=heir_hh.household_id,
            deceased_agent_id=deceased.agent_id,
        )
        return heir_hh

    def _write_off_debts(self, world, household: HouseholdState, *, reason: str) -> None:
        """核销家庭全部剩余债务：逐笔写 debt_written_off（可追溯，不静默消失），再清空列表。

        这是账面坏账核销（家庭无粮可还 / 债权家庭消亡），不涉及粮的凭空产生或消灭；
        世界总粮不变，世界总债减少并由事件完整记录。
        """
        for rec in list(household.debts):
            creditor_hh = world.state.human.households.get(rec.creditor_household_id)
            creditor_head = (
                world.state.human.agents.get(creditor_hh.head_id or "") if creditor_hh is not None else None
            )
            creditor_name = (
                creditor_head.name if creditor_head is not None else rec.creditor_household_id
            )
            creditor_agent_id = (
                creditor_head.agent_id if creditor_head is not None else rec.creditor_household_id
            )
            debtor_head = world.state.human.agents.get(household.head_id or "")
            debtor_name = (
                debtor_head.name if debtor_head is not None
                else (household.head_id or household.household_id)
            )
            world.event_log.append(
                world.current_tick,
                "debt_written_off",
                {
                    "creditor_id": creditor_agent_id,
                    "creditor_name": creditor_name,
                    "creditor_household_id": rec.creditor_household_id,
                    "debtor_id": (household.head_id or household.household_id),
                    "debtor_name": debtor_name,
                    "debtor_household_id": household.household_id,
                    "household_id": household.household_id,
                    "amount": round(rec.amount, 2),
                    "resource": rec.resource,
                    "reason": reason,
                },
            )
        household.debts = []

    # -- 死亡→继承/接任（任务12 迁移第2步，P0）----------------------------- #
    def _handle_death(self, world, deceased: AgentState, tuning: AgentTuning) -> None:
        """P0：家庭仍有存活成员 → 只移除成员并按需接任户主，不分配继承。

        最后成员死亡才走 D10 继承/归公、债权家庭消亡处理，并写 household_dissolved。
        """
        household = household_of(world, deceased)
        items = self._inheritance_items(tuning)
        assets_before = _inventory(household, items)
        debts_before = len(household.debts)
        if deceased.agent_id in household.member_ids:
            household.member_ids.remove(deceased.agent_id)
        living_members = [
            world.state.human.agents[mid]
            for mid in household.member_ids
            if mid in world.state.human.agents and world.state.human.agents[mid].alive
        ]
        if living_members:
            if household.head_id in (None, deceased.agent_id):
                self._succeed_head(world, household, deceased, living_members, tuning)
            return  # 家庭未消亡：资产/债务不动，不写继承事件（Q9）

        heir_hh = self._execute_inheritance(world, deceased, tuning)
        self._settle_creditor_dissolution(world, household, deceased, heir_hh)
        household.member_ids = []
        household.head_id = None
        world.event_log.append(
            world.current_tick,
            "household_dissolved",
            {
                "household_id": household.household_id,
                "last_member_id": deceased.agent_id,
                "last_member_name": deceased.name,
                "assets": assets_before,
                "debts": debts_before,
                "reason": "all_dead",
            },
        )

    def _succeed_head(self, world, household: HouseholdState, deceased: AgentState,
                      living_members: list[AgentState], tuning: AgentTuning) -> None:
        """户主接任：配偶 > 最长成年子女 > 最长成年成员 > 全未成年取最长成员。"""
        min_age = tuning.marriage.min_age

        def _age(a: AgentState) -> int:
            return age_years(a.birth_tick, world.current_tick)

        new_head: Optional[AgentState] = None
        head_is_minor = False
        spouse = next(
            (m for m in living_members if m.agent_id == deceased.spouse_id), None
        )
        if spouse is not None and _age(spouse) >= min_age:
            new_head = spouse
        if new_head is None:
            adult_children = [
                m for m in living_members
                if m.agent_id in deceased.children_ids and _age(m) >= min_age
            ]
            if adult_children:
                new_head = min(adult_children, key=lambda a: (a.birth_tick, a.agent_id))
        if new_head is None:
            adults = [m for m in living_members if _age(m) >= min_age]
            if adults:
                new_head = min(adults, key=lambda a: (a.birth_tick, a.agent_id))
        if new_head is None:
            new_head = min(living_members, key=lambda a: (a.birth_tick, a.agent_id))
            head_is_minor = True
        if new_head is None:
            return
        old_head_id = household.head_id
        old_head = world.state.human.agents.get(old_head_id or "")
        household.head_id = new_head.agent_id
        world.event_log.append(
            world.current_tick,
            "household_head_changed",
            {
                "household_id": household.household_id,
                "old_head_id": old_head_id,
                "old_head_name": old_head.name if old_head is not None else old_head_id,
                "new_head_id": new_head.agent_id,
                "new_head_name": new_head.name,
                "reason": "death",
                "head_is_minor": head_is_minor,
            },
        )

    def _settle_creditor_dissolution(self, world, dissolved: HouseholdState,
                                     deceased: AgentState,
                                     heir_hh: Optional[HouseholdState]) -> None:
        """债权家庭消亡（Q5）：应收债务由继承家庭承接，否则逐笔核销。"""
        for other in world.state.human.households.values():
            if other.household_id == dissolved.household_id:
                continue
            kept: list[DebtRecord] = []
            for rec in other.debts:
                if rec.creditor_household_id != dissolved.household_id:
                    kept.append(rec)
                    continue
                debtor_head = world.state.human.agents.get(other.head_id or "")
                if heir_hh is not None:
                    heir_head = world.state.human.agents.get(heir_hh.head_id or "")
                    rec.creditor_household_id = heir_hh.household_id
                    kept.append(rec)
                    world.event_log.append(
                        world.current_tick,
                        "debt_transferred",
                        {
                            "from_id": deceased.agent_id,
                            "from_name": deceased.name,
                            "from_household_id": dissolved.household_id,
                            "to_id": heir_head.agent_id if heir_head is not None else heir_hh.household_id,
                            "to_name": heir_head.name if heir_head is not None else heir_hh.household_id,
                            "to_household_id": heir_hh.household_id,
                            "creditor_id": heir_head.agent_id if heir_head is not None else heir_hh.household_id,
                            "creditor_name": heir_head.name if heir_head is not None else heir_hh.household_id,
                            "creditor_household_id": heir_hh.household_id,
                            "debtor_household_id": other.household_id,
                            "amount": round(rec.amount, 2),
                            "resource": rec.resource,
                            "due_tick": rec.due_tick,
                        },
                    )
                else:
                    world.event_log.append(
                        world.current_tick,
                        "debt_written_off",
                        {
                            "creditor_id": deceased.agent_id,
                            "creditor_name": deceased.name,
                            "creditor_household_id": dissolved.household_id,
                            "debtor_id": (other.head_id or other.household_id),
                            "debtor_name": (
                                debtor_head.name if debtor_head is not None
                                else (other.head_id or other.household_id)
                            ),
                            "debtor_household_id": other.household_id,
                            "household_id": other.household_id,
                            "amount": round(rec.amount, 2),
                            "reason": "creditor_household_dissolved",
                        },
                    )
            other.debts = kept

    # -- 婚配（ADR 007：双向认知、从夫居、家庭协商）------------------------ #
    def _marriage_acquaintance_views(self, world, a: AgentState, b: AgentState,
                                     tuning: AgentTuning) -> tuple[dict, dict]:
        """读取双方各自对对方的认知；短期记忆 buffer 不作为资格门槛。"""
        ttl = tuning.social.acquaintance_ttl
        return (
            social.get_social_view(world.state, a.agent_id, b.agent_id,
                                   world.current_tick, ttl),
            social.get_social_view(world.state, b.agent_id, a.agent_id,
                                   world.current_tick, ttl),
        )

    def _marriage_eligible(self, world, agent: AgentState, tuning: AgentTuning) -> bool:
        m = tuning.marriage
        if not agent.alive or agent.incapacitated:
            return False
        age = age_years(agent.birth_tick, world.current_tick)
        if age < m.min_age or agent.health < m.min_health:
            return False
        if agent.spouse_id is None:
            return True
        # 鳏寡再婚：配偶已死且允许再婚
        spouse = world.state.human.agents.get(agent.spouse_id)
        return m.remarriage_allowed and (spouse is None or not spouse.alive)

    def _is_close_kin(self, a: AgentState, b: AgentState) -> bool:
        """D15：禁止亲子、同父、同母婚配。"""
        if a.agent_id in (b.mother_id, b.father_id) or b.agent_id in (a.mother_id, a.father_id):
            return True
        if a.mother_id and a.mother_id == b.mother_id:
            return True
        if a.father_id and a.father_id == b.father_id:
            return True
        return False

    def _find_courtship_target(self, world, agent: AgentState,
                               tuning: AgentTuning) -> Optional[AgentState]:
        """为未婚者选"最近且合格"的婚配候选（感知层）。

        排序键 (家距, agent_id) 对称且确定：双方各自独立选择时，互为最近的
        配对天然互指，构成 court「双向互选」的基础；无法互指者即单相思、落空。
        """
        m = tuning.marriage
        if self._spatial is None:
            return None
        home = home_node_of(world, agent)
        best: Optional[tuple[float, str, AgentState]] = None
        for other in living_agents(world.state.human.agents):
            if other.agent_id == agent.agent_id:
                continue
            if not m.allow_same_sex and other.sex == agent.sex:
                continue
            if not self._marriage_eligible(world, other, tuning):
                continue
            if m.forbid_close_kin and self._is_close_kin(agent, other):
                continue
            dist = self._spatial.travel_tu(home, home_node_of(world, other))
            if math.isinf(dist) or dist > m.max_distance_tu:
                continue
            if best is None or (dist, other.agent_id) < best[:2]:
                best = (dist, other.agent_id, other)
        return best[2] if best else None

    def _settle_marriage(self, world, tuning: AgentTuning) -> None:
        """确定性贪心配对；候选必须互相 known，且不依赖有限长度的近期记忆 buffer。"""
        m = tuning.marriage
        if self._spatial is None:
            return
        eligible = [
            a for a in living_agents(world.state.human.agents)
            if self._marriage_eligible(world, a, tuning)
        ]
        eligible.sort(key=lambda a: a.agent_id)
        eligible_by_id = {agent.agent_id: agent for agent in eligible}
        candidates: list[tuple[float, str, str, AgentState, AgentState]] = []
        # 只枚举已有认知边，不再对全镇所有适婚人口做 O(n²) 配对扫描。
        for a in eligible:
            for target_id in sorted(a.acquaintances):
                if target_id <= a.agent_id:
                    continue
                b = eligible_by_id.get(target_id)
                if b is None:
                    continue
                if not m.allow_same_sex and a.sex == b.sex:
                    continue
                if m.forbid_close_kin and self._is_close_kin(a, b):
                    continue
                dist = self._spatial.travel_tu(
                    home_node_of(world, a), home_node_of(world, b)
                )
                if math.isinf(dist) or dist > m.max_distance_tu:
                    continue
                view_ab, view_ba = self._marriage_acquaintance_views(world, a, b, tuning)
                if not view_ab["known"] or not view_ba["known"]:
                    # 同镇通婚：单镇世界无外部婚源，认知边缺失但家距在婚配半径内的
                    # 适婚者亦可成婚；事件如实记录 known=False（level=same_town）
                    view_ab = {"level": "same_town", "known": False}
                    view_ba = {"level": "same_town", "known": False}
                candidates.append((dist, a.agent_id, b.agent_id, a, b))
        candidates.sort(key=lambda x: (x[0], x[1], x[2]))

        married: set[str] = set()
        for dist, _, _, a, b in candidates:
            if a.agent_id in married or b.agent_id in married:
                continue
            wife, husband = (a, b) if a.sex == AgentSex.FEMALE else (b, a)
            if not self._can_move_wife(world, wife, husband):
                continue
            view_ab, view_ba = self._marriage_acquaintance_views(world, a, b, tuning)
            married.update((a.agent_id, b.agent_id))
            self._finalize_marriage(world, a, b, dist, view_ab, view_ba, tuning)

    def _finalize_marriage(self, world, a: AgentState, b: AgentState, dist: float,
                           view_ab: dict, view_ba: dict, tuning: AgentTuning) -> None:
        """成婚结算：一份逻辑，供 _settle_marriage（测试入口）与 court 意向结算复用。

        同户男女（如开局双人户）成婚时不迁移、不转移资产；异户按从夫居迁移并结算彩礼/陪嫁。
        """
        m = tuning.marriage
        wife, husband = (a, b) if a.sex == AgentSex.FEMALE else (b, a)
        source_household_id = wife.household_id
        target_household_id = husband.household_id
        a.spouse_id, b.spouse_id = b.agent_id, a.agent_id
        a.married_tick = b.married_tick = world.current_tick
        world.event_log.append(
            world.current_tick,
            "agent_married",
            {
                "agent_id": a.agent_id,
                "agent_name": a.name,
                "spouse_id": b.agent_id,
                "spouse_name": b.name,
                "household_id": target_household_id,
                "source_household_id": source_household_id,
                "distance_tu": round(dist, 3),
                "acquaintance": {
                    f"{a.agent_id}_to_{b.agent_id}": {
                        "level": view_ab["level"],
                        "known": view_ab["known"],
                    },
                    f"{b.agent_id}_to_{a.agent_id}": {
                        "level": view_ba["level"],
                        "known": view_ba["known"],
                    },
                },
                "participants": [
                    {"id": a.agent_id, "name": a.name},
                    {"id": b.agent_id, "name": b.name},
                ],
            },
        )
        if source_household_id == target_household_id:
            return  # 同户成婚：无迁移、无资产转移
        # 只迁移女方本人；既有子女、原家庭资产和债务均留在原家庭。
        self._move_wife_to_husband_household(world, wife, husband)
        target = household_of(world, husband)
        source = world.state.human.households[source_household_id]
        self._transfer_marriage_assets(
            world, target, source, m.bride_price_surplus_ratio,
            transfer_type="bride_price", wife=wife, husband=husband, tuning=tuning,
        )
        # 陪嫁默认不发生；只有配置明确选择正比例时才从女方原家庭独立转移。
        self._transfer_marriage_assets(
            world, source, target, m.dowry_surplus_ratio,
            transfer_type="dowry", wife=wife, husband=husband, tuning=tuning,
        )

    def _settle_courtship(self, world, tuning: AgentTuning) -> None:
        """日末结算当日结亲意向：互为目标的配对成婚（双向互选）。

        意向由 court 动作在日内写入；系统只负责把"双方都选了我"的配对落实，
        不做任何贪心配对。单相思（对方未同时选我）当日落空，次日可再选。
        """
        offers = self._courtship_offers
        m = tuning.marriage
        settled: set[str] = set()
        for a_id in sorted(offers):
            if a_id in settled:
                continue
            b_id = offers[a_id]
            if offers.get(b_id) != a_id:
                continue
            a = world.state.human.agents.get(a_id)
            b = world.state.human.agents.get(b_id)
            if a is None or b is None or not a.alive or not b.alive:
                continue
            if not self._marriage_eligible(world, a, tuning):
                continue
            if not self._marriage_eligible(world, b, tuning):
                continue
            if m.forbid_close_kin and self._is_close_kin(a, b):
                continue
            dist = self._spatial.travel_tu(home_node_of(world, a), home_node_of(world, b))
            if math.isinf(dist) or dist > m.max_distance_tu:
                continue
            view_ab, view_ba = self._marriage_acquaintance_views(world, a, b, tuning)
            settled.update((a_id, b_id))
            self._finalize_marriage(world, a, b, dist, view_ab, view_ba, tuning)
        offers.clear()

    def _can_move_wife(self, world, wife: AgentState, husband: AgentState) -> bool:
        """婚姻家庭迁移只要求双方属于不同家庭，不设成员容量或原家庭成年成员限制。"""
        return wife.household_id != husband.household_id

    def _move_wife_to_husband_household(self, world, wife: AgentState,
                                        husband: AgentState) -> None:
        source = household_of(world, wife)
        target = household_of(world, husband)
        source_members_before = list(source.member_ids)
        target_members_before = list(target.member_ids)
        source_head_before = source.head_id
        target_head_before = target.head_id

        if wife.agent_id in source.member_ids:
            source.member_ids.remove(wife.agent_id)
        if wife.agent_id not in target.member_ids:
            target.member_ids.append(wife.agent_id)
        wife.household_id = target.household_id
        wife.location = target.home_node
        wife.work_node = None
        if source.head_id == wife.agent_id:
            remaining = [
                world.state.human.agents[mid] for mid in source.member_ids
                if mid in world.state.human.agents and world.state.human.agents[mid].alive
            ]
            source.head_id = remaining[0].agent_id if remaining else None
        if target.head_id is None:
            target.head_id = husband.agent_id

        world.event_log.append(
            world.current_tick,
            "household_member_transferred",
            {
                "agent_id": wife.agent_id,
                "agent_name": wife.name,
                "source_household_id": source.household_id,
                "target_household_id": target.household_id,
                "source_members_before": source_members_before,
                "source_members_after": list(source.member_ids),
                "target_members_before": target_members_before,
                "target_members_after": list(target.member_ids),
                "source_head_before": source_head_before,
                "source_head_after": source.head_id,
                "target_head_before": target_head_before,
                "target_head_after": target.head_id,
                "location_after": wife.location,
                "work_node_after": wife.work_node,
                "reason": "marriage_patrilocal",
            },
        )
        if not source.member_ids:
            world.event_log.append(
                world.current_tick, "household_dissolved",
                {
                    "household_id": source.household_id,
                    "last_member_id": wife.agent_id,
                    "reason": "marriage_member_moved",
                },
            )

    def _marriage_asset_budget(self, world, household: HouseholdState,
                               tuning: AgentTuning) -> dict[str, float]:
        """估算可协商余量：先留家庭食物/用水安全储备，再按劳动力与债务压力折减。"""
        items = self._inheritance_items(tuning)
        food_fields = [name for name in tuning.physiology.food_fields if name in items]
        food_stock = sum(max(0.0, float(getattr(household, name, 0.0)))
                         for name in food_fields)
        daily_food_need = 0.0
        daily_water_need = 0.0
        living_members = 0
        for member_id in household.member_ids:
            member = world.state.human.agents.get(member_id)
            if member is None or not member.alive:
                continue
            living_members += 1
            member_age = age_years(member.birth_tick, world.current_tick)
            share = (tuning.consumption.minor_food_share
                     if member_age < tuning.dependency.max_age else 1.0)
            daily_food_need += (
                tuning.physiology.eat_grain_cost
                * tuning.physiology.daily_meals_per_member * share
            )
            daily_water_need += (
                tuning.water.daily_consumption_per_member
                + tuning.water.water_per_meal
                * tuning.physiology.daily_meals_per_member * share
            )
        workers = self._work_capable_count(world, household, tuning)
        labor_pressure = max(1.0, living_members / max(1, workers))
        food_reserve = (
            daily_food_need * tuning.utility.food_security_target_days * labor_pressure
        )
        water_reserve = (
            daily_water_need * tuning.environment.household_water_reserve_days
        )
        debt_factor = (
            food_stock / (food_stock + household.debt)
            if household.debt > 0 and food_stock > 0 else
            (0.0 if household.debt > 0 else 1.0)
        )
        budget: dict[str, float] = {}
        for item in items:
            stock = max(0.0, float(getattr(household, item, 0.0)))
            reserve = 0.0
            if item in food_fields and food_stock > 0:
                reserve = food_reserve * stock / food_stock
            elif item == "water":
                reserve = water_reserve
            budget[item] = round(max(0.0, stock - reserve) * debt_factor, 2)
        return budget

    def _transfer_marriage_assets(self, world, source: HouseholdState,
                                  target: HouseholdState, ratio: float, *,
                                  transfer_type: str, wife: AgentState,
                                  husband: AgentState, tuning: AgentTuning) -> None:
        """按双方家庭可支配余量转移彩礼/陪嫁；每次转移独立记账且严格守恒。"""
        if ratio <= 0 or source.household_id == target.household_id:
            return
        items = self._inheritance_items(tuning)
        budget = self._marriage_asset_budget(world, source, tuning)
        resources = {
            item: min(
                max(0.0, float(getattr(source, item, 0.0))),
                round(budget.get(item, 0.0) * ratio, 2),
            )
            for item in items
        }
        resources = {item: amount for item, amount in resources.items() if amount > 0}
        if not resources:
            return
        from_before = _inventory(source, items)
        to_before = _inventory(target, items)
        for item, amount in resources.items():
            setattr(source, item, round(getattr(source, item) - amount, 2))
            setattr(target, item, round(getattr(target, item) + amount, 2))
        world.event_log.append(
            world.current_tick,
            "marriage_assets_transferred",
            {
                "transfer_type": transfer_type,
                "from_household_id": source.household_id,
                "to_household_id": target.household_id,
                "resources": resources,
                "from_inventory_before": from_before,
                "from_inventory_after": _inventory(source, items),
                "to_inventory_before": to_before,
                "to_inventory_after": _inventory(target, items),
                "wife_id": wife.agent_id,
                "husband_id": husband.agent_id,
                "participants": [
                    {"id": wife.agent_id, "name": wife.name},
                    {"id": husband.agent_id, "name": husband.name},
                ],
            },
        )

    # -- 分家（任务12 第3步 / 设计 §9.2）------------------------------------- #
    def _settle_split(self, world, tuning: AgentTuning) -> None:
        """每户每 tick 最多分家一次：人数达标且存在“丈夫非户主”的已婚成年夫妻。"""
        split = tuning.split
        min_age = tuning.marriage.min_age
        for household in list(living_households(world)):
            if len(household.member_ids) < split.min_members:
                continue
            members = [a for a in household_members(world, household) if a.alive]
            couple = self._split_couple(world, household, members, min_age)
            if couple is None:
                continue
            self._split_household(world, household, couple[0], couple[1], tuning)

    def _split_couple(self, world, household: HouseholdState, members: list[AgentState],
                      min_age: int) -> Optional[tuple[AgentState, AgentState]]:
        """按 member_ids 顺序取第一对合法夫妻：(丈夫, 妻子)。确定性，不用 rng。"""
        for member in members:
            if not member.spouse_id:
                continue
            spouse = world.state.human.agents.get(member.spouse_id)
            if spouse is None or not spouse.alive:
                continue
            if spouse.household_id != household.household_id:
                continue
            if member.sex == spouse.sex:
                continue
            husband = member if member.sex == AgentSex.MALE else spouse
            wife = spouse if husband is member else member
            if husband.agent_id == household.head_id:
                continue  # 丈夫必须是“非户主”
            if age_years(husband.birth_tick, world.current_tick) < min_age:
                continue
            if age_years(wife.birth_tick, world.current_tick) < min_age:
                continue
            return husband, wife
        return None

    def _split_household(self, world, source: HouseholdState, husband: AgentState,
                         wife: AgentState, tuning: AgentTuning) -> None:
        """分出夫妻 + 未成年子女：资产/债务按比例拆分，余额留原户（守恒）。"""
        split = tuning.split
        min_age = tuning.marriage.min_age
        items = self._inheritance_items(tuning)
        assets_before = _inventory(source, items)
        debts_before = round(source.debt, 2)

        children = [
            m for m in household_members(world, source)
            if m.alive and m.agent_id not in (husband.agent_id, wife.agent_id)
            and age_years(m.birth_tick, world.current_tick) < min_age
            and (m.mother_id == wife.agent_id or m.father_id == husband.agent_id)
        ]
        moving = [husband, wife] + children

        new_id = self._next_household_id(world, source.household_id)
        candidates = split.home_node_candidates
        if candidates:
            occupied = {
                hh.home_node for hh in world.state.human.households.values()
                if hh.household_id != source.household_id
                and any(m.alive for m in household_members(world, hh))
            }
            available = [node for node in candidates
                         if node not in occupied and node != source.home_node]
            if not available:
                world.event_log.append(world.current_tick, "household_split_skipped", {
                    "source_household_id": source.household_id,
                    "reason": "no_vacant_residence",
                })
                return
            home = available[0]
        else:
            home = source.home_node
        work_node = husband.work_node or source.work_node
        new_household = HouseholdState(
            household_id=new_id,
            member_ids=[m.agent_id for m in moving],
            head_id=husband.agent_id,
            home_node=home,
            work_node=work_node,
            formed_tick=world.current_tick,
            registry_node=source.registry_node,
            registered_tick=world.current_tick if source.registry_node else None,
        )

        # 资产：新户取 round(before × ratio)，原户取差额
        new_assets: dict[str, float] = {}
        for item in items:
            before = round(getattr(source, item, 0.0), 2)
            new_amount = round(before * split.asset_ratio, 2)
            setattr(source, item, round(before - new_amount, 2))
            setattr(new_household, item, new_amount)
            new_assets[item] = new_amount
        # 债务：同比例拆分，余额留原户
        for rec in list(source.debts):
            amount = round(rec.amount, 2)
            new_amount = round(amount * split.asset_ratio, 2)
            remainder = round(amount - new_amount, 2)
            if new_amount > 0:
                new_household.debts.append(
                    DebtRecord(
                        debtor_household_id=new_id,
                        creditor_household_id=rec.creditor_household_id,
                        amount=new_amount,
                        originated_tick=rec.originated_tick,
                        due_tick=rec.due_tick,
                        overdue=rec.overdue,
                        resource=rec.resource,
                    )
                )
            if remainder > 0:
                rec.amount = remainder
            else:
                source.debts.remove(rec)

        for member in moving:
            if member.agent_id in source.member_ids:
                source.member_ids.remove(member.agent_id)
            member.household_id = new_id
            member.location = home
            member.work_node = None  # 迁入新户后取新户默认劳作点
        world.state.human.households[new_id] = new_household
        if new_household.registry_node:
            world.event_log.append(world.current_tick, "household_registered", {
                "household_id": new_id, "head_id": husband.agent_id,
                "home_node": home, "work_node": work_node,
                "registry_node": new_household.registry_node,
                "registered_tick": world.current_tick,
            })

        world.event_log.append(
            world.current_tick,
            "household_split",
            {
                "source_household_id": source.household_id,
                "new_household_id": new_id,
                "head_id": husband.agent_id,
                "head_name": husband.name,
                "members": [{"id": m.agent_id, "name": m.name} for m in moving],
                "assets_before": assets_before,
                "source_assets_after": _inventory(source, items),
                "new_assets": new_assets,
                "source_members_after": list(source.member_ids),
                "source_debt_records_after": [d.model_dump() for d in source.debts],
                "new_debt_records": [d.model_dump() for d in new_household.debts],
                "debts_before": debts_before,
                "source_debts_after": round(source.debt, 2),
                "new_debts": round(new_household.debt, 2),
                "home_node": home,
                "work_node": work_node,
                "reason": "married_couple_out",
                "participants": [{"id": m.agent_id, "name": m.name} for m in moving],
            },
        )

    def _next_household_id(self, world, source_id: str) -> str:
        """新户 id：hh_{source}_{序号}，全库查重。"""
        n = 1
        while True:
            candidate = f"hh_{source_id}_{n}"
            if candidate not in world.state.human.households:
                return candidate
            n += 1

    # -- 生育与新生儿（任务12 D6-D8 / A4 / A5）------------------------------ #
    def _fertility_boost(self, world, tuning: AgentTuning) -> float:
        """A5 低人口保护：存活成年 ≤ 阈值且无未成年子女时提升婚育概率。"""
        b = tuning.birth
        living = living_agents(world.state.human.agents)
        adults = [
            a for a in living
            if age_years(a.birth_tick, world.current_tick) >= tuning.marriage.min_age
        ]
        has_minor = any(
            age_years(a.birth_tick, world.current_tick) < tuning.marriage.min_age
            for a in living
        )
        if len(adults) <= b.low_population_adults and not has_minor:
            return b.low_population_fertility_boost
        return 1.0

    def _birth_eligible(self, world, mother: AgentState, father: AgentState,
                        tuning: AgentTuning) -> bool:
        b = tuning.birth
        tick = world.current_tick
        mother_age = age_years(mother.birth_tick, tick)
        father_age = age_years(father.birth_tick, tick)
        if not (b.min_age_female <= mother_age <= b.max_age_female):
            return False
        if father_age > b.max_age_male:
            return False
        if mother.health < b.min_health or father.health < b.min_health:
            return False
        if mother.last_birth_tick is not None and tick - mother.last_birth_tick < b.interval_days:
            return False
        return True

    def _birth_resource_factor(self, world, mother: AgentState,
                               tuning: AgentTuning) -> float:
        """以家庭食物天数和用水天数连续调节生育概率，不设置人口阈值。"""
        household = household_of(world, mother)
        food_fields = tuning.physiology.food_fields
        food_stock = sum(
            max(0.0, float(getattr(household, field_name, 0.0)))
            for field_name in food_fields
        )
        daily_food_need = 0.0
        daily_water_need = 0.0
        for member_id in household.member_ids:
            member = world.state.human.agents.get(member_id)
            if member is None or not member.alive:
                continue
            member_age = age_years(member.birth_tick, world.current_tick)
            share = (tuning.consumption.minor_food_share
                     if member_age < tuning.dependency.max_age else 1.0)
            daily_food_need += (
                tuning.physiology.eat_grain_cost
                * tuning.physiology.daily_meals_per_member * share
            )
            daily_water_need += (
                tuning.water.daily_consumption_per_member
                + tuning.water.water_per_meal
                * tuning.physiology.daily_meals_per_member * share
            )
        food_days = (
            food_stock / daily_food_need if daily_food_need > 0 else float("inf")
        )
        water_days = (
            household.water / daily_water_need if daily_water_need > 0 else float("inf")
        )
        food_factor = min(
            1.0, food_days / tuning.utility.food_security_target_days
        )
        water_target_days = max(
            1.0, tuning.environment.household_water_reserve_days
        )
        water_factor = min(1.0, water_days / water_target_days)
        return round(max(0.0, min(food_factor, water_factor)), 4)

    def _settle_birth(self, world, tuning: AgentTuning) -> None:
        """逐对配偶判断生育；资源充足时概率较高，短缺时连续降低，不设人口/户规模上限。"""
        b = tuning.birth
        boost = self._fertility_boost(world, tuning)
        base_chance = min(1.0, b.chance_per_day * boost)
        mothers = [
            a for a in living_agents(world.state.human.agents)
            if a.sex == AgentSex.FEMALE and not a.incapacitated
        ]
        mothers.sort(key=lambda a: a.agent_id)
        for mother in mothers:
            father = world.state.human.agents.get(mother.spouse_id) if mother.spouse_id else None
            if father is None or not father.alive or father.spouse_id != mother.agent_id:
                continue
            if not self._birth_eligible(world, mother, father, tuning):
                continue
            resource_factor = self._birth_resource_factor(world, mother, tuning)
            chance = min(1.0, base_chance * resource_factor)
            if self.rng.random() >= chance:
                continue
            self._give_birth(
                world, mother, father, tuning, resource_factor=resource_factor
            )

    def _child_id(self, world) -> str:
        n = 1
        while f"child_{n}" in world.state.human.agents:
            n += 1
        return f"child_{n}"

    def _child_name(self, world, mother: AgentState, father: AgentState,
                    tuning: AgentTuning) -> tuple[str, str]:
        """返回 (姓, 姓名)；姓名全局唯一（timeline 按姓名筛选，重名会串档）。"""
        b = tuning.birth
        surname_src = father if b.surname_from == "father" else mother
        surname = surname_src.surname or b.default_surname
        used = {a.name for a in world.state.human.agents.values()}
        for given in b.given_names:
            name = f"{surname}{given}"
            if name not in used:
                return surname, name
        base = f"{surname}{b.given_names[0]}"
        n = 1
        while b.name_fallback_suffix.format(name=base, n=n) in used:
            n += 1
        return surname, b.name_fallback_suffix.format(name=base, n=n)

    def _give_birth(self, world, mother: AgentState, father: AgentState,
                    tuning: AgentTuning, resource_factor: float = 1.0) -> None:
        b = tuning.birth
        child_id = self._child_id(world)
        surname, name = self._child_name(world, mother, father, tuning)
        sex = AgentSex.MALE if self.rng.random() < b.male_ratio else AgentSex.FEMALE
        avg_health = (mother.health + father.health) / 2.0
        avg_stamina = (mother.stamina + father.stamina) / 2.0
        health_cap = self._health_cap(0, tuning)
        stamina_cap = 100.0 * tuning.aging.stage_for(0).stamina_max_mult
        health = min(
            health_cap,
            max(b.newborn_min_health, avg_health * b.newborn_health_parent_ratio),
        )
        stamina = min(
            stamina_cap,
            max(b.newborn_min_stamina, avg_stamina * b.newborn_stamina_parent_ratio),
        )
        household = household_of(world, mother)
        home = household.home_node

        child = AgentState(
            agent_id=child_id,
            name=name,
            surname=surname,
            sex=sex,
            birth_tick=world.current_tick,
            life_stage=tuning.aging.stage_for(0).name,
            household_id=household.household_id,
            location=home,
            work_node=None,  # 阶段二 C：不继承个人偏好，取家庭可分配田块/默认
            health=round(health, 2),
            hunger=b.initial_hunger,
            stamina=round(stamina, 2),
            fatigue=0.0,
            mother_id=mother.agent_id,
            father_id=father.agent_id,
        )
        world.state.human.agents[child_id] = child
        household.member_ids.append(child_id)
        mother.children_ids.append(child_id)
        father.children_ids.append(child_id)
        mother.last_birth_tick = world.current_tick
        # 阶段二 C：新生儿不继承个人偏好，取家庭可分配田块（按可劳作成员序确定性分配）
        work = work_node_of(world, child)
        work_source = "household_allocation" if household.work_nodes else "household"
        # 阶段二 §3.0：分娩健康代价（01-physical-state §4.4 普通分娩 health −10）
        mother_health_before = mother.health
        mother.health = max(0.0, round(mother_health_before - b.mother_health_cost, 2))

        world.event_log.append(
            world.current_tick,
            "agent_born",
            {
                "agent_id": child_id,
                "agent_name": name,
                "child_id": child_id,
                "child_name": name,
                "household_id": household.household_id,
                "mother_id": mother.agent_id,
                "mother_name": mother.name,
                "father_id": father.agent_id,
                "father_name": father.name,
                "sex": sex.value,
                "birth_tick": world.current_tick,
                "initial_health": round(child.health, 2),
                "initial_stamina": round(child.stamina, 2),
                "home_node": home,
                "work_node": work,
                "work_node_source": work_source,
                "mother_health_before": round(mother_health_before, 2),
                "mother_health_after": round(mother.health, 2),
                "population_after": len(living_agents(world.state.human.agents)),
                "fertility_resource_factor": round(resource_factor, 4),
            },
        )

    def _forgive_debts(self, world, household: HouseholdState, *, cause: str) -> None:
        """核销家庭全部剩余债务：逐笔写 debt_forgiven（可追溯，不静默消失），再清空列表。

        守恒说明：这是账面坏账核销（家庭无粮可还，债权家庭承担损失），不涉及粮的凭空产生或消灭；
        世界总粮不变，世界总债减少并由事件完整记录。
        """
        for rec in list(household.debts):
            creditor_hh = world.state.human.households.get(rec.creditor_household_id)
            creditor_head = (
                world.state.human.agents.get(creditor_hh.head_id or "") if creditor_hh is not None else None
            )
            creditor_name = (
                creditor_head.name if creditor_head is not None else rec.creditor_household_id
            )
            creditor_agent_id = (
                creditor_head.agent_id if creditor_head is not None else rec.creditor_household_id
            )
            debtor_head = world.state.human.agents.get(household.head_id or "")
            debtor_name = (
                debtor_head.name if debtor_head is not None
                else (household.head_id or household.household_id)
            )
            world.event_log.append(
                world.current_tick,
                "debt_forgiven",
                {
                    "creditor_id": creditor_agent_id,
                    "creditor_name": creditor_name,
                    "creditor_household_id": rec.creditor_household_id,
                    "debtor_id": (household.head_id or household.household_id),
                    "debtor_name": debtor_name,
                    "debtor_household_id": household.household_id,
                    "household_id": household.household_id,
                    "amount": round(rec.amount, 2),
                    "resource": rec.resource,
                    "cause": cause,
                },
            )
        household.debts = []

    @staticmethod
    def _household_foodless(household: HouseholdState) -> bool:
        """全家无任何可食物资（含债务标的物），用于断粮坏账核销判定。"""
        return (
            household.grain <= 0
            and household.fish <= 0
            and household.meat <= 0
            and household.vegetable <= 0
        )

    def _forgive_one_debt(self, world, household: HouseholdState, rec, *, cause: str) -> None:
        """核销单笔债务：写 debt_forgiven（可追溯，不静默消失），从列表移除。

        守恒说明与 _forgive_debts 相同：账面坏账核销，债权家庭承担损失，
        世界总粮不变，世界总债减少并由事件完整记录。
        """
        creditor_hh = world.state.human.households.get(rec.creditor_household_id)
        creditor_head = (
            world.state.human.agents.get(creditor_hh.head_id or "") if creditor_hh is not None else None
        )
        creditor_name = (
            creditor_head.name if creditor_head is not None else rec.creditor_household_id
        )
        creditor_agent_id = (
            creditor_head.agent_id if creditor_head is not None else rec.creditor_household_id
        )
        debtor_head = world.state.human.agents.get(household.head_id or "")
        debtor_name = (
            debtor_head.name if debtor_head is not None
            else (household.head_id or household.household_id)
        )
        world.event_log.append(
            world.current_tick,
            "debt_forgiven",
            {
                "creditor_id": creditor_agent_id,
                "creditor_name": creditor_name,
                "creditor_household_id": rec.creditor_household_id,
                "debtor_id": (household.head_id or household.household_id),
                "debtor_name": debtor_name,
                "debtor_household_id": household.household_id,
                "household_id": household.household_id,
                "amount": round(rec.amount, 2),
                "resource": getattr(rec, "resource", "grain") or "grain",
                "cause": cause,
            },
        )
        if rec in household.debts:
            household.debts.remove(rec)

    def _collect_debts(self, world, agent: AgentState, tuning: AgentTuning) -> None:
        """到期债务催收，区分「违约状态变更」与「催收尝试」（任务10，降低叙事噪声）。

        - 到期后每 collection_interval_days 天催收一次（last_collected_tick 节流）。
        - **违约状态变更**（debt_defaulted）：一笔债务首次到期且无力全额偿还时，由未逾期变为
          逾期，只写一次；此后该笔不再重复写 debt_defaulted。
        - **催收尝试**（debt_collection_attempt）：已是逾期的债务后续每次零粮催收，写该事件
          （可重复，但语义明确为「催收失败」而非「新增违约」），人生档案可按类型过滤刷屏。
        - 有粮则扣粮还债权家庭写 debt_collected；足额清偿 overdue 清零，部分还款剩余仍 overdue。
          逾期家庭后续借粮被 _score 禁止。
        """
        tick = world.current_tick
        interval = tuning.debt.collection_interval_days
        household = household_of(world, agent)
        for rec in list(household.debts):  # 遍历副本，避免边迭代边修改
            if tick < rec.due_tick:
                continue
            last = rec.last_collected_tick
            if last is not None and tick - last < interval:
                continue
            rec.last_collected_tick = tick
            creditor_hh = world.state.human.households.get(rec.creditor_household_id)
            if creditor_hh is None:
                continue
            creditor_head = world.state.human.agents.get(creditor_hh.head_id or "")
            creditor_agent_id = (
                creditor_head.agent_id if creditor_head is not None else creditor_hh.household_id
            )
            creditor_name = (
                creditor_head.name if creditor_head is not None else creditor_hh.household_id
            )
            resource = getattr(rec, "resource", "grain") or "grain"
            debtor_stock = float(getattr(household, resource, 0.0))
            pay = min(rec.amount, debtor_stock)
            first_due = not rec.overdue  # 本次是否为该笔首次到期催收
            if pay > 0:
                creditor_stock = float(getattr(creditor_hh, resource, 0.0))
                setattr(household, resource, round(debtor_stock - pay, 2))
                setattr(creditor_hh, resource, round(creditor_stock + pay, 2))
                rec.amount = round(rec.amount - pay, 2)
                rec.overdue = rec.amount > 0
                world.event_log.append(
                    tick,
                    "debt_collected",
                    {
                        "creditor_id": creditor_agent_id,
                        "creditor_name": creditor_name,
                        "creditor_household_id": creditor_hh.household_id,
                        "debtor_id": agent.agent_id,
                        "debtor_name": agent.name,
                        "debtor_household_id": household.household_id,
                        "household_id": household.household_id,
                        "amount_paid": round(pay, 2),
                        "remaining": round(rec.amount, 2),
                        "overdue": rec.overdue,
                        "originated_tick": rec.originated_tick,
                        "resource": resource,
                        f"debtor_{resource}_after": round(getattr(household, resource), 2),
                        f"creditor_{resource}_after": round(getattr(creditor_hh, resource), 2),
                        "debtor_grain_after": round(household.grain, 2),
                        "creditor_grain_after": round(creditor_hh.grain, 2),
                    },
                )
            elif first_due:
                # 首次到期零粮：违约状态变更（只写一次）
                rec.overdue = True
                world.event_log.append(
                    tick,
                    "debt_defaulted",
                    {
                        "creditor_id": creditor_agent_id,
                        "creditor_name": creditor_name,
                        "creditor_household_id": creditor_hh.household_id,
                        "debtor_id": agent.agent_id,
                        "debtor_name": agent.name,
                        "debtor_household_id": household.household_id,
                        "household_id": household.household_id,
                        "amount": round(rec.amount, 2),
                        "overdue_ticks": tick - rec.due_tick,
                    },
                )
                if tuning.debt.write_off_unpayable and self._household_foodless(household):
                    # 断粮户坏账核销：逾期标记会永久锁死借粮/借食/赊账救济渠道，
                    # 家庭无粮可还时当场核销该笔（debt_forgiven 可追溯），有粮户不受影响
                    self._forgive_one_debt(world, household, rec, cause="断粮坏账核销")
            else:
                # 已逾期的重复催收失败：写催收尝试（可重复，语义明确），不刷违约
                world.event_log.append(
                    tick,
                    "debt_collection_attempt",
                    {
                        "creditor_id": creditor_agent_id,
                        "creditor_name": creditor_name,
                        "creditor_household_id": creditor_hh.household_id,
                        "debtor_id": agent.agent_id,
                        "debtor_name": agent.name,
                        "debtor_household_id": household.household_id,
                        "household_id": household.household_id,
                        "amount": round(rec.amount, 2),
                        "overdue_ticks": tick - rec.due_tick,
                        "interval_days": interval,
                    },
                )
        household.debts = [d for d in household.debts if d.amount > 0]

    # -- 债务纠纷：2 轮私下催收（任务15 阶段二）---------------------------- #
    def _settle_debt_disputes(self, world, tuning: AgentTuning) -> int:
        """赊账逾期 ≥ trigger_overdue_days 且「有粮但不还」时，债权家庭发起一次私下催收。

        触发窗口：``refusal_threshold < 债务家庭存粮 ≤ trigger_max_grain``。断粮
        （≤ refusal_threshold）不进会话，走既有 debt_defaulted / debt_collection_attempt
        强制扣粮路径；存粮高于上限说明有能力偿还，不需要私下催收。

        收窄实现（裁决 §3.2）：只有 ``origin="market_credit"`` 的债务参与；每笔债务最多
        发起一次会话（``dispute_started_tick`` 标记；延期后清零，进入下一周期）；拒绝后
        不再重复发起，后续仍走既有 debt_defaulted / debt_collection_attempt。
        仅用已有事实：家庭库存、逾期天数、事件流中的 debt_defaulted / debt_repaid、亲缘关系。
        返回发起的会话数。
        """
        cfg = tuning.conflict.debt_dispute
        tick = world.current_tick
        living_ids = {h.household_id for h in living_households(world)}
        candidates: list[tuple[HouseholdState, DebtRecord]] = []
        for household in sorted(world.state.human.households.values(), key=lambda h: h.household_id):
            if household.household_id not in living_ids:
                continue
            for rec in household.debts:
                if rec.origin != "market_credit" or rec.amount <= 0:
                    continue
                if rec.dispute_started_tick is not None:
                    continue
                if tick - rec.due_tick < cfg.trigger_overdue_days:
                    continue
                resource = getattr(rec, "resource", "grain") or "grain"
                resource_stock = float(getattr(household, resource, 0.0))
                if resource_stock <= cfg.refusal_threshold:
                    continue  # 该物资断库存：不走会话，交给既有催收路径
                if resource_stock > cfg.trigger_max_grain:
                    continue  # 有足额该物资：有能力偿还，无需私下催收
                if rec.creditor_household_id not in living_ids:
                    continue
                candidates.append((household, rec))
        if not candidates:
            return 0

        defaulted, repaid = self._debt_history_sets(world)
        count = 0
        for index, (debtor_hh, rec) in enumerate(candidates):
            creditor_hh = world.state.human.households.get(rec.creditor_household_id)
            if creditor_hh is None:
                continue
            self._negotiate_debt(
                world, tuning, debtor_hh, creditor_hh, rec,
                defaulted=defaulted, repaid=repaid, index=index,
            )
            count += 1
        # 清偿完毕的记录移出列表
        for household, _rec in candidates:
            household.debts = [d for d in household.debts if d.amount > 0]
        return count

    def _negotiate_debt(
        self,
        world,
        tuning: AgentTuning,
        debtor_hh: HouseholdState,
        creditor_hh: HouseholdState,
        rec: DebtRecord,
        *,
        defaulted: set[str],
        repaid: set[str],
        index: int = 0,
    ) -> dict:
        """执行固定 2 轮私下催收，返回结果摘要（便于测试与日志）。

        第 1 轮：债权人提诉求（全额 / 部分 / 延期）——由既有事实决定：
          亲缘 → 延期；有违约前科 → 全额；否则 → 部分。
          P2 开关（impression_in_decision）打开且印象档位为 defaulting 时按全额处理；
          开关默认关闭，关闭时读不到印象、行为与 P1 完全一致。
          任务16 阶段二：社会记忆调节（只读 get_social_view，裁决 §3.5）——
          上次破裂 → 部分升全额；上次守约 → 部分放宽为延期；不动 kin/前科优先级。
        第 2 轮：债务人回应（还款 / 请求延期 / 拒绝）——由库存与 refusal_threshold 决定；
          请求延期时，债权人按「亲缘或曾守约」接受，否则坚持 → 破裂。
        四种结果：repaid / partial_repaid / deferred / broken；两轮后必结束，不悬置。
        结果写回双方短期记忆并互升 KNOWN（裁决 §3.3 交互即互升，阶段二简化点）。
        """
        cfg = tuning.conflict.debt_dispute
        tick = world.current_tick
        resource = getattr(rec, "resource", "grain") or "grain"
        debtor_id = debtor_hh.head_id or debtor_hh.household_id
        creditor_id = creditor_hh.head_id or creditor_hh.household_id
        debtor_name = self._head_name(world, debtor_hh)
        creditor_name = self._head_name(world, creditor_hh)
        conflict_id = (
            f"cf-{tick}-{debtor_hh.household_id}-{creditor_hh.household_id}-{index}"
        )
        kin = self._households_are_kin(world, debtor_hh, creditor_hh)
        prior_default = debtor_hh.household_id in defaulted
        prior_honored = debtor_hh.household_id in repaid

        # 第 1 轮：债权人诉求
        # 任务25 P2：印象参与决策（独立开关、默认关闭）。关闭时不读印象，行为与 P1 完全一致。
        impression_defaulting = False
        if tuning.social.impression_in_decision:
            impression = social.get_impression(world.state, creditor_id, debtor_id)
            impression_defaulting = (
                impression is not None and impression.label == social.IMPRESSION_DEFAULTING
            )
        if kin:
            proposal = "deferral"
        elif prior_default or impression_defaulting:
            proposal = "full"
        else:
            proposal = "partial"
        # 任务17 裁决 4.1：诉求成因只读元数据（供渲染追溯"为何开这个口"），不改决策。
        proposal_basis = "kin" if kin else ("prior_default" if prior_default else "plain")
        # 任务16 阶段二：债权人短期记忆调节诉求（防"只记不读"的接入点）。
        # 只读不写事件（裁决 §3.5）；记忆 outcome 与结果写回口径一致。
        view = social.get_social_view(
            world.state, creditor_id, debtor_id, tick, tuning.social.acquaintance_ttl,
        )
        last_outcome = social.last_memory_outcome(view["memories"])
        social_adjustment = None
        if proposal == "partial":
            if last_outcome == "broken":
                proposal = "full"       # 上次破裂：部分诉求升全额
                social_adjustment = "prior_broken→full"
            elif last_outcome in ("repaid", "partial_repaid"):
                proposal = "deferral"   # 上次守约：部分诉求放宽为延期
                social_adjustment = "prior_repaid→deferral"
        if proposal == "full":
            proposed_amount = round(rec.amount, 2)
        elif proposal == "partial":
            proposed_amount = round(rec.amount * cfg.partial_ratio, 2)
        else:
            proposed_amount = 0.0

        world.event_log.append(
            tick,
            "conflict_started",
            {
                "conflict_id": conflict_id,
                "conflict_type": "debt-disputes",
                "creditor_id": creditor_id,
                "creditor_name": creditor_name,
                "creditor_household_id": creditor_hh.household_id,
                "debtor_id": debtor_id,
                "debtor_name": debtor_name,
                "debtor_household_id": debtor_hh.household_id,
                "household_id": debtor_hh.household_id,
                "trigger_event": "market_credit_overdue",
                "amount": round(rec.amount, 2),
                "resource": resource,
                "overdue_ticks": tick - rec.due_tick,
            },
        )

        # 第 2 轮：债务人回应（只依赖库存与既有事实，不引入 trust/grudge 新状态）
        if proposal == "deferral":
            response = "accept_deferral"
        elif float(getattr(debtor_hh, resource, 0.0)) >= proposed_amount > 0:
            response = "repay"
        elif float(getattr(debtor_hh, resource, 0.0)) <= cfg.refusal_threshold:
            response = "refuse"
        else:
            response = "request_deferral"

        for (
            round_no, actor, actor_name, proposal_key, amount_key,
            responder, responder_name, response_key,
        ) in (
            (1, creditor_id, creditor_name, proposal, proposed_amount,
             debtor_id, debtor_name, None),
            (2, debtor_id, debtor_name, None, None,
             creditor_id, creditor_name, response),
        ):
            payload = {
                "conflict_id": conflict_id,
                "round": round_no,
                "initiator": actor,
                # 任务17 补丁二：只读姓名字段，供 timeline 按姓名命中与渲染直读；replay 不读。
                "initiator_name": actor_name,
                "responder": responder,
                "responder_name": responder_name,
                "proposal": proposal_key,
                "proposal_amount": amount_key,
                "response": response_key,
                "resource": resource,
            }
            if round_no == 1:
                # 任务17 裁决 4.1：只读元数据（成因随事件落库，replay 不读）。
                payload["social_adjustment"] = social_adjustment
                payload["proposal_basis"] = proposal_basis
            world.event_log.append(tick, "conflict_negotiation_round", payload)

        result: dict = {
            "conflict_id": conflict_id,
            "proposal": proposal,
            "response": response,
        }

        if response == "repay":
            debtor_stock = float(getattr(debtor_hh, resource, 0.0))
            creditor_stock = float(getattr(creditor_hh, resource, 0.0))
            pay = min(proposed_amount, debtor_stock, rec.amount)
            setattr(creditor_hh, resource, round(creditor_stock + pay, 2))
            setattr(debtor_hh, resource, round(debtor_stock - pay, 2))
            rec.amount = round(rec.amount - pay, 2)
            rec.overdue = rec.amount > 0
            rec.dispute_started_tick = tick
            # 会话已扣粮：同 tick 后续 _collect_debts 不得重复扣（按催收间隔节流到下一周期）
            rec.last_collected_tick = tick
            world.event_log.append(
                tick,
                "debt_repaid",
                {
                    "creditor_id": creditor_id,
                    "creditor_name": creditor_name,
                    "creditor_household_id": creditor_hh.household_id,
                    "debtor_id": debtor_id,
                    "debtor_name": debtor_name,
                    "debtor_household_id": debtor_hh.household_id,
                    "household_id": debtor_hh.household_id,
                    "amount": round(pay, 2),
                    "remaining": round(rec.amount, 2),
                    "source": "debt_dispute",
                    "originated_tick": rec.originated_tick,
                    "resource": resource,
                    f"debtor_{resource}_after": round(getattr(debtor_hh, resource), 2),
                    f"creditor_{resource}_after": round(getattr(creditor_hh, resource), 2),
                    "debtor_grain_after": round(debtor_hh.grain, 2),
                    "creditor_grain_after": round(creditor_hh.grain, 2),
                },
            )
            resolution = "repaid" if rec.amount <= 0 else "partial_repaid"
            result["resolution"] = resolution
            world.event_log.append(
                tick,
                "conflict_resolved",
                {
                    "conflict_id": conflict_id,
                    "resolution": resolution,
                    "amount_paid": round(pay, 2),
                    "remaining": round(rec.amount, 2),
                    "creditor_household_id": creditor_hh.household_id,
                    "debtor_household_id": debtor_hh.household_id,
                },
            )
            self._remember_dispute(world, tuning, creditor_id, debtor_id, resolution)
            return result

        accept_deferral = response == "accept_deferral" or (
            response == "request_deferral" and (kin or prior_honored)
        )
        if accept_deferral:
            old_due = rec.due_tick
            rec.due_tick = tick + cfg.deferral_days
            rec.overdue = False
            rec.dispute_started_tick = None  # 延期后进入下一周期，仍可再次触发
            result["resolution"] = "deferred"
            world.event_log.append(
                tick,
                "debt_deferred",
                {
                    "conflict_id": conflict_id,
                    "creditor_id": creditor_id,
                    "creditor_name": creditor_name,
                    "creditor_household_id": creditor_hh.household_id,
                    "debtor_id": debtor_id,
                    "debtor_name": debtor_name,
                    "debtor_household_id": debtor_hh.household_id,
                    "household_id": debtor_hh.household_id,
                    "amount": round(rec.amount, 2),
                    "resource": resource,
                    "old_due_tick": old_due,
                    "new_due_tick": rec.due_tick,
                    "deferral_days": cfg.deferral_days,
                },
            )
            world.event_log.append(
                tick,
                "conflict_resolved",
                {
                    "conflict_id": conflict_id,
                    "resolution": "deferred",
                    "new_due_tick": rec.due_tick,
                    "creditor_household_id": creditor_hh.household_id,
                    "debtor_household_id": debtor_hh.household_id,
                },
            )
            self._remember_dispute(world, tuning, creditor_id, debtor_id, "deferred")
            return result

        # 拒绝（或债权人坚持不延期）→ 破裂；该笔不再重复发起会话
        rec.dispute_started_tick = tick
        reason = "refused" if response == "refuse" else "creditor_insists"
        result["resolution"] = "broken"
        result["reason"] = reason
        world.event_log.append(
            tick,
            "conflict_broken",
            {
                "conflict_id": conflict_id,
                "reason": reason,
                "amount": round(rec.amount, 2),
                "resource": resource,
                "overdue_ticks": tick - rec.due_tick,
                "creditor_household_id": creditor_hh.household_id,
                "debtor_household_id": debtor_hh.household_id,
            },
        )
        self._remember_dispute(world, tuning, creditor_id, debtor_id, "broken")
        return result

    def _remember_dispute(self, world, tuning: AgentTuning,
                          creditor_id: str, debtor_id: str, outcome: str) -> None:
        """债争结果写回双方记忆 + 交互即互升 KNOWN（任务16 阶段二）。

        裁决 §3.4 纯净性：写入只用 (tick, target_id, event_type, outcome)，
        不读运行时中间态；replay 侧由 conflict_resolved / conflict_broken
        以相同口径重建（户→户主映射在回放态上等价解析）。
        语义：repaid 系 / deferred / broken 三种结果都算一次真实交互，均写记忆
        ——延期是「曾给过宽限」的印象而非违约；诉求调节只认 broken / repaid 系
        outcome，deferred 不改下一轮诉求档位（见 _negotiate_debt 调节段与
        test_negotiation_proposal_direction 的 deferred→partial 断言）。
        """
        cap = tuning.social.memory_capacity
        tick = world.current_tick
        social.record_interaction(
            world, creditor_id, debtor_id, tick, cap, "debt_dispute", outcome,
        )
        social.record_interaction(
            world, debtor_id, creditor_id, tick, cap, "debt_dispute", outcome,
        )
        # 任务 18 P1：记忆写回后合成印象（B 为主 + C 作门槛）；仅 label 变化写事件。
        window = tuning.social.impression_window
        social.update_impression(world, creditor_id, debtor_id, window)
        social.update_impression(world, debtor_id, creditor_id, window)

    @staticmethod
    def _head_name(world, household: HouseholdState) -> str:
        """家庭对外称谓：存活户主名 → 户主 id → 家庭 id。"""
        head = world.state.human.agents.get(household.head_id or "")
        if head is not None and head.alive:
            return head.name
        return household.head_id or household.household_id

    @staticmethod
    def _households_are_kin(world, a: HouseholdState, b: HouseholdState) -> bool:
        """两户是否存在直接亲缘（配偶/父母/子女），只读已有亲缘字段，不引入新状态。"""
        a_ids = set(a.member_ids)
        b_ids = set(b.member_ids)
        for member_id in a_ids:
            agent = world.state.human.agents.get(member_id)
            if agent is None:
                continue
            if agent.spouse_id in b_ids:
                return True
            if agent.mother_id in b_ids or agent.father_id in b_ids:
                return True
            if any(child in b_ids for child in agent.children_ids):
                return True
        return False

    @staticmethod
    def _debt_history_sets(world) -> tuple[set[str], set[str]]:
        """从事件流反查「有违约前科」「曾守约」的家庭集合（不新增状态）。"""
        defaulted: set[str] = set()
        repaid: set[str] = set()
        for evt in world.event_log.by_type("debt_defaulted"):
            payload = evt.get("payload") or {}
            hid = payload.get("debtor_household_id") or payload.get("household_id")
            if hid:
                defaulted.add(hid)
        for evt in world.event_log.by_type("debt_repaid"):
            payload = evt.get("payload") or {}
            hid = payload.get("debtor_household_id") or payload.get("household_id")
            if hid:
                repaid.add(hid)
        return defaulted, repaid

    def _recover_health(self, world, agent: AgentState, tuning: AgentTuning) -> None:
        """饥饿低于阈值且体力高于阈值时回血，封顶 100；仅数值实际变化时写 health_recovered。

        饥饿扣血（在 _process_one 中）保留：若本日 hunger 仍高，则不满足回血条件，惩罚不被覆盖。
        """
        h = tuning.health
        if agent.hunger >= h.health_recovery_hunger_threshold:
            return
        if agent.stamina <= h.health_recovery_stamina_threshold:
            return
        before = agent.health
        age = age_years(agent.birth_tick, world.current_tick)
        after = min(self._health_cap(age, tuning), before + h.health_recovery_per_day)
        if after <= before:
            return
        agent.health = after
        world.event_log.append(
            world.current_tick,
            "health_recovered",
            {
                "agent_id": agent.agent_id,
                "agent_name": agent.name,
                "before": round(before, 2),
                "after": round(after, 2),
                "reason": "hunger_and_stamina_ok",
                "hunger": round(agent.hunger, 2),
                "stamina": round(agent.stamina, 2),
            },
        )
