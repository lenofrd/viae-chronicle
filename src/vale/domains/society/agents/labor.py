"""家庭劳动：可劳作成员计数、可分配田块对账与当日分工计划。"""

from __future__ import annotations

from vale.config.schema.agents import AgentTuning
from vale.contracts.queries import SpatialQuery
from vale.core.household import home_node_of, living_households
from vale.core.state import HouseholdState
from vale.domains.society.agents.constants import IMPOSSIBLE
from vale.domains.society.agents.demographics import age_years, living_agents
from vale.domains.society.agents.spatial import SpatialIndex


class LaborMixin:

    def _work_capable_count(self, world, household: HouseholdState,
                            tuning: AgentTuning) -> int:
        """户内可劳作存活成员数（年龄分段 work_allowed；确定性计数，不依赖 life_stage 投影）。"""
        count = 0
        for member_id in household.member_ids:
            member = world.state.human.agents.get(member_id)
            if member is None or not member.alive:
                continue
            stage = tuning.aging.stage_for(age_years(member.birth_tick, world.current_tick))
            if stage.work_allowed:
                count += 1
        return count

    def _desired_work_nodes(self, world, household: HouseholdState,
                            tuning: AgentTuning) -> list[str]:
        """家庭可分配田块（labor.allocation_policy=deterministic_distance）。

        默认田排首位（保证单人户与既有 work_node_of 等价），其余可达田按
        「家→田距离升序、节点 id 升序」补足；列表长度取可劳作成员数（至少 1）。
        家庭默认劳作点不是田（如集市）时返回空表，保持既有语义、不做田块分配。
        """
        field_ids = list(SpatialQuery.field_ids(world))
        if household.work_node not in field_ids:
            return []
        if self._spatial is None:
            self._spatial = SpatialIndex(world.config.spatial)
        default = household.work_node
        others = sorted(
            (fid for fid in field_ids
             if fid != default
             and self._spatial.travel_tu(household.home_node, fid) != float("inf")),
            key=lambda fid: (self._spatial.travel_tu(household.home_node, fid), fid),
        )
        workers = max(1, self._work_capable_count(world, household, tuning))
        return ([default] + others)[:workers]

    def _reconcile_work_nodes(self, world, tuning: AgentTuning) -> None:
        """每 tick 对账：家庭可分配田块重算 + 个人偏好失效回收（确定性，无随机）。

        - 家庭列表变化写 ``household_work_nodes_changed``（before/after/reason）；
        - 个人偏好指向不存在或不可达节点时置 None，写 ``agent_work_node_changed``
          （reason=preference_invalid）。
        """
        if self._spatial is None:
            self._spatial = SpatialIndex(world.config.spatial)
        for household in living_households(world):
            desired = self._desired_work_nodes(world, household, tuning)
            if desired == household.work_nodes:
                continue
            before = list(household.work_nodes)
            household.work_nodes = desired
            world.event_log.append(
                world.current_tick,
                "household_work_nodes_changed",
                {
                    "household_id": household.household_id,
                    "home_node": household.home_node,
                "well_distance_tu": (
                    round(self._spatial.travel_tu(household.home_node, "well"), 3)
                    if self._spatial is not None else None
                ),
                    "before": before,
                    "after": list(desired),
                    "reason": "reassigned",
                    "work_capable_members": self._work_capable_count(
                        world, household, tuning
                    ),
                },
            )
        node_ids = {n.id for n in world.config.spatial.nodes}
        for agent in living_agents(world.state.human.agents):
            if not agent.work_node:
                continue
            if agent.work_node in node_ids and (
                self._spatial.travel_tu(home_node_of(world, agent), agent.work_node)
                != float("inf")
            ):
                continue
            before = agent.work_node
            agent.work_node = None
            world.event_log.append(
                world.current_tick,
                "agent_work_node_changed",
                {
                    "agent_id": agent.agent_id,
                    "agent_name": agent.name,
                    "household_id": agent.household_id,
                    "before": before,
                    "after": None,
                    "reason": "preference_invalid",
                },
            )

    def _plan_household_work(self, world, tuning: AgentTuning) -> dict[str, str]:
        """Allocate distinct feasible daily tasks across each household's capable members.

        Assignments are preferences, not locks: urgent eating, water and rest needs
        still override them. Extra workers reinforce the best remaining task.
        """
        assignments: dict[str, str] = {}
        excluded = {"eat", "rest", "borrow_grain", "borrow_food"}
        for household in living_households(world):
            workers = []
            for member_id in household.member_ids:
                member = world.state.human.agents.get(member_id)
                if member is None or not member.alive or member.incapacitated:
                    continue
                stage = tuning.aging.stage_for(age_years(member.birth_tick, world.current_tick))
                if stage.work_allowed:
                    workers.append(member)
            # Single-worker households have no division to coordinate; leave their
            # existing utility-driven behavior untouched.
            if len(workers) < 2:
                continue
            workers.sort(key=lambda item: item.agent_id)
            offset = (world.current_tick - 1) % len(workers)
            rotated = workers[offset:] + workers[:offset]
            rank = {member.agent_id: index for index, member in enumerate(rotated)}
            by_action: dict[str, list[tuple[float, int, str]]] = {}
            by_member: dict[str, list[tuple[float, str]]] = {}
            for member in workers:
                perception = self._perceive(world, member)
                options = []
                for action in self._candidate_actions_for(member, tuning):
                    if action in excluded:
                        continue
                    score = self.score_action(action, perception, tuning)
                    if score == IMPOSSIBLE or score <= 0:
                        continue
                    options.append((score, action))
                    by_action.setdefault(action, []).append((score, rank[member.agent_id], member.agent_id))
                by_member[member.agent_id] = options
            task_order = sorted(
                by_action,
                key=lambda action: (-max(item[0] for item in by_action[action]), action),
            )
            assigned_members: set[str] = set()
            for action in task_order:
                choices = sorted(by_action[action], key=lambda item: (-item[0], item[1], item[2]))
                choice = next((item for item in choices if item[2] not in assigned_members), None)
                if choice is None:
                    continue
                assignments[choice[2]] = action
                assigned_members.add(choice[2])
            for member in rotated:
                if member.agent_id in assigned_members:
                    continue
                options = sorted(by_member.get(member.agent_id, []), key=lambda item: (-item[0], item[1]))
                if options:
                    assignments[member.agent_id] = options[0][1]
            household_plan = {
                member_id: action for member_id, action in assignments.items()
                if member_id in household.member_ids
            }
            if household_plan:
                world.event_log.append(world.current_tick, "household_work_plan_created", {
                    "household_id": household.household_id,
                    "assignments": household_plan,
                    "worker_count": len(workers),
                    "distinct_task_count": len(set(household_plan.values())),
                })
        return assignments
