"""投影基类：绑定引擎、共享户/人物解析与库存写回辅助。

SocietyProjection 的组成部分；统一注册入口见 ``__init__``。
"""
from __future__ import annotations

from typing import Optional

from vale.core.calendar import DAYS_PER_YEAR
from vale.core.replay import ProjectionBase
from vale.domains.society.social import apply_kin_defaults
from vale.domains.society.state import AgentState, DebtRecord, HouseholdState

_ASSET_FIELDS = ("grain", "meat", "fish", "vegetable", "cloth", "firewood",
                 "herbs", "hardwood", "coin", "water")

# 事件里可能出现的、以 <field>_after 形式给出的家庭库存快照
_INV_AFTER_KEYS = {
    "grain_after": "grain",
    "meat_after": "meat",
    "fish_after": "fish",
    "vegetable_after": "vegetable",
    "cloth_after": "cloth",
    "firewood_after": "firewood",
    "herbs_after": "herbs",
    "hardwood_after": "hardwood",
    "coin_after": "coin",
    # 任务30：生活用水（collect_water 产水；旧库无此键自动跳过）
    "water_after": "water",
}


def _hh_id(agent_id: str) -> str:
    return f"hh_{agent_id}"


class SocietyProjectionBase(ProjectionBase):
    def bind(self, engine) -> None:
        super().bind(engine)
        self.agent_cfg = {a.id: a for a in engine.config.agents.agents}

    def _household(self, household_id: str, *, home: str, work: str,
                   formed_tick: int, member_id: Optional[str] = None) -> HouseholdState:
        household = self.state.human.households.get(household_id)
        if household is None:
            household = HouseholdState(
                household_id=household_id,
                home_node=home if home in self.node_ids else self._default_home,
                work_node=work if work in self.node_ids else self._default_home,
                formed_tick=max(0, formed_tick),
            )
            self.state.human.households[household_id] = household
        if member_id and member_id not in household.member_ids:
            household.member_ids.append(member_id)
            if household.head_id is None:
                household.head_id = member_id
        return household

    def _ensure_agent(self, agent_id: str, payload: dict) -> AgentState:
        agent = self.state.human.agents.get(agent_id)
        if agent is not None:
            return agent
        cfg = self.agent_cfg.get(agent_id)
        if cfg is not None:
            age = cfg.age
            birth_tick = self.start_tick - age * DAYS_PER_YEAR
            name, surname, sex = cfg.name, cfg.surname or "", cfg.sex
            home, work = cfg.home_node, cfg.work_node
            physiology = self.config.agents.tuning.physiology
            health = cfg.initial_health if cfg.initial_health is not None else physiology.initial_health
            hunger = cfg.initial_hunger if cfg.initial_hunger is not None else physiology.initial_hunger
            stamina = cfg.initial_stamina if cfg.initial_stamina is not None else physiology.initial_stamina
        else:
            physiology = self.config.agents.tuning.physiology
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
        household_id = payload.get("household_id") or (cfg.household_id if cfg is not None else None) or _hh_id(agent_id)
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
            fatigue=physiology.initial_fatigue,
        )
        self.state.human.agents[agent_id] = agent
        return agent

    def _hh_for(self, agent_id: str, payload: dict) -> HouseholdState:
        agent = self._ensure_agent(agent_id, payload)
        return self.state.human.households[agent.household_id]

    def _set_inventory(self, household: HouseholdState, payload: dict) -> None:
        for key, field_name in _INV_AFTER_KEYS.items():
            if key in payload and payload[key] is not None:
                setattr(household, field_name, max(0.0, round(float(payload[key]), 2)))

    def _find_record(self, household: HouseholdState,
                     creditor_household_id: str,
                     resource: Optional[str] = None) -> Optional[DebtRecord]:
        candidates = [
            d for d in household.debts
            if d.creditor_household_id == creditor_household_id
            and (resource is None or getattr(d, "resource", "grain") == resource)
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda d: (d.due_tick, d.originated_tick))

    def _reduce_debt(
        self, household: HouseholdState, creditor_hh_id: str,
        amount: float, resource: Optional[str] = None,
    ) -> None:
        left = amount
        while left > 1e-9:
            rec = self._find_record(household, creditor_hh_id, resource)
            if rec is None:
                return
            take = min(rec.amount, left)
            rec.amount = round(rec.amount - take, 2)
            left = round(left - take, 2)
            if rec.amount <= 1e-9:
                household.debts.remove(rec)

    def _apply_household_inventories(self, inventories: dict) -> None:
        for household_id, inventory in inventories.items():
            household = self.state.human.households.get(household_id)
            if household:
                for item, amount in inventory.items():
                    if hasattr(household, item):
                        setattr(household, item, max(0.0, float(amount)))

    def finalize(self, state, last_tick: int, *, has_events: bool) -> None:
        # 任务16 阶段二：kin 默认 known（裁决 §3.1——运行时每 tick 与此处共用同一
        # 纯函数；kin 不写事件，只能由结构派生。零事件库跳过）
        if has_events:
            apply_kin_defaults(state, last_tick)

    def validate(self, state) -> None:
        for agent in state.human.agents.values():
            if not agent.household_id or agent.household_id not in state.human.households:
                raise ValueError(f"replay: orphan agent {agent.agent_id}")
        for household in state.human.households.values():
            if household.member_ids and household.head_id not in household.member_ids:
                raise ValueError(f"replay: head {household.head_id} not in {household.household_id}")
            for member_id in household.member_ids:
                if member_id not in state.human.agents:
                    raise ValueError(
                        f"replay: member {member_id} missing in {household.household_id}"
                    )


def _sex(value) -> "AgentSex":
    from vale.config.schema.agents import AgentSex

    if isinstance(value, AgentSex):
        return value
    try:
        return AgentSex(str(value))
    except ValueError:
        return AgentSex.MALE
