"""Event-sourced village governance for the existing Brookvale settlement.

One active adult representative per household; village headman elections are
community-led but require county recognition. Council votes enforce quorum,
supermajorities for major matters, and recusal for direct household interests.
"""
from __future__ import annotations

import math

from vale.core.calendar import DAYS_PER_YEAR
from vale.domains.society.state import AppealState, CouncilDecisionState, HouseholdRepresentativeState, VillageElectionState
from vale.domains.society.agents.demographics import age_years


def _adult_alive(world, agent_id: str) -> bool:
    agent = world.state.human.agents.get(agent_id)
    return bool(agent and agent.alive and not agent.incapacitated
                and age_years(agent.birth_tick, world.current_tick) >= 18)


def _active_representatives(world):
    return {
        household_id: rep
        for household_id, rep in world.state.human.representatives.items()
        if rep.active and household_id in world.state.human.households
        and rep.agent_id in world.state.human.households[household_id].member_ids
        and _adult_alive(world, rep.agent_id)
    }


def register_representative(world, household_id: str, agent_id: str):
    household = world.state.human.households.get(household_id)
    if household is None or agent_id not in household.member_ids:
        raise ValueError("representative must belong to the household")
    existing = world.state.human.representatives.get(household_id)
    if existing is not None and existing.active:
        raise ValueError("household already has an active representative")
    if not _adult_alive(world, agent_id):
        raise ValueError("representative must be a living, capable adult")
    rep = HouseholdRepresentativeState(
        household_id=household_id, agent_id=agent_id,
        appointed_tick=world.current_tick,
    )
    world.event_log.append(world.current_tick, "representative_registered", {
        "representative": rep.model_dump(mode="json"),
    })
    world.state.human.representatives[household_id] = rep
    return rep


def revoke_representative(world, household_id: str, *, reason: str):
    rep = world.state.human.representatives.get(household_id)
    if rep is None or not rep.active:
        raise ValueError("household has no active representative")
    world.event_log.append(world.current_tick, "representative_revoked", {
        "household_id": household_id, "agent_id": rep.agent_id, "reason": reason,
    })
    rep.active = False


def open_election(world, election_id: str):
    if election_id in world.state.human.elections:
        raise ValueError("election id already exists")
    if world.state.human.headman_id:
        raise ValueError("a recognized headman is still in office")
    reps = _active_representatives(world)
    required = math.ceil(2 * len(world.state.human.households) / 3)
    if len(reps) < required:
        raise ValueError("election requires two-thirds household representation")
    election = VillageElectionState(election_id=election_id)
    world.event_log.append(world.current_tick, "election_opened", {
        "election": election.model_dump(mode="json"),
    })
    world.state.human.elections[election_id] = election
    return election


def nominate_candidate(world, election_id: str, candidate_id: str, nominating_household_id: str):
    election = world.state.human.elections.get(election_id)
    if election is None or election.status != "nominating":
        raise ValueError("election is not accepting nominations")
    reps = _active_representatives(world)
    if nominating_household_id not in reps:
        raise ValueError("candidate must be nominated by an active household representative")
    if not _adult_alive(world, candidate_id):
        raise ValueError("candidate must be a living, capable adult")
    if candidate_id not in {a.agent_id for a in world.state.human.agents.values()
                            if a.alive and not a.incapacitated}:
        raise ValueError("candidate must be a village resident")
    if candidate_id in election.candidates:
        return election
    world.event_log.append(world.current_tick, "candidate_nominated", {
        "election_id": election_id, "candidate_id": candidate_id,
        "nominated_by_household_id": nominating_household_id,
    })
    election.nominations[candidate_id] = nominating_household_id
    election.candidates.append(candidate_id)
    return election


def close_nominations(world, election_id: str):
    election = world.state.human.elections[election_id]
    if election.status != "nominating" or len(election.candidates) < 2:
        raise ValueError("at least two candidates are required")
    election.status = "voting"
    world.event_log.append(world.current_tick, "election_round_advanced", {
        "election_id": election_id, "round": 1, "status": "voting",
    })


def cast_election_vote(world, election_id: str, representative_agent_id: str,
                       candidate_id: str, *, round_no: int | None = None):
    election = world.state.human.elections.get(election_id)
    round_no = round_no or (election.current_round if election else 0)
    if election is None or election.status != "voting" or round_no != election.current_round:
        raise ValueError("election is not accepting votes for this round")
    household_id = next((hid for hid, rep in _active_representatives(world).items()
                         if rep.agent_id == representative_agent_id), None)
    if household_id is None:
        raise ValueError("voter must be an active household representative")
    if candidate_id not in election.candidates:
        raise ValueError("vote must target a nominated candidate")
    votes = election.votes_by_round.setdefault(str(round_no), {})
    if household_id in votes:
        raise ValueError("each household has one vote per round")
    world.event_log.append(world.current_tick, "election_vote_cast", {
        "election_id": election_id, "round": round_no,
        "household_id": household_id, "representative_agent_id": representative_agent_id,
        "candidate_id": candidate_id,
    })
    votes[household_id] = candidate_id


def tally_election(world, election_id: str):
    election = world.state.human.elections[election_id]
    if election.status != "voting":
        raise ValueError("election is not in voting state")
    votes = election.votes_by_round.get(str(election.current_round), {})
    required_quorum = math.ceil(2 * len(_active_representatives(world)) / 3)
    if len(votes) < required_quorum:
        raise ValueError("election round did not reach the two-thirds voting quorum")
    counts = {candidate: sum(v == candidate for v in votes.values())
              for candidate in election.candidates}
    total = len(votes)
    if total == 0:
        raise ValueError("cannot tally an election without valid votes")
    winner = None
    if election.current_round == 1:
        for candidate, count in counts.items():
            if count >= math.ceil(2 * total / 3):
                winner = candidate
                break
        if winner is None:
            ranked = sorted(counts, key=lambda c: (-counts[c], c))
            if len(ranked) < 2:
                raise ValueError("runoff requires two candidates")
            election.current_round = 2
            election.candidates = ranked[:2]
            world.event_log.append(world.current_tick, "election_round_advanced", {
                "election_id": election_id, "round": 2, "status": "voting",
                "candidates": list(election.candidates),
            })
            return {"status": "runoff", "candidates": election.candidates}
    else:
        ranked = sorted(counts, key=lambda c: (-counts[c], c))
        if counts[ranked[0]] > total / 2:
            winner = ranked[0]
    if winner is None:
        election.status = "failed"
        world.event_log.append(world.current_tick, "election_result_declared", {
            "election_id": election_id, "winner_id": None, "status": "failed",
        })
        return {"status": "failed"}
    election.winner_id = winner
    election.status = "awaiting_recognition"
    world.event_log.append(world.current_tick, "election_result_declared", {
        "election_id": election_id, "winner_id": winner,
        "status": "awaiting_recognition",
    })
    return {"status": election.status, "winner_id": winner}


def recognize_election(world, election_id: str, *, approved: bool,
                       county_reason: str = "", deputy_id: str | None = None):
    election = world.state.human.elections.get(election_id)
    if election is None or election.status != "awaiting_recognition" or not election.winner_id:
        raise ValueError("election has no result awaiting county recognition")
    if not approved:
        if not county_reason.strip():
            raise ValueError("county rejection must state its reason")
        election.status = "rejected"
        election.rejection_reason = county_reason
        world.event_log.append(world.current_tick, "election_rejected", {
            "election_id": election_id, "reason": county_reason,
        })
        return election
    if deputy_id and not _adult_alive(world, deputy_id):
        raise ValueError("deputy must be a living, capable adult")
    term_end = world.current_tick + 3 * DAYS_PER_YEAR
    election.status = "recognized"
    election.deputy_id = deputy_id
    election.recognized_tick = world.current_tick
    election.term_start_tick = world.current_tick
    election.term_end_tick = term_end
    world.state.human.headman_id = election.winner_id
    world.state.human.acting_headman_id = None
    world.event_log.append(world.current_tick, "election_recognized", {
        "election_id": election_id, "headman_id": election.winner_id,
        "deputy_id": deputy_id, "term_end_tick": term_end,
    })
    return election


def expire_headman_term(world):
    headman_id = world.state.human.headman_id
    if not headman_id:
        return False
    current = next((e for e in world.state.human.elections.values()
                    if e.status == "recognized" and e.winner_id == headman_id
                    and e.term_end_tick is not None), None)
    if current is None or world.current_tick < current.term_end_tick:
        return False
    world.event_log.append(world.current_tick, "headman_term_expired", {
        "headman_id": headman_id, "election_id": current.election_id,
    })
    world.state.human.headman_id = None
    world.state.human.acting_headman_id = None
    return True


def activate_deputy(world, *, reason: str):
    headman_id = world.state.human.headman_id
    election = next((e for e in world.state.human.elections.values()
                    if e.status == "recognized" and e.winner_id == headman_id), None)
    if election is None or not election.deputy_id or _adult_alive(world, headman_id):
        raise ValueError("deputy activation requires an unavailable headman")
    if not _adult_alive(world, election.deputy_id):
        raise ValueError("appointed deputy is unavailable")
    world.event_log.append(world.current_tick, "deputy_activated", {
        "headman_id": headman_id, "deputy_id": election.deputy_id, "reason": reason,
    })
    world.state.human.acting_headman_id = election.deputy_id
    return election.deputy_id


def propose_council_decision(world, decision_id: str, *, subject: str,
                             proposer_agent_id: str, affected_household_ids=(),
                             major: bool = False, appeal_id: str | None = None):
    if decision_id in world.state.human.council_decisions:
        raise ValueError("decision id already exists")
    reps = _active_representatives(world)
    recused = sorted(set(affected_household_ids) & set(reps))
    eligible = len(reps) - len(recused)
    quorum = math.ceil(2 * len(reps) / 3)
    if eligible < quorum:
        raise ValueError("conflicts of interest leave fewer than two-thirds eligible representatives")
    approval = math.ceil(2 * eligible / 3) if major else (eligible // 2 + 1)
    decision = CouncilDecisionState(
        decision_id=decision_id, subject=subject,
        proposer_agent_id=proposer_agent_id,
        affected_household_ids=sorted(set(affected_household_ids)),
        major=major, appeal_id=appeal_id,
        recused_household_ids=recused,
        quorum_required=quorum, approval_required=approval,
        created_tick=world.current_tick,
    )
    world.event_log.append(world.current_tick, "council_decision_proposed", {
        "decision": decision.model_dump(mode="json"),
    })
    world.state.human.council_decisions[decision_id] = decision
    return decision


def cast_council_vote(world, decision_id: str, representative_agent_id: str, approve: bool):
    decision = world.state.human.council_decisions.get(decision_id)
    if decision is None or decision.status != "voting":
        raise ValueError("council decision is not open for voting")
    household_id = next((hid for hid, rep in _active_representatives(world).items()
                         if rep.agent_id == representative_agent_id), None)
    if household_id is None:
        raise ValueError("voter must be an active household representative")
    if household_id in decision.recused_household_ids:
        raise ValueError("representative must recuse for a direct household interest")
    if household_id in decision.votes:
        raise ValueError("each household has one vote")
    world.event_log.append(world.current_tick, "council_vote_cast", {
        "decision_id": decision_id, "household_id": household_id,
        "representative_agent_id": representative_agent_id, "approve": bool(approve),
    })
    decision.votes[household_id] = bool(approve)
    if len(decision.votes) >= decision.quorum_required:
        yes = sum(decision.votes.values())
        no = len(decision.votes) - yes
        eligible_count = len(_active_representatives(world)) - len(decision.recused_household_ids)
        if yes >= decision.approval_required or no > eligible_count - decision.approval_required:
            decision.status = "approved" if yes >= decision.approval_required else "rejected"
            decision.resolved_tick = world.current_tick
            world.event_log.append(world.current_tick, "council_decision_resolved", {
                "decision_id": decision_id, "status": decision.status,
            })
    return decision


def submit_appeal(world, appeal_id: str, *, applicant_agent_id: str,
                  original_decision_id: str, grounds: str):
    original = world.state.human.council_decisions.get(original_decision_id)
    if original is None or original.status not in {"approved", "rejected"}:
        raise ValueError("appeal requires a resolved original council decision")
    if appeal_id in world.state.human.appeals or not grounds.strip():
        raise ValueError("appeal id must be new and grounds must be stated")
    appeal = AppealState(
        appeal_id=appeal_id, applicant_agent_id=applicant_agent_id,
        original_decision_id=original_decision_id, grounds=grounds,
        created_tick=world.current_tick,
    )
    world.event_log.append(world.current_tick, "appeal_submitted", {
        "appeal": appeal.model_dump(mode="json"),
    })
    world.state.human.appeals[appeal_id] = appeal
    return appeal


def resolve_appeal(world, appeal_id: str, *, review_decision_id: str, outcome: str):
    appeal = world.state.human.appeals.get(appeal_id)
    decision = world.state.human.council_decisions.get(review_decision_id)
    if appeal is None or appeal.status != "pending":
        raise ValueError("appeal is not pending")
    if decision is None or decision.status != "approved" or decision.appeal_id != appeal_id:
        raise ValueError("appeal outcome requires an approved council review decision")
    if outcome not in {"upheld", "amended", "overturned", "remanded"}:
        raise ValueError("unsupported appeal outcome")
    appeal.status = "resolved"
    appeal.review_decision_id = review_decision_id
    appeal.outcome = outcome
    appeal.resolved_tick = world.current_tick
    world.event_log.append(world.current_tick, "appeal_resolved", {
        "appeal_id": appeal_id, "review_decision_id": review_decision_id,
        "outcome": outcome,
    })
    return appeal
