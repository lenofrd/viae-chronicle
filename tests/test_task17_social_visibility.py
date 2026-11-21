"""任务 17B 测试：社会认知进档案 — 观察层接线。

覆盖裁决 17-verdict-17B §四：
- 4.1 conflict_negotiation_round round=1 只读元数据（social_adjustment / proposal_basis）
  落库正确、round=2 不带；决策逻辑与取值口径不变（null 场景回退）；
- 4.1/4.2 渲染：三种 adjustment + 两种 basis 文案分支、null/字段缺失回退现状、
  round=1 主语 names 有/无映射；
- 4.6 timeline 成对人字段命中：认知/债争事件双方可命中（姓名与 id）、
  negotiation_round 裸 id 命中；match_participants=False 与 participants 旧行为不变；不误命中；
- 4.3/4.5 viz：observer/target 人名提取、acquaintance_changed 入 social tab、不进转折点；
- 4.2 CLI 人名收集（id→姓名，供 _print_events 并入渲染映射）。
全部内存事件库或纯构造 payload，seeded rng，可复现。
"""
from __future__ import annotations

import random

import pytest

from household_helpers import attach_test_resource_pools, hh
from vale.core.config_loader import load_config
from vale.core.event_log import EventLog
from vale.world.replay import rebuild_state
from vale.core.scheduler import run_tick
from vale.domains.society.state import DebtRecord
from vale.observability.query import EventFilter, apply_filter
from vale.observability.render import render_event
from vale.domains.society.agents import AgentModule
from vale.domains.environment.climate import ClimateModule
from vale.core.world import World


def _build(seed: int = 0) -> World:
    cfg = load_config("brookvale-town-001")
    w = World(world_id=cfg.world.world_id, event_log=EventLog(":memory:"),
              start_tick=cfg.world.start_tick, config=cfg)
    attach_test_resource_pools(w)
    w.register(ClimateModule(rng=random.Random(seed)))
    w.register(AgentModule(rng=random.Random(seed * 7 + 13)))
    for m in w.modules:
        if m.name == "agents":
            m._settle_marriage = lambda *a, **k: None  # noqa: SLF001
            m._settle_courtship = lambda *a, **k: None  # noqa: SLF001 婚配已下沉为 court 动作
    return w


@pytest.fixture
def world():
    w = _build(0)
    run_tick(w)
    return w


def _module(world) -> AgentModule:
    return next(m for m in world.modules if m.name == "agents")  # type: ignore[return-value]


def _pair(world):
    debtor = world.state.human.agents["lin_yuan"]
    creditor = world.state.human.agents["li_quan"]
    return hh(world, debtor), hh(world, creditor)


def _dispute_debt(world, debtor_hh, creditor_hh, amount=6.0) -> DebtRecord:
    tick = max(world.current_tick, 1)
    rec = DebtRecord(
        debtor_household_id=debtor_hh.household_id,
        creditor_household_id=creditor_hh.household_id,
        amount=amount,
        originated_tick=max(tick - 20, 0),
        due_tick=max(tick - 10, 0),
        overdue=True,
        origin="market_credit",
    )
    debtor_hh.debts.append(rec)
    return rec


def _seed_creditor_memory(world, outcome):
    from vale.domains.society.state import AcquaintanceEntry, MemoryEntry
    creditor = world.state.human.agents["li_quan"]
    debtor = world.state.human.agents["lin_yuan"]
    creditor.acquaintances[debtor.agent_id] = AcquaintanceEntry(
        level=2, last_seen_tick=1,
    )
    if outcome is not None:
        creditor.recent_interactions.append(MemoryEntry(
            tick=1, target_id=debtor.agent_id,
            event_type="debt_dispute", outcome=outcome,
        ))


def _rounds(world):
    rounds = world.event_log.by_type("conflict_negotiation_round")
    by_round = {r["payload"]["round"]: r["payload"] for r in rounds}
    return by_round[1], by_round[2]


# --------------------------------------------------------------------------- #
# 4.1 元数据落库：三种 adjustment × 三种 basis 场景 + round=2 不带
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("memory,defaulted,kin,expect_proposal,expect_adjust,expect_basis", [
    (None,   set(), False, "partial",   None,                       "plain"),         # 无记忆
    ("broken", set(), False, "full",    "prior_broken→full",        "plain"),         # 上次破裂
    ("repaid", set(), False, "deferral", "prior_repaid→deferral",   "plain"),         # 上次守约
    (None,   {"hh"}, False, "full",     None,                       "prior_default"), # 违约前科
    (None,   set(), True,   "deferral", None,                       "kin"),           # 亲缘
])
def test_round1_metadata_written(world, memory, defaulted, kin,
                                 expect_proposal, expect_adjust, expect_basis):
    module = _module(world)
    debtor_hh, creditor_hh = _pair(world)
    debtor = world.state.human.agents["lin_yuan"]
    creditor = world.state.human.agents["li_quan"]
    if kin:
        debtor.mother_id = creditor.agent_id
        assert module._households_are_kin(world, debtor_hh, creditor_hh)  # noqa: SLF001
    _seed_creditor_memory(world, memory)
    rec = _dispute_debt(world, debtor_hh, creditor_hh)
    debtor_hh.grain = 8.0
    if defaulted == {"hh"}:
        defaulted = {debtor_hh.household_id}

    result = module._negotiate_debt(  # noqa: SLF001
        world, world.config.agents.tuning, debtor_hh, creditor_hh,
        rec, defaulted=defaulted, repaid=set(),
    )
    assert result["proposal"] == expect_proposal  # 决策不变，仅记录成因
    r1, r2 = _rounds(world)
    assert r1["social_adjustment"] == expect_adjust
    assert r1["proposal_basis"] == expect_basis
    # 只读元数据仅随 round=1 落库；round=2 保持原字段集
    assert "social_adjustment" not in r2
    assert "proposal_basis" not in r2


def test_round1_metadata_replay_ignored(world):
    """新字段为只读元数据：replay 不读，回放态照旧重建。"""
    module = _module(world)
    debtor_hh, creditor_hh = _pair(world)
    _seed_creditor_memory(world, "broken")
    rec = _dispute_debt(world, debtor_hh, creditor_hh)
    debtor_hh.grain = 8.0
    module._negotiate_debt(  # noqa: SLF001
        world, world.config.agents.tuning, debtor_hh, creditor_hh,
        rec, defaulted=set(), repaid=set(),
    )
    state = rebuild_state(world.event_log.all(), world.config).state
    creditor = state.human.agents["li_quan"]
    debtor = state.human.agents["lin_yuan"]
    # 预塞的 creditor 认知不写事件（同对只写一次），replay 侧本就无此条目；
    # debtor 侧认知全新，运行时写 acquaintance_changed，replay 重建 KNOWN。
    assert "lin_yuan" not in creditor.acquaintances
    assert debtor.acquaintances[creditor.agent_id].level == 2
    assert [m.outcome for m in creditor.recent_interactions if m.target_id == debtor.agent_id]


# --------------------------------------------------------------------------- #
# 4.1/4.2 渲染：adjustment / basis 文案 + null 回退 + names 主语
# --------------------------------------------------------------------------- #
def _round1_event(payload: dict) -> dict:
    base = {
        "conflict_id": "cf-1-0-1-0", "round": 1,
        "initiator": "ag-1", "responder": "ag-2",
        "proposal": "full", "proposal_amount": 6.0, "response": None,
    }
    base.update(payload)
    return {"id": 1, "tick": 10, "event_type": "conflict_negotiation_round",
            "payload": base}


def test_render_round1_adjustment_notes():
    cases = [
        ("prior_broken→full", "全额偿还", "记得上次谈崩"),
        ("prior_repaid→deferral", "宽限些时日", "念其上次守约"),
    ]
    for adjust, demand, note in cases:
        evt = _round1_event({"social_adjustment": adjust,
                             "proposal_basis": "plain",
                             "proposal": "deferral" if "deferral" in adjust else "full"})
        r = render_event(evt)
        assert not r.degraded
        assert demand in r.text and note in r.text, r.text


def test_render_round1_basis_notes():
    evt = _round1_event({"social_adjustment": None, "proposal_basis": "prior_default"})
    assert "违约前科" in render_event(evt).text
    evt = _round1_event({"social_adjustment": None, "proposal_basis": "kin",
                         "proposal": "deferral", "proposal_amount": None})
    assert "亲缘" in render_event(evt).text


def test_render_round1_null_and_missing_fallback():
    """null / 旧库缺字段：文案与现状一致（无注记），不降级。"""
    legacy_text = "[ag-1] 第 1 轮开口：全额偿还 6 石"
    evt_null = _round1_event({"social_adjustment": None, "proposal_basis": "plain"})
    evt_missing = _round1_event({})  # 旧库事件：base 本就不带两字段
    for evt in (evt_null, evt_missing):
        r = render_event(evt)
        assert not r.degraded
        assert r.text == legacy_text, r.text


def test_render_round1_names_subject():
    evt = _round1_event({"social_adjustment": None, "proposal_basis": "plain"})
    # 有 names：主语显示姓名
    r = render_event(evt, names={"ag-1": "李权"})
    assert r.text.startswith("[李权]") and "第 1 轮开口" in r.text
    # 无 names / names 未命中：回退 id（现状）
    assert render_event(evt).text.startswith("[ag-1]")
    assert render_event(evt, names={"ag-9": "王五"}).text.startswith("[ag-1]")


# --------------------------------------------------------------------------- #
# 4.6 timeline 成对人字段命中
# --------------------------------------------------------------------------- #
def _acq_event() -> dict:
    return {"id": 1, "tick": 5, "event_type": "acquaintance_changed", "payload": {
        "observer_id": "ag-1", "observer_name": "李权",
        "target_id": "ag-2", "target_name": "林远",
        "old_level": 0, "new_level": 2, "cause": "interaction",
    }}


def _conflict_started_event() -> dict:
    return {"id": 2, "tick": 6, "event_type": "conflict_started", "payload": {
        "conflict_id": "cf-1", "conflict_type": "debt-disputes",
        "creditor_id": "ag-1", "creditor_name": "李权",
        "debtor_id": "ag-2", "debtor_name": "林远",
        "amount": 6.0,
    }}


def _round1_bare_event() -> dict:
    return _round1_event({"social_adjustment": None, "proposal_basis": "plain"})


def _married_event() -> dict:
    return {"id": 3, "tick": 7, "event_type": "agent_married", "payload": {
        "agent_id": "ag-3", "agent_name": "赵翠兰",
        "participants": [{"id": "ag-3", "name": "赵翠兰"}, {"id": "ag-4", "name": "陈默"}],
    }}


@pytest.mark.parametrize("evt,query", [
    (_acq_event(), "李权"), (_acq_event(), "林远"),          # 认知事件双方按姓名
    (_acq_event(), "ag-1"), (_acq_event(), "ag-2"),          # 认知事件双方按 id
    (_conflict_started_event(), "李权"), (_conflict_started_event(), "林远"),
    (_round1_bare_event(), "ag-1"), (_round1_bare_event(), "ag-2"),  # 裸 initiator/responder
])
def test_timeline_paired_fields_hit(evt, query):
    out = apply_filter([evt], EventFilter(agent=query, match_participants=True))
    assert len(out) == 1, f"{evt['event_type']} 应被 {query} 命中"


@pytest.mark.parametrize("evt,query", [
    (_acq_event(), "王五"), (_conflict_started_event(), "ag-9"),  # 无关人/无关 id
    ({"id": 4, "tick": 1, "event_type": "weather_changed", "payload": {"temp": 3}}, "李权"),
    # head 不在裁决三组：household_head_changed 不因 head_name 命中
    ({"id": 5, "tick": 1, "event_type": "household_head_changed",
      "payload": {"head_id": "ag-1", "head_name": "李权"}}, "李权"),
])
def test_timeline_no_false_hit(evt, query):
    out = apply_filter([evt], EventFilter(agent=query, match_participants=True))
    assert out == [], f"{evt['event_type']} 不应被 {query} 命中"


def test_timeline_participants_behavior_unchanged():
    """既有 participants 匹配不变：命中与不命中两侧。"""
    out = apply_filter([_married_event()], EventFilter(agent="陈默", match_participants=True))
    assert len(out) == 1
    assert apply_filter([_married_event()], EventFilter(agent="王五", match_participants=True)) == []


def test_events_list_legacy_behavior_unchanged():
    """match_participants=False（events list 旧默认）：成对字段不参与匹配。"""
    for evt, query in [(_acq_event(), "李权"), (_conflict_started_event(), "ag-1"),
                       (_round1_bare_event(), "ag-1")]:
        assert apply_filter([evt], EventFilter(agent=query)) == []
    # agent_name 命中路径保持
    assert len(apply_filter([_married_event()], EventFilter(agent="赵翠兰"))) == 1


def test_replayed_events_hit_timeline(world):
    """端到端：真实会话事件经 timeline 双方姓名可命中（含谈判轮次）。"""
    module = _module(world)
    debtor_hh, creditor_hh = _pair(world)
    rec = _dispute_debt(world, debtor_hh, creditor_hh)
    debtor_hh.grain = 8.0
    module._negotiate_debt(  # noqa: SLF001
        world, world.config.agents.tuning, debtor_hh, creditor_hh,
        rec, defaulted=set(), repaid=set(),
    )
    events = world.event_log.all()
    creditor_name = world.state.human.agents["li_quan"].name
    debtor_name = world.state.human.agents["lin_yuan"].name
    for name in (creditor_name, debtor_name):
        out = apply_filter(events, EventFilter(agent=name, match_participants=True))
        types = {e["event_type"] for e in out}
        # 任务17 补丁二后谈判轮次带 initiator_name/responder_name，按姓名可命中双方
        assert {"conflict_started", "debt_repaid",
                "conflict_negotiation_round"} <= types, types
    # 裸 id（negotiation_round initiator）同样命中
    creditor_id = world.state.human.agents["li_quan"].agent_id
    out = apply_filter(events, EventFilter(agent=creditor_id, match_participants=True))
    assert any(e["event_type"] == "conflict_negotiation_round" for e in out)


# --------------------------------------------------------------------------- #
# 4.3/4.5 viz：人名提取 + 关注点分类
# --------------------------------------------------------------------------- #
def test_viz_people_extracts_observer_target():
    from viz.data import event_people
    people = event_people(_acq_event())
    by_id = {p["id"]: p["name"] for p in people}
    assert by_id.get("ag-1") == "李权"
    assert by_id.get("ag-2") == "林远"


def test_viz_focus_and_turning_points():
    from viz.data import focus_category, turning_point
    assert focus_category(_acq_event()) == "social"
    assert turning_point(_acq_event()) == ""  # 裁决 4.5：不进转折点


# --------------------------------------------------------------------------- #
# 4.2 CLI：人名收集
# --------------------------------------------------------------------------- #
def test_cli_agent_names_collector():
    from vale.cli import _agent_names
    events = [
        _conflict_started_event(),                # creditor/debtor 对
        _acq_event(),                             # observer/target 对
        {"id": 9, "tick": 1, "event_type": "weather_changed", "payload": "broken"},  # 坏载荷跳过
    ]
    names = _agent_names(events)
    assert names == {"ag-1": "李权", "ag-2": "林远"}


# --------------------------------------------------------------------------- #
# 17B 收尾补丁（17-verdict-17B-accept-and-patch §三）
# --------------------------------------------------------------------------- #
def _round_event(round_no: int, payload: dict) -> dict:
    """带 initiator_name/responder_name 的谈判轮事件（补丁二落库形态）。"""
    base = {
        "conflict_id": "cf-1-0-1-0", "round": round_no,
        "initiator": "ag-1" if round_no == 1 else "ag-2",
        "initiator_name": "李权" if round_no == 1 else "林远",
        "responder": "ag-2" if round_no == 1 else "ag-1",
        "responder_name": "林远" if round_no == 1 else "李权",
        "proposal": "full" if round_no == 1 else None,
        "proposal_amount": 6.0 if round_no == 1 else None,
        "response": None if round_no == 1 else "repay",
    }
    base.update(payload)
    return {"id": 10 + round_no, "tick": 10,
            "event_type": "conflict_negotiation_round", "payload": base}


def test_patch2_round_names_written(world):
    """补丁二：round=1/2 都写双方姓名；既有字段语义不变。"""
    module = _module(world)
    debtor_hh, creditor_hh = _pair(world)
    rec = _dispute_debt(world, debtor_hh, creditor_hh)
    debtor_hh.grain = 8.0
    module._negotiate_debt(  # noqa: SLF001
        world, world.config.agents.tuning, debtor_hh, creditor_hh,
        rec, defaulted=set(), repaid=set(),
    )
    r1, r2 = _rounds(world)
    creditor = world.state.human.agents["li_quan"]
    debtor = world.state.human.agents["lin_yuan"]
    assert (r1["initiator_name"], r1["responder_name"]) == (creditor.name, debtor.name)
    assert (r2["initiator_name"], r2["responder_name"]) == (debtor.name, creditor.name)
    # 既有 id 字段语义不变
    assert (r1["initiator"], r1["responder"]) == (creditor.agent_id, debtor.agent_id)
    assert (r2["initiator"], r2["responder"]) == (debtor.agent_id, creditor.agent_id)
    # 渲染直读 payload 姓名：无需外部 names 映射也显示姓名
    evt = next(e for e in world.event_log.by_type("conflict_negotiation_round")
               if e["payload"]["round"] == 1)
    r = render_event(evt)
    assert r.text.startswith(f"[{creditor.name}]"), r.text


@pytest.mark.parametrize("round_no,name", [
    (1, "李权"), (1, "林远"), (2, "林远"), (2, "李权"),
])
def test_patch2_timeline_negotiation_by_name(round_no, name):
    """补丁二：round=1/2 各一条 timeline 按姓名命中。"""
    out = apply_filter([_round_event(round_no, {})],
                       EventFilter(agent=name, match_participants=True))
    assert len(out) == 1, f"round={round_no} 应被 {name} 命中"


def test_patch2_legacy_round_without_names():
    """旧库谈判轮次（无 name 字段）：渲染回退裸 id 且不降级；按姓名不命中，按 id 命中。"""
    evt = _round1_event({"social_adjustment": None, "proposal_basis": "plain"})
    r = render_event(evt)
    assert not r.degraded and r.text.startswith("[ag-1]"), r.text
    assert apply_filter([evt], EventFilter(agent="李权", match_participants=True)) == []
    assert len(apply_filter([evt], EventFilter(agent="ag-1", match_participants=True))) == 1


def test_patch1_household_merged_render():
    """补丁一：household_merged 渲染不抛、不降级；缺字段降级并带原因。"""
    evt = {"id": 20, "tick": 3, "event_type": "household_merged", "payload": {
        "target_household_id": "hh-1", "source_household_id": "hh-2",
        "members_after": ["a", "b"], "target_assets_after": {"grain": 12.0},
    }}
    r = render_event(evt)
    assert not r.degraded and r.reason is None, r.text
    assert "家庭 hh-2 并入 hh-1" in r.text

    bad = {"id": 21, "tick": 4, "event_type": "household_merged", "payload": {}}
    rb = render_event(bad)
    assert rb.degraded and rb.reason == "missing_household_field"
