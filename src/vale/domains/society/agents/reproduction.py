"""分家与生育：分家建户、生育可行性、新生儿命名与登记。"""

from __future__ import annotations

from typing import Optional

from vale.config.schema.agents import AgentSex, AgentTuning
from vale.core.household import household_members, household_of, living_households, work_node_of
from vale.core.state import AgentState, DebtRecord, HouseholdState
from vale.domains.society.agents.demographics import age_years, living_agents
from vale.domains.society.agents.production import _inventory


class ReproductionMixin:

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
