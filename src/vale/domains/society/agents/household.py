"""家庭日常：同住/同工接触形成认知、日常用水结算。"""

from __future__ import annotations

from vale.config.schema.agents import AgentTuning
from vale.core.household import home_node_of, work_node_of
from vale.core.state import AgentState
from vale.domains.society import social
from vale.domains.society.agents.demographics import living_agents


class HouseholdMixin:

    def _record_shared_location_interactions(self, world, tuning: AgentTuning) -> None:
        """共同居住或工作节点视为有日常接触；只更新双向认知，不污染短期互动记忆。"""
        groups: dict[str, list[AgentState]] = {}
        for agent in living_agents(world.state.human.agents):
            meeting_nodes = {
                node for node in (work_node_of(world, agent), home_node_of(world, agent))
                if node
            }
            for node in meeting_nodes:
                groups.setdefault(node, []).append(agent)

        seen_pairs: set[tuple[str, str]] = set()
        for node in sorted(groups):
            members = sorted(groups[node], key=lambda item: item.agent_id)
            if len(members) < 2:
                continue
            # 轮转配对：每 tick 只生成 O(n) 次接触，跨日轮换覆盖同一地点的人群。
            offset = 1 + ((world.current_tick - 1) % (len(members) - 1))
            for index, observer in enumerate(members):
                target = members[(index + offset) % len(members)]
                if observer.household_id == target.household_id:
                    continue
                pair = tuple(sorted((observer.agent_id, target.agent_id)))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                view_a = social.get_social_view(
                    world.state, observer.agent_id, target.agent_id,
                    world.current_tick, tuning.social.acquaintance_ttl,
                )
                view_b = social.get_social_view(
                    world.state, target.agent_id, observer.agent_id,
                    world.current_tick, tuning.social.acquaintance_ttl,
                )
                if view_a["known"] and view_b["known"]:
                    continue
                social.upgrade_acquaintance(
                    world, observer.agent_id, target.agent_id, world.current_tick,
                    cause="interaction", location_source=f"shared:{node}",
                )
                social.upgrade_acquaintance(
                    world, target.agent_id, observer.agent_id, world.current_tick,
                    cause="interaction", location_source=f"shared:{node}",
                )

    def _settle_water(self, world, tuning: AgentTuning) -> None:
        """按存活成员扣除日常饮水；缺口只记账，不在本版直接扣健康。"""
        per_member = tuning.water.daily_consumption_per_member
        if per_member <= 0:
            return
        for household in world.state.human.households.values():
            members = [
                m for m in household.member_ids
                if m in world.state.human.agents and world.state.human.agents[m].alive
            ]
            if not members:
                continue
            need = round(per_member * len(members), 2)
            before = max(0.0, float(household.water))
            consumed = min(before, need)
            after = round(max(0.0, before - need), 2)
            shortage = round(max(0.0, need - before), 2)
            household.water = after
            if consumed > 0:
                world.event_log.append(
                    world.current_tick,
                    "water_consumed",
                    {
                        "household_id": household.household_id,
                        "member_count": len(members),
                        "need": need,
                        "amount": round(consumed, 2),
                        "shortage": shortage,
                        "before": round(before, 2),
                        "after": after,
                    },
                )
            if shortage > 0:
                world.event_log.append(
                    world.current_tick,
                    "water_shortage",
                    {
                        "household_id": household.household_id,
                        "member_count": len(members),
                        "need": need,
                        "available": round(before, 2),
                        "shortage": shortage,
                        "health_penalty_applied": False,
                    },
                )
