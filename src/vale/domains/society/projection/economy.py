"""经济投影：借贷、交易、仓储、社区储备、债务与纠纷。

SocietyProjection 的组成部分；统一注册入口见 ``__init__``。
"""
from __future__ import annotations

from vale.domains.society.social import record_memory
from vale.domains.society.state import DebtRecord

from .base import SocietyProjectionBase


class EconomyProjection(SocietyProjectionBase):
    def _on_resource_loan_created(self, payload: dict, tick: int) -> None:
        loan = payload.get("loan")
        if loan:
            self.state.human.resource_loans[loan["loan_id"]] = dict(loan)
        self._apply_household_inventories(payload.get("inventories_after") or {})

    def _on_resource_loan_overdue(self, payload: dict, tick: int) -> None:
        loan = self.state.human.resource_loans.get(payload.get("loan_id", ""))
        if loan:
            loan.update(payload.get("loan_after") or {})

    def _on_resource_loan_repaid(self, payload: dict, tick: int) -> None:
        loan = self.state.human.resource_loans.get(payload.get("loan_id", ""))
        if loan:
            loan.update(payload.get("loan_after") or {})
        self._apply_household_inventories(payload.get("inventories_after") or {})

    def _on_household_trade_settled(self, payload: dict, tick: int) -> None:
        self._apply_household_inventories(payload.get("inventories_after") or {})

    def _on_shared_storage_deposit(self, payload: dict, tick: int) -> None:
        building = self.state.human.buildings.get(payload.get("building_id", ""))
        if building is not None:
            building.stored_inventory = dict(payload.get("stored_inventory_after") or {})
            building.depositor_balances = dict(payload.get("depositor_balances_after") or {})
        self._apply_household_inventories({payload.get("household_id"): payload.get("household_inventory_after") or {}})

    def _on_shared_storage_withdrawal(self, payload: dict, tick: int) -> None:
        building = self.state.human.buildings.get(payload.get("building_id", ""))
        if building is not None:
            building.stored_inventory = dict(payload.get("stored_inventory_after") or {})
            building.depositor_balances = dict(payload.get("depositor_balances_after") or {})
        self._apply_household_inventories({payload.get("household_id"): payload.get("household_inventory_after") or {}})

    def _on_service_request_queued(self, payload: dict, tick: int) -> None:
        key = payload.get("queue_key")
        if key:
            self.state.human.service_queues[key] = dict(payload.get("queue_after") or {})

    def _on_service_queue_processed(self, payload: dict, tick: int) -> None:
        key = payload.get("queue_key")
        if key:
            self.state.human.service_queues[key] = dict(payload.get("queue_after") or {})

    def _apply_community_reserve_transfer(self, payload: dict, *, deposited: bool) -> None:
        household = self.state.human.households.get(payload.get("household_id", ""))
        resources = payload.get("resources") or {}
        if household is None:
            return
        sign = -1.0 if deposited else 1.0
        for item, amount in resources.items():
            amount = max(0.0, float(amount))
            field_name = "water" if item == "water" else item
            if hasattr(household, field_name):
                setattr(household, field_name, max(
                    0.0, round(float(getattr(household, field_name)) + sign * amount, 2)
                ))
        for item, value in (payload.get("reserve_after") or {}).items():
            self.state.human.community_reserves[item] = max(0.0, float(value))

    def _on_community_reserve_voluntarily_deposited(self, payload: dict, tick: int) -> None:
        household = self.state.human.households.get(payload.get("household_id", ""))
        if household is not None:
            for item, value in (payload.get("household_inventory_after") or {}).items():
                if hasattr(household, item):
                    setattr(household, item, max(0.0, float(value)))
        for item, value in (payload.get("reserve_after") or {}).items():
            self.state.human.community_reserves[item] = max(0.0, float(value))

    def _on_community_relief_issued(self, payload: dict, tick: int) -> None:
        household = self.state.human.households.get(payload.get("household_id", ""))
        if household is not None:
            for item, value in (payload.get("household_inventory_after") or {}).items():
                if hasattr(household, item):
                    setattr(household, item, max(0.0, float(value)))
        for item, value in (payload.get("reserve_after") or {}).items():
            self.state.human.community_reserves[item] = max(0.0, float(value))

    def _on_community_reserve_deposited(self, payload: dict, tick: int) -> None:
        self._apply_community_reserve_transfer(payload, deposited=True)

    def _on_community_reserve_withdrawn(self, payload: dict, tick: int) -> None:
        self._apply_community_reserve_transfer(payload, deposited=False)

    def _on_debt_formed(self, payload: dict, tick: int) -> None:
        debtor_id = payload.get("debtor_id")
        creditor_id = payload.get("creditor_id")
        if not debtor_id or not creditor_id:
            return
        debtor_hh = self._hh_for(debtor_id, payload)
        creditor_hh = self._hh_for(creditor_id, payload)
        creditor_hh_id = payload.get("creditor_household_id") or creditor_hh.household_id
        resource = payload.get("resource") or payload.get("debt_type") or "grain"
        debtor_hh.debts.append(
            DebtRecord(
                debtor_household_id=debtor_hh.household_id,
                creditor_household_id=creditor_hh_id,
                amount=max(0.0, round(float(payload.get("amount", 0.0)), 2)),
                originated_tick=int(payload.get("originated_tick", tick)),
                due_tick=int(payload.get("due_tick", tick)),
                origin=payload.get("origin"),
                resource=resource,
            )
        )
        for side, agent_key in (("debtor", "debtor_id"), ("creditor", "creditor_id")):
            key = f"{side}_{resource}_after"
            if key in payload and payload[key] is not None and payload.get(agent_key):
                hh = self._hh_for(payload[agent_key], payload)
                setattr(hh, resource, max(0.0, round(float(payload[key]), 2)))

    def _on_debt_repaid(self, payload: dict, tick: int) -> None:
        debtor_id = payload.get("debtor_id")
        creditor_id = payload.get("creditor_id")
        if not debtor_id or not creditor_id:
            return
        debtor_hh = self._hh_for(debtor_id, payload)
        creditor_hh = self._hh_for(creditor_id, payload)
        creditor_hh_id = payload.get("creditor_household_id") or creditor_hh.household_id
        resource = payload.get("resource") or payload.get("debt_type") or "grain"
        self._reduce_debt(debtor_hh, creditor_hh_id, float(payload.get("amount", 0.0)), resource)
        for side, agent_key in (("debtor", "debtor_id"), ("creditor", "creditor_id")):
            key = f"{side}_{resource}_after"
            if key in payload and payload[key] is not None:
                hh = self._hh_for(payload[agent_key], payload)
                setattr(hh, resource, max(0.0, round(float(payload[key]), 2)))

    def _on_debt_collected(self, payload: dict, tick: int) -> None:
        debtor_id = payload.get("debtor_id")
        creditor_id = payload.get("creditor_id")
        if not debtor_id or not creditor_id:
            return
        debtor_hh = self._hh_for(debtor_id, payload)
        creditor_hh = self._hh_for(creditor_id, payload)
        creditor_hh_id = payload.get("creditor_household_id") or creditor_hh.household_id
        resource = payload.get("resource", "grain")
        self._reduce_debt(debtor_hh, creditor_hh_id, float(payload.get("amount_paid", 0.0)), resource)
        for side, agent_key in (("debtor", "debtor_id"), ("creditor", "creditor_id")):
            key = f"{side}_{resource}_after"
            if key in payload and payload[key] is not None:
                hh = self._hh_for(payload[agent_key], payload)
                setattr(hh, resource, max(0.0, round(float(payload[key]), 2)))

    def _on_debt_defaulted(self, payload: dict, tick: int) -> None:
        debtor_id = payload.get("debtor_id")
        creditor_id = payload.get("creditor_id")
        if not debtor_id:
            return
        debtor_hh = self._hh_for(debtor_id, payload)
        creditor_hh_id = None
        if creditor_id:
            creditor_hh_id = (
                payload.get("creditor_household_id")
                or self._hh_for(creditor_id, payload).household_id
            )
        for rec in debtor_hh.debts:
            if creditor_hh_id is None or rec.creditor_household_id == creditor_hh_id:
                rec.overdue = True

    def _on_debt_collection_attempt(self, payload: dict, tick: int) -> None:
        return

    def _on_debt_forgiven(self, payload: dict, tick: int) -> None:
        debtor_id = payload.get("debtor_id")
        creditor_id = payload.get("creditor_id")
        if not debtor_id or not creditor_id:
            return
        debtor_hh = self._hh_for(debtor_id, payload)
        creditor_hh_id = (
            payload.get("creditor_household_id")
            or self._hh_for(creditor_id, payload).household_id
        )
        self._reduce_debt(debtor_hh, creditor_hh_id, float(payload.get("amount", 0.0)), payload.get("resource", "grain"))

    def _on_debt_transferred(self, payload: dict, tick: int) -> None:
        from_id = payload.get("from_id")
        to_id = payload.get("to_id")
        creditor_id = payload.get("creditor_id")
        amount = float(payload.get("amount", 0.0))
        if not from_id or not to_id or not creditor_id:
            return
        from_hh = self._hh_for(from_id, payload)
        to_hh = self._hh_for(to_id, payload)
        creditor_hh_id = (
            payload.get("creditor_household_id")
            or self._hh_for(creditor_id, payload).household_id
        )
        debtor_household_id = payload.get("debtor_household_id")
        if debtor_household_id:
            # 债权侧转移（Q5）：债务方不变，债权方从死者家庭改挂继承人家庭。
            # 旧库无该键时走下方债务侧逻辑，保持既有重放行为。
            debtor_hh = self.state.human.households.get(debtor_household_id)
            if debtor_hh is None:
                return
            self._reduce_debt(debtor_hh, from_hh.household_id, amount, payload.get("resource", "grain"))
            debtor_hh.debts.append(
                DebtRecord(
                    debtor_household_id=debtor_hh.household_id,
                    creditor_household_id=creditor_hh_id,
                    amount=round(amount, 2),
                    originated_tick=int(payload.get("originated_tick", tick)),
                    due_tick=int(payload.get("due_tick", tick)),
                    resource=payload.get("resource", "grain"),
                )
            )
            return
        self._reduce_debt(from_hh, creditor_hh_id, amount, payload.get("resource", "grain"))
        to_hh.debts.append(
            DebtRecord(
                debtor_household_id=to_hh.household_id,
                creditor_household_id=creditor_hh_id,
                amount=round(amount, 2),
                originated_tick=int(payload.get("originated_tick", tick)),
                due_tick=int(payload.get("due_tick", tick)),
                resource=payload.get("resource", "grain"),
            )
        )

    def _on_debt_written_off(self, payload: dict, tick: int) -> None:
        debtor_id = payload.get("debtor_id")
        creditor_household_id = payload.get("creditor_household_id")
        if not debtor_id:
            return
        debtor_hh = self._hh_for(debtor_id, payload)
        if creditor_household_id is None and payload.get("creditor_id"):
            creditor_household_id = self._hh_for(
                payload["creditor_id"], payload
            ).household_id
        if creditor_household_id is None:
            return
        self._reduce_debt(debtor_hh, creditor_household_id, float(payload.get("amount", 0.0)), payload.get("resource", "grain"))

    def _on_debt_deferred(self, payload: dict, tick: int) -> None:
        debtor_hh = self.state.human.households.get(payload.get("debtor_household_id") or "")
        creditor_hh_id = payload.get("creditor_household_id")
        if debtor_hh is None or not creditor_hh_id:
            return
        rec = self._find_record(debtor_hh, creditor_hh_id, payload.get("resource"))
        if rec is None:
            return
        rec.due_tick = int(payload.get("new_due_tick", tick))
        rec.overdue = False
        rec.dispute_started_tick = None  # 延期后进入下一周期

    def _on_conflict_started(self, payload: dict, tick: int) -> None:
        """标记该笔赊账已发起过催收会话，保证回放后不重复触发（金额不变）。"""
        debtor_hh = self.state.human.households.get(payload.get("debtor_household_id") or "")
        creditor_hh_id = payload.get("creditor_household_id")
        if debtor_hh is None or not creditor_hh_id:
            return
        rec = self._find_record(debtor_hh, creditor_hh_id)
        if rec is not None:
            rec.dispute_started_tick = tick

    def _on_conflict_negotiation_round(self, payload: dict, tick: int) -> None:
        return  # 纯叙事事件，不改状态

    def _on_conflict_resolved(self, payload: dict, tick: int) -> None:
        # 金额/期限变更已由 debt_repaid / debt_deferred 重建；
        # 任务16 阶段二：以 resolution 重建双方短期记忆（裁决 §3.4 纯事件投影）。
        self._replay_remember_dispute(payload, tick, payload.get("resolution"))

    def _on_conflict_broken(self, payload: dict, tick: int) -> None:
        # dispute_started_tick 已由 conflict_started 标记；
        # 任务16 阶段二：破裂结果同样重建双方短期记忆。
        self._replay_remember_dispute(payload, tick, "broken")

    def _replay_remember_dispute(self, payload: dict, tick: int, outcome) -> None:
        """按运行时 _remember_dispute 同口径重建记忆（户→户主映射，裁决 §3.4）。

        运行时在会话当场用 head 写入；回放态在处理到该事件时 household.head_id
        已由更早事件重建，两者解析结果一致（户主只经死亡/继承事件变更）。
        """
        if not outcome:
            return
        debtor_hh = self.state.human.households.get(payload.get("debtor_household_id") or "")
        creditor_hh = self.state.human.households.get(payload.get("creditor_household_id") or "")
        if debtor_hh is None or creditor_hh is None:
            return
        cap = self.config.agents.tuning.social.memory_capacity
        debtor_id = debtor_hh.head_id or debtor_hh.household_id
        creditor_id = creditor_hh.head_id or creditor_hh.household_id
        for observer_id, target_id in (
            (creditor_id, debtor_id), (debtor_id, creditor_id),
        ):
            observer = self.state.human.agents.get(observer_id)
            if observer is not None:
                record_memory(observer, target_id, "debt_dispute", outcome, tick, cap)
