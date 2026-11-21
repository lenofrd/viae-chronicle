"""土地治理投影：租约产权、建筑建造、村庄治理。

SocietyProjection 的组成部分；统一注册入口见 ``__init__``。
"""
from __future__ import annotations

from vale.domains.society.state import (
    AppealState,
    BuildingNeedState,
    BuildingState,
    ConstructionProjectState,
    CouncilDecisionState,
    HouseholdRepresentativeState,
    LandParcelState,
    LandRightState,
    VillageElectionState,
)

from .base import _hh_id, SocietyProjectionBase


class LandGovernanceProjection(SocietyProjectionBase):
    def _on_land_lease_created(self, payload: dict, tick: int) -> None:
        lease = payload.get("lease")
        if lease:
            self.state.human.land_leases[lease["lease_id"]] = dict(lease)
            parcel = self.state.human.land_parcels.get(lease.get("parcel_id"))
            right = payload.get("land_right")
            if parcel is not None and right:
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

    def _on_building_condition_changed(self, payload: dict, tick: int) -> None:
        building = self.state.human.buildings.get(payload.get("building_id", ""))
        if building is None:
            return
        if payload.get("condition_after") is not None:
            building.condition = float(payload["condition_after"])
        if payload.get("status_after") is not None:
            building.status = str(payload["status_after"])

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

    def _on_representative_registered(self, payload: dict, tick: int) -> None:
        data = payload.get("representative")
        if data:
            rep = HouseholdRepresentativeState.model_validate(data)
            self.state.human.representatives[rep.household_id] = rep

    def _on_representative_revoked(self, payload: dict, tick: int) -> None:
        rep = self.state.human.representatives.get(payload.get("household_id"))
        if rep:
            rep.active = False

    def _on_election_opened(self, payload: dict, tick: int) -> None:
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
