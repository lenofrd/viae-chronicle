"""动作执行：日内动作结算（农事、采集、进食、休息、搬水、建造、婚育）与债务偿还。"""

from __future__ import annotations

import math
from typing import Optional

from vale.config.schema.agents import AgentTuning
from vale.contracts.impacts import EcologicalImpact
from vale.contracts.queries import EnvironmentQuery, SpatialQuery
from vale.contracts.resources import ResourceService
from vale.core.household import home_node_of, household_of, inventory_of, work_node_of
from vale.core.state import AgentState, DebtRecord
from vale.domains.society.agents.demographics import age_years
from vale.domains.society.agents.perception import Perception, select_creditor, select_food_creditor
from vale.domains.society.agents.production import _node_crop_type, _target_node, expected_yield
from vale.domains.society.community import environmental_injury_multiplier, fatigue_efficiency


class ActionMixin:

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
            from vale.domains.society.construction import advance_construction
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
