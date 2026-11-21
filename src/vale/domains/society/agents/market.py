"""集市结算：赶集扣体力、以物易物撮合、集市赊账挂账。"""

from __future__ import annotations

import math
from typing import Optional

from vale.config.schema.agents import AgentTuning
from vale.core.household import living_households
from vale.core.state import AgentState, DebtRecord, HouseholdState
from vale.domains.society.agents.demographics import age_years
from vale.domains.society.agents.production import _floor_to_step, _inventory


class MarketMixin:

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
