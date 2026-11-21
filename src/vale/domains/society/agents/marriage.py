"""婚配：双向认知、从夫居迁移、家庭协商与婚姻资产转移。"""

from __future__ import annotations

import math
from typing import Optional

from vale.config.schema.agents import AgentSex, AgentTuning
from vale.core.household import home_node_of, household_of
from vale.core.state import AgentState, HouseholdState
from vale.domains.society import social
from vale.domains.society.agents.demographics import age_years, living_agents
from vale.domains.society.agents.production import _inventory


class MarriageMixin:

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
