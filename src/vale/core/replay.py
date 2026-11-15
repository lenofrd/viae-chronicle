"""事件流只读重放（任务 12 家庭模型迁移第 1 步）。

用途：
1. 旧事件库（个人模型，无 household_id）可被重放为「每人一个单人家庭」的家庭状态；
2. 新事件库（含 household_id）直接按家庭重放；
3. 迁移验收用：旧库重放后的资产/债务/住所/工作节点与旧实现快照一致。

约束：
- 只读：不修改事件、不写事件库；
- 旧事件键名保持兼容（creditor_id/debtor_id 仍为 agent id，映射为 hh_{agent_id}）；
- 未知事件计入 ignored_events，不中断；
- 重放结束校验每个 agent 有 household_id、每个家庭 head 在成员内。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from vale.core.calendar import DAYS_PER_YEAR
from vale.core.state import AgentState, DebtRecord, HouseholdState, WorldState

_ASSET_FIELDS = ("grain", "meat", "fish", "vegetable", "cloth")

# 事件里可能出现的、以 <field>_after 形式给出的家庭库存快照
_INV_AFTER_KEYS = {
    "grain_after": "grain",
    "meat_after": "meat",
    "fish_after": "fish",
    "vegetable_after": "vegetable",
    "cloth_after": "cloth",
}


@dataclass
class ReplayResult:
    state: WorldState
    ignored_events: dict[str, int] = field(default_factory=dict)


def _hh_id(agent_id: str) -> str:
    return f"hh_{agent_id}"


class _Replayer:
    def __init__(self, config, start_tick: int) -> None:
        self.config = config
        self.start_tick = start_tick
        self.state = WorldState()
        self.ignored: dict[str, int] = {}
        self.agent_cfg = {a.id: a for a in config.agents.agents}
        self.node_ids = {n.id for n in config.spatial.nodes}
        self._default_home = config.agents.agents[0].home_node if config.agents.agents else "well"

    # -- 基础设施 ----------------------------------------------------------- #
    def _household(self, household_id: str, *, home: str, work: str,
                   formed_tick: int, member_id: Optional[str] = None) -> HouseholdState:
        household = self.state.households.get(household_id)
        if household is None:
            household = HouseholdState(
                household_id=household_id,
                home_node=home if home in self.node_ids else self._default_home,
                work_node=work if work in self.node_ids else self._default_home,
                formed_tick=max(0, formed_tick),
            )
            self.state.households[household_id] = household
        if member_id and member_id not in household.member_ids:
            household.member_ids.append(member_id)
            if household.head_id is None:
                household.head_id = member_id
        return household

    def _ensure_agent(self, agent_id: str, payload: dict) -> AgentState:
        agent = self.state.agents.get(agent_id)
        if agent is not None:
            return agent
        cfg = self.agent_cfg.get(agent_id)
        if cfg is not None:
            age = cfg.age
            birth_tick = self.start_tick - age * DAYS_PER_YEAR
            name, surname, sex = cfg.name, cfg.surname or "", cfg.sex
            home, work = cfg.home_node, cfg.work_node
            health = cfg.initial_health if cfg.initial_health is not None else 100.0
            hunger = cfg.initial_hunger if cfg.initial_hunger is not None else 30.0
            stamina = cfg.initial_stamina if cfg.initial_stamina is not None else 100.0
        else:
            birth_tick = int(payload.get("birth_tick", self.start_tick))
            name = payload.get("agent_name") or payload.get("child_name") or agent_id
            surname = ""
            sex_value = payload.get("sex", "male")
            sex = _sex(sex_value)
            home = payload.get("home_node") or self._default_home
            work = payload.get("work_node") or home
            health = float(payload.get("initial_health") or 60.0)
            hunger = float(payload.get("initial_hunger") or 30.0)
            stamina = float(payload.get("initial_stamina") or 40.0)
        age_now = max(0, (self.start_tick - birth_tick) // DAYS_PER_YEAR)
        household_id = payload.get("household_id") or _hh_id(agent_id)
        household = self._household(
            household_id, home=home, work=work,
            formed_tick=birth_tick if birth_tick >= 0 else 0, member_id=agent_id,
        )
        agent = AgentState(
            agent_id=agent_id,
            name=name,
            surname=surname,
            sex=sex,
            birth_tick=birth_tick,
            life_stage=self.config.agents.tuning.aging.stage_for(age_now).name,
            household_id=household.household_id,
            location=household.home_node,
            work_node=work,  # 个人劳作点偏好；旧库按配置还原
            health=health,
            hunger=hunger,
            stamina=stamina,
        )
        self.state.agents[agent_id] = agent
        return agent

    def _hh_for(self, agent_id: str, payload: dict) -> HouseholdState:
        agent = self._ensure_agent(agent_id, payload)
        return self.state.households[agent.household_id]

    def _set_inventory(self, household: HouseholdState, payload: dict) -> None:
        for key, field_name in _INV_AFTER_KEYS.items():
            if key in payload and payload[key] is not None:
                setattr(household, field_name, max(0.0, round(float(payload[key]), 2)))

    # -- 债务 --------------------------------------------------------------- #
    def _find_record(self, household: HouseholdState,
                     creditor_household_id: str) -> Optional[DebtRecord]:
        candidates = [
            d for d in household.debts if d.creditor_household_id == creditor_household_id
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda d: (d.due_tick, d.originated_tick))

    def _reduce_debt(self, household: HouseholdState, creditor_hh_id: str, amount: float) -> None:
        left = amount
        while left > 1e-9:
            rec = self._find_record(household, creditor_hh_id)
            if rec is None:
                return
            take = min(rec.amount, left)
            rec.amount = round(rec.amount - take, 2)
            left = round(left - take, 2)
            if rec.amount <= 1e-9:
                household.debts.remove(rec)

    # -- 主循环 ------------------------------------------------------------- #
    def replay(self, events: list[dict]) -> ReplayResult:
        for evt in events:
            event_type = evt.get("event_type")
            payload = evt.get("payload") or {}
            tick = int(evt.get("tick", 0))
            handler = getattr(self, f"_on_{event_type}", None)
            if handler is None:
                self.ignored[event_type] = self.ignored.get(event_type, 0) + 1
                continue
            handler(payload, tick)
        self._validate()
        return ReplayResult(state=self.state, ignored_events=self.ignored)

    # -- 通用事件 ----------------------------------------------------------- #
    def _on_agent_action_taken(self, payload: dict, tick: int) -> None:
        agent_id = payload.get("agent_id")
        if not agent_id:
            return
        household = self._hh_for(agent_id, payload)
        self._set_inventory(household, payload)
        for key, field_name in (
            ("hunger_after", "hunger"), ("stamina_after", "stamina"),
        ):
            if key in payload and payload[key] is not None:
                setattr(self.state.agents[agent_id], field_name, float(payload[key]))

    def _on_gather_success(self, payload: dict, tick: int) -> None:
        agent_id = payload.get("agent_id")
        field_name = payload.get("output_field")
        if agent_id and field_name in _ASSET_FIELDS and "output_after" in payload:
            household = self._hh_for(agent_id, payload)
            setattr(household, field_name, max(0.0, round(float(payload["output_after"]), 2)))

    def _on_weave_success(self, payload: dict, tick: int) -> None:
        agent_id = payload.get("agent_id")
        if agent_id and "cloth_after" in payload:
            self._hh_for(agent_id, payload).cloth = max(
                0.0, round(float(payload["cloth_after"]), 2)
            )

    def _on_trade_executed(self, payload: dict, tick: int) -> None:
        for agent_key, inv_key in (
            ("seller_id", "seller_inv_after"), ("buyer_id", "buyer_inv_after"),
        ):
            agent_id = payload.get(agent_key)
            inv = payload.get(inv_key)
            if not agent_id or not isinstance(inv, dict):
                continue
            household = self._hh_for(agent_id, payload)
            for item, value in inv.items():
                if item in _ASSET_FIELDS and value is not None:
                    setattr(household, item, max(0.0, round(float(value), 2)))

    def _on_birth_asset_transfer(self, payload: dict, tick: int) -> None:
        for agent_key, inv_key in (
            ("parent_id", "parent_inv_after"), ("child_id", "child_inv_after"),
        ):
            agent_id = payload.get(agent_key)
            inv = payload.get(inv_key)
            if not agent_id or not isinstance(inv, dict):
                continue
            household = self._hh_for(agent_id, payload)
            for item, value in inv.items():
                if item in _ASSET_FIELDS and value is not None:
                    setattr(household, item, max(0.0, round(float(value), 2)))

    def _on_inheritance_executed(self, payload: dict, tick: int) -> None:
        item = payload.get("item")
        for agent_key, after_key in (
            ("deceased_id", "deceased_after"), ("heir_id", "heir_after"),
        ):
            agent_id = payload.get(agent_key)
            if agent_id and item in _ASSET_FIELDS and after_key in payload:
                household = self._hh_for(agent_id, payload)
                setattr(household, item, max(0.0, round(float(payload[after_key]), 2)))

    def _on_inheritance_escheated(self, payload: dict, tick: int) -> None:
        agent_id = payload.get("deceased_id")
        item = payload.get("item")
        if agent_id and item in _ASSET_FIELDS:
            household = self._hh_for(agent_id, payload)
            current = getattr(household, item, 0.0)
            setattr(household, item, max(0.0, round(current - float(payload.get("amount", 0.0)), 2)))

    def _on_debt_formed(self, payload: dict, tick: int) -> None:
        debtor_id = payload.get("debtor_id")
        creditor_id = payload.get("creditor_id")
        if not debtor_id or not creditor_id:
            return
        debtor_hh = self._hh_for(debtor_id, payload)
        creditor_hh = self._hh_for(creditor_id, payload)
        creditor_hh_id = payload.get("creditor_household_id") or creditor_hh.household_id
        debtor_hh.debts.append(
            DebtRecord(
                debtor_household_id=debtor_hh.household_id,
                creditor_household_id=creditor_hh_id,
                amount=max(0.0, round(float(payload.get("amount", 0.0)), 2)),
                originated_tick=int(payload.get("originated_tick", tick)),
                due_tick=int(payload.get("due_tick", tick)),
            )
        )
        for key, agent_key in (
            ("debtor_grain_after", "debtor_id"), ("creditor_grain_after", "creditor_id"),
        ):
            if key in payload and payload[key] is not None and payload.get(agent_key):
                hh = self._hh_for(payload[agent_key], payload)
                hh.grain = max(0.0, round(float(payload[key]), 2))

    def _on_debt_repaid(self, payload: dict, tick: int) -> None:
        debtor_id = payload.get("debtor_id")
        creditor_id = payload.get("creditor_id")
        if not debtor_id or not creditor_id:
            return
        debtor_hh = self._hh_for(debtor_id, payload)
        creditor_hh = self._hh_for(creditor_id, payload)
        creditor_hh_id = payload.get("creditor_household_id") or creditor_hh.household_id
        self._reduce_debt(debtor_hh, creditor_hh_id, float(payload.get("amount", 0.0)))
        for key, agent_key in (
            ("debtor_grain_after", "debtor_id"), ("creditor_grain_after", "creditor_id"),
        ):
            if key in payload and payload[key] is not None:
                hh = self._hh_for(payload[agent_key], payload)
                hh.grain = max(0.0, round(float(payload[key]), 2))

    def _on_debt_collected(self, payload: dict, tick: int) -> None:
        debtor_id = payload.get("debtor_id")
        creditor_id = payload.get("creditor_id")
        if not debtor_id or not creditor_id:
            return
        debtor_hh = self._hh_for(debtor_id, payload)
        creditor_hh = self._hh_for(creditor_id, payload)
        creditor_hh_id = payload.get("creditor_household_id") or creditor_hh.household_id
        self._reduce_debt(debtor_hh, creditor_hh_id, float(payload.get("amount_paid", 0.0)))
        for key, agent_key in (
            ("debtor_grain_after", "debtor_id"), ("creditor_grain_after", "creditor_id"),
        ):
            if key in payload and payload[key] is not None:
                hh = self._hh_for(payload[agent_key], payload)
                hh.grain = max(0.0, round(float(payload[key]), 2))

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
        self._reduce_debt(debtor_hh, creditor_hh_id, float(payload.get("amount", 0.0)))

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
        self._reduce_debt(from_hh, creditor_hh_id, amount)
        to_hh.debts.append(
            DebtRecord(
                debtor_household_id=to_hh.household_id,
                creditor_household_id=creditor_hh_id,
                amount=round(amount, 2),
                originated_tick=int(payload.get("originated_tick", tick)),
                due_tick=int(payload.get("due_tick", tick)),
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
        self._reduce_debt(debtor_hh, creditor_household_id, float(payload.get("amount", 0.0)))

    # -- 家庭生命周期事件（迁移第2步）------------------------------------- #
    def _on_household_merged(self, payload: dict, tick: int) -> None:
        target_id = payload.get("target_household_id")
        source_id = payload.get("source_household_id")
        if not target_id or not source_id:
            return
        home = payload.get("home_node") or self._default_home
        work = payload.get("work_node") or home
        target = self._household(target_id, home=home, work=work, formed_tick=tick)
        source = self._household(source_id, home=home, work=work, formed_tick=tick)
        for member_id in payload.get("members_after") or []:
            if member_id not in target.member_ids:
                target.member_ids.append(member_id)
            agent = self.state.agents.get(member_id)
            if agent is not None:
                agent.household_id = target.household_id
        target.head_id = payload.get("head_id") or target.head_id
        after = payload.get("target_assets_after")
        if isinstance(after, dict):
            for item in _ASSET_FIELDS:
                if item in after and after[item] is not None:
                    setattr(target, item, max(0.0, round(float(after[item]), 2)))
        for rec in source.debts:
            rec.debtor_household_id = target.household_id
            target.debts.append(rec)
        source.debts = []
        for item in _ASSET_FIELDS:
            setattr(source, item, 0.0)

    def _on_household_head_changed(self, payload: dict, tick: int) -> None:
        household_id = payload.get("household_id")
        new_head_id = payload.get("new_head_id")
        if not household_id or not new_head_id:
            return
        household = self.state.households.get(household_id)
        if household is not None:
            household.head_id = new_head_id

    def _on_household_dissolved(self, payload: dict, tick: int) -> None:
        household_id = payload.get("household_id")
        if not household_id:
            return
        household = self.state.households.get(household_id)
        if household is not None:
            household.member_ids = []
            household.head_id = None

    # -- 劳作点分配（阶段二 C）--------------------------------------------- #
    def _on_household_work_nodes_changed(self, payload: dict, tick: int) -> None:
        household_id = payload.get("household_id")
        if not household_id:
            return
        household = self.state.households.get(household_id)
        if household is not None:
            household.work_nodes = [str(n) for n in (payload.get("after") or [])]

    def _on_agent_work_node_changed(self, payload: dict, tick: int) -> None:
        agent_id = payload.get("agent_id")
        if not agent_id:
            return
        agent = self.state.agents.get(agent_id)
        if agent is not None:
            after = payload.get("after")
            agent.work_node = str(after) if after else None

    def _on_birth_skipped(self, payload: dict, tick: int) -> None:
        """生育因户容量顺延：人口与资产均未变，无状态需要重放。"""
        return

    # -- 生命周期 ----------------------------------------------------------- #
    def _on_agent_born(self, payload: dict, tick: int) -> None:
        child_id = payload.get("child_id") or payload.get("agent_id")
        if not child_id:
            return
        self._ensure_agent(child_id, payload)
        child = self.state.agents[child_id]
        for parent_key, field_name in (("mother_id", "mother_id"), ("father_id", "father_id")):
            parent_id = payload.get(parent_key)
            if parent_id:
                setattr(child, field_name, parent_id)
                parent = self._ensure_agent(parent_id, payload)
                if child_id not in parent.children_ids:
                    parent.children_ids.append(child_id)
        last_birth_key = payload.get("mother_id")
        if last_birth_key:
            self.state.agents[last_birth_key].last_birth_tick = int(
                payload.get("birth_tick", tick)
            )

    def _on_agent_married(self, payload: dict, tick: int) -> None:
        agent_id = payload.get("agent_id")
        spouse_id = payload.get("spouse_id")
        if not agent_id or not spouse_id:
            return
        agent = self._ensure_agent(agent_id, payload)
        spouse = self._ensure_agent(spouse_id, payload)
        agent.spouse_id, spouse.spouse_id = spouse_id, agent_id
        agent.married_tick = spouse.married_tick = tick

    def _on_agent_incapacitated(self, payload: dict, tick: int) -> None:
        agent_id = payload.get("agent_id")
        if not agent_id:
            return
        agent = self._ensure_agent(agent_id, payload)
        agent.incapacitated = True
        agent.incapacitated_tick = tick
        if "health" in payload and payload["health"] is not None:
            agent.health = float(payload["health"])

    def _on_agent_died(self, payload: dict, tick: int) -> None:
        agent_id = payload.get("agent_id")
        if not agent_id:
            return
        agent = self._ensure_agent(agent_id, payload)
        agent.alive = False
        agent.died_tick = tick
        agent.death_cause = payload.get("cause")

    def _on_cold_exposure(self, payload: dict, tick: int) -> None:
        agent_id = payload.get("agent_id")
        if agent_id and "health_after" in payload:
            self._ensure_agent(agent_id, payload).health = float(payload["health_after"])

    def _on_gather_injury(self, payload: dict, tick: int) -> None:
        agent_id = payload.get("agent_id")
        if agent_id and "health_after" in payload:
            self._ensure_agent(agent_id, payload).health = float(payload["health_after"])

    def _on_health_recovered(self, payload: dict, tick: int) -> None:
        agent_id = payload.get("agent_id")
        if agent_id and "health_after" in payload:
            self._ensure_agent(agent_id, payload).health = float(payload["health_after"])

    # -- 校验 --------------------------------------------------------------- #
    def _validate(self) -> None:
        for agent in self.state.agents.values():
            if not agent.household_id or agent.household_id not in self.state.households:
                raise ValueError(f"replay: orphan agent {agent.agent_id}")
        for household in self.state.households.values():
            if household.member_ids and household.head_id not in household.member_ids:
                raise ValueError(f"replay: head {household.head_id} not in {household.household_id}")
            for member_id in household.member_ids:
                if member_id not in self.state.agents:
                    raise ValueError(
                        f"replay: member {member_id} missing in {household.household_id}"
                    )


def _sex(value) -> "AgentSex":
    from config.schema.agents import AgentSex

    if isinstance(value, AgentSex):
        return value
    try:
        return AgentSex(str(value))
    except ValueError:
        return AgentSex.MALE


def rebuild_state(events: list[dict], config) -> ReplayResult:
    """只读重放事件流为家庭状态（旧库 → 单人家庭；新库 → 按 household_id）。"""
    replayer = _Replayer(config, start_tick=config.world.start_tick)
    return replayer.replay(events)
