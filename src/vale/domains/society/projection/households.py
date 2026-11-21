"""家庭投影：注册/分户/并户/迁移/户主、资产与继承。

SocietyProjection 的组成部分；统一注册入口见 ``__init__``。
"""
from __future__ import annotations

from vale.domains.society.state import DebtRecord

from .base import _ASSET_FIELDS, SocietyProjectionBase


class HouseholdProjection(SocietyProjectionBase):
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

    def _on_household_work_nodes_changed(self, payload: dict, tick: int) -> None:
        household_id = payload.get("household_id")
        if not household_id:
            return
        household = self.state.human.households.get(household_id)
        if household is not None:
            household.work_nodes = [str(n) for n in (payload.get("after") or [])]
