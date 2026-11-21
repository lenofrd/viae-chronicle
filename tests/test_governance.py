from __future__ import annotations

import pytest

from vale.core.calendar import DAYS_PER_YEAR
from vale.core.config_loader import LoadedConfig, load_config
from vale.core.event_log import EventLog
from vale.core.replay import rebuild_state
from vale.core.world import World
from vale.modules.agents import AgentModule
from vale.modules.governance import (
    cast_council_vote, cast_election_vote, close_nominations,
    nominate_candidate, open_election, propose_council_decision,
    recognize_election, register_representative, submit_appeal,
    tally_election, resolve_appeal,
)
from vale.worldgen.xigu import build_xigu_agents_config, generate_xigu_town


def make_world():
    base = load_config("brookvale-town-001")
    generated = generate_xigu_town(base_spatial=base.spatial)
    config = LoadedConfig(
        world=base.world, natural_params=base.natural_params,
        spatial=generated.spatial,
        agents=build_xigu_agents_config(generated, base.agents.tuning, base.agents),
        terrain=generated.terrain,
        resources=generated.resources,
    )
    log = EventLog(":memory:")
    world = World(config.world.world_id, log, config.world.start_tick, config)
    AgentModule()._ensure_agents(world, config.agents)
    return world, log, config


def register_all(world):
    for household in world.state.human.households.values():
        adult = next((world.state.human.agents[aid] for aid in household.member_ids
                      if world.state.human.agents[aid].alive
                      and (world.current_tick - world.state.human.agents[aid].birth_tick) // 365 >= 18), None)
        if adult:
            register_representative(world, household.household_id, adult.agent_id)


def test_election_requires_quorum_two_rounds_and_county_recognition():
    world, log, config = make_world()
    try:
        register_all(world)
        reps = list(world.state.human.representatives.values())
        assert len(reps) >= 20
        with pytest.raises(ValueError, match="already has an active representative"):
            register_representative(world, reps[0].household_id, reps[0].agent_id)
        election = open_election(world, "election-001")
        candidates = [r.agent_id for r in reps[:2]]
        nominate_candidate(world, election.election_id, candidates[0], reps[0].household_id)
        nominate_candidate(world, election.election_id, candidates[1], reps[1].household_id)
        close_nominations(world, election.election_id)
        for rep in reps[:2]:
            cast_election_vote(world, election.election_id, rep.agent_id, candidates[0])
        with pytest.raises(ValueError, match="two-thirds voting quorum"):
            tally_election(world, election.election_id)
        # Complete a balanced first round: quorum is met, but nobody has two-thirds.
        for index, rep in enumerate(reps[2:], start=2):
            cast_election_vote(world, election.election_id, rep.agent_id,
                               candidates[index % 2])
        result = tally_election(world, election.election_id)
        assert result["status"] == "runoff"
        for rep in reps:
            cast_election_vote(world, election.election_id, rep.agent_id, candidates[0])
        result = tally_election(world, election.election_id)
        assert result["status"] == "awaiting_recognition"
        recognize_election(world, election.election_id, approved=True,
                           deputy_id=candidates[1])
        assert world.state.human.headman_id == result["winner_id"]
        election_state = world.state.human.elections[election.election_id]
        assert election_state.term_end_tick - election_state.term_start_tick == 3 * DAYS_PER_YEAR
        governance_types = {
            "representative_registered", "election_opened", "candidate_nominated",
            "election_round_advanced", "election_vote_cast",
            "election_result_declared", "election_recognized",
        }
        replayed = rebuild_state(
            [event for event in log.all() if event["event_type"] in governance_types],
            config,
        ).state
        assert replayed.human.headman_id == world.state.human.headman_id
    finally:
        log.close()


def test_council_majority_recusal_and_appeal_review_replay():
    world, log, config = make_world()
    try:
        register_all(world)
        reps = list(world.state.human.representatives.values())
        affected = reps[0].household_id
        decision = propose_council_decision(
            world, "decision-001", subject="land_use_change",
            proposer_agent_id=reps[1].agent_id,
            affected_household_ids=[affected], major=True,
        )
        with pytest.raises(ValueError, match="recuse"):
            cast_council_vote(world, decision.decision_id, reps[0].agent_id, True)
        for rep in reps[1:]:
            if rep.household_id not in decision.recused_household_ids:
                cast_council_vote(world, decision.decision_id, rep.agent_id, True)
                if decision.status != "voting":
                    break
        assert decision.status == "approved"
        appeal = submit_appeal(
            world, "appeal-001", applicant_agent_id=reps[0].agent_id,
            original_decision_id=decision.decision_id, grounds="procedural error",
        )
        review = propose_council_decision(
            world, "decision-002", subject="appeal_review",
            proposer_agent_id=reps[1].agent_id, major=False, appeal_id=appeal.appeal_id,
        )
        for rep in reps[1:]:
            if rep.household_id not in review.recused_household_ids:
                cast_council_vote(world, review.decision_id, rep.agent_id, True)
                if review.status != "voting":
                    break
        resolve_appeal(world, appeal.appeal_id,
                       review_decision_id=review.decision_id, outcome="remanded")
        governance_types = {
            "representative_registered", "council_decision_proposed",
            "council_vote_cast", "council_decision_resolved",
            "appeal_submitted", "appeal_resolved",
        }
        replayed = rebuild_state(
            [event for event in log.all() if event["event_type"] in governance_types],
            config,
        ).state
        assert replayed.human.appeals["appeal-001"].outcome == "remanded"
    finally:
        log.close()
