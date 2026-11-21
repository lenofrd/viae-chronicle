"""生命周期：开局播种、衰老与健康上限、自然死亡、依赖者进食、日内推进与恢复。"""

from __future__ import annotations

from typing import Optional

from vale.config.schema.agents import AgentTuning
from vale.config.schema.natural_params import Season
from vale.contracts.impacts import EcologicalImpact
from vale.contracts.queries import EnvironmentQuery
from vale.core.calendar import DAYS_PER_YEAR
from vale.core.household import home_node_of, household_of
from vale.core.state import AgentState, HouseholdState
from vale.domains.society.agents.constants import _candidate_actions
from vale.domains.society.agents.demographics import age_years, living_agents


class LifecycleMixin:

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
        from vale.domains.society.land import initialize_land
        initialize_land(world)

    def _health_cap(self, age: int, tuning: AgentTuning) -> float:
        """健康上限 = 分段乘数 × 100 − 老年衰减，下限 min_health_cap（D3）。"""
        ag = tuning.aging
        base = 100.0 * ag.stage_for(age).health_max_mult
        decline = ag.health_cap_decline_per_year * max(0, age - ag.health_cap_decline_start_age)
        return max(ag.min_health_cap, base - decline)

    def _stamina_cap(self, agent: AgentState, tuning: AgentTuning) -> float:
        stage = tuning.aging.stage_by_name(agent.life_stage) or tuning.aging.stage_for(0)
        return 100.0 * stage.stamina_max_mult

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
