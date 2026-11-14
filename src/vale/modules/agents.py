"""人物模块：感知隔离 + 效用驱动决策 + 动作执行。

设计约束（system-prompt）：
- 机制/内容分离：所有权重/消耗/阈值来自 world.config.agents（agents.yaml），代码不写死具体数值。
- 事件溯源：agent_action_taken 写入 EventLog（单一真相源），AgentState 是同步维护的快照投影。
- 感知隔离：决策只用 Perception（自身状态 + 天气 + 家到目标的距离），不直接读 WorldState 全貌。
- 模块隔离：单个人物处理异常被捕获、写 agent_error 事件，不影响其他人物与世界。
"""
from __future__ import annotations

import heapq
import traceback
from dataclasses import dataclass, field
from typing import Callable, Optional

from config.schema.agents import AgentConfig, AgentTuning
from config.schema.natural_params import Season, WeatherType
from vale.core.state import AgentState

# 视为降雨的天气（B9：影响户外劳作）
RAIN_WEATHERS = {WeatherType.LIGHT_RAIN, WeatherType.MODERATE_RAIN, WeatherType.HEAVY_RAIN}
# 不可行动作的得分（体力不足 / 无粮等），保证不会被选中
IMPOSSIBLE = float("-inf")

# 候选动作集合（内容外置：动作→目标节点的映射在 _target_node）
CANDIDATE_ACTIONS = ["eat", "rest", "farm", "collect_water", "harvest", "borrow_grain"]


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
    lender_node: str
    # 家 → 各候选目标的单程 TU；打分时往返 = 2 × 单程（C1）
    distance_from_home: dict[str, float] = field(default_factory=dict)


def _lender_node(world, agent: AgentState) -> str:
    """借粮目标：当前存粮最多的其他人的家（ emergently 指向富户，不写死姓名）。"""
    others = [a for a in world.state.agents.values() if a.agent_id != agent.agent_id]
    if not others:
        return agent.home_node
    richest = max(others, key=lambda a: a.grain)
    return richest.home_node


def _target_node(action: str, agent: AgentState, world) -> str:
    """动作 → 目标节点（内容映射）。eat/rest 在家；farm/harvest 在田地；collect_water 在水井；borrow 去债主家。"""
    if action in ("eat", "rest"):
        return agent.home_node
    if action in ("farm", "harvest"):
        return agent.work_node
    if action == "collect_water":
        return "well"
    if action == "borrow_grain":
        return _lender_node(world, agent)
    return agent.home_node


# --------------------------------------------------------------------------- #
# 人物模块
# --------------------------------------------------------------------------- #
class AgentModule:
    name = "agents"
    depends_on = ["climate"]

    def __init__(self) -> None:
        self._spatial: Optional[SpatialIndex] = None

    # -- 生命周期 ----------------------------------------------------------- #
    def step(self, world) -> None:
        cfg = world.config.agents
        if self._spatial is None:
            self._spatial = SpatialIndex(world.config.spatial)
        self._ensure_agents(world, cfg)
        tuning = cfg.tuning
        for agent_cfg in cfg.agents:
            try:
                self._process_one(world, agent_cfg, tuning)
            except Exception as exc:  # noqa: BLE001 — 模块隔离：单个人物失败不拖垮世界
                world.event_log.append(
                    world.current_tick,
                    "agent_error",
                    {
                        "agent_id": agent_cfg.id,
                        "agent_name": agent_cfg.name,
                        "error": repr(exc),
                        "traceback": traceback.format_exc(limit=2),
                    },
                )

    def _ensure_agents(self, world, cfg) -> None:
        if world.state.agents:
            return
        phys = cfg.tuning.physiology
        for a in cfg.agents:
            world.state.agents[a.id] = AgentState(
                agent_id=a.id,
                name=a.name,
                sex=a.sex,
                age=a.age,
                location=a.home_node,
                home_node=a.home_node,
                work_node=a.work_node,
                health=a.initial_health if a.initial_health is not None else phys.initial_health,
                hunger=a.initial_hunger if a.initial_hunger is not None else phys.initial_hunger,
                stamina=a.initial_stamina if a.initial_stamina is not None else phys.initial_stamina,
                fatigue=phys.initial_fatigue,
                grain=a.assets.grain,
            )
        # 初始化所有 FIELD 节点的长势为 0（内容来自 spatial 配置，不写死节点 id）
        if not world.state.field_growth:
            for n in world.config.spatial.nodes:
                if getattr(n.type, "value", n.type) == "field":
                    world.state.field_growth[n.id] = 0.0

    # -- 单个人物的一天 ----------------------------------------------------- #
    def _process_one(self, world, agent_cfg: AgentConfig, tuning: AgentTuning) -> None:
        agent = world.state.agents[agent_cfg.id]
        phys = tuning.physiology

        # 1. 每日自然生理演化（A1 饥饿增长；A4 饥饿过高掉健康）
        agent.hunger = min(100.0, agent.hunger + phys.hunger_gain_per_tick)
        if agent.hunger > phys.hunger_health_damage_threshold:
            agent.health = max(0.0, agent.health - phys.hunger_health_damage)

        # 2. 感知（隔离层）
        perception = self._perceive(world, agent)

        # 3. 效用打分 → 选动作
        action = self._decide(perception, tuning)

        # 4. 执行：更新快照 + 写事件
        self._execute(world, agent, action, perception, tuning)

    def _perceive(self, world, agent: AgentState) -> Perception:
        climate = world.state.climate
        weather = climate.current_weather if climate is not None else WeatherType.SUNNY
        temp = climate.temperature_c if climate is not None else 0.0
        season = climate.season if climate is not None else Season.SPRING
        dist: dict[str, float] = {}
        for act in CANDIDATE_ACTIONS:
            target = _target_node(act, agent, world)
            dist[target] = self._spatial.travel_tu(agent.home_node, target) if self._spatial else 0.0
        return Perception(
            agent=agent,
            weather=weather,
            temperature_c=temp,
            is_raining=weather in RAIN_WEATHERS,
            season=season,
            work_field_growth=world.state.field_growth.get(agent.work_node, 0.0),
            lender_node=_lender_node(world, agent),
            distance_from_home=dist,
        )

    # -- 决策（只依赖 Perception + tuning）--------------------------------- #
    def _decide(self, p: Perception, tuning: AgentTuning) -> str:
        scored = [(self.score_action(act, p, tuning), act) for act in CANDIDATE_ACTIONS]
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
                    if p.agent.grain <= 0
                    else tuning.utility.economy_urgency_grain_positive
                )
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
        if action in ("eat", "rest"):
            target = agent.home_node
        elif action in ("farm", "harvest"):
            target = agent.work_node
        elif action == "collect_water":
            target = "well"
        elif action == "borrow_grain":
            target = p.lender_node
        else:
            target = agent.home_node

        # 可行性前置过滤（不可行 → -inf，不会被选中）
        if action == "eat" and agent.grain <= 0:
            return IMPOSSIBLE
        if action == "borrow_grain" and agent.grain >= bor.borrow_grain_threshold:
            return IMPOSSIBLE
        if action == "harvest" and (
            p.season != Season.AUTUMN or p.work_field_growth < agr.harvest_growth_threshold
        ):
            return IMPOSSIBLE

        one_way = p.distance_from_home.get(target, 0.0)
        round_trip = one_way * 2.0  # C1：每天 move 往返

        move_stamina = round_trip * util.move_stamina_per_tu
        flat_stamina = act.stamina_cost.get(action, 0.0)
        total_stamina_cost = move_stamina + flat_stamina
        if agent.stamina < total_stamina_cost:
            return IMPOSSIBLE  # 体力不足以完成移动+动作

        # 效用 = Σ weight(need) * 紧缺度(need) * fulfill(action, need)
        # [机制修正] 原 (1 + 紧缺度) 会给每个需求留 +1 地板，导致 rest 等即使不紧缺也有正分、
        # 压过一切；改为紧缺度为 0 时贡献为 0（标准效用 AI 形式）。权重/fulfill 已相应重平衡。
        fulfill = act.fulfill.get(action, {})
        gross = 0.0
        for need, w in weights.items():
            if w == 0:
                continue
            gross += w * urgency(need) * fulfill.get(need, 0.0)

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
    ) -> None:
        phys = tuning.physiology
        util = tuning.utility
        act = tuning.action
        agr = tuning.agriculture
        bor = tuning.borrow

        target = _target_node(action, agent, world)
        one_way = p.distance_from_home.get(target, 0.0)
        round_trip = one_way * 2.0

        move_stamina = round_trip * util.move_stamina_per_tu
        flat_stamina = act.stamina_cost.get(action, 0.0)

        hunger_before = agent.hunger
        grain_before = agent.grain
        debt_before = agent.debt
        fg = world.state.field_growth
        field_growth_before = fg.get(agent.work_node, 0.0)

        # 扣体力（移动 + 动作）
        agent.stamina = max(0.0, agent.stamina - move_stamina - flat_stamina)

        # 动作效果
        if action == "eat":
            agent.hunger = max(0.0, agent.hunger - phys.eat_hunger_reduction)
            agent.grain = max(0.0, agent.grain - phys.eat_grain_cost)
        elif action == "rest":
            agent.stamina = min(100.0, agent.stamina + phys.rest_stamina_recovery)
        elif action == "farm":
            # 只提升长势，绝不直接产粮（农业周期：farm → 累积 → harvest）
            fg[agent.work_node] = min(
                agr.max_field_growth, field_growth_before + agr.field_growth_per_farm
            )
        elif action == "harvest":
            # 秋季且长势达标：长势清零，获得存粮，并偿还部分债务
            fg[agent.work_node] = 0.0
            agent.grain = agent.grain + agr.harvest_grain_gain
            agent.debt = max(0.0, agent.debt - agr.harvest_debt_repayment)
        elif action == "borrow_grain":
            # 第一版极简：必借到，存粮 +X，等额计入债务（后续里程碑实现纠纷/利息）
            agent.grain = agent.grain + bor.borrow_grain_amount
            agent.debt = agent.debt + bor.borrow_grain_amount
        # collect_water：本阶段仅消耗体力（饮水资产暂不建模）

        field_growth_after = fg.get(agent.work_node, 0.0)

        # 每天结束回家（C1）
        agent.location = agent.home_node

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
                "action": action,
                "target_node": target,
                "round_trip_tu": round(round_trip, 3),
                "stamina_cost": round(move_stamina + flat_stamina, 3),
                "hunger_before": round(hunger_before, 2),
                "hunger_after": round(agent.hunger, 2),
                "grain_before": round(grain_before, 2),
                "grain_after": round(agent.grain, 2),
                "debt_before": round(debt_before, 2),
                "debt_after": round(agent.debt, 2),
                "field_growth_before": round(field_growth_before, 2),
                "field_growth_after": round(field_growth_after, 2),
                "stamina_after": round(agent.stamina, 2),
                "weather": p.weather.value,
            },
        )
