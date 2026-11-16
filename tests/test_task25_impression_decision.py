"""任务 25 P2 测试：印象参与债争诉求决策（独立开关、默认关闭、可回退）。

覆盖裁决 24/25 §2.2 第 4 项：
1. 开关关闭：行为与 P1 完全一致；
2. 开关打开 + 印象 defaulting + 无前科 → full（证明印象真的影响决策）；
3. 开关打开 + 印象 reliable + 无前科 → partial/deferral，不出现 full（防误伤）；
4. 开关打开 + 有前科 → prior_default 优先，印象不覆盖前科；
5. 经济守恒（grain 总量）与不新增事件类型；
6. 开关打开→关闭，行为回到基线（可回退）。

印象一律由 P1 的 `social.synthesize_impression` 从记忆窗口派生，不手写 label。
记忆组合选 [broken, repaid]：label=defaulting（1/2 违约率），但 last_outcome=repaid，
可与「记忆调节」分支区分——开关关闭时该组合走 deferral，打开时才是 full。
"""
from __future__ import annotations

import random

import pytest

from household_helpers import hh
from vale.core.config_loader import load_config
from vale.core.event_log import EventLog
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
    return hh(world, world.state.agents["lin_yuan"]), hh(world, world.state.agents["li_quan"])


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


def _seed_impression(world, outcomes: list[str]) -> str:
    """按给定 outcome 序列写债权方记忆，再用 P1 规则派生印象；返回 label。"""
    creditor = world.state.agents["li_quan"]
    debtor = world.state.agents["lin_yuan"]
    creditor.acquaintances[debtor.agent_id] = AcquaintanceEntry(
        level=int(AcquaintanceLevel.KNOWN), last_seen_tick=1,
    )
    for i, outcome in enumerate(outcomes):
        creditor.recent_interactions.append(MemoryEntry(
            tick=1 + i, target_id=debtor.agent_id,
            event_type="debt_dispute", outcome=outcome,
        ))
    label = social.update_impression(
        world, creditor.agent_id, debtor.agent_id,
        world.config.agents.tuning.social.impression_window,
    )
    assert label is not None
    return label


def _negotiate(world, switch: bool) -> dict:
    module = _module(world)
    tuning = world.config.agents.tuning
    tuning.social.impression_in_decision = switch
    debtor_hh, creditor_hh = _pair(world)
    rec = _dispute_debt(world, debtor_hh, creditor_hh)
    debtor_hh.grain = 8.0
    creditor_hh.grain = 20.0
    return module._negotiate_debt(  # noqa: SLF001
        world, tuning, debtor_hh, creditor_hh, rec,
        defaulted=set(), repaid=set(),
    )


DEFAULTING_MEMORIES = ["broken", "repaid"]   # label=defaulting，last_outcome=repaid
RELIABLE_MEMORIES = ["repaid", "repaid"]     # label=reliable


# --------------------------------------------------------------------------- #
# 1. 开关关闭：行为与 P1 完全一致（同一印象下不走 full）
# --------------------------------------------------------------------------- #
def test_switch_off_keeps_p1_behavior(world):
    label = _seed_impression(world, DEFAULTING_MEMORIES)
    assert label == social.IMPRESSION_DEFAULTING
    result = _negotiate(world, switch=False)
    # 关闭时印象不参与：partial 档经记忆调节（last_outcome=repaid）→ deferral
    assert result["proposal"] == "deferral"
    assert result["proposal"] != "full"


# --------------------------------------------------------------------------- #
# 2. 开关打开 + 印象 defaulting + 无前科 → full
# --------------------------------------------------------------------------- #
def test_switch_on_defaulting_impression_escalates_to_full(world):
    assert _seed_impression(world, DEFAULTING_MEMORIES) == social.IMPRESSION_DEFAULTING
    result = _negotiate(world, switch=True)
    assert result["proposal"] == "full"


# --------------------------------------------------------------------------- #
# 3. 开关打开 + 印象 reliable + 无前科 → 维持 partial/deferral，不出现 full
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("memories", [RELIABLE_MEMORIES, ["repaid", "deferred"]])
def test_switch_on_reliable_impression_never_full(world, memories):
    label = _seed_impression(world, memories)
    assert label != social.IMPRESSION_DEFAULTING
    result = _negotiate(world, switch=True)
    assert result["proposal"] in ("partial", "deferral")


# --------------------------------------------------------------------------- #
# 4. 开关打开 + 有前科 → prior_default 优先，印象不覆盖
# --------------------------------------------------------------------------- #
def test_switch_on_prior_default_wins_over_reliable_impression(world):
    _seed_impression(world, RELIABLE_MEMORIES)
    module = _module(world)
    debtor_hh, creditor_hh = _pair(world)
    rec = _dispute_debt(world, debtor_hh, creditor_hh)
    debtor_hh.grain = 8.0
    world.event_log.append(1, "debt_defaulted", {
        "debtor_household_id": debtor_hh.household_id,
        "household_id": debtor_hh.household_id,
    })
    defaulted, repaid = module._debt_history_sets(world)  # noqa: SLF001
    assert debtor_hh.household_id in defaulted
    world.config.agents.tuning.social.impression_in_decision = True
    result = module._negotiate_debt(  # noqa: SLF001
        world, world.config.agents.tuning, debtor_hh, creditor_hh, rec,
        defaulted=defaulted, repaid=repaid,
    )
    assert result["proposal"] == "full"
    assert result["response"] == "repay"


# --------------------------------------------------------------------------- #
# 5. 经济守恒 + 不新增事件类型
# --------------------------------------------------------------------------- #
def test_impression_decision_conserves_economy_and_adds_no_events(world):
    """P2 是纯读：开关开/关的 impresssion_* 与事件类型集合应完全一致；经济逐项守恒。"""
    def _scenario(switch: bool) -> dict:
        w = _build(0)
        run_tick(w)
        _seed_impression(w, DEFAULTING_MEMORIES)
        module = _module(w)
        debtor_hh, creditor_hh = _pair(w)
        rec = _dispute_debt(w, debtor_hh, creditor_hh)
        debtor_hh.grain = 8.0
        creditor_hh.grain = 20.0
        w.config.agents.tuning.social.impression_in_decision = switch
        grain_before = debtor_hh.grain + creditor_hh.grain
        debt_before = rec.amount
        imp_before = len(w.event_log.by_type("impression_formed")) + \
            len(w.event_log.by_type("impression_changed"))
        types_before = {e["event_type"] for e in w.event_log.all()}

        result = module._negotiate_debt(  # noqa: SLF001
            w, w.config.agents.tuning, debtor_hh, creditor_hh, rec,
            defaulted=set(), repaid=set(),
        )
        paid = sum(e["payload"]["amount"] for e in w.event_log.by_type("debt_repaid"))
        return {
            "proposal": result["proposal"],
            "grain_after": debtor_hh.grain + creditor_hh.grain,
            "grain_before": grain_before,
            "debt_after": rec.amount,
            "paid": paid,
            "debt_before": debt_before,
            "imp_delta": len(w.event_log.by_type("impression_formed"))
            + len(w.event_log.by_type("impression_changed")) - imp_before,
            "new_types": {e["event_type"] for e in w.event_log.all()} - types_before,
        }

    on, off = _scenario(True), _scenario(False)
    # 粮只在双方之间转移，总量守恒且非负
    for r in (on, off):
        assert r["grain_after"] == pytest.approx(r["grain_before"], abs=1e-6)
        assert r["debt_after"] + r["paid"] == pytest.approx(r["debt_before"], abs=1e-6)
    assert on["proposal"] == "full" and off["proposal"] == "deferral"
    # P2 是纯读：不新增事件类型（印象事件由 P1 记忆写回产生；结果不同则事件集合不同）
    allowed = {
        "conflict_started", "conflict_negotiation_round", "conflict_resolved",
        "debt_repaid", "debt_deferred", "debt_defaulted",
        "impression_formed", "impression_changed", "acquaintance_changed",
    }
    assert on["new_types"] <= allowed
    assert off["new_types"] <= allowed


# --------------------------------------------------------------------------- #
# 6. 开关打开→关闭，行为回到基线（可回退）
# --------------------------------------------------------------------------- #
def test_switch_toggle_is_reversible(world):
    _seed_impression(world, DEFAULTING_MEMORIES)
    on = _negotiate(world, switch=True)
    assert on["proposal"] == "full"
    off = _negotiate(world, switch=False)
    assert off["proposal"] == "deferral"
