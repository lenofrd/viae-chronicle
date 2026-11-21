"""死亡与继承：死亡结算、遗产分配、户主接任、债权家庭解散与债务核销。"""

from __future__ import annotations

from typing import Optional

from vale.config.schema.agents import AgentTuning
from vale.domains.society.households import household_of
from vale.domains.society.state import AgentState, DebtRecord, HouseholdState
from vale.domains.society.agents.demographics import age_years
from vale.domains.society.agents.production import _inventory


class MortalityMixin:

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
            from vale.domains.society.land import settle_household_land_inheritance
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
        from vale.domains.society.land import settle_household_land_inheritance
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
