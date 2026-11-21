"""债务催收与纠纷：债务豁免、强制催收、两轮私下催收与纠纷记忆。"""

from __future__ import annotations

from vale.config.schema.agents import AgentTuning
from vale.domains.society.households import household_of, living_households
from vale.domains.society.state import AgentState, DebtRecord, HouseholdState
from vale.domains.society import social


class DebtMixin:

    def _forgive_debts(self, world, household: HouseholdState, *, cause: str) -> None:
        """核销家庭全部剩余债务：逐笔写 debt_forgiven（可追溯，不静默消失），再清空列表。

        守恒说明：这是账面坏账核销（家庭无粮可还，债权家庭承担损失），不涉及粮的凭空产生或消灭；
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
                "debt_forgiven",
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
                    "cause": cause,
                },
            )
        household.debts = []

    @staticmethod
    def _household_foodless(household: HouseholdState) -> bool:
        """全家无任何可食物资（含债务标的物），用于断粮坏账核销判定。"""
        return (
            household.grain <= 0
            and household.fish <= 0
            and household.meat <= 0
            and household.vegetable <= 0
        )

    def _forgive_one_debt(self, world, household: HouseholdState, rec, *, cause: str) -> None:
        """核销单笔债务：写 debt_forgiven（可追溯，不静默消失），从列表移除。

        守恒说明与 _forgive_debts 相同：账面坏账核销，债权家庭承担损失，
        世界总粮不变，世界总债减少并由事件完整记录。
        """
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
            "debt_forgiven",
            {
                "creditor_id": creditor_agent_id,
                "creditor_name": creditor_name,
                "creditor_household_id": rec.creditor_household_id,
                "debtor_id": (household.head_id or household.household_id),
                "debtor_name": debtor_name,
                "debtor_household_id": household.household_id,
                "household_id": household.household_id,
                "amount": round(rec.amount, 2),
                "resource": getattr(rec, "resource", "grain") or "grain",
                "cause": cause,
            },
        )
        if rec in household.debts:
            household.debts.remove(rec)

    def _collect_debts(self, world, agent: AgentState, tuning: AgentTuning) -> None:
        """到期债务催收，区分「违约状态变更」与「催收尝试」（任务10，降低叙事噪声）。

        - 到期后每 collection_interval_days 天催收一次（last_collected_tick 节流）。
        - **违约状态变更**（debt_defaulted）：一笔债务首次到期且无力全额偿还时，由未逾期变为
          逾期，只写一次；此后该笔不再重复写 debt_defaulted。
        - **催收尝试**（debt_collection_attempt）：已是逾期的债务后续每次零粮催收，写该事件
          （可重复，但语义明确为「催收失败」而非「新增违约」），人生档案可按类型过滤刷屏。
        - 有粮则扣粮还债权家庭写 debt_collected；足额清偿 overdue 清零，部分还款剩余仍 overdue。
          逾期家庭后续借粮被 _score 禁止。
        """
        tick = world.current_tick
        interval = tuning.debt.collection_interval_days
        household = household_of(world, agent)
        for rec in list(household.debts):  # 遍历副本，避免边迭代边修改
            if tick < rec.due_tick:
                continue
            last = rec.last_collected_tick
            if last is not None and tick - last < interval:
                continue
            rec.last_collected_tick = tick
            creditor_hh = world.state.human.households.get(rec.creditor_household_id)
            if creditor_hh is None:
                continue
            creditor_head = world.state.human.agents.get(creditor_hh.head_id or "")
            creditor_agent_id = (
                creditor_head.agent_id if creditor_head is not None else creditor_hh.household_id
            )
            creditor_name = (
                creditor_head.name if creditor_head is not None else creditor_hh.household_id
            )
            resource = getattr(rec, "resource", "grain") or "grain"
            debtor_stock = float(getattr(household, resource, 0.0))
            pay = min(rec.amount, debtor_stock)
            first_due = not rec.overdue  # 本次是否为该笔首次到期催收
            if pay > 0:
                creditor_stock = float(getattr(creditor_hh, resource, 0.0))
                setattr(household, resource, round(debtor_stock - pay, 2))
                setattr(creditor_hh, resource, round(creditor_stock + pay, 2))
                rec.amount = round(rec.amount - pay, 2)
                rec.overdue = rec.amount > 0
                world.event_log.append(
                    tick,
                    "debt_collected",
                    {
                        "creditor_id": creditor_agent_id,
                        "creditor_name": creditor_name,
                        "creditor_household_id": creditor_hh.household_id,
                        "debtor_id": agent.agent_id,
                        "debtor_name": agent.name,
                        "debtor_household_id": household.household_id,
                        "household_id": household.household_id,
                        "amount_paid": round(pay, 2),
                        "remaining": round(rec.amount, 2),
                        "overdue": rec.overdue,
                        "originated_tick": rec.originated_tick,
                        "resource": resource,
                        f"debtor_{resource}_after": round(getattr(household, resource), 2),
                        f"creditor_{resource}_after": round(getattr(creditor_hh, resource), 2),
                        "debtor_grain_after": round(household.grain, 2),
                        "creditor_grain_after": round(creditor_hh.grain, 2),
                    },
                )
            elif first_due:
                # 首次到期零粮：违约状态变更（只写一次）
                rec.overdue = True
                world.event_log.append(
                    tick,
                    "debt_defaulted",
                    {
                        "creditor_id": creditor_agent_id,
                        "creditor_name": creditor_name,
                        "creditor_household_id": creditor_hh.household_id,
                        "debtor_id": agent.agent_id,
                        "debtor_name": agent.name,
                        "debtor_household_id": household.household_id,
                        "household_id": household.household_id,
                        "amount": round(rec.amount, 2),
                        "overdue_ticks": tick - rec.due_tick,
                    },
                )
                if tuning.debt.write_off_unpayable and self._household_foodless(household):
                    # 断粮户坏账核销：逾期标记会永久锁死借粮/借食/赊账救济渠道，
                    # 家庭无粮可还时当场核销该笔（debt_forgiven 可追溯），有粮户不受影响
                    self._forgive_one_debt(world, household, rec, cause="断粮坏账核销")
            else:
                # 已逾期的重复催收失败：写催收尝试（可重复，语义明确），不刷违约
                world.event_log.append(
                    tick,
                    "debt_collection_attempt",
                    {
                        "creditor_id": creditor_agent_id,
                        "creditor_name": creditor_name,
                        "creditor_household_id": creditor_hh.household_id,
                        "debtor_id": agent.agent_id,
                        "debtor_name": agent.name,
                        "debtor_household_id": household.household_id,
                        "household_id": household.household_id,
                        "amount": round(rec.amount, 2),
                        "overdue_ticks": tick - rec.due_tick,
                        "interval_days": interval,
                    },
                )
        household.debts = [d for d in household.debts if d.amount > 0]

    def _settle_debt_disputes(self, world, tuning: AgentTuning) -> int:
        """赊账逾期 ≥ trigger_overdue_days 且「有粮但不还」时，债权家庭发起一次私下催收。

        触发窗口：``refusal_threshold < 债务家庭存粮 ≤ trigger_max_grain``。断粮
        （≤ refusal_threshold）不进会话，走既有 debt_defaulted / debt_collection_attempt
        强制扣粮路径；存粮高于上限说明有能力偿还，不需要私下催收。

        收窄实现（裁决 §3.2）：只有 ``origin="market_credit"`` 的债务参与；每笔债务最多
        发起一次会话（``dispute_started_tick`` 标记；延期后清零，进入下一周期）；拒绝后
        不再重复发起，后续仍走既有 debt_defaulted / debt_collection_attempt。
        仅用已有事实：家庭库存、逾期天数、事件流中的 debt_defaulted / debt_repaid、亲缘关系。
        返回发起的会话数。
        """
        cfg = tuning.conflict.debt_dispute
        tick = world.current_tick
        living_ids = {h.household_id for h in living_households(world)}
        candidates: list[tuple[HouseholdState, DebtRecord]] = []
        for household in sorted(world.state.human.households.values(), key=lambda h: h.household_id):
            if household.household_id not in living_ids:
                continue
            for rec in household.debts:
                if rec.origin != "market_credit" or rec.amount <= 0:
                    continue
                if rec.dispute_started_tick is not None:
                    continue
                if tick - rec.due_tick < cfg.trigger_overdue_days:
                    continue
                resource = getattr(rec, "resource", "grain") or "grain"
                resource_stock = float(getattr(household, resource, 0.0))
                if resource_stock <= cfg.refusal_threshold:
                    continue  # 该物资断库存：不走会话，交给既有催收路径
                if resource_stock > cfg.trigger_max_grain:
                    continue  # 有足额该物资：有能力偿还，无需私下催收
                if rec.creditor_household_id not in living_ids:
                    continue
                candidates.append((household, rec))
        if not candidates:
            return 0

        defaulted, repaid = self._debt_history_sets(world)
        count = 0
        for index, (debtor_hh, rec) in enumerate(candidates):
            creditor_hh = world.state.human.households.get(rec.creditor_household_id)
            if creditor_hh is None:
                continue
            self._negotiate_debt(
                world, tuning, debtor_hh, creditor_hh, rec,
                defaulted=defaulted, repaid=repaid, index=index,
            )
            count += 1
        # 清偿完毕的记录移出列表
        for household, _rec in candidates:
            household.debts = [d for d in household.debts if d.amount > 0]
        return count

    def _negotiate_debt(
        self,
        world,
        tuning: AgentTuning,
        debtor_hh: HouseholdState,
        creditor_hh: HouseholdState,
        rec: DebtRecord,
        *,
        defaulted: set[str],
        repaid: set[str],
        index: int = 0,
    ) -> dict:
        """执行固定 2 轮私下催收，返回结果摘要（便于测试与日志）。

        第 1 轮：债权人提诉求（全额 / 部分 / 延期）——由既有事实决定：
          亲缘 → 延期；有违约前科 → 全额；否则 → 部分。
          P2 开关（impression_in_decision）打开且印象档位为 defaulting 时按全额处理；
          开关默认关闭，关闭时读不到印象、行为与 P1 完全一致。
          任务16 阶段二：社会记忆调节（只读 get_social_view，裁决 §3.5）——
          上次破裂 → 部分升全额；上次守约 → 部分放宽为延期；不动 kin/前科优先级。
        第 2 轮：债务人回应（还款 / 请求延期 / 拒绝）——由库存与 refusal_threshold 决定；
          请求延期时，债权人按「亲缘或曾守约」接受，否则坚持 → 破裂。
        四种结果：repaid / partial_repaid / deferred / broken；两轮后必结束，不悬置。
        结果写回双方短期记忆并互升 KNOWN（裁决 §3.3 交互即互升，阶段二简化点）。
        """
        cfg = tuning.conflict.debt_dispute
        tick = world.current_tick
        resource = getattr(rec, "resource", "grain") or "grain"
        debtor_id = debtor_hh.head_id or debtor_hh.household_id
        creditor_id = creditor_hh.head_id or creditor_hh.household_id
        debtor_name = self._head_name(world, debtor_hh)
        creditor_name = self._head_name(world, creditor_hh)
        conflict_id = (
            f"cf-{tick}-{debtor_hh.household_id}-{creditor_hh.household_id}-{index}"
        )
        kin = self._households_are_kin(world, debtor_hh, creditor_hh)
        prior_default = debtor_hh.household_id in defaulted
        prior_honored = debtor_hh.household_id in repaid

        # 第 1 轮：债权人诉求
        # 任务25 P2：印象参与决策（独立开关、默认关闭）。关闭时不读印象，行为与 P1 完全一致。
        impression_defaulting = False
        if tuning.social.impression_in_decision:
            impression = social.get_impression(world.state, creditor_id, debtor_id)
            impression_defaulting = (
                impression is not None and impression.label == social.IMPRESSION_DEFAULTING
            )
        if kin:
            proposal = "deferral"
        elif prior_default or impression_defaulting:
            proposal = "full"
        else:
            proposal = "partial"
        # 任务17 裁决 4.1：诉求成因只读元数据（供渲染追溯"为何开这个口"），不改决策。
        proposal_basis = "kin" if kin else ("prior_default" if prior_default else "plain")
        # 任务16 阶段二：债权人短期记忆调节诉求（防"只记不读"的接入点）。
        # 只读不写事件（裁决 §3.5）；记忆 outcome 与结果写回口径一致。
        view = social.get_social_view(
            world.state, creditor_id, debtor_id, tick, tuning.social.acquaintance_ttl,
        )
        last_outcome = social.last_memory_outcome(view["memories"])
        social_adjustment = None
        if proposal == "partial":
            if last_outcome == "broken":
                proposal = "full"       # 上次破裂：部分诉求升全额
                social_adjustment = "prior_broken→full"
            elif last_outcome in ("repaid", "partial_repaid"):
                proposal = "deferral"   # 上次守约：部分诉求放宽为延期
                social_adjustment = "prior_repaid→deferral"
        if proposal == "full":
            proposed_amount = round(rec.amount, 2)
        elif proposal == "partial":
            proposed_amount = round(rec.amount * cfg.partial_ratio, 2)
        else:
            proposed_amount = 0.0

        world.event_log.append(
            tick,
            "conflict_started",
            {
                "conflict_id": conflict_id,
                "conflict_type": "debt-disputes",
                "creditor_id": creditor_id,
                "creditor_name": creditor_name,
                "creditor_household_id": creditor_hh.household_id,
                "debtor_id": debtor_id,
                "debtor_name": debtor_name,
                "debtor_household_id": debtor_hh.household_id,
                "household_id": debtor_hh.household_id,
                "trigger_event": "market_credit_overdue",
                "amount": round(rec.amount, 2),
                "resource": resource,
                "overdue_ticks": tick - rec.due_tick,
            },
        )

        # 第 2 轮：债务人回应（只依赖库存与既有事实，不引入 trust/grudge 新状态）
        if proposal == "deferral":
            response = "accept_deferral"
        elif float(getattr(debtor_hh, resource, 0.0)) >= proposed_amount > 0:
            response = "repay"
        elif float(getattr(debtor_hh, resource, 0.0)) <= cfg.refusal_threshold:
            response = "refuse"
        else:
            response = "request_deferral"

        for (
            round_no, actor, actor_name, proposal_key, amount_key,
            responder, responder_name, response_key,
        ) in (
            (1, creditor_id, creditor_name, proposal, proposed_amount,
             debtor_id, debtor_name, None),
            (2, debtor_id, debtor_name, None, None,
             creditor_id, creditor_name, response),
        ):
            payload = {
                "conflict_id": conflict_id,
                "round": round_no,
                "initiator": actor,
                # 任务17 补丁二：只读姓名字段，供 timeline 按姓名命中与渲染直读；replay 不读。
                "initiator_name": actor_name,
                "responder": responder,
                "responder_name": responder_name,
                "proposal": proposal_key,
                "proposal_amount": amount_key,
                "response": response_key,
                "resource": resource,
            }
            if round_no == 1:
                # 任务17 裁决 4.1：只读元数据（成因随事件落库，replay 不读）。
                payload["social_adjustment"] = social_adjustment
                payload["proposal_basis"] = proposal_basis
            world.event_log.append(tick, "conflict_negotiation_round", payload)

        result: dict = {
            "conflict_id": conflict_id,
            "proposal": proposal,
            "response": response,
        }

        if response == "repay":
            debtor_stock = float(getattr(debtor_hh, resource, 0.0))
            creditor_stock = float(getattr(creditor_hh, resource, 0.0))
            pay = min(proposed_amount, debtor_stock, rec.amount)
            setattr(creditor_hh, resource, round(creditor_stock + pay, 2))
            setattr(debtor_hh, resource, round(debtor_stock - pay, 2))
            rec.amount = round(rec.amount - pay, 2)
            rec.overdue = rec.amount > 0
            rec.dispute_started_tick = tick
            # 会话已扣粮：同 tick 后续 _collect_debts 不得重复扣（按催收间隔节流到下一周期）
            rec.last_collected_tick = tick
            world.event_log.append(
                tick,
                "debt_repaid",
                {
                    "creditor_id": creditor_id,
                    "creditor_name": creditor_name,
                    "creditor_household_id": creditor_hh.household_id,
                    "debtor_id": debtor_id,
                    "debtor_name": debtor_name,
                    "debtor_household_id": debtor_hh.household_id,
                    "household_id": debtor_hh.household_id,
                    "amount": round(pay, 2),
                    "remaining": round(rec.amount, 2),
                    "source": "debt_dispute",
                    "originated_tick": rec.originated_tick,
                    "resource": resource,
                    f"debtor_{resource}_after": round(getattr(debtor_hh, resource), 2),
                    f"creditor_{resource}_after": round(getattr(creditor_hh, resource), 2),
                    "debtor_grain_after": round(debtor_hh.grain, 2),
                    "creditor_grain_after": round(creditor_hh.grain, 2),
                },
            )
            resolution = "repaid" if rec.amount <= 0 else "partial_repaid"
            result["resolution"] = resolution
            world.event_log.append(
                tick,
                "conflict_resolved",
                {
                    "conflict_id": conflict_id,
                    "resolution": resolution,
                    "amount_paid": round(pay, 2),
                    "remaining": round(rec.amount, 2),
                    "creditor_household_id": creditor_hh.household_id,
                    "debtor_household_id": debtor_hh.household_id,
                },
            )
            self._remember_dispute(world, tuning, creditor_id, debtor_id, resolution)
            return result

        accept_deferral = response == "accept_deferral" or (
            response == "request_deferral" and (kin or prior_honored)
        )
        if accept_deferral:
            old_due = rec.due_tick
            rec.due_tick = tick + cfg.deferral_days
            rec.overdue = False
            rec.dispute_started_tick = None  # 延期后进入下一周期，仍可再次触发
            result["resolution"] = "deferred"
            world.event_log.append(
                tick,
                "debt_deferred",
                {
                    "conflict_id": conflict_id,
                    "creditor_id": creditor_id,
                    "creditor_name": creditor_name,
                    "creditor_household_id": creditor_hh.household_id,
                    "debtor_id": debtor_id,
                    "debtor_name": debtor_name,
                    "debtor_household_id": debtor_hh.household_id,
                    "household_id": debtor_hh.household_id,
                    "amount": round(rec.amount, 2),
                    "resource": resource,
                    "old_due_tick": old_due,
                    "new_due_tick": rec.due_tick,
                    "deferral_days": cfg.deferral_days,
                },
            )
            world.event_log.append(
                tick,
                "conflict_resolved",
                {
                    "conflict_id": conflict_id,
                    "resolution": "deferred",
                    "new_due_tick": rec.due_tick,
                    "creditor_household_id": creditor_hh.household_id,
                    "debtor_household_id": debtor_hh.household_id,
                },
            )
            self._remember_dispute(world, tuning, creditor_id, debtor_id, "deferred")
            return result

        # 拒绝（或债权人坚持不延期）→ 破裂；该笔不再重复发起会话
        rec.dispute_started_tick = tick
        reason = "refused" if response == "refuse" else "creditor_insists"
        result["resolution"] = "broken"
        result["reason"] = reason
        world.event_log.append(
            tick,
            "conflict_broken",
            {
                "conflict_id": conflict_id,
                "reason": reason,
                "amount": round(rec.amount, 2),
                "resource": resource,
                "overdue_ticks": tick - rec.due_tick,
                "creditor_household_id": creditor_hh.household_id,
                "debtor_household_id": debtor_hh.household_id,
            },
        )
        self._remember_dispute(world, tuning, creditor_id, debtor_id, "broken")
        return result

    def _remember_dispute(self, world, tuning: AgentTuning,
                          creditor_id: str, debtor_id: str, outcome: str) -> None:
        """债争结果写回双方记忆 + 交互即互升 KNOWN（任务16 阶段二）。

        裁决 §3.4 纯净性：写入只用 (tick, target_id, event_type, outcome)，
        不读运行时中间态；replay 侧由 conflict_resolved / conflict_broken
        以相同口径重建（户→户主映射在回放态上等价解析）。
        语义：repaid 系 / deferred / broken 三种结果都算一次真实交互，均写记忆
        ——延期是「曾给过宽限」的印象而非违约；诉求调节只认 broken / repaid 系
        outcome，deferred 不改下一轮诉求档位（见 _negotiate_debt 调节段与
        test_negotiation_proposal_direction 的 deferred→partial 断言）。
        """
        cap = tuning.social.memory_capacity
        tick = world.current_tick
        social.record_interaction(
            world, creditor_id, debtor_id, tick, cap, "debt_dispute", outcome,
        )
        social.record_interaction(
            world, debtor_id, creditor_id, tick, cap, "debt_dispute", outcome,
        )
        # 任务 18 P1：记忆写回后合成印象（B 为主 + C 作门槛）；仅 label 变化写事件。
        window = tuning.social.impression_window
        social.update_impression(world, creditor_id, debtor_id, window)
        social.update_impression(world, debtor_id, creditor_id, window)

    @staticmethod
    def _head_name(world, household: HouseholdState) -> str:
        """家庭对外称谓：存活户主名 → 户主 id → 家庭 id。"""
        head = world.state.human.agents.get(household.head_id or "")
        if head is not None and head.alive:
            return head.name
        return household.head_id or household.household_id

    @staticmethod
    def _households_are_kin(world, a: HouseholdState, b: HouseholdState) -> bool:
        """两户是否存在直接亲缘（配偶/父母/子女），只读已有亲缘字段，不引入新状态。"""
        a_ids = set(a.member_ids)
        b_ids = set(b.member_ids)
        for member_id in a_ids:
            agent = world.state.human.agents.get(member_id)
            if agent is None:
                continue
            if agent.spouse_id in b_ids:
                return True
            if agent.mother_id in b_ids or agent.father_id in b_ids:
                return True
            if any(child in b_ids for child in agent.children_ids):
                return True
        return False

    @staticmethod
    def _debt_history_sets(world) -> tuple[set[str], set[str]]:
        """从事件流反查「有违约前科」「曾守约」的家庭集合（不新增状态）。"""
        defaulted: set[str] = set()
        repaid: set[str] = set()
        for evt in world.event_log.by_type("debt_defaulted"):
            payload = evt.get("payload") or {}
            hid = payload.get("debtor_household_id") or payload.get("household_id")
            if hid:
                defaulted.add(hid)
        for evt in world.event_log.by_type("debt_repaid"):
            payload = evt.get("payload") or {}
            hid = payload.get("debtor_household_id") or payload.get("household_id")
            if hid:
                repaid.add(hid)
        return defaulted, repaid
