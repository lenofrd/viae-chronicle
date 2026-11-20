from __future__ import annotations

import json

from viz.data import (
    DEFAULT_FIXTURE,
    EventSource,
    activity_label,
    activity_spans,
    agent_activity_spans,
    agent_profile,
    biography,
    build_person_index,
    event_details,
    event_households,
    event_locations,
    event_people,
    filter_events,
    focus_category,
    focus_events,
    group_events,
    household_profile,
    person_keys,
    turning_point,
)


def event(event_id, tick, event_type, **payload):
    return {"id": event_id, "tick": tick, "event_type": event_type, "payload": payload}


def test_default_fixture_loads_all_legacy_events():
    events = EventSource.fixture().load()
    assert DEFAULT_FIXTURE.name == "legacy_events.json"
    assert len(events) >= 1
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


def test_activity_label_uses_action_verbs():
    farm = event(1, 0, "agent_action_taken", agent_id="a", action="farm")
    unknown_action = event(2, 0, "agent_action_taken", agent_id="a", action="new_livelihood")
    born = event(3, 0, "agent_born", agent_id="a")
    other = event(4, 0, "debt_formed", debtor_id="a")
    gather = event(5, 0, "gather_success", agent_id="a", action="fish")
    assert activity_label(farm) == "劳作"
    assert activity_label(unknown_action) == "new_livelihood"
    assert activity_label(born) == "出生"
    assert activity_label(other) == "举债"
    assert activity_label(gather) == "捕鱼"  # gather 按 action 借用采集动词


def test_agent_activity_spans_merge_with_interruptions_and_break_on_gap():
    """种田穿插歇息/进食仍是一段；间隔超过 gap 才断段（林远案例的抽象）。"""
    events = [
        event(1, 0, "agent_action_taken", agent_id="a", agent_name="阿远", action="farm"),
        event(2, 1, "agent_action_taken", agent_id="a", agent_name="阿远", action="rest"),
        event(3, 3, "agent_action_taken", agent_id="a", agent_name="阿远", action="farm"),
        event(4, 5, "agent_action_taken", agent_id="a", agent_name="阿远", action="farm"),
        # 间隔 26 tick > gap=20：劳作断段
        event(5, 31, "agent_action_taken", agent_id="a", agent_name="阿远", action="farm"),
        event(6, 32, "agent_action_taken", agent_id="b", agent_name="阿秀", action="fish"),
    ]
    spans = agent_activity_spans(events, "a", gap=20)
    farm_spans = [s for s in spans if s.label == "劳作"]
    rest_spans = [s for s in spans if s.label == "歇息"]
    assert [s.count for s in farm_spans] == [3, 1]
    assert farm_spans[0].from_tick == 0 and farm_spans[0].to_tick == 5
    assert farm_spans[1].from_tick == 31
    assert len(rest_spans) == 1 and rest_spans[0].count == 1
    # 只含本人事件；subject 显示带名字
    assert all(s.subject == "a" for s in spans)
    assert spans[0].subject_label == "阿远（a）"


def test_activity_spans_all_subjects_skip_world_events():
    """混排模式：按首要人物聚合；无人物无家庭的世界事件（天气）跳过。"""
    events = [
        event(1, 0, "weather_changed"),
        event(2, 0, "agent_action_taken", agent_id="a", agent_name="阿远", action="farm"),
        event(3, 1, "agent_action_taken", agent_id="b", agent_name="阿秀", action="farm"),
        event(4, 2, "agent_action_taken", agent_id="a", agent_name="阿远", action="farm"),
    ]
    spans = activity_spans(events, gap=20)
    # 两人各自的劳作段 + 天气被跳过
    assert {(s.subject, s.label, s.count) for s in spans} == {
        ("a", "劳作", 2), ("b", "劳作", 1),
    }


def test_group_events_activity_granularity_makes_one_row_per_span():
    events = [
        event(1, 0, "agent_action_taken", agent_id="a", agent_name="阿远", action="farm"),
        event(2, 1, "agent_action_taken", agent_id="a", agent_name="阿远", action="rest"),
        event(3, 3, "agent_action_taken", agent_id="a", agent_name="阿远", action="farm"),
    ]
    groups = group_events(events, "activity")
    labels = [g.label for g in groups]
    assert len(groups) == 2  # 劳作一段（两次）+ 歇息一段
    assert any("劳作" in label and "阿远" in label for label in labels)
    work = next(g for g in groups if "劳作" in g.label)
    assert work.event_ids == [1, 3]
    # gap 生效：间隔 26>20 断为两段
    events.append(event(4, 30, "agent_action_taken", agent_id="a", agent_name="阿远", action="farm"))
    assert len([g for g in group_events(events, "activity", gap=20) if "劳作" in g.label]) == 2
    assert len([g for g in group_events(events, "activity", gap=29) if "劳作" in g.label]) == 1


def test_event_source_incremental_load(tmp_path):
    path = tmp_path / "events.json"
    events = [
        {"id": 1, "tick": 0, "event_type": "weather_changed", "payload": {"weather": "sunny"}},
        {"id": 2, "tick": 1, "event_type": "agent_action_taken",
         "payload": {"agent_id": "a", "agent_name": "阿远", "action": "farm"}},
    ]
    path.write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")
    source = EventSource.fixture(path)
    assert [e["id"] for e in source.load()] == [1, 2]
    assert [e["id"] for e in source.load(since_id=1)] == [2]
    assert source.load(since_id=2) == []


def test_conflict_and_debt_deferred_viz_mappings():
    """任务15 新事件在 viz 增强映射中的归类、高亮与人物提取。"""
    started = event(1, 10, "conflict_started", creditor_id="c", creditor_name="债主",
                    debtor_id="d", debtor_name="欠债人", amount=5, overdue_ticks=40)
    resolved = event(2, 10, "conflict_resolved", resolution="repaid",
                     amount_paid=5, remaining=0)
    broken = event(3, 10, "conflict_broken", reason="refused",
                   amount=5, overdue_ticks=40)
    deferred = event(4, 10, "debt_deferred", creditor_id="c", creditor_name="债主",
                     debtor_id="d", debtor_name="欠债人", amount=5,
                     old_due_tick=10, new_due_tick=40, deferral_days=30)
    round1 = event(5, 10, "conflict_negotiation_round", round=1,
                   initiator="c", responder="d", proposal="partial", proposal_amount=3)
    round2 = event(6, 10, "conflict_negotiation_round", round=2,
                   initiator="d", responder="c", response="repay")
    unknown = event(7, 10, "some_future_event", foo="bar")

    # 关键转折：交涉始末 + 延期高亮；negotiation_round 轮次默认不高亮（3.1 决定，避免刷屏）
    assert turning_point(started) == "债务交涉"
    assert turning_point(resolved) == "债务议和"
    assert turning_point(broken) == "交涉破裂"
    assert turning_point(deferred) == "债务延期"
    assert turning_point(round1) == ""
    assert turning_point(round2) == ""
    assert turning_point(unknown) == ""

    # 关注点分类：4 个 conflict 入 social；debt_deferred 入 economy；未知不入
    assert focus_category(started) == "social"
    assert focus_category(resolved) == "social"
    assert focus_category(broken) == "social"
    assert focus_category(round1) == "social"  # 轮次仍在关注点 tab 可见
    assert focus_category(deferred) == "economy"
    assert focus_category(unknown) == ""

    # initiator/responder 裸 id 提取：参与者列不再为空
    assert {p.get("id") for p in event_people(round1)} == {"c", "d"}
    assert {p.get("id") for p in event_people(round2)} == {"c", "d"}
    # 只有 initiator 时仍只提取发起方，不崩
    solo = event(8, 10, "conflict_negotiation_round", round=1, initiator="c")
    assert {p.get("id") for p in event_people(solo)} == {"c"}
    # 未知事件类型不崩
    assert event_people(unknown) == []


def test_person_keys_cover_all_event_people_identifiers():
    """person_keys 必须覆盖 event_people 提取出的全部 id 与 name（索引匹配语义一致）。"""
    events = [
        event(1, 0, "agent_action_taken", agent_id="a", agent_name="阿远"),
        event(2, 1, "agent_married", participants=[{"id": "b", "name": "阿秀"}],
              initiator="a", responder="b"),
        event(3, 2, "household_merged", head_id="a", head_name="阿远",
              members_after=[{"id": "b", "name": "阿秀"}]),
        event(4, 3, "some_future_event", foo="bar"),
        {"id": 5, "tick": 4, "event_type": "no_payload", "payload": "{bad"},
    ]
    for item in events:
        keys = person_keys(item)
        for person in event_people(item):
            for value in (person.get("id"), person.get("name")):
                if value:
                    assert str(value) in keys


def test_build_person_index_and_profile_match_scan_path():
    """索引路径的档案必须与全库扫描路径完全一致（timeline、头部信息、配偶、家庭）。"""
    events = [
        event(1, 0, "agent_born", agent_id="a", agent_name="阿远", child_id="a",
              birth_tick=0, household_id="hh_a"),
        event(2, 2, "agent_married", agent_id="a", agent_name="阿远",
              spouse_id="b", spouse_name="阿秀", household_id="hh_a"),
        event(3, 3, "agent_action_taken", agent_id="b", agent_name="阿秀",
              action="farm", household_id="hh_a"),
        event(4, 9, "agent_died", agent_id="a", agent_name="阿远", household_id="hh_a", died_tick=9),
    ]
    index = build_person_index(events)
    assert set(index) == {"a", "阿远", "b", "阿秀"}  # household_id 非人物键，不入索引
    # 事件列表保持 id 升序
    assert [e["id"] for e in index["a"]] == [1, 2, 4]

    for selector in ("a", "b", "阿秀"):
        scanned = agent_profile(events, selector)
        indexed = agent_profile(events, selector, index=index)
        assert [e["id"] for e in indexed.timeline] == [e["id"] for e in scanned.timeline]
        assert indexed.name == scanned.name
        assert indexed.agent_id == scanned.agent_id
        assert indexed.birth_tick == scanned.birth_tick
        assert indexed.death_tick == scanned.death_tick
        assert indexed.spouse_id == scanned.spouse_id
        assert indexed.spouse_name == scanned.spouse_name
        assert indexed.household_id == scanned.household_id

    missing = agent_profile(events, "nobody", index=index)
    assert missing.timeline == []
    assert missing.name == "nobody"


def test_biography_extracts_life_events_in_order():
    """传记：本人出生/婚配/子女出生/迁徙按时间序成条；普通劳作不入传。"""
    events = [
        event(1, 0, "agent_born", agent_id="a", agent_name="阿远", child_id="a",
              child_name="阿远", birth_tick=0, household_id="hh_a"),
        event(2, 5, "agent_action_taken", agent_id="a", agent_name="阿远",
              action="farm", target_node="field"),
        event(3, 10, "agent_married", agent_id="a", agent_name="阿远",
              spouse_id="b", spouse_name="阿秀", household_id="hh_a"),
        event(4, 30, "agent_born", agent_id="a", agent_name="阿远", child_id="c",
              child_name="阿小", birth_tick=30, household_id="hh_a"),
        event(5, 40, "household_split", agent_id="a", agent_name="阿远",
              household_id="hh_a", new_household_id="hh_c"),
        event(6, 90, "agent_died", agent_id="a", agent_name="阿远", died_tick=90),
    ]
    profile = agent_profile(events, "a")
    bio = biography(profile)
    assert [(e.label, e.tick) for e in bio] == [
        ("出生", 0), ("婚配", 10), ("生育", 30), ("分家 / 迁徙", 40), ("死亡", 90),
    ]
    assert [e.event_id for e in bio] == [1, 3, 4, 5, 6]
    assert all(e.text for e in bio)

    # 同一事件集换到子女视角：出生事件属于子女本人，父亲那条对其是「生育」
    child_profile = agent_profile(events, "c")
    child_bio = biography(child_profile)
    assert [(e.label, e.tick) for e in child_bio] == [("出生", 30)]

    # 无转折的纯劳作人物：空传记
    plain = agent_profile([event(1, 5, "agent_action_taken", agent_id="d", action="farm")], "d")
    assert biography(plain) == []
