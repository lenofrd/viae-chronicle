"""任务 15 阶段二测试：集市赊账 + 2 轮私下催收。

覆盖裁决 §五：
- 赊账触发（短缺/富余/上限/已逾期不新增）、粮当期转移守恒、origin/due_tick、借粮旧路径；
- 催收 2 轮上限、四种结果（全额/部分/延期/拒绝）、只依赖既有事实、不新增 trust/grudge；
- 4 类 conflict_* 与 debt_deferred 渲染；新旧事件回放兼容。
全部内存事件库，seeded rng，可复现。
"""
from __future__ import annotations

import random

import pytest
from pydantic import ValidationError

from vale.config.schema.agents import DebtDisputeTuning
from household_helpers import attach_test_resource_pools, hh
from vale.core.config_loader import load_config
from vale.core.event_log import EventLog
from vale.world.replay import rebuild_state
from vale.core.scheduler import run_tick
from vale.domains.society.state import DebtRecord
from vale.core.world import World
from vale.domains.society.agents import AgentModule, _floor_to_step
from vale.domains.environment.climate import ClimateModule
from vale.observability.render import render_event


def _build(seed: int = 0) -> World:
    cfg = load_config("brookvale-town-001")
    w = World(world_id=cfg.world.world_id, event_log=EventLog(":memory:"),
              start_tick=cfg.world.start_tick, config=cfg)
    attach_test_resource_pools(w)
    w.register(ClimateModule(rng=random.Random(seed)))
    w.register(AgentModule(rng=random.Random(seed * 7 + 13)))
    # 隔离婚配合并，保证家庭/库存按测试构造
    for m in w.modules:
        if m.name == "agents":
            m._settle_marriage = lambda *a, **k: None  # noqa: SLF001
            m._settle_courtship = lambda *a, **k: None  # noqa: SLF001 婚配已下沉为 court 动作
    return w


@pytest.fixture
def world():
    w = _build(0)
    run_tick(w)  # 初始化 agents / households
    return w


def _module(world) -> AgentModule:
    return next(m for m in world.modules if m.name == "agents")  # type: ignore[return-value]


def _pair(world):
    """返回 (债务方家庭, 债务方户主, 债权方家庭, 债权方户主)。"""
    debtor_agent = world.state.human.agents["lin_yuan"]
    creditor_agent = world.state.human.agents["li_quan"]
    return hh(world, debtor_agent), debtor_agent, hh(world, creditor_agent), creditor_agent


def _market_credit(world, *, amount=5.0, due_tick=0, overdue=False,
                   debtor=None, creditor=None) -> DebtRecord:
    debtor = debtor or hh(world, world.state.human.agents["lin_yuan"])
    creditor = creditor or hh(world, world.state.human.agents["li_quan"])
    rec = DebtRecord(
        debtor_household_id=debtor.household_id,
        creditor_household_id=creditor.household_id,
        amount=amount,
        originated_tick=0,
        due_tick=due_tick,
        overdue=overdue,
        origin="market_credit",
    )
    debtor.debts.append(rec)
    return rec


# --------------------------------------------------------------------------- #
# 集市赊账
# --------------------------------------------------------------------------- #
def test_market_credit_transfers_grain_and_records_origin(world):
    module = _module(world)
    tuning = world.config.agents.tuning
    debtor_hh, debtor, creditor_hh, creditor = _pair(world)
    debtor_hh.grain = 0.0
    creditor_stock = 80.0  # 需覆盖 min_surplus(45) + min_shortage(30) 的可赊出量
    creditor_hh.grain = creditor_stock
    world.current_tick = 10

    count = module._settle_market_credit(  # noqa: SLF001
        world, tuning, [(debtor_hh, debtor), (creditor_hh, creditor)]
    )

    assert count == 1
    assert debtor_hh.grain == pytest.approx(tuning.market.credit.min_shortage)  # 补到 min_shortage
    assert creditor_hh.grain == pytest.approx(creditor_stock - tuning.market.credit.min_shortage)
    assert debtor_hh.debt == pytest.approx(tuning.market.credit.min_shortage)
    rec = debtor_hh.debts[0]
    assert rec.origin == "market_credit"
    assert rec.due_tick == 10 + tuning.market.credit.due_days
    ev = world.event_log.by_type("debt_formed")[-1]["payload"]
    assert ev["origin"] == "market_credit"
    assert ev["amount"] == pytest.approx(tuning.market.credit.min_shortage)
    assert ev["due_tick"] == 10 + tuning.market.credit.due_days
    assert (ev["creditor_grain_before"] - ev["creditor_grain_after"]) == pytest.approx(
        ev["debtor_grain_after"] - ev["debtor_grain_before"]
    ), "粮当期转移应守恒"


def test_market_credit_requires_shortage_and_surplus(world):
    module = _module(world)
    tuning = world.config.agents.tuning
    debtor_hh, debtor, creditor_hh, creditor = _pair(world)
    participants = [(debtor_hh, debtor), (creditor_hh, creditor)]

    debtor_hh.grain = tuning.market.credit.min_shortage  # 不短缺
    creditor_hh.grain = 50.0
    assert module._settle_market_credit(world, tuning, participants) == 0  # noqa: SLF001

    debtor_hh.grain = 0.0
    creditor_hh.grain = tuning.market.credit.min_surplus - 1  # 不够富余
    assert module._settle_market_credit(world, tuning, participants) == 0  # noqa: SLF001


def test_market_credit_respects_household_cap(world):
    module = _module(world)
    tuning = world.config.agents.tuning
    credit = tuning.market.credit
    debtor_hh, debtor, creditor_hh, creditor = _pair(world)
    existing = 8.0
    _market_credit(world, amount=existing, due_tick=999)  # 预置一笔未清偿赊账
    debtor_hh.grain = 0.0
    creditor_stock = 80.0  # 需覆盖 min_surplus(45) + min_shortage(30) 的可赊出量
    creditor_hh.grain = creditor_stock

    assert module._settle_market_credit(world, tuning,  # noqa: SLF001
                                        [(debtor_hh, debtor), (creditor_hh, creditor)]) == 1
    # 期望值从 config 推导：本次赊入 = min(缺口, 卖方可赊余量, 上限余量) 按步长向下取整，
    # 不写死上限数值，配置调整不致碎测。
    expected_top_up = _floor_to_step(
        min(
            credit.min_shortage,                      # 买方存粮 0，缺口即 min_shortage
            creditor_stock - credit.min_surplus,      # 卖方至少余 min_surplus
            credit.max_per_household - existing,      # 单户未清偿赊账上限余量
        ),
        tuning.market.trade_unit_step,
    )
    assert debtor_hh.debt == pytest.approx(existing + expected_top_up)
    assert debtor_hh.debt <= credit.max_per_household  # 不越过单户赊账上限


def test_market_credit_blocked_when_existing_overdue(world):
    module = _module(world)
    tuning = world.config.agents.tuning
    debtor_hh, debtor, creditor_hh, creditor = _pair(world)
    _market_credit(world, amount=5.0, due_tick=0, overdue=True)
    debtor_hh.grain = 0.0
    creditor_hh.grain = 50.0
    before = len(world.event_log.by_type("debt_formed"))

    assert module._settle_market_credit(world, tuning,  # noqa: SLF001
                                        [(debtor_hh, debtor), (creditor_hh, creditor)]) == 0
    assert len(world.event_log.by_type("debt_formed")) == before
    assert debtor_hh.debt == pytest.approx(5.0)


def test_borrow_path_unaffected_no_origin_key(world):
    """借粮仍走旧语义：debt_formed 不写 origin（None = 借粮）。"""
    module = _module(world)
    tuning = world.config.agents.tuning
    debtor_hh, debtor, creditor_hh, _creditor = _pair(world)
    debtor_hh.grain = 1.0
    creditor_hh.grain = 50.0
    p = module._perceive(world, debtor)  # noqa: SLF001
    module._execute(world, debtor, "borrow_grain", p, tuning)  # noqa: SLF001

    ev = [e for e in world.event_log.by_type("debt_formed")
          if e["payload"]["debtor_id"] == debtor.agent_id][-1]["payload"]
    assert "origin" not in ev
    assert debtor_hh.debts[-1].origin is None


# --------------------------------------------------------------------------- #
# 2 轮私下催收
# --------------------------------------------------------------------------- #
def test_negotiation_full_repayment(world):
    module = _module(world)
    tuning = world.config.agents.tuning
    debtor_hh, debtor, creditor_hh, _creditor = _pair(world)
    rec = _market_credit(world, amount=10.0, due_tick=0, overdue=True)
    debtor_hh.grain = 12.0
    creditor_before = creditor_hh.grain
    world.current_tick = 40

    result = module._negotiate_debt(  # noqa: SLF001
        world, tuning, debtor_hh, creditor_hh, rec,
        defaulted={debtor_hh.household_id}, repaid=set(),
    )

    assert result["proposal"] == "full"       # 有违约前科 → 全额
    assert result["resolution"] == "repaid"
    assert debtor_hh.debt == pytest.approx(0.0)
    assert creditor_hh.grain == pytest.approx(creditor_before + 10.0)
    assert len(world.event_log.by_type("conflict_negotiation_round")) == 2
    repaid = world.event_log.by_type("debt_repaid")[-1]["payload"]
    assert repaid["source"] == "debt_dispute"
    assert world.event_log.by_type("conflict_resolved")[-1]["payload"]["resolution"] == "repaid"


def test_negotiation_partial_repayment(world):
    module = _module(world)
    tuning = world.config.agents.tuning
    debtor_hh, _debtor, creditor_hh, _creditor = _pair(world)
    rec = _market_credit(world, amount=10.0, due_tick=0, overdue=True)
    debtor_hh.grain = 10.0
    creditor_before = creditor_hh.grain
    world.current_tick = 40

    result = module._negotiate_debt(  # noqa: SLF001
        world, tuning, debtor_hh, creditor_hh, rec, defaulted=set(), repaid=set()
    )

    assert result["proposal"] == "partial"
    assert result["resolution"] == "partial_repaid"
    assert debtor_hh.debt == pytest.approx(5.0)  # 10 × 0.5
    assert creditor_hh.grain == pytest.approx(creditor_before + 5.0)


def test_negotiation_deferred_for_kin(world):
    module = _module(world)
    tuning = world.config.agents.tuning
    debtor_hh, debtor, creditor_hh, creditor = _pair(world)
    debtor.mother_id = creditor.agent_id  # 直接亲缘
    rec = _market_credit(world, amount=10.0, due_tick=0, overdue=True)
    debtor_hh.grain = 0.0
    world.current_tick = 40

    result = module._negotiate_debt(  # noqa: SLF001
        world, tuning, debtor_hh, creditor_hh, rec, defaulted=set(), repaid=set()
    )

    assert result["proposal"] == "deferral"
    assert result["resolution"] == "deferred"
    assert rec.due_tick == 40 + tuning.conflict.debt_dispute.deferral_days
    assert rec.overdue is False
    assert rec.dispute_started_tick is None  # 下一周期可再次触发
    assert world.event_log.by_type("debt_deferred")
    assert world.event_log.by_type("conflict_resolved")[-1]["payload"]["resolution"] == "deferred"


def test_negotiation_refusal_breaks_and_does_not_repeat(world):
    module = _module(world)
    tuning = world.config.agents.tuning
    debtor_hh, _debtor, creditor_hh, _creditor = _pair(world)
    rec = _market_credit(world, amount=10.0, due_tick=0, overdue=True)
    debtor_hh.grain = 0.0
    world.current_tick = 40

    result = module._negotiate_debt(  # noqa: SLF001
        world, tuning, debtor_hh, creditor_hh, rec, defaulted=set(), repaid=set()
    )

    assert result["response"] == "refuse"
    assert result["resolution"] == "broken"
    assert rec.dispute_started_tick == 40
    assert rec.amount == pytest.approx(10.0)
    assert world.event_log.by_type("conflict_broken")

    # 同一笔不再发起第二次会话（既有 debt_defaulted / collection_attempt 接管）
    before = len(world.event_log.by_type("conflict_started"))
    world.current_tick = 100
    debtor_hh.grain = 4.0  # 即使进入有粮窗口，已发起过的债务也不重复谈
    assert module._settle_debt_disputes(world, tuning) == 0  # noqa: SLF001
    assert len(world.event_log.by_type("conflict_started")) == before


def test_zero_grain_goes_forced_collection_not_conflict(world):
    """断粮（≤ refusal_threshold）不走会话，走既有 debt_defaulted 强制路径。"""
    module = _module(world)
    tuning = world.config.agents.tuning
    debtor_hh, debtor, _creditor_hh, _creditor = _pair(world)
    world.current_tick = 100
    _market_credit(world, amount=5.0, due_tick=70, overdue=False)
    debtor_hh.grain = 0.0

    assert module._settle_debt_disputes(world, tuning) == 0  # noqa: SLF001
    assert not world.event_log.by_type("conflict_started")

    module._collect_debts(world, debtor, tuning)  # noqa: SLF001
    assert world.event_log.by_type("debt_defaulted")
    assert not world.event_log.by_type("conflict_started")


def test_settle_runs_dispute_before_forced_collection_without_double_deduction(world):
    """结算顺序：会话先看到库存并扣款，随后 _collect_debts 同 tick 不再重复扣。"""
    module = _module(world)
    tuning = world.config.agents.tuning
    debtor_hh, _debtor, _creditor_hh, _creditor = _pair(world)
    world.current_tick = 101  # 非集市日
    _market_credit(world, amount=10.0, due_tick=71, overdue=True)
    debtor_hh.grain = 5.0  # 窗口内；部分诉求 5 → 当场还 5

    module._settle(world, tuning)  # noqa: SLF001

    repaid = [p for p in (e["payload"] for e in world.event_log.by_type("debt_repaid"))
              if p.get("source") == "debt_dispute"]
    assert len(repaid) == 1 and repaid[0]["amount"] == pytest.approx(5.0)
    assert debtor_hh.grain == pytest.approx(0.0)
    assert not [
        e for e in world.event_log.by_type("debt_collected")
        if e["tick"] == 101 and e["payload"].get("debtor_household_id") == debtor_hh.household_id
    ], "会话扣款后同 tick 不应再被强制扣粮"


def test_dispute_trigger_requires_overdue_days_stock_window_and_market_credit(world):
    module = _module(world)
    tuning = world.config.agents.tuning
    cfg = tuning.conflict.debt_dispute
    debtor_hh, _debtor, _creditor_hh, _creditor = _pair(world)
    world.current_tick = 100

    # 未满 trigger_overdue_days
    _market_credit(world, amount=5.0, due_tick=71, overdue=True)
    debtor_hh.grain = cfg.refusal_threshold + 1
    assert module._settle_debt_disputes(world, tuning) == 0  # noqa: SLF001

    # 满 30 天但存粮高于 trigger_max_grain
    debtor_hh.debts.clear()
    _market_credit(world, amount=5.0, due_tick=70, overdue=True)
    debtor_hh.grain = cfg.trigger_max_grain + 1
    assert module._settle_debt_disputes(world, tuning) == 0  # noqa: SLF001

    # 借粮债务（origin=None）不参与
    debtor_hh.debts.clear()
    debtor_hh.debts.append(DebtRecord(
        debtor_household_id=debtor_hh.household_id,
        creditor_household_id="hh_li_quan", amount=5.0,
        originated_tick=0, due_tick=0, overdue=True,
    ))
    debtor_hh.grain = cfg.refusal_threshold + 1
    assert module._settle_debt_disputes(world, tuning) == 0  # noqa: SLF001

    # 断粮（≤ refusal_threshold）不进会话，走强制扣粮
    debtor_hh.debts.clear()
    _market_credit(world, amount=5.0, due_tick=70, overdue=True)
    debtor_hh.grain = cfg.refusal_threshold
    assert module._settle_debt_disputes(world, tuning) == 0  # noqa: SLF001

    # 有粮但不还（refusal_threshold < grain ≤ trigger_max_grain）→ 触发
    debtor_hh.debts.clear()
    _market_credit(world, amount=5.0, due_tick=70, overdue=True)
    debtor_hh.grain = cfg.refusal_threshold + 1
    assert module._settle_debt_disputes(world, tuning) == 1  # noqa: SLF001


def test_dispute_trigger_grain_window_boundary(world):
    """窗口边界：≤ refusal_threshold 与 > trigger_max_grain 不触发，窗口内触发。"""
    module = _module(world)
    tuning = world.config.agents.tuning
    cfg = tuning.conflict.debt_dispute
    debtor_hh, _debtor, _creditor_hh, _creditor = _pair(world)
    world.current_tick = 100

    cases = (
        (0.0, 0),
        (cfg.refusal_threshold, 0),
        (cfg.refusal_threshold + 1, 1),
        (cfg.trigger_max_grain, 1),
        (cfg.trigger_max_grain + 1, 0),
    )
    for grain, expected in cases:
        debtor_hh.debts.clear()
        _market_credit(world, amount=5.0, due_tick=70, overdue=True)
        debtor_hh.grain = grain
        assert module._settle_debt_disputes(world, tuning) == expected, f"grain={grain}"  # noqa: SLF001


def test_negotiation_request_deferral_creditor_insists(world):
    """窗口分支：refusal_threshold < grain < 诉求额 → 请求延期；无守约前科则债权人坚持。"""
    module = _module(world)
    tuning = world.config.agents.tuning
    debtor_hh, _debtor, creditor_hh, _creditor = _pair(world)
    rec = _market_credit(world, amount=10.0, due_tick=0, overdue=True)
    debtor_hh.grain = 4.0  # > refusal_threshold=2，< 部分诉求 5
    world.current_tick = 40

    result = module._negotiate_debt(  # noqa: SLF001
        world, tuning, debtor_hh, creditor_hh, rec, defaulted=set(), repaid=set()
    )

    assert result["proposal"] == "partial"
    assert result["response"] == "request_deferral"
    assert result["resolution"] == "broken"
    assert result["reason"] == "creditor_insists"
    assert rec.amount == pytest.approx(10.0)


def test_negotiation_request_deferral_accepted_when_prior_honored(world):
    """窗口分支：请求延期 + 曾守约 → 债权人接受，进入下一周期。"""
    module = _module(world)
    tuning = world.config.agents.tuning
    debtor_hh, _debtor, creditor_hh, _creditor = _pair(world)
    rec = _market_credit(world, amount=10.0, due_tick=0, overdue=True)
    debtor_hh.grain = 4.0
    world.current_tick = 40

    result = module._negotiate_debt(  # noqa: SLF001
        world, tuning, debtor_hh, creditor_hh, rec,
        defaulted=set(), repaid={debtor_hh.household_id},
    )

    assert result["response"] == "request_deferral"
    assert result["resolution"] == "deferred"
    assert rec.due_tick == 40 + tuning.conflict.debt_dispute.deferral_days
    assert rec.dispute_started_tick is None


def test_schema_rejects_refusal_threshold_not_below_trigger_max_grain():
    with pytest.raises(ValidationError):
        DebtDisputeTuning(refusal_threshold=5.0, trigger_max_grain=5.0)


def test_credit_and_repayment_conserve_grain(world):
    module = _module(world)
    tuning = world.config.agents.tuning
    debtor_hh, debtor, creditor_hh, creditor = _pair(world)
    debtor_hh.grain = 0.0
    creditor_hh.grain = 50.0
    total_before = debtor_hh.grain + creditor_hh.grain

    module._settle_market_credit(world, tuning,  # noqa: SLF001
                                 [(debtor_hh, debtor), (creditor_hh, creditor)])
    assert debtor_hh.grain + creditor_hh.grain == pytest.approx(total_before)

    # 秋收后有粮，全额还款仍守恒
    debtor_hh.grain = 5.0
    rec = debtor_hh.debts[0]
    world.current_tick = 80
    module._negotiate_debt(world, tuning, debtor_hh, creditor_hh, rec,  # noqa: SLF001
                           defaulted={debtor_hh.household_id}, repaid=set())
    assert debtor_hh.debt == pytest.approx(0.0)
    assert debtor_hh.grain + creditor_hh.grain == pytest.approx(total_before)
    assert debtor_hh.grain >= 0 and creditor_hh.grain >= 0


# --------------------------------------------------------------------------- #
# 观察层渲染
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "evt",
    [
        {"id": 1, "tick": 40, "event_type": "conflict_started",
         "payload": {"conflict_id": "cf-1", "conflict_type": "debt-disputes",
                     "creditor_id": "li_quan", "creditor_name": "李全",
                     "debtor_id": "lin_yuan", "debtor_name": "林远",
                     "amount": 10.0, "overdue_ticks": 30}},
        {"id": 2, "tick": 40, "event_type": "conflict_negotiation_round",
         "payload": {"conflict_id": "cf-1", "round": 1, "initiator": "li_quan",
                     "responder": "lin_yuan", "proposal": "full",
                     "proposal_amount": 10.0, "response": None}},
        {"id": 3, "tick": 40, "event_type": "conflict_negotiation_round",
         "payload": {"conflict_id": "cf-1", "round": 2, "initiator": "lin_yuan",
                     "responder": "li_quan", "proposal": None,
                     "proposal_amount": None, "response": "refuse"}},
        {"id": 4, "tick": 40, "event_type": "conflict_resolved",
         "payload": {"conflict_id": "cf-1", "resolution": "partial_repaid",
                     "amount_paid": 5.0, "remaining": 5.0}},
        {"id": 5, "tick": 40, "event_type": "conflict_broken",
         "payload": {"conflict_id": "cf-1", "reason": "refused", "amount": 10.0}},
        {"id": 6, "tick": 40, "event_type": "debt_deferred",
         "payload": {"creditor_id": "li_quan", "creditor_name": "李全",
                     "debtor_id": "lin_yuan", "debtor_name": "林远",
                     "amount": 10.0, "old_due_tick": 10, "new_due_tick": 100,
                     "deferral_days": 90}},
    ],
)
def test_render_conflict_and_deferred_events(evt):
    r = render_event(evt)
    assert r.degraded is False
    assert r.text


# --------------------------------------------------------------------------- #
# 回放兼容
# --------------------------------------------------------------------------- #
def test_replay_old_debt_formed_without_origin():
    cfg = load_config("brookvale-town-001")
    events = [
        {"id": 1, "tick": 0, "event_type": "debt_formed", "payload": {
            "debtor_id": "lin_yuan", "debtor_household_id": "hh_lin_yuan",
            "creditor_id": "li_quan", "creditor_household_id": "hh_li_quan",
            "amount": 5.0, "due_tick": 100}},
    ]
    rec = rebuild_state(events, cfg).state.human.households["hh_lin_yuan"].debts[0]
    assert rec.origin is None
    assert rec.debtor_household_id == "hh_lin_yuan"
    assert rec.creditor_household_id == "hh_li_quan"
    assert rec.due_tick == 100


def test_replay_new_credit_and_deferral_events():
    cfg = load_config("brookvale-town-001")
    events = [
        {"id": 1, "tick": 10, "event_type": "debt_formed", "payload": {
            "debtor_id": "lin_yuan", "debtor_household_id": "hh_lin_yuan",
            "creditor_id": "li_quan", "creditor_household_id": "hh_li_quan",
            "amount": 5.0, "due_tick": 70, "origin": "market_credit"}},
        {"id": 2, "tick": 100, "event_type": "conflict_started", "payload": {
            "conflict_id": "cf-1", "debtor_household_id": "hh_lin_yuan",
            "creditor_household_id": "hh_li_quan", "amount": 5.0}},
        {"id": 3, "tick": 100, "event_type": "conflict_negotiation_round",
         "payload": {"conflict_id": "cf-1", "round": 1}},
        {"id": 4, "tick": 100, "event_type": "conflict_negotiation_round",
         "payload": {"conflict_id": "cf-1", "round": 2}},
        {"id": 5, "tick": 100, "event_type": "debt_deferred", "payload": {
            "debtor_household_id": "hh_lin_yuan", "creditor_household_id": "hh_li_quan",
            "amount": 5.0, "old_due_tick": 70, "new_due_tick": 160}},
        {"id": 6, "tick": 100, "event_type": "conflict_resolved",
         "payload": {"conflict_id": "cf-1", "resolution": "deferred", "new_due_tick": 160}},
    ]
    result = rebuild_state(events, cfg)
    rec = result.state.human.households["hh_lin_yuan"].debts[0]
    assert rec.origin == "market_credit"
    assert rec.amount == pytest.approx(5.0)
    assert rec.due_tick == 160
    assert rec.overdue is False
    assert rec.dispute_started_tick is None
    assert not any(k.startswith("conflict_") for k in result.ignored_events), (
        f"新事件应被识别，未识别：{result.ignored_events}"
    )


def test_replay_broken_conflict_keeps_dispute_marker():
    cfg = load_config("brookvale-town-001")
    events = [
        {"id": 1, "tick": 0, "event_type": "debt_formed", "payload": {
            "debtor_id": "lin_yuan", "debtor_household_id": "hh_lin_yuan",
            "creditor_id": "li_quan", "creditor_household_id": "hh_li_quan",
            "amount": 5.0, "due_tick": 40, "origin": "market_credit"}},
        {"id": 2, "tick": 100, "event_type": "conflict_started", "payload": {
            "conflict_id": "cf-1", "debtor_household_id": "hh_lin_yuan",
            "creditor_household_id": "hh_li_quan", "amount": 5.0}},
        {"id": 3, "tick": 100, "event_type": "conflict_broken",
         "payload": {"conflict_id": "cf-1", "reason": "refused", "amount": 5.0}},
    ]
    rec = rebuild_state(events, cfg).state.human.households["hh_lin_yuan"].debts[0]
    assert rec.dispute_started_tick == 100
    assert rec.amount == pytest.approx(5.0)
