"""人物投影：人物状态、生命周期、劳作簿记、认知与印象。

SocietyProjection 的组成部分；统一注册入口见 ``__init__``。
"""
from __future__ import annotations

from vale.domains.society.social import record_memory
from vale.domains.society.state import AcquaintanceEntry, ImpressionEntry

from .base import _ASSET_FIELDS, SocietyProjectionBase


class PeopleProjection(SocietyProjectionBase):
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

    def _on_wildlife_attack(self, payload: dict, tick: int) -> None:
        agent_id = payload.get("agent_id")
        agent = self.state.human.agents.get(agent_id) if agent_id else None
        if agent is not None and payload.get("health_after") is not None:
            agent.health = max(0.0, float(payload["health_after"]))
            agent.last_injury_tick = tick

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
