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
from vale.core.pools import ResourcePoolState
from vale.core.state import WorldState
from vale.domains.environment.state import WaterSourceState
from vale.domains.society.state import AcquaintanceEntry, AgentState, BuildingNeedState, BuildingState, ConstructionProjectState, DebtRecord, HouseholdState, ImpressionEntry, LandParcelState, LandRightState
from vale.domains.wildlife.state import WILDLIFE_RESOURCE_TYPES
from vale.domains.society.social import apply_kin_defaults, record_memory

_ASSET_FIELDS = ("grain", "meat", "fish", "vegetable", "cloth", "firewood", "herbs", "hardwood", "coin", "water")

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

    # -- 债务 --------------------------------------------------------------- #
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
        # 任务16 阶段二：kin 默认 known（裁决 §3.1——运行时每 tick 与此处共用同一
        # 纯函数；kin 不写事件，只能由结构派生。零事件库跳过）
        if events:
            apply_kin_defaults(self.state, int(events[-1].get("tick", 0)))
        self._validate()
        return ReplayResult(state=self.state, ignored_events=self.ignored)


    def _on_land_lease_created(self, payload: dict, tick: int) -> None:
        lease = payload.get("lease")
        if lease:
            self.state.human.land_leases[lease["lease_id"]] = dict(lease)
            parcel = self.state.human.land_parcels.get(lease.get("parcel_id"))
            right = payload.get("land_right")
            if parcel is not None and right:
                from vale.domains.society.state import LandRightState
                if not any(item.right_id == right["right_id"] for item in parcel.use_rights):
                    parcel.use_rights.append(LandRightState.model_validate(right))
            self._apply_household_inventories({payload.get("lessee_household_id"): payload.get("lessee_inventory_after") or {}})




    def _on_land_ownership_relinquished(self, payload: dict, tick: int) -> None:
        parcel = self.state.human.land_parcels.get(payload.get("parcel_id", ""))
        if parcel is not None:
            parcel.owner_type, parcel.owner_id = "collective", "village"
            parcel.management_authority = "village_council"
        for building_id in payload.get("building_ids") or []:
            building = self.state.human.buildings.get(building_id)
            if building is not None:
                building.owner_type, building.owner_id = "collective", "village"

    def _on_land_lease_renewed(self, payload: dict, tick: int) -> None:
        lease = self.state.human.land_leases.get(payload.get("lease_id", ""))
        if lease:
            lease.update(payload.get("lease_after") or {})
            parcel = self.state.human.land_parcels.get(lease.get("parcel_id"))
            if parcel is not None:
                for right in parcel.use_rights:
                    if right.right_id == f"lease:{lease['lease_id']}":
                        right.expires_tick = lease.get("expires_tick")

    def _on_land_lease_inherited(self, payload: dict, tick: int) -> None:
        lease = self.state.human.land_leases.get(payload.get("lease_id", ""))
        if lease:
            lease.update(payload.get("lease_after") or {})

    def _on_land_rent_paid(self, payload: dict, tick: int) -> None:
        lease = self.state.human.land_leases.get(payload.get("lease_id", ""))
        if lease:
            lease.update(payload.get("lease_after") or {})
        self._apply_household_inventories(payload.get("inventories_after") or {})
        self.state.human.public_treasury = dict(payload.get("public_treasury_after") or self.state.human.public_treasury)

    def _on_land_rent_missed(self, payload: dict, tick: int) -> None:
        lease = self.state.human.land_leases.get(payload.get("lease_id", ""))
        if lease:
            lease.update(payload.get("lease_after") or {})

    def _on_land_lease_terminated(self, payload: dict, tick: int) -> None:
        lease = self.state.human.land_leases.get(payload.get("lease_id", ""))
        if lease:
            lease.update(payload.get("lease_after") or {})
        parcel = self.state.human.land_parcels.get(payload.get("parcel_id", ""))
        if parcel is not None:
            parcel.use_rights = [r for r in parcel.use_rights if r.right_id != payload.get("right_id")]
        self._apply_household_inventories(payload.get("inventories_after") or {})
        self.state.human.public_treasury = dict(payload.get("public_treasury_after") or self.state.human.public_treasury)

    def _apply_household_inventories(self, inventories: dict) -> None:
        for household_id, inventory in inventories.items():
            household = self.state.human.households.get(household_id)
            if household:
                for item, amount in inventory.items():
                    if hasattr(household, item):
                        setattr(household, item, max(0.0, float(amount)))


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
                setattr(self.state.human.agents[agent_id], field_name, float(payload[key]))

    def _on_agent_fatigue_settled(self, payload: dict, tick: int) -> None:
        agent = self.state.human.agents.get(payload.get("agent_id", ""))
        if agent is None:
            return
        if payload.get("after") is not None:
            agent.fatigue = max(0.0, min(100.0, float(payload["after"])))
        if payload.get("high_days_after") is not None:
            agent.fatigue_high_days = max(0, int(payload["high_days_after"]))

    def _on_cold_exposure(self, payload: dict, tick: int) -> None:
        agent_id = payload.get("agent_id")
        if not agent_id or payload.get("health_after") is None:
            return
        agent = self._ensure_agent(str(agent_id), payload)
        agent.health = max(0.0, min(100.0, float(payload["health_after"])))

    def _on_field_labor_progressed(self, payload: dict, tick: int) -> None:
        field_node = payload.get("field_node")
        if not field_node:
            return
        self.state.human.field_season_labor[field_node] = {
            "year": int(payload.get("year", 1)),
            "season": str(payload.get("season", "spring")),
            "labor_completed": max(0.0, float(payload.get("labor_after", 0.0))),
        }

    def _on_building_condition_changed(self, payload: dict, tick: int) -> None:
        building = self.state.human.buildings.get(payload.get("building_id", ""))
        if building is None:
            return
        if payload.get("condition_after") is not None:
            building.condition = float(payload["condition_after"])
        if payload.get("status_after") is not None:
            building.status = str(payload["status_after"])

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

    def _on_household_storage_overflow_loss(self, payload: dict, tick: int) -> None:
        household = self.state.human.households.get(payload.get("household_id", ""))
        inventory = payload.get("inventory_after") or {}
        if household is None:
            return
        for field_name, value in inventory.items():
            if hasattr(household, field_name):
                setattr(household, field_name, max(0.0, float(value)))

    def _on_household_relocated(self, payload: dict, tick: int) -> None:
        household = self.state.human.households.get(payload.get("household_id", ""))
        if household is None:
            return
        old_node = payload.get("old_home_node")
        new_node = payload.get("new_home_node")
        if new_node:
            household.home_node = str(new_node)
        old_parcel = self.state.human.land_parcels.get(payload.get("old_parcel_id", ""))
        new_parcel = self.state.human.land_parcels.get(payload.get("new_parcel_id", ""))
        if old_parcel is not None:
            old_parcel.owner_type, old_parcel.owner_id = "collective", "village"
            old_parcel.management_authority = "village_council"
        if new_parcel is not None:
            new_parcel.owner_type, new_parcel.owner_id = "household", household.household_id
            new_parcel.management_authority = None
        old_building = self.state.human.buildings.get(payload.get("old_building_id", ""))
        new_building = self.state.human.buildings.get(payload.get("new_building_id", ""))
        if old_building is not None:
            old_building.owner_type, old_building.owner_id = "collective", "village"
            old_building.status = "vacant"
        if new_building is not None:
            new_building.owner_type, new_building.owner_id = "household", household.household_id
            new_building.status = "occupied"
        for member_id in payload.get("member_ids") or household.member_ids:
            agent = self.state.human.agents.get(member_id)
            if agent is not None:
                agent.home_node = str(new_node)
                if agent.location == old_node:
                    agent.location = str(new_node)

    def _on_building_access_shared(self, payload: dict, tick: int) -> None:
        building = self.state.human.buildings.get(payload.get("building_id", ""))
        if building is not None:
            building.attributes["shared_with_household_ids"] = list(
                payload.get("shared_with_household_ids") or []
            )

    def _on_building_expanded(self, payload: dict, tick: int) -> None:
        building = self.state.human.buildings.get(payload.get("building_id", ""))
        if building is not None and payload.get("footprint_after") is not None:
            building.footprint_area = float(payload["footprint_after"])

    def _on_building_demolished(self, payload: dict, tick: int) -> None:
        building = self.state.human.buildings.get(payload.get("building_id", ""))
        if building is not None:
            building.status = "demolished"
            building.condition = 0.0

    def _on_building_repaired(self, payload: dict, tick: int) -> None:
        building = self.state.human.buildings.get(payload.get("building_id", ""))
        if building is None:
            return
        if payload.get("condition_after") is not None:
            building.condition = float(payload["condition_after"])
            if building.condition > 0 and building.status == "ruined":
                building.status = "active"


    def _on_building_need_resolved(self, payload: dict, tick: int) -> None:
        raw = payload.get("need")
        if raw and raw.get("need_id"):
            self.state.human.building_needs[raw["need_id"]] = BuildingNeedState.model_validate(raw)

    def _on_building_need_updated(self, payload: dict, tick: int) -> None:
        raw = payload.get("need")
        if not raw or not raw.get("need_id"):
            return
        need = BuildingNeedState.model_validate(raw)
        self.state.human.building_needs[need.need_id] = need

    def _on_agent_fatigue_settled(self, payload: dict, tick: int) -> None:
        agent_id = payload.get("agent_id")
        if agent_id and agent_id in self.state.human.agents:
            agent = self.state.human.agents[agent_id]
            if payload.get("after") is not None:
                agent.fatigue = float(payload["after"])
            if payload.get("high_days_after") is not None:
                agent.fatigue_high_days = int(payload["high_days_after"])

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



    def _on_field_labor_progressed(self, payload: dict, tick: int) -> None:
        node_id = payload.get("field_node")
        if node_id and payload.get("labor_after") is not None:
            self.state.human.field_season_labor[node_id] = {
                "year": int(payload.get("year", 1)),
                "season": str(payload.get("season", "")),
                "labor_completed": float(payload["labor_after"]),
            }

    def _on_field_flood_damage(self, payload: dict, tick: int) -> None:
        node_id = payload.get("field_node")
        if node_id and payload.get("after") is not None:
            self.state.environment.field_growth[node_id] = max(0.0, float(payload["after"]))

    def _on_field_drought_damage(self, payload: dict, tick: int) -> None:
        node_id = payload.get("field_node")
        if node_id and payload.get("after") is not None:
            self.state.environment.field_growth[node_id] = max(0.0, float(payload["after"]))

    def _on_landslide_damage(self, payload: dict, tick: int) -> None:
        node_id = payload.get("field_node")
        if node_id and payload.get("fertility_after") is not None:
            self.state.environment.fertility_factor[node_id] = max(.1, float(payload["fertility_after"]))

    def _on_wildlife_attack(self, payload: dict, tick: int) -> None:
        agent_id = payload.get("agent_id")
        agent = self.state.human.agents.get(agent_id) if agent_id else None
        if agent is not None and payload.get("health_after") is not None:
            agent.health = max(0.0, float(payload["health_after"]))
            agent.last_injury_tick = tick



    def _on_household_split(self, payload: dict, tick: int) -> None:
        source_id = payload.get("source_household_id")
        new_id = payload.get("new_household_id")
        if not source_id or not new_id:
            return
        source = self.state.human.households.get(source_id)
        if source is None:
            source = self._household(source_id, home=payload.get("home_node") or self._default_home,
                                    work=payload.get("work_node") or self._default_home,
                                    formed_tick=tick)
        new_household = self.state.human.households.get(new_id)
        if new_household is None:
            new_household = self._household(
                new_id, home=payload.get("home_node") or source.home_node,
                work=payload.get("work_node") or source.work_node,
                formed_tick=tick,
            )
            self.state.human.households[new_id] = new_household
        new_household.head_id = payload.get("head_id")
        new_household.home_node = payload.get("home_node") or new_household.home_node
        new_household.work_node = payload.get("work_node") or new_household.work_node
        new_household.registry_node = source.registry_node
        new_household.registered_tick = tick if source.registry_node else None
        members = payload.get("members", [])
        moving_ids = [m.get("id") for m in members if m.get("id")]
        source.member_ids = list(payload.get("source_members_after",
                                             [m for m in source.member_ids if m not in moving_ids]))
        new_household.member_ids = moving_ids
        for agent_id in moving_ids:
            agent = self.state.human.agents.get(agent_id)
            if agent is None:
                agent = self._ensure_agent(agent_id, {
                    "household_id": new_id, "home_node": new_household.home_node,
                    "work_node": new_household.work_node,
                })
            agent.household_id = new_id
            agent.location = new_household.home_node
            agent.work_node = None
        for item, value in (payload.get("source_assets_after") or {}).items():
            if item in _ASSET_FIELDS:
                setattr(source, item, max(0.0, float(value)))
        for item, value in (payload.get("new_assets") or {}).items():
            if item in _ASSET_FIELDS:
                setattr(new_household, item, max(0.0, float(value)))
        if "source_debt_records_after" in payload:
            source.debts = [DebtRecord(**d) for d in payload["source_debt_records_after"]]
        if "new_debt_records" in payload:
            new_household.debts = [DebtRecord(**d) for d in payload["new_debt_records"]]

    def _on_household_registered(self, payload: dict, tick: int) -> None:
        household_id = payload.get("household_id")
        if not household_id:
            return
        household = self._household(
            household_id, home=payload.get("home_node") or self._default_home,
            work=payload.get("work_node") or payload.get("home_node") or self._default_home,
            formed_tick=int(payload.get("registered_tick", tick)),
            member_id=payload.get("head_id"),
        )
        household.registry_node = payload.get("registry_node")
        household.registered_tick = int(payload.get("registered_tick", tick))
        for item, value in (payload.get("assets") or {}).items():
            if item in _ASSET_FIELDS:
                setattr(household, item, max(0.0, float(value)))
        head_id = payload.get("head_id")
        if head_id:
            # The household registration event is also the initial registration
            # record for its head; otherwise singleton households have no later
            # member/action event from which Replay could reconstruct the agent.
            self._ensure_agent(str(head_id), {
                "household_id": household_id,
                "home_node": payload.get("home_node") or household.home_node,
                "work_node": payload.get("work_node") or household.work_node,
            })

    def _on_household_member_registered(self, payload: dict, tick: int) -> None:
        household_id = payload.get("household_id")
        agent_id = payload.get("agent_id")
        household = self.state.human.households.get(household_id) if household_id else None
        if household is None or not agent_id:
            return
        # Registration events must reconstruct both sides of the household
        # relation, even when no later action event exists to lazily create the agent.
        self._ensure_agent(agent_id, {
            "household_id": household_id,
            "home_node": payload.get("home_node") or household.home_node,
            "work_node": payload.get("work_node") or household.work_node,
        })

    def _pool_container(self, pool_payload: dict):
        """按资源类型路由池容器（P4）：fish/game 归动物域，其余归环境域。"""
        if pool_payload.get("resource_type") in WILDLIFE_RESOURCE_TYPES:
            return self.state.wildlife.pools
        return self.state.environment.ecological_resources

    def _find_pool(self, node_id: str):
        pool = self.state.environment.ecological_resources.get(node_id)
        if pool is None:
            pool = self.state.wildlife.pools.get(node_id)
        return pool

    def _on_resource_pool_initialized(self, payload: dict, tick: int) -> None:
        node_id = payload.get("resource_node")
        if node_id:
            data = dict(payload.get("pool", {}))
            self._pool_container(data)[node_id] = ResourcePoolState(**data)

    def _on_resource_regenerated(self, payload: dict, tick: int) -> None:
        node_id = payload.get("resource_node")
        pool = self._find_pool(node_id) if node_id else None
        if pool is not None and payload.get("stock_after") is not None:
            pool.current_stock = float(payload["stock_after"])

    def _on_resource_harvested(self, payload: dict, tick: int) -> None:
        node_id = payload.get("resource_node")
        pool = self._find_pool(node_id) if node_id else None
        if pool is not None and payload.get("stock_after") is not None:
            pool.current_stock = float(payload["stock_after"])
            pool.harvested_this_tick = float(payload.get("harvested_this_tick", 0.0))
            pool.harvest_tick = int(payload.get("harvest_tick", tick))

    # -- 任务30：水文与生活用水 ---------------------------------------------- #
    def _on_water_level_changed(self, payload: dict, tick: int) -> None:
        if payload.get("after") is not None:
            self.state.environment.water_level_ratio = max(0.0, min(1.0, float(payload["after"])))

    # -- P3a：水源库存 ------------------------------------------------------- #
    def _on_water_source_initialized(self, payload: dict, tick: int) -> None:
        node_id = payload.get("water_node")
        source = payload.get("source")
        if node_id and isinstance(source, dict):
            data = dict(source)
            data.setdefault("node_id", node_id)
            self.state.environment.water_sources[node_id] = WaterSourceState(**data)

    def _on_water_source_regenerated(self, payload: dict, tick: int) -> None:
        self._set_water_stock(payload)

    def _on_water_withdrawn(self, payload: dict, tick: int) -> None:
        self._set_water_stock(payload)

    def _set_water_stock(self, payload: dict) -> None:
        node_id = payload.get("water_node")
        source = self.state.environment.water_sources.get(node_id) if node_id else None
        if source is not None and payload.get("stock_after") is not None:
            source.current_stock = max(0.0, round(float(payload["stock_after"]), 6))

    def _on_irrigation_gear_changed(self, payload: dict, tick: int) -> None:
        if payload.get("to"):
            self.state.environment.irrigation_gear = str(payload["to"])

    def _on_water_consumed(self, payload: dict, tick: int) -> None:
        household_id = payload.get("household_id")
        household = self.state.human.households.get(household_id) if household_id else None
        if household is not None and payload.get("after") is not None:
            household.water = max(0.0, round(float(payload["after"]), 2))

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

    # -- 集市赊账与债务纠纷（任务15 阶段二）--------------------------------- #
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

    def _on_acquaintance_changed(self, payload: dict, tick: int) -> None:
        """任务16 阶段二：重建认知条目（new_level<=0 视为遗忘删除）。"""
        observer = self.state.human.agents.get(payload.get("observer_id") or "")
        target_id = payload.get("target_id")
        if observer is None or not target_id:
            return
        try:
            new_level = int(payload.get("new_level") or 0)
        except (TypeError, ValueError):
            return
        if new_level <= 0:
            observer.acquaintances.pop(target_id, None)
        else:
            observer.acquaintances[target_id] = AcquaintanceEntry(
                level=new_level, last_seen_tick=tick,
            )

    # -- 印象沉淀层（任务 18 P1）------------------------------------------- #
    def _on_impression_formed(self, payload: dict, tick: int) -> None:
        """任务18 P1：首次形成印象，幂等写回条目（事件载荷即运行时快照）。"""
        self._replay_impression(payload)

    def _on_impression_changed(self, payload: dict, tick: int) -> None:
        """任务18 P1：label 翻转，幂等写回条目。"""
        self._replay_impression(payload)

    def _replay_impression(self, payload: dict) -> None:
        observer = self.state.human.agents.get(payload.get("observer_id") or "")
        target_id = payload.get("target_id")
        if observer is None or not target_id:
            return
        try:
            entry = ImpressionEntry(
                label=str(payload.get("label") or ""),
                contracts=int(payload.get("contracts") or 0),
                defaults=int(payload.get("defaults") or 0),
                repays=int(payload.get("repays") or 0),
                last_outcome=payload.get("last_outcome"),
                last_tick=int(payload.get("last_tick") or 0),
            )
        except (TypeError, ValueError):
            return
        observer.impressions[target_id] = entry

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
            agent = self.state.human.agents.get(member_id)
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

    def _on_household_member_transferred(self, payload: dict, tick: int) -> None:
        source_id = payload.get("source_household_id")
        target_id = payload.get("target_household_id")
        agent_id = payload.get("agent_id")
        if not source_id or not target_id or not agent_id:
            return
        source = self.state.human.households.get(source_id)
        target = self.state.human.households.get(target_id)
        if source is None or target is None:
            return
        source.member_ids = list(payload.get("source_members_after", source.member_ids))
        target.member_ids = list(payload.get("target_members_after", target.member_ids))
        source.head_id = payload.get("source_head_after")
        target.head_id = payload.get("target_head_after")
        agent = self._ensure_agent(agent_id, {
            "household_id": target_id,
            "home_node": target.home_node,
            "work_node": target.work_node,
        })
        agent.household_id = target_id
        if "location_after" in payload:
            agent.location = str(payload["location_after"])
        if "work_node_after" in payload:
            agent.work_node = payload["work_node_after"]

    def _on_marriage_assets_transferred(self, payload: dict, tick: int) -> None:
        for household_key, inventory_key in (
            ("from_household_id", "from_inventory_after"),
            ("to_household_id", "to_inventory_after"),
        ):
            household = self.state.human.households.get(payload.get(household_key, ""))
            inventory = payload.get(inventory_key)
            if household is None or not isinstance(inventory, dict):
                continue
            for item, value in inventory.items():
                if item in _ASSET_FIELDS and value is not None:
                    setattr(household, item, max(0.0, round(float(value), 2)))

    def _on_household_head_changed(self, payload: dict, tick: int) -> None:
        household_id = payload.get("household_id")
        new_head_id = payload.get("new_head_id")
        if not household_id or not new_head_id:
            return
        household = self.state.human.households.get(household_id)
        if household is not None:
            household.head_id = new_head_id

    def _on_household_dissolved(self, payload: dict, tick: int) -> None:
        household_id = payload.get("household_id")
        if not household_id:
            return
        household = self.state.human.households.get(household_id)
        if household is not None:
            household.member_ids = []
            household.head_id = None

    # -- 劳作点分配（阶段二 C）--------------------------------------------- #
    def _on_household_work_nodes_changed(self, payload: dict, tick: int) -> None:
        household_id = payload.get("household_id")
        if not household_id:
            return
        household = self.state.human.households.get(household_id)
        if household is not None:
            household.work_nodes = [str(n) for n in (payload.get("after") or [])]

    def _on_agent_work_node_changed(self, payload: dict, tick: int) -> None:
        agent_id = payload.get("agent_id")
        if not agent_id:
            return
        agent = self.state.human.agents.get(agent_id)
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
        child = self.state.human.agents[child_id]
        for parent_key, field_name in (("mother_id", "mother_id"), ("father_id", "father_id")):
            parent_id = payload.get(parent_key)
            if parent_id:
                setattr(child, field_name, parent_id)
                parent = self._ensure_agent(parent_id, payload)
                if child_id not in parent.children_ids:
                    parent.children_ids.append(child_id)
        last_birth_key = payload.get("mother_id")
        if last_birth_key:
            self.state.human.agents[last_birth_key].last_birth_tick = int(
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

    # -- 土地权属、地块与建筑 ----------------------------------------------- #
    def _on_land_parcel_created(self, payload: dict, tick: int) -> None:
        data = payload.get("parcel")
        if not data:
            return
        parcel = LandParcelState.model_validate(data)
        self.state.human.land_parcels[parcel.parcel_id] = parcel

    def _on_land_right_granted(self, payload: dict, tick: int) -> None:
        parcel = self.state.human.land_parcels.get(payload.get("parcel_id"))
        data = payload.get("right")
        if parcel is None or not data:
            return
        right = LandRightState.model_validate(data)
        if not any(item.right_id == right.right_id for item in parcel.use_rights):
            parcel.use_rights.append(right)

    def _on_land_right_revoked(self, payload: dict, tick: int) -> None:
        parcel = self.state.human.land_parcels.get(payload.get("parcel_id"))
        right_id = payload.get("right_id")
        if parcel is not None and right_id:
            parcel.use_rights = [item for item in parcel.use_rights if item.right_id != right_id]

    def _on_land_ownership_transferred(self, payload: dict, tick: int) -> None:
        parcel = self.state.human.land_parcels.get(payload.get("parcel_id"))
        new_owner = payload.get("new_owner_household_id")
        if parcel is not None and new_owner:
            previous_owner = payload.get("previous_owner_household_id")
            parcel.owner_type = "household"
            parcel.owner_id = str(new_owner)
            for building in self.state.human.buildings.values():
                if building.parcel_id == parcel.parcel_id and building.owner_id == previous_owner:
                    building.owner_type = "household"
                    building.owner_id = str(new_owner)

    def _on_land_ownership_inherited(self, payload: dict, tick: int) -> None:
        parcel = self.state.human.land_parcels.get(payload.get("parcel_id"))
        new_owner = payload.get("new_owner_household_id")
        if parcel is None or not new_owner:
            return
        previous_owner = payload.get("previous_owner_household_id")
        parcel.owner_type, parcel.owner_id = "household", str(new_owner)
        parcel.management_authority = None
        for building in self.state.human.buildings.values():
            if building.parcel_id == parcel.parcel_id and building.owner_id == previous_owner:
                building.owner_type, building.owner_id = "household", str(new_owner)

    def _on_land_ownership_escheated(self, payload: dict, tick: int) -> None:
        parcel = self.state.human.land_parcels.get(payload.get("parcel_id"))
        if parcel is None:
            return
        parcel.owner_type = str(payload.get("new_owner_type", "collective"))
        parcel.owner_id = str(payload.get("new_owner_id", "village"))
        parcel.management_authority = "village_council"
        previous_owner = payload.get("previous_owner_household_id")
        for building in self.state.human.buildings.values():
            if building.parcel_id == parcel.parcel_id and building.owner_id == previous_owner:
                building.owner_type, building.owner_id = "collective", "village"

    def _on_land_right_inherited(self, payload: dict, tick: int) -> None:
        parcel = self.state.human.land_parcels.get(payload.get("parcel_id"))
        if parcel is None:
            return
        right_id = payload.get("right_id")
        right = next((item for item in parcel.use_rights if item.right_id == right_id), None)
        if right is not None:
            right.holder_id = str(payload["new_holder_household_id"])
            right.purpose = "inherited"

    def _on_land_use_changed(self, payload: dict, tick: int) -> None:
        parcel = self.state.human.land_parcels.get(payload.get("parcel_id"))
        if parcel is not None and payload.get("after"):
            parcel.land_use = str(payload["after"])
            if payload.get("buildable_area_after") is not None:
                parcel.buildable_area = float(payload["buildable_area_after"])

    def _on_building_created(self, payload: dict, tick: int) -> None:
        data = payload.get("building")
        if not data:
            return
        building = BuildingState.model_validate(data)
        self.state.human.buildings[building.building_id] = building



    def _on_construction_project_created(self, payload: dict, tick: int) -> None:
        data = payload.get("project")
        if not data:
            return
        from vale.domains.society.state import ConstructionProjectState
        project = ConstructionProjectState.model_validate(data)
        self.state.human.construction_projects[project.project_id] = project
        # Rebuild household members from the canonical Brookvale agent config.
        for cfg in self.config.agents.agents:
            household_id = cfg.household_id or _hh_id(cfg.id)
            if household_id == project.household_id:
                self._ensure_agent(cfg.id, {
                    "household_id": household_id,
                    "home_node": cfg.home_node,
                    "work_node": cfg.work_node,
                })
        household = self.state.human.households.get(project.household_id)
        if household:
            for field_name in ("coin", "hardwood"):
                key = f"{field_name}_after"
                if key in payload:
                    setattr(household, field_name, max(0.0, float(payload[key])))

    def _on_construction_worked(self, payload: dict, tick: int) -> None:
        from vale.domains.society.state import ConstructionProjectState
        data = payload.get("project")
        if data:
            project = ConstructionProjectState.model_validate(data)
            self.state.human.construction_projects[project.project_id] = project
        worker_id = payload.get("worker_id")
        worker = self.state.human.agents.get(worker_id)
        if worker is None and worker_id:
            worker = self._ensure_agent(worker_id, payload)
        if worker is not None and payload.get("stamina_after") is not None:
            worker.stamina = float(payload["stamina_after"])

    def _on_construction_paused(self, payload: dict, tick: int) -> None:
        data = payload.get("project")
        if data:
            self.state.human.construction_projects[data["project_id"]] = ConstructionProjectState.model_validate(data)

    def _on_construction_cancelled(self, payload: dict, tick: int) -> None:
        data = payload.get("project")
        if data:
            self.state.human.construction_projects[data["project_id"]] = ConstructionProjectState.model_validate(data)

    def _on_construction_abandoned(self, payload: dict, tick: int) -> None:
        data = payload.get("project")
        if data:
            self.state.human.construction_projects[data["project_id"]] = ConstructionProjectState.model_validate(data)

    # -- 村庄治理：代表、选举、议事会与申诉 -------------------------------
    def _on_representative_registered(self, payload: dict, tick: int) -> None:
        data = payload.get("representative")
        if data:
            from vale.domains.society.state import HouseholdRepresentativeState
            rep = HouseholdRepresentativeState.model_validate(data)
            self.state.human.representatives[rep.household_id] = rep

    def _on_representative_revoked(self, payload: dict, tick: int) -> None:
        rep = self.state.human.representatives.get(payload.get("household_id"))
        if rep:
            rep.active = False

    def _on_election_opened(self, payload: dict, tick: int) -> None:
        from vale.domains.society.state import VillageElectionState
        data = payload.get("election")
        if data:
            election = VillageElectionState.model_validate(data)
            self.state.human.elections[election.election_id] = election

    def _on_candidate_nominated(self, payload: dict, tick: int) -> None:
        election = self.state.human.elections.get(payload.get("election_id"))
        if election:
            candidate = str(payload["candidate_id"])
            election.nominations[candidate] = str(payload["nominated_by_household_id"])
            if candidate not in election.candidates:
                election.candidates.append(candidate)

    def _on_election_vote_cast(self, payload: dict, tick: int) -> None:
        election = self.state.human.elections.get(payload.get("election_id"))
        if election:
            round_key = str(payload.get("round", 1))
            election.votes_by_round.setdefault(round_key, {})[
                str(payload["household_id"])
            ] = str(payload["candidate_id"])

    def _on_election_round_advanced(self, payload: dict, tick: int) -> None:
        election = self.state.human.elections.get(payload.get("election_id"))
        if election:
            election.current_round = int(payload["round"])
            election.status = str(payload.get("status", "voting"))
            if payload.get("candidates") is not None:
                election.candidates = list(payload["candidates"])

    def _on_election_result_declared(self, payload: dict, tick: int) -> None:
        election = self.state.human.elections.get(payload.get("election_id"))
        if election:
            election.winner_id = payload.get("winner_id")
            election.status = str(payload.get("status", "awaiting_recognition"))

    def _on_election_recognized(self, payload: dict, tick: int) -> None:
        election = self.state.human.elections.get(payload.get("election_id"))
        if election:
            election.status = "recognized"
            election.winner_id = str(payload["headman_id"])
            election.deputy_id = payload.get("deputy_id")
            election.recognized_tick = tick
            election.term_start_tick = tick
            election.term_end_tick = int(payload["term_end_tick"])
            self.state.human.headman_id = election.winner_id
            self.state.human.acting_headman_id = None

    def _on_election_rejected(self, payload: dict, tick: int) -> None:
        election = self.state.human.elections.get(payload.get("election_id"))
        if election:
            election.status = "rejected"
            election.rejection_reason = str(payload.get("reason", ""))

    def _on_headman_term_expired(self, payload: dict, tick: int) -> None:
        if self.state.human.headman_id == payload.get("headman_id"):
            self.state.human.headman_id = None
            self.state.human.acting_headman_id = None

    def _on_deputy_activated(self, payload: dict, tick: int) -> None:
        self.state.human.acting_headman_id = str(payload["deputy_id"])

    def _on_council_decision_proposed(self, payload: dict, tick: int) -> None:
        from vale.domains.society.state import CouncilDecisionState
        data = payload.get("decision")
        if data:
            decision = CouncilDecisionState.model_validate(data)
            self.state.human.council_decisions[decision.decision_id] = decision

    def _on_council_vote_cast(self, payload: dict, tick: int) -> None:
        decision = self.state.human.council_decisions.get(payload.get("decision_id"))
        if decision:
            decision.votes[str(payload["household_id"])] = bool(payload["approve"])

    def _on_council_decision_resolved(self, payload: dict, tick: int) -> None:
        decision = self.state.human.council_decisions.get(payload.get("decision_id"))
        if decision:
            decision.status = str(payload["status"])
            decision.resolved_tick = tick

    def _on_appeal_submitted(self, payload: dict, tick: int) -> None:
        from vale.domains.society.state import AppealState
        data = payload.get("appeal")
        if data:
            appeal = AppealState.model_validate(data)
            self.state.human.appeals[appeal.appeal_id] = appeal

    def _on_appeal_resolved(self, payload: dict, tick: int) -> None:
        appeal = self.state.human.appeals.get(payload.get("appeal_id"))
        if appeal:
            appeal.status = "resolved"
            appeal.outcome = str(payload["outcome"])
            appeal.review_decision_id = payload.get("review_decision_id")
            appeal.resolved_tick = tick

    # -- 校验 --------------------------------------------------------------- #
    def _validate(self) -> None:
        for agent in self.state.human.agents.values():
            if not agent.household_id or agent.household_id not in self.state.human.households:
                raise ValueError(f"replay: orphan agent {agent.agent_id}")
        for household in self.state.human.households.values():
            if household.member_ids and household.head_id not in household.member_ids:
                raise ValueError(f"replay: head {household.head_id} not in {household.household_id}")
            for member_id in household.member_ids:
                if member_id not in self.state.human.agents:
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


def rebuild_state(events: list[dict], config) -> ReplayResult:
    """只读重放事件流为家庭状态（旧库 → 单人家庭；新库 → 按 household_id）。"""
    replayer = _Replayer(config, start_tick=config.world.start_tick)
    return replayer.replay(events)
