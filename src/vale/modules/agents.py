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
from vale.core.state import AgentState, DebtRecord

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
    # 可选债主（存粮 ≥ 借出量的最富其他人）；None 表示无人可借 → borrow 不可行
    creditor_id: Optional[str] = None
    # 家 → 各候选目标的单程 TU；打分时往返 = 2 × 单程（C1）
    distance_from_home: dict[str, float] = field(default_factory=dict)


def select_creditor(
    agents: dict[str, AgentState], debtor_id: str, amount: float
) -> Optional[AgentState]:
    """选存粮 >= amount 的其他人，按存粮降序取最富者（并列按 id 稳定）；无人可借则 None。

    纯函数，可独立单测；被 _perceive（可行性判定）与 _execute（实际扣粮）共用，保证一致。
    """
    candidates = [a for a in agents.values() if a.agent_id != debtor_id and a.grain >= amount]
    if not candidates:
        return None
    return max(candidates, key=lambda a: (a.grain, a.agent_id))


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
        # 每日结算（任务 08）：债务催收 + 健康回血，统一在所有人物动作之后处理跨人粮转移
        self._settle(world, tuning)

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
        bor = world.config.agents.tuning.borrow
        creditor = select_creditor(world.state.agents, agent.agent_id, bor.borrow_grain_amount)
        return Perception(
            agent=agent,
            weather=weather,
            temperature_c=temp,
            is_raining=weather in RAIN_WEATHERS,
            season=season,
            work_field_growth=world.state.field_growth.get(agent.work_node, 0.0),
            lender_node=_lender_node(world, agent),
            creditor_id=creditor.agent_id if creditor else None,
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
        # farm 封顶：长势达上限后不可再选 farm，避免无效劳作与体力消耗（任务 08）
        if action == "farm" and p.work_field_growth >= agr.max_field_growth:
            return IMPOSSIBLE
        # borrow 可行性：存粮 < 阈值（上已判） + 有存粮足够的债主 + 无逾期债务
        if action == "borrow_grain":
            if p.creditor_id is None:
                return IMPOSSIBLE
            if any(d.overdue for d in agent.debts):
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
            # 秋季且长势达标：长势清零，获得存粮；再按债务记录还给对应债主（粮从借粮者到债主）
            fg[agent.work_node] = 0.0
            agent.grain = agent.grain + agr.harvest_grain_gain
            self._repay_debts(
                world, agent, tuning, source="harvest", max_repay=agr.harvest_debt_repayment
            )
        elif action == "borrow_grain":
            # 借粮闭合：从债主扣粮、借粮者加粮、创建债务记录；无债主/不足则不产粮不欠债
            amount = bor.borrow_grain_amount
            creditor = select_creditor(world.state.agents, agent.agent_id, amount)
            if creditor is not None and creditor.grain >= amount:
                creditor_grain_before = creditor.grain
                creditor.grain = creditor.grain - amount
                agent.grain = agent.grain + amount
                due_tick = world.current_tick + tuning.debt.due_days
                agent.debts.append(
                    DebtRecord(
                        creditor_id=creditor.agent_id,
                        amount=amount,
                        originated_tick=world.current_tick,
                        due_tick=due_tick,
                    )
                )
                world.event_log.append(
                    world.current_tick,
                    "debt_formed",
                    {
                        "creditor_id": creditor.agent_id,
                        "creditor_name": creditor.name,
                        "debtor_id": agent.agent_id,
                        "debtor_name": agent.name,
                        "debt_type": "grain",
                        "amount": round(amount, 2),
                        "due_tick": due_tick,
                        "originated_tick": world.current_tick,
                        "debtor_grain_before": round(grain_before, 2),
                        "debtor_grain_after": round(agent.grain, 2),
                        "creditor_grain_before": round(creditor_grain_before, 2),
                        "creditor_grain_after": round(creditor.grain, 2),
                        "debt_before": round(debt_before, 2),
                        "debt_after": round(agent.debt, 2),
                    },
                )
            # 若 creditor 为 None 或存粮不足（理论上 _score 已过滤），不产粮不欠债，仅消耗往返体力
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

    # -- 债务还款（秋收 / 通用）-------------------------------------------- #
    def _repay_debts(
        self, world, agent: AgentState, tuning: AgentTuning, *, source: str, max_repay: float
    ) -> None:
        """按最早到期优先，从 agent 扣粮还给各债主，最多 max_repay 石；逐笔写 debt_repaid 事件。

        粮守恒：借粮者扣的每石都加到对应债主，绝不凭空消债。不得扣成负粮。
        """
        if max_repay <= 0 or not agent.debts:
            return
        ordered = sorted(agent.debts, key=lambda d: (d.due_tick, d.originated_tick))
        budget = max_repay
        for rec in ordered:
            if budget <= 0:
                break
            pay = min(rec.amount, budget, agent.grain)  # 不得扣成负粮
            if pay <= 0:
                continue
            creditor = world.state.agents.get(rec.creditor_id)
            if creditor is None:
                continue
            agent.grain = agent.grain - pay
            creditor.grain = creditor.grain + pay
            rec.amount = rec.amount - pay
            budget = budget - pay
            world.event_log.append(
                world.current_tick,
                "debt_repaid",
                {
                    "creditor_id": creditor.agent_id,
                    "creditor_name": creditor.name,
                    "debtor_id": agent.agent_id,
                    "debtor_name": agent.name,
                    "amount": round(pay, 2),
                    "remaining": round(rec.amount, 2),
                    "source": source,
                    "debtor_grain_after": round(agent.grain, 2),
                    "creditor_grain_after": round(creditor.grain, 2),
                },
            )
        # 清偿完毕（amount==0）的记录移出列表，保持债务列表干净
        agent.debts = [d for d in agent.debts if d.amount > 0]

    # -- 每日结算：债务催收 + 健康回血 ------------------------------------- #
    def _settle(self, world, tuning: AgentTuning) -> None:
        """tick 末尾统一结算。逐人错误隔离：单人结算失败写 agent_error，不拖垮世界。"""
        for agent in list(world.state.agents.values()):
            try:
                self._collect_debts(world, agent, tuning)
                self._recover_health(world, agent, tuning)
            except Exception as exc:  # noqa: BLE001 — 单人结算失败不拖垮世界
                world.event_log.append(
                    world.current_tick,
                    "agent_error",
                    {
                        "agent_id": agent.agent_id,
                        "agent_name": agent.name,
                        "phase": "daily_settlement",
                        "error": repr(exc),
                        "traceback": traceback.format_exc(limit=2),
                    },
                )

    def _collect_debts(self, world, agent: AgentState, tuning: AgentTuning) -> None:
        """到期债务催收：足额/部分转粮给债主写 debt_collected；无粮可还则违约写 debt_defaulted。

        到期后每 collection_interval_days 天催收一次（last_collected_tick 节流）。
        部分还款后剩余标 overdue；逾期者后续借粮被 _score 禁止。
        """
        tick = world.current_tick
        interval = tuning.debt.collection_interval_days
        for rec in list(agent.debts):  # 遍历副本，避免边迭代边修改
            if tick < rec.due_tick:
                continue
            last = rec.last_collected_tick
            if last is not None and tick - last < interval:
                continue
            rec.last_collected_tick = tick
            creditor = world.state.agents.get(rec.creditor_id)
            if creditor is None:
                continue
            pay = min(rec.amount, agent.grain)
            if pay > 0:
                agent.grain = agent.grain - pay
                creditor.grain = creditor.grain + pay
                rec.amount = rec.amount - pay
                rec.overdue = rec.amount > 0
                world.event_log.append(
                    tick,
                    "debt_collected",
                    {
                        "creditor_id": creditor.agent_id,
                        "creditor_name": creditor.name,
                        "debtor_id": agent.agent_id,
                        "debtor_name": agent.name,
                        "amount_paid": round(pay, 2),
                        "remaining": round(rec.amount, 2),
                        "overdue": rec.overdue,
                        "debtor_grain_after": round(agent.grain, 2),
                        "creditor_grain_after": round(creditor.grain, 2),
                    },
                )
            else:
                rec.overdue = True
                world.event_log.append(
                    tick,
                    "debt_defaulted",
                    {
                        "creditor_id": creditor.agent_id,
                        "creditor_name": creditor.name,
                        "debtor_id": agent.agent_id,
                        "debtor_name": agent.name,
                        "amount": round(rec.amount, 2),
                        "overdue_ticks": tick - rec.due_tick,
                    },
                )
        agent.debts = [d for d in agent.debts if d.amount > 0]

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
        after = min(100.0, before + h.health_recovery_per_day)
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
