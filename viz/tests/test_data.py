from __future__ import annotations

import json

from viz.data import (
    DEFAULT_FIXTURE,
    EventSource,
    agent_profile,
    event_details,
    event_households,
    event_locations,
    event_people,
    filter_events,
    focus_category,
    focus_events,
    group_events,
    household_profile,
    turning_point,
)


def event(event_id, tick, event_type, **payload):
    return {"id": event_id, "tick": tick, "event_type": event_type, "payload": payload}


def test_default_fixture_loads_all_legacy_events():
    events = EventSource.fixture().load()
    assert DEFAULT_FIXTURE.name == "legacy_events.json"
    assert len(events) == 1567
    assert events[0]["id"] == 1
    assert isinstance(events[0]["payload"], dict)


def test_filter_is_inclusive_and_matches_participants():
    events = [
        event(1, 0, "weather_changed"),
        event(2, 1, "agent_action_taken", agent_id="a", agent_name="阿远"),
        event(3, 2, "agent_married", participants=[{"id": "b", "name": "阿秀"}]),
        event(4, 3, "agent_action_taken", agent_id="a", agent_name="阿远"),
    ]
    assert [e["id"] for e in filter_events(events, tick_from=1, tick_to=2)] == [2, 3]
    assert [e["id"] for e in filter_events(events, agent="阿秀")] == [3]
    assert [e["id"] for e in filter_events(events, agent="a", tick_to=1)] == [2]


def test_filter_by_household_location_and_type():
    events = [
        event(1, 0, "agent_action_taken", agent_id="a", household_id="hh_a", target_node="field"),
        event(2, 0, "trade_executed", buyer_id="b", market_node="market"),
        event(3, 1, "agent_action_taken", agent_id="b", household_id="hh_b", target_node="water"),
    ]
    assert [e["id"] for e in filter_events(events, household="hh_a")] == [1]
    assert [e["id"] for e in filter_events(events, location="market")] == [2]
    assert [e["id"] for e in filter_events(events, event_types="trade_executed")] == [2]


def test_event_projection_extracts_people_households_and_locations():
    evt = event(
        1, 0, "debt_defaulted",
        debtor_id="d", debtor_name="欠债人", creditor_id="c", creditor_name="债权人",
        debtor_household_id="hh_d", creditor_household_id="hh_c", market_node="market",
    )
    people = event_people(evt)
    assert {p.get("id") for p in people} == {"d", "c"}
    assert set(event_households(evt)) == {"hh_d", "hh_c"}
    assert event_locations(evt) == ["market"]


def test_three_grouping_modes():
    events = [
        event(1, 0, "agent_action_taken", agent_id="a", action="farm"),
        event(2, 0, "agent_action_taken", agent_id="a", action="rest"),
        event(3, 1, "agent_action_taken", agent_id="a", action="farm"),
    ]
    assert len(group_events(events, "event")) == 3
    days = group_events(events, "day")
    assert [g.key for g in days] == ["day:0", "day:1"]
    assert days[0].event_ids == [1, 2]
    clusters = group_events(events, "cluster")
    assert len(clusters) == 2
    assert clusters[0].event_ids == [1, 2]
    assert group_events(events, "day")[0].label == "Tick 0"


def test_focus_categories_and_turning_points():
    work = event(1, 0, "agent_action_taken", agent_id="a", action="farm")
    social = event(2, 0, "agent_married", agent_id="a")
    economy = event(3, 0, "trade_executed", buyer_id="b")
    ignored = event(4, 0, "weather_changed")
    events = [work, social, economy, ignored]
    assert focus_category(work) == "work"
    assert focus_category(social) == "social"
    assert focus_category(economy) == "economy"
    assert focus_category(ignored) == ""
    assert [e["id"] for e in focus_events(events, "economy")] == [3]
    assert turning_point(social) == "婚配"
    assert turning_point(event(5, 0, "debt_defaulted")) == "债务违约"
    assert turning_point(ignored) == ""


def test_agent_and_household_profiles():
    events = [
        event(1, 0, "agent_born", agent_id="a", agent_name="阿远", child_id="a", child_name="阿远",
              birth_tick=0, household_id="hh_a", home_node="home"),
        event(2, 2, "agent_married", agent_id="a", agent_name="阿远", spouse_id="b", spouse_name="阿秀",
              household_id="hh_a", source_household_id="hh_b",
              participants=[{"id": "a", "name": "阿远"}, {"id": "b", "name": "阿秀"}]),
        event(3, 2, "household_merged", target_household_id="hh_a", source_household_id="hh_b",
              head_id="a", head_name="阿远", members_after=[{"id": "a", "name": "阿远"}, {"id": "b", "name": "阿秀"}],
              home_node="home", work_node="field"),
        event(4, 9, "agent_died", agent_id="a", agent_name="阿远", household_id="hh_a", died_tick=9),
    ]
    profile = agent_profile(events, "a")
    assert profile.name == "阿远"
    assert profile.birth_tick == 0
    assert profile.death_tick == 9
    assert profile.spouse_name == "阿秀"
    assert profile.household_id == "hh_a"
    assert len(profile.timeline) == 4
    assert profile.recent_events[0]["id"] == 4

    spouse = agent_profile(events, "b")
    assert spouse.spouse_id == "a"
    assert spouse.household_id == "hh_a"

    household = household_profile(events, "hh_a")
    assert household.head_name == "阿远"
    assert household.home_node == "home"
    assert {m.get("id") for m in household.members} == {"a", "b"}
    assert [e["id"] for e in household.timeline] == [1, 2, 3, 4]

    missing = household_profile(events, "hh_missing")
    assert missing.members == []
    assert missing.timeline == []


def test_broken_fixture_payload_is_readable(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text(json.dumps([{"id": 1, "tick": 0, "event_type": "agent_action_taken", "payload": "{bad"}]), encoding="utf-8")
    loaded = EventSource.fixture(path).load()
    assert loaded[0]["_payload_broken"] is True
    assert event_people(loaded[0]) == []
    assert "{bad" in event_details(loaded[0])
