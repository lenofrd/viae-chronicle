"""决策层：TU 预算、感知快照、效用打分与动作选择。"""

from __future__ import annotations

import math
from typing import Callable, Optional

from vale.config.schema.agents import AgentSex, AgentTuning
from vale.config.schema.natural_params import Season
from vale.contracts.queries import EnvironmentQuery, SpatialQuery
from vale.core.calendar import DAYS_PER_YEAR
from vale.core.household import home_node_of, household_of, work_node_of
from vale.core.state import AgentState
from vale.domains.society.agents.constants import IMPOSSIBLE, RAIN_WEATHERS
from vale.domains.society.agents.demographics import age_years
from vale.domains.society.agents.perception import Perception, _lender_node, select_creditor, select_food_creditor
from vale.domains.society.agents.production import _target_node
from vale.domains.society.agents.spatial import SpatialIndex
from vale.domains.society.community import fatigue_efficiency, production_efficiency_at_node, service_capacity_available


class DecisionMixin:

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
