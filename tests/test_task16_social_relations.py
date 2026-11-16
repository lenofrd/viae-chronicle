"""任务 16 阶段二测试：社会认知与关系层（两级认知 + 短期记忆 + TTL 遗忘 + 债争接入）。

覆盖裁决 16-verdict §五：
- 行为差异 A/B 对照（方向断言：broken→full、repaid→deferral、无记忆→partial），防"只记不读"；
- 运行时 vs replay 认知/记忆逐项一致（裁决 §3.1/§3.4 硬验收）；
- 记忆容量环形缓冲、TTL 遗忘过滤、低频清理写 forgot 事件（§3.5）；
- 交互即互升 KNOWN（§3.3 简化点）与结果写回双方记忆；
- acquaintance_changed 渲染；社交接入不动经济守恒。
全部内存事件库，seeded rng，可复现。
"""
from __future__ import annotations

import random

import pytest

from household_helpers import hh
from vale.core.config_loader import load_config
from vale.core.event_log import EventLog
from vale.core.replay import rebuild_state
from vale.core.scheduler import run_tick
from vale.core.state import (
    AcquaintanceEntry,
    AcquaintanceLevel,
    DebtRecord,
    MemoryEntry,
)
from vale.core.world import World
from vale.modules import social
from vale.modules.agents import AgentModule
from vale.modules.climate import ClimateModule
from vale.observability.render import render_event


def _build(seed: int = 0) -> World:
    cfg = load_config("brookvale-town-001")
    w = World(world_id=cfg.world.world_id, event_log=EventLog(":memory:"),
              start_tick=cfg.world.start_tick, config=cfg)
    w.register(ClimateModule(rng=random.Random(seed)))
    w.register(AgentModule(rng=random.Random(seed * 7 + 13)))
    for m in w.modules:
        if m.name == "agents":
            m._settle_marriage = lambda *a, **k: None  # noqa: SLF001
    return w


@pytest.fixture
def world():
    w = _build(0)
    run_tick(w)
    return w


def _module(world) -> AgentModule:
    return next(m for m in world.modules if m.name == "agents")  # type: ignore[return-value]


def _pair(world):
    """非亲缘的 (债务方家庭, 债权方家庭)。"""
    debtor = world.state.agents["lin_yuan"]
    creditor = world.state.agents["li_quan"]
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


# --------------------------------------------------------------------------- #
# 配置与认知载体
# --------------------------------------------------------------------------- #
def test_social_tuning_defaults_loaded(world):
    soc = world.config.agents.tuning.social
    assert soc.memory_capacity == 5      # 裁决 §四 初值，待阶段三复核
    assert soc.acquaintance_ttl == 360
    assert soc.cleanup_interval == 360


def test_agent_state_social_fields_default_empty(world):
    for agent in world.state.agents.values():
        assert agent.acquaintances == {}
        assert agent.recent_interactions == []


def test_kin_and_same_household_default_known(world):
    """同户/亲缘默认 KNOWN（裁决 §3.1：不写事件、由结构派生）。"""
    run_tick(world)
    acq_events = world.event_log.by_type("acquaintance_changed")
    assert acq_events == []  # kin 初始化不写事件，避免开局刷屏
    # 开局单人户、无亲缘：认知集合为空
    assert all(a.acquaintances == {} for a in world.state.agents.values())

    # 结构派生：结亲（配偶字段）→ apply_kin_defaults 后互为 KNOWN
    a = world.state.agents["lin_yuan"]
    b = world.state.agents["li_quan"]
    a.spouse_id, b.spouse_id = b.agent_id, a.agent_id
    social.apply_kin_defaults(world.state, world.current_tick)
    assert a.acquaintances[b.agent_id].level == int(AcquaintanceLevel.KNOWN)
    assert b.acquaintances[a.agent_id].level == int(AcquaintanceLevel.KNOWN)

    # 同户派生：第三人并入该户
    c = world.state.agents["zhao_cuilan"]
    c.household_id = a.household_id
    social.apply_kin_defaults(world.state, world.current_tick)
    assert c.acquaintances[a.agent_id].level == int(AcquaintanceLevel.KNOWN)
    assert a.acquaintances[c.agent_id].level == int(AcquaintanceLevel.KNOWN)
    # 幂等：重复调用不产生额外条目
    social.apply_kin_defaults(world.state, world.current_tick)
    assert len(a.acquaintances) == 2


# --------------------------------------------------------------------------- #
# 行为差异 A/B（裁决 §五硬验收：方向断言，防只记不读）
# --------------------------------------------------------------------------- #
def _seed_creditor_memory(world, outcome):
    creditor = world.state.agents["li_quan"]
    debtor = world.state.agents["lin_yuan"]
    creditor.acquaintances[debtor.agent_id] = AcquaintanceEntry(
        level=int(AcquaintanceLevel.KNOWN), last_seen_tick=1,
    )
    if outcome is not None:
        creditor.recent_interactions.append(MemoryEntry(
            tick=1, target_id=debtor.agent_id,
            event_type="debt_dispute", outcome=outcome,
        ))


@pytest.mark.parametrize("outcome,expected_proposal", [
    (None, "partial"),                    # 无记忆：既有事实路径（部分）
    ("broken", "full"),                   # 上次破裂：升全额
    ("repaid", "deferral"),               # 上次守约：放宽为延期
    ("partial_repaid", "deferral"),       # 部分守约同宽待
    ("deferred", "partial"),              # 延期不改变诉求档位
])
def test_negotiation_proposal_direction(world, outcome, expected_proposal):
    module = _module(world)
    debtor_hh, creditor_hh = _pair(world)
    assert not module._households_are_kin(world, debtor_hh, creditor_hh)  # noqa: SLF001
    _seed_creditor_memory(world, outcome)
    rec = _dispute_debt(world, debtor_hh, creditor_hh)
    debtor_hh.grain = 8.0
    creditor_hh.grain = 20.0
    grain_before = debtor_hh.grain + creditor_hh.grain

    result = module._negotiate_debt(  # noqa: SLF001
        world, world.config.agents.tuning, debtor_hh, creditor_hh,
        rec, defaulted=set(), repaid=set(),
    )
    assert result["proposal"] == expected_proposal
    # 社交层只改诉求文案，不动经济：总粮守恒
    assert debtor_hh.grain + creditor_hh.grain == pytest.approx(grain_before, abs=1e-6)


def test_negotiation_prior_default_not_overridden_by_good_memory(world):
    """违约前科（事件流事实）优先于良好记忆：仍是 full。"""
    module = _module(world)
    debtor_hh, creditor_hh = _pair(world)
    _seed_creditor_memory(world, "repaid")
    rec = _dispute_debt(world, debtor_hh, creditor_hh)
    debtor_hh.grain = 8.0
    world.event_log.append(1, "debt_defaulted", {
        "debtor_household_id": debtor_hh.household_id,
        "household_id": debtor_hh.household_id,
    })
    defaulted, _repaid = module._debt_history_sets(world)  # noqa: SLF001
    assert debtor_hh.household_id in defaulted

    result = module._negotiate_debt(  # noqa: SLF001
        world, world.config.agents.tuning, debtor_hh, creditor_hh,
        rec, defaulted=defaulted, repaid=_repaid,
    )
    assert result["proposal"] == "full"  # 前科优先，记忆只调 partial 档


# --------------------------------------------------------------------------- #
# 记忆写回与互升 KNOWN
# --------------------------------------------------------------------------- #
def test_dispute_outcome_written_back_both_sides(world):
    module = _module(world)
    debtor_hh, creditor_hh = _pair(world)
    rec = _dispute_debt(world, debtor_hh, creditor_hh)
    debtor_hh.grain = 8.0
    creditor = world.state.agents["li_quan"]
    debtor = world.state.agents["lin_yuan"]

    result = module._negotiate_debt(  # noqa: SLF001
        world, world.config.agents.tuning, debtor_hh, creditor_hh,
        rec, defaulted=set(), repaid=set(),
    )
    outcome = result["resolution"]
    for observer, target in ((creditor, debtor), (debtor, creditor)):
        memories = social.recall(observer, target.agent_id)
        assert memories and memories[-1].event_type == "debt_dispute"
        assert memories[-1].outcome == outcome


def test_interaction_upgrades_acquaintance_both_ways_once_only(world):
    module = _module(world)
    debtor_hh, creditor_hh = _pair(world)
    rec = _dispute_debt(world, debtor_hh, creditor_hh)
    debtor_hh.grain = 8.0
    creditor = world.state.agents["li_quan"]
    debtor = world.state.agents["lin_yuan"]
    assert creditor.agent_id not in debtor.acquaintances

    module._negotiate_debt(  # noqa: SLF001
        world, world.config.agents.tuning, debtor_hh, creditor_hh,
        rec, defaulted=set(), repaid=set(),
    )
    # 交互即互升 KNOWN（§3.3 简化点）：双方各一条新事件，同一对只写一次
    events = [e["payload"] for e in world.event_log.by_type("acquaintance_changed")]
    pair_events = [p for p in events
                   if {p["observer_id"], p["target_id"]} == {creditor.agent_id, debtor.agent_id}]
    assert len(pair_events) == 2  # 观察者侧单向，双方各一条
    assert debtor.acquaintances[creditor.agent_id].level == int(AcquaintanceLevel.KNOWN)
    assert creditor.acquaintances[debtor.agent_id].level == int(AcquaintanceLevel.KNOWN)

    # 第二次交互：同对同级别不再写事件
    rec2 = _dispute_debt(world, debtor_hh, creditor_hh)
    module._negotiate_debt(  # noqa: SLF001
        world, world.config.agents.tuning, debtor_hh, creditor_hh,
        rec2, defaulted=set(), repaid=set(),
    )
    events2 = [e["payload"] for e in world.event_log.by_type("acquaintance_changed")]
    pair_events2 = [p for p in events2
                    if {p["observer_id"], p["target_id"]} == {creditor.agent_id, debtor.agent_id}]
    assert len(pair_events2) == 2


def _bare_agent(agent_id="x"):
    from vale.core.state import AgentState
    return AgentState(agent_id=agent_id, name=agent_id, sex="male", birth_tick=0,
                      household_id=f"hh_{agent_id}", location="well",
                      health=100.0, hunger=0.0, stamina=100.0)


def test_memory_capacity_ring_buffer():
    a = _bare_agent()
    for i in range(7):
        social.record_memory(a, f"t{i}", "debt_dispute", "repaid", tick=i, capacity=5)
    assert len(a.recent_interactions) == 5
    assert [m.target_id for m in a.recent_interactions] == ["t2", "t3", "t4", "t5", "t6"]


def test_last_memory_outcome_picks_latest():
    a = _bare_agent()
    social.record_memory(a, "t", "debt_dispute", "repaid", tick=1, capacity=5)
    social.record_memory(a, "t", "debt_dispute", "broken", tick=9, capacity=5)
    social.record_memory(a, "t", "debt_dispute", "deferred", tick=5, capacity=5)
    assert social.last_memory_outcome(social.recall(a, "t")) == "broken"


# --------------------------------------------------------------------------- #
# 遗忘：TTL 过滤 + 低频清理（裁决 §3.5）
# --------------------------------------------------------------------------- #
def test_is_forgotten_threshold():
    entry = AcquaintanceEntry(level=2, last_seen_tick=0)
    assert not social.is_forgotten(entry, now=360, ttl=360)   # 恰好等于未过期
    assert social.is_forgotten(entry, now=361, ttl=360)       # 严格超过才遗忘


def test_get_social_view_filters_forgotten(world):
    debtor = world.state.agents["lin_yuan"]
    creditor = world.state.agents["li_quan"]
    creditor.acquaintances[debtor.agent_id] = AcquaintanceEntry(
        level=int(AcquaintanceLevel.KNOWN), last_seen_tick=0,
    )
    view_fresh = social.get_social_view(
        world.state, creditor.agent_id, debtor.agent_id, now=100, ttl=360)
    assert view_fresh["known"] is True
    view_stale = social.get_social_view(
        world.state, creditor.agent_id, debtor.agent_id, now=400, ttl=360)
    assert view_stale["known"] is False  # 查询时只过滤，不写事件
    assert world.event_log.by_type("acquaintance_changed") == []


def test_cleanup_forgotten_removes_and_writes_event(world):
    observer = world.state.agents["li_quan"]
    world.current_tick = 720
    observer.acquaintances["lin_yuan"] = AcquaintanceEntry(level=2, last_seen_tick=0)
    observer.acquaintances["zhao_cuilan"] = AcquaintanceEntry(
        level=2, last_seen_tick=world.current_tick - 100)  # 未过期

    removed = social.cleanup_forgotten(world, world.current_tick, ttl=360)

    assert removed == 1
    assert "lin_yuan" not in observer.acquaintances
    assert "zhao_cuilan" in observer.acquaintances
    events = world.event_log.by_type("acquaintance_changed")
    assert len(events) == 1
    p = events[0]["payload"]
    assert p["cause"] == "forgot" and p["new_level"] == 0
    assert p["observer_id"] == observer.agent_id and p["target_id"] == "lin_yuan"


def test_decay_relation_stub_returns_none():
    assert social.decay_relation(AcquaintanceEntry(level=2), now=1) is None


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #
def test_render_acquaintance_changed():
    met = render_event({"event_type": "acquaintance_changed", "tick": 5, "payload": {
        "observer_id": "li_quan", "observer_name": "李全",
        "target_id": "lin_yuan", "target_name": "林远",
        "old_level": 0, "new_level": 2, "cause": "interaction",
        "location": "market", "location_source": "home",
    }})
    assert not met.degraded and "李全" in met.text and "林远" in met.text

    forgot = render_event({"event_type": "acquaintance_changed", "tick": 5, "payload": {
        "observer_id": "li_quan", "observer_name": "李全",
        "target_id": "lin_yuan", "target_name": "林远",
        "old_level": 2, "new_level": 0, "cause": "forgot",
    }})
    assert not forgot.degraded and "记不清" in forgot.text

    bad = render_event({"event_type": "acquaintance_changed", "tick": 5,
                        "payload": {"observer_id": "li_quan"}})
    assert bad.degraded and bad.reason == "missing_social_field"


# --------------------------------------------------------------------------- #
# 运行时 vs replay 逐项一致（裁决 §3.1/§3.4 硬验收）
# --------------------------------------------------------------------------- #
def test_runtime_replay_consistency_with_dispute(world):
    module = _module(world)
    debtor_hh, creditor_hh = _pair(world)
    rec = _dispute_debt(world, debtor_hh, creditor_hh)
    debtor_hh.grain = 8.0
    # 两次会话制造多条记忆 + 认知升级事件
    module._negotiate_debt(  # noqa: SLF001
        world, world.config.agents.tuning, debtor_hh, creditor_hh,
        rec, defaulted=set(), repaid=set(),
    )
    rec2 = _dispute_debt(world, debtor_hh, creditor_hh)
    module._negotiate_debt(  # noqa: SLF001
        world, world.config.agents.tuning, debtor_hh, creditor_hh,
        rec2, defaulted=set(), repaid=set(),
    )
    for _ in range(11):
        run_tick(world)

    events = world.event_log.all()
    assert events, "事件流非空是本对比的前提"
    final_tick = max(int(e["tick"]) for e in events)
    # 采样点对齐：kin 刷新在生产里每 tick 发生，此处按 replay 的末事件 tick 对齐采样
    social.apply_kin_defaults(world.state, final_tick)

    replayed = rebuild_state(events, world.config).state

    assert set(replayed.agents) == set(world.state.agents)
    for agent_id, rt in world.state.agents.items():
        rp = replayed.agents[agent_id]
        # 认知逐项相等（level + last_seen_tick）
        assert rp.acquaintances == rt.acquaintances, agent_id
        # 记忆逐项相等（tick/target/event_type/outcome）
        assert rp.recent_interactions == rt.recent_interactions, agent_id

    # 记忆确实由事件重建：债争双方有 debt_dispute 记录
    creditor_rp = replayed.agents["li_quan"]
    assert any(m.event_type == "debt_dispute" for m in creditor_rp.recent_interactions)


def test_replay_rebuilds_memory_and_forgetting_from_bare_events():
    """不跑世界，直接以最小事件序列验证 replay 重建口径。"""
    cfg = load_config("brookvale-town-001")
    events = [
        # 债务形成：按真实序先建立两户与户主（conflict 事件不带建户语义）
        {"tick": 1, "event_type": "debt_formed", "payload": {
            "debtor_id": "lin_yuan", "debtor_household_id": "hh_lin_yuan",
            "creditor_id": "li_quan", "creditor_household_id": "hh_li_quan",
            "amount": 6.0, "origin": "market_credit",
        }},
        {"tick": 1, "event_type": "conflict_started", "payload": {
            "conflict_id": "cf-1", "debtor_household_id": "hh_lin_yuan",
            "creditor_household_id": "hh_li_quan", "amount": 6.0,
            "debtor_id": "lin_yuan", "creditor_id": "li_quan",
        }},
        {"tick": 2, "event_type": "conflict_resolved", "payload": {
            "conflict_id": "cf-1", "resolution": "partial_repaid",
            "amount_paid": 3.0, "remaining": 3.0,
            "creditor_household_id": "hh_li_quan", "debtor_household_id": "hh_lin_yuan",
        }},
        {"tick": 3, "event_type": "acquaintance_changed", "payload": {
            "observer_id": "li_quan", "observer_name": "李全",
            "target_id": "wang_xi", "target_name": "王喜",
            "old_level": 0, "new_level": 2, "cause": "interaction",
        }},
        {"tick": 4, "event_type": "acquaintance_changed", "payload": {
            "observer_id": "li_quan", "observer_name": "李全",
            "target_id": "wang_xi", "target_name": "王喜",
            "old_level": 2, "new_level": 0, "cause": "forgot",
        }},
    ]
    state = rebuild_state(events, cfg).state
    li = state.agents["li_quan"]
    lin = state.agents["lin_yuan"]
    # 双方记忆由 conflict_resolved 重建
    assert [(m.tick, m.target_id, m.event_type, m.outcome)
            for m in li.recent_interactions] == [(2, "lin_yuan", "debt_dispute", "partial_repaid")]
    assert [(m.tick, m.target_id, m.event_type, m.outcome)
            for m in lin.recent_interactions] == [(2, "li_quan", "debt_dispute", "partial_repaid")]
    # 升级后遗忘：条目被删
    assert "wang_xi" not in li.acquaintances
