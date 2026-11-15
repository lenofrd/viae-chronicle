"""任务 08 测试：经济与生理闭环。

覆盖：借粮守恒/债主选择、催收足额/不足/违约/节流、秋收还款优先级、
健康回血条件与上限、farm 封顶、债务派生聚合、无负不变量、结算错误隔离、
观察层对新增事件类型的渲染与未知兜底。

全部用临时 db（:memory:），不依赖固定 events.db。
"""

from __future__ import annotations

import pytest

from config.schema.natural_params import Season
from vale.core.config_loader import load_config
from vale.core.event_log import EventLog
from vale.core.scheduler import run_tick
from vale.core.state import DebtRecord
from vale.core.world import World
from vale.modules.agents import IMPOSSIBLE, AgentModule, select_creditor
from vale.modules.climate import ClimateModule
from vale.observability.render import render_event


@pytest.fixture
def world():
    cfg = load_config("brookvale-town-001")
    log = EventLog(":memory:")
    w = World(
        world_id=cfg.world.world_id,
        event_log=log,
        start_tick=cfg.world.start_tick,
        config=cfg,
    )
    w.register(ClimateModule())
    w.register(AgentModule())
    return w


def _module(world) -> AgentModule:
    return next(m for m in world.modules if m.name == "agents")  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# 债主选择（纯函数 select_creditor）
# --------------------------------------------------------------------------- #
def test_select_creditor_picks_richest(world):
    run_tick(world)  # 初始化 agents
    agents = world.state.agents
    # li_quan 最富且 ≥5 → 选他
    assert select_creditor(agents, "lin_yuan", 5.0).agent_id == "li_quan"


def test_select_creditor_returns_none_when_none_sufficient(world):
    run_tick(world)  # 初始化 agents
    for a in world.state.agents.values():
        if a.agent_id != "lin_yuan":
            a.grain = 3.0  # 都 < 5
    assert select_creditor(world.state.agents, "lin_yuan", 5.0) is None


# --------------------------------------------------------------------------- #
# 借粮闭合
# --------------------------------------------------------------------------- #
def test_borrow_transaction_conserves_grain(world):
    """所有 debt_formed 事件中，借粮者增量 + 债主减量 == 0（粮守恒，不凭空产粮）。

    任务10 调参后开局存粮宽裕（30/35/100），自然演化 60 天不会借粮；
    故构造断粮状态（清空采集动作 + 零食物 + 高饥饿）触发借粮再验证守恒。
    """
    run_tick(world)
    world.config.agents.tuning.gathering.actions.clear()
    lin = world.state.agents["lin_yuan"]
    lin.grain = 0.0
    lin.hunger = 95.0
    lin.stamina = 100.0  # 体力满：borrow > rest（同 test_borrow_grain_triggers_when_low_grain）
    for _ in range(12):
        run_tick(world)
    formed = world.event_log.by_type("debt_formed")
    assert formed, "断粮且无采集时应在数日内发生借粮"
    total = 0.0
    for e in formed:
        p = e["payload"]
        total += (p["debtor_grain_after"] - p["debtor_grain_before"])
        total += (p["creditor_grain_after"] - p["creditor_grain_before"])
    assert total == pytest.approx(0.0), "借粮不应凭空产生或消灭粮食"


def test_borrow_chooses_creditor_with_sufficient_grain(world):
    """最富者存粮不足时，改选存粮足够的次富者（不写死姓名）。

    直接驱动 _execute（借粮闭合），与效用决策解耦：决策选择已由
    test_borrow_grain_triggers_when_low_grain 覆盖。
    """
    run_tick(world)
    lin = world.state.agents["lin_yuan"]
    world.state.agents["li_quan"].grain = 3.0  # 最富但 < 5，借不出
    zhao = world.state.agents["zhao_cuilan"]
    zhao.grain = 50.0
    lin.grain = 1.0
    module = _module(world)
    tuning = world.config.agents.tuning
    p = module._perceive(world, lin)  # noqa: SLF001
    assert p.creditor_id == "zhao_cuilan"  # 感知层即跳过存粮不足者

    module._execute(world, lin, "borrow_grain", p, tuning)  # noqa: SLF001

    formed = [e for e in world.event_log.by_type("debt_formed")
              if e["payload"]["debtor_id"] == "lin_yuan"]
    assert formed
    assert formed[-1]["payload"]["creditor_id"] == "zhao_cuilan"
    # 债主扣粮（按事件载荷，借粮执行时刻）
    assert formed[-1]["payload"]["creditor_grain_before"] - formed[-1]["payload"]["creditor_grain_after"] == pytest.approx(5.0)


def test_borrow_score_impossible_when_no_creditor(world):
    run_tick(world)
    module = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    for a in world.state.agents.values():
        if a.agent_id != "lin_yuan":
            a.grain = 1.0
    lin.grain = 1.0
    p = module._perceive(world, lin)  # noqa: SLF001
    assert p.creditor_id is None
    assert module.score_action("borrow_grain", p, tuning) == IMPOSSIBLE


def test_borrow_score_impossible_when_overdue(world):
    run_tick(world)
    module = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    lin.grain = 1.0
    lin.debts = [DebtRecord(creditor_id="li_quan", amount=5.0,
                            originated_tick=0, due_tick=90, overdue=True)]
    p = module._perceive(world, lin)  # noqa: SLF001
    assert module.score_action("borrow_grain", p, tuning) == IMPOSSIBLE


# --------------------------------------------------------------------------- #
# 每日结算：债务催收
# --------------------------------------------------------------------------- #
def test_collection_full_payment_clears_debt(world):
    run_tick(world)
    module = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    li = world.state.agents["li_quan"]
    lin.grain = 20.0
    lin.debts = [DebtRecord(creditor_id="li_quan", amount=10.0,
                            originated_tick=0, due_tick=90)]
    li_before = li.grain
    world.current_tick = 90
    module._collect_debts(world, lin, tuning)  # noqa: SLF001

    assert lin.grain == pytest.approx(10.0)   # 20 - 10
    assert li.grain == pytest.approx(li_before + 10.0)
    assert lin.debt == pytest.approx(0.0)
    assert lin.debts == []  # 清偿完毕移出列表
    ev = world.event_log.by_type("debt_collected")[-1]
    assert ev["payload"]["amount_paid"] == pytest.approx(10.0)
    assert ev["payload"]["remaining"] == pytest.approx(0.0)
    assert ev["payload"]["overdue"] is False


def test_collection_partial_marks_overdue(world):
    run_tick(world)
    module = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    li = world.state.agents["li_quan"]
    lin.grain = 4.0
    lin.debts = [DebtRecord(creditor_id="li_quan", amount=10.0,
                            originated_tick=0, due_tick=90)]
    li_before = li.grain
    world.current_tick = 90
    module._collect_debts(world, lin, tuning)  # noqa: SLF001

    assert lin.grain == pytest.approx(0.0)      # 扣尽
    assert li.grain == pytest.approx(li_before + 4.0)
    assert lin.debt == pytest.approx(6.0)       # 10 - 4，剩余逾期
    ev = world.event_log.by_type("debt_collected")[-1]
    assert ev["payload"]["amount_paid"] == pytest.approx(4.0)
    assert ev["payload"]["remaining"] == pytest.approx(6.0)
    assert ev["payload"]["overdue"] is True


def test_collection_defaulted_when_no_grain(world):
    run_tick(world)
    module = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    li = world.state.agents["li_quan"]
    lin.grain = 0.0
    lin.debts = [DebtRecord(creditor_id="li_quan", amount=10.0,
                            originated_tick=0, due_tick=90)]
    li_before = li.grain
    world.current_tick = 90
    module._collect_debts(world, lin, tuning)  # noqa: SLF001

    assert li.grain == pytest.approx(li_before)  # 无粮可转
    assert lin.debt == pytest.approx(10.0)       # 债务仍在，标逾期
    assert lin.debts[0].overdue is True
    ev = world.event_log.by_type("debt_defaulted")[-1]
    assert ev["payload"]["amount"] == pytest.approx(10.0)


def test_collection_interval_throttles_repeated_attempts(world):
    """到期后每 collection_interval_days 才催收一次，不会每天扣粮。"""
    run_tick(world)
    module = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    lin.grain = 100.0
    lin.debts = [DebtRecord(creditor_id="li_quan", amount=10.0,
                            originated_tick=0, due_tick=90)]
    world.current_tick = 90
    module._collect_debts(world, lin, tuning)  # noqa: SLF001
    n_first = len(world.event_log.by_type("debt_collected"))
    assert n_first == 1

    # 同日到期的新债务，但 last_collected 距当前不足 interval → 不再催收
    lin.debts = [DebtRecord(creditor_id="li_quan", amount=8.0,
                            originated_tick=80, due_tick=90, last_collected_tick=90)]
    world.current_tick = 91
    module._collect_debts(world, lin, tuning)  # noqa: SLF001
    assert len(world.event_log.by_type("debt_collected")) == n_first


# --------------------------------------------------------------------------- #
# 秋收还款
# --------------------------------------------------------------------------- #
def test_harvest_repayment_earliest_due_first(world):
    run_tick(world)
    module = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    lin.grain = 100.0
    # 两笔债务：due 120 晚、due 90 早
    lin.debts = [
        DebtRecord(creditor_id="li_quan", amount=20.0, originated_tick=0, due_tick=120),
        DebtRecord(creditor_id="li_quan", amount=20.0, originated_tick=0, due_tick=90),
    ]
    world.state.climate.season = Season.AUTUMN
    world.state.field_growth[lin.work_node] = 90.0
    p = module._perceive(world, lin)  # noqa: SLF001

    module._execute(world, lin, "harvest", p, tuning)  # noqa: SLF001

    early = [d for d in lin.debts if d.due_tick == 90]
    late = [d for d in lin.debts if d.due_tick == 120]
    assert early[0].amount == pytest.approx(10.0)  # 20 - 10（还款上限全给最早到期）
    assert late[0].amount == pytest.approx(20.0)   # 未还
    repaid = world.event_log.by_type("debt_repaid")
    assert repaid[-1]["payload"]["amount"] == pytest.approx(10.0)
    assert repaid[-1]["payload"]["source"] == "harvest"


# --------------------------------------------------------------------------- #
# 健康回血
# --------------------------------------------------------------------------- #
def test_health_recovers_when_conditions_met(world):
    run_tick(world)
    module = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    lin.health = 50.0
    lin.hunger = 30.0   # < 阈值 40
    lin.stamina = 60.0  # > 阈值 50
    world.current_tick = 5

    module._recover_health(world, lin, tuning)  # noqa: SLF001

    assert lin.health == pytest.approx(50.5)
    ev = world.event_log.by_type("health_recovered")[-1]
    assert ev["payload"]["before"] == pytest.approx(50.0)
    assert ev["payload"]["after"] == pytest.approx(50.5)


def test_health_no_recovery_when_hunger_high(world):
    run_tick(world)
    module = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    lin.health = 50.0
    lin.hunger = 50.0   # ≥ 阈值 40
    lin.stamina = 60.0
    world.current_tick = 5
    before_events = len(world.event_log.by_type("health_recovered"))

    module._recover_health(world, lin, tuning)  # noqa: SLF001

    assert lin.health == pytest.approx(50.0)
    assert len(world.event_log.by_type("health_recovered")) == before_events


def test_health_recovery_capped_at_100(world):
    run_tick(world)
    module = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    lin.health = 99.8
    lin.hunger = 30.0
    lin.stamina = 60.0
    world.current_tick = 5

    module._recover_health(world, lin, tuning)  # noqa: SLF001

    assert lin.health == pytest.approx(100.0)  # 不是 100.3
    ev = world.event_log.by_type("health_recovered")[-1]
    assert ev["payload"]["after"] == pytest.approx(100.0)


# --------------------------------------------------------------------------- #
# farm 封顶
# --------------------------------------------------------------------------- #
def test_farm_score_impossible_when_growth_capped(world):
    run_tick(world)
    module = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    cap = tuning.agriculture.max_field_growth
    world.state.field_growth[lin.work_node] = cap
    p = module._perceive(world, lin)  # noqa: SLF001
    assert module.score_action("farm", p, tuning) == IMPOSSIBLE


def test_no_farm_event_after_growth_capped(world):
    run_tick(world)
    module = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    world.state.field_growth[lin.work_node] = tuning.agriculture.max_field_growth
    farm_before = [e for e in world.event_log.by_type("agent_action_taken")
                   if e["payload"].get("agent_name") == "林远" and e["payload"].get("action") == "farm"]

    run_tick(world)

    farm_after = [e for e in world.event_log.by_type("agent_action_taken")
                  if e["payload"].get("agent_name") == "林远" and e["payload"].get("action") == "farm"]
    assert len(farm_after) == len(farm_before), "封顶后不应再产生 farm 事件"


# --------------------------------------------------------------------------- #
# 债务派生聚合
# --------------------------------------------------------------------------- #
def test_debt_aggregate_matches_sum_of_records(world):
    run_tick(world)
    lin = world.state.agents["lin_yuan"]
    lin.debts = [
        DebtRecord(creditor_id="li_quan", amount=3.0, originated_tick=0, due_tick=90),
        DebtRecord(creditor_id="zhao_cuilan", amount=7.0, originated_tick=0, due_tick=90),
    ]
    assert lin.debt == pytest.approx(10.0)
    lin.debts[0].amount = 0.0  # 偿还一笔
    assert lin.debt == pytest.approx(7.0)
    lin.debts = []
    assert lin.debt == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# 不变量：跨长模拟无负粮/无负债/无崩溃
# --------------------------------------------------------------------------- #
def test_invariant_no_negative_grain_or_debt_over_long_run(world):
    ticks = 200  # 跨过首个到期日(90)与多个催收间隔(90/120/150/180)
    for _ in range(ticks):
        run_tick(world)
    for a in world.state.agents.values():
        assert a.grain >= 0, f"{a.name} 存粮为负: {a.grain}"
        assert a.debt >= 0, f"{a.name} 负债为负: {a.debt}"
        for d in a.debts:
            assert d.amount >= 0, f"{a.name} 单笔债务为负: {d.amount}"
    errors = world.event_log.by_type("agent_error")
    assert not errors, f"长模拟中出现 agent_error: {errors}"


# --------------------------------------------------------------------------- #
# 结算错误隔离
# --------------------------------------------------------------------------- #
def test_settlement_error_isolated_per_agent(world, monkeypatch):
    run_tick(world)
    module = _module(world)
    original = AgentModule._collect_debts

    def patched(self, w, agent, tuning):
        if agent.agent_id == "zhao_cuilan":
            raise RuntimeError("settle boom")
        return original(self, w, agent, tuning)

    monkeypatch.setattr(AgentModule, "_collect_debts", patched)
    run_tick(world)  # 不应抛异常

    settle_errors = [e for e in world.event_log.by_type("agent_error")
                     if e["payload"].get("phase") == "daily_settlement"]
    assert any(e["payload"]["agent_name"] == "赵翠兰" for e in settle_errors)
    # 世界仍在推进：tick 应已自增
    assert world.current_tick >= 2


# --------------------------------------------------------------------------- #
# 观察层渲染：新增事件类型可读，未知仍兜底
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "evt",
    [
        {"id": 1, "tick": 5, "event_type": "debt_formed",
         "payload": {"creditor_id": "li_quan", "creditor_name": "李全",
                     "debtor_id": "lin_yuan", "debtor_name": "林远",
                     "amount": 5.0, "due_tick": 95, "originated_tick": 5,
                     "debtor_grain_before": 1, "debtor_grain_after": 6,
                     "creditor_grain_before": 100, "creditor_grain_after": 95,
                     "debt_before": 0, "debt_after": 5}},
        {"id": 2, "tick": 95, "event_type": "debt_collected",
         "payload": {"creditor_id": "li_quan", "creditor_name": "李全",
                     "debtor_id": "lin_yuan", "debtor_name": "林远",
                     "amount_paid": 5.0, "remaining": 0.0, "overdue": False,
                     "debtor_grain_after": 0, "creditor_grain_after": 100}},
        {"id": 3, "tick": 95, "event_type": "debt_defaulted",
         "payload": {"creditor_id": "li_quan", "creditor_name": "李全",
                     "debtor_id": "lin_yuan", "debtor_name": "林远",
                     "amount": 5.0, "overdue_ticks": 0}},
        {"id": 4, "tick": 30, "event_type": "debt_repaid",
         "payload": {"creditor_id": "li_quan", "creditor_name": "李全",
                     "debtor_id": "lin_yuan", "debtor_name": "林远",
                     "amount": 10.0, "remaining": 10.0, "source": "harvest",
                     "debtor_grain_after": 30, "creditor_grain_after": 110}},
        {"id": 5, "tick": 10, "event_type": "health_recovered",
         "payload": {"agent_id": "lin_yuan", "agent_name": "林远",
                     "before": 50.0, "after": 50.5, "reason": "hunger_and_stamina_ok",
                     "hunger": 30, "stamina": 60}},
    ],
)
def test_render_new_event_types_not_degraded(evt):
    r = render_event(evt)
    assert r.degraded is False
    assert ("林远" in r.text) or ("李全" in r.text)


def test_render_unknown_event_still_degraded():
    r = render_event({"id": 9, "tick": 1, "event_type": "weird_unknown", "payload": {"a": 1}})
    assert r.degraded is True
    assert "未知事件类型" in r.text
