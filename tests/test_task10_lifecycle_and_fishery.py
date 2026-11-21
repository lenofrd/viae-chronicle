"""任务 10 测试：死亡/失能生命周期、债务叙事分离、渔业生计、守恒与观察层。

覆盖任务 §6 清单：
- 失能/死亡事件幂等（只写一次）、失能后停止主动动作、债务核销可追溯；
- 违约状态变更（debt_defaulted，一次）与催收尝试（debt_collection_attempt，可重复）分离；
- 渔业配置驱动（fish 产出/失败/季节天气修正）、eat 多食物优先级（粮>肉>鱼）；
- 粮/肉/鱼/债非负守恒、观察层中文渲染、扩展点（新采集动作不改核心结算）、
  1800 tick × 5 种子不全员灭绝。
全部用内存 db，不依赖固定 events.db。
"""
from __future__ import annotations

from household_helpers import attach_test_resource_pools, hh
from vale.core.household import home_node_of, work_node_of

import dataclasses
import random

import pytest

from vale.config.schema.agents import GatheringActionTuning
from vale.config.schema.natural_params import Season
from vale.core.config_loader import load_config
from vale.core.event_log import EventLog
from vale.core.scheduler import run_tick
from vale.core.state import DebtRecord, HouseholdState
from vale.core.world import World
from vale.domains.society.agents import AgentModule, _candidate_actions, _target_node
from vale.domains.environment.climate import ClimateModule
from vale.observability.render import render_event


def _build(seed: int = 0) -> World:
    cfg = load_config("brookvale-town-001")
    log = EventLog(":memory:")
    w = World(world_id=cfg.world.world_id, event_log=log,
              start_tick=cfg.world.start_tick, config=cfg)
    attach_test_resource_pools(w)
    w.register(ClimateModule(rng=random.Random(seed)))
    w.register(AgentModule(rng=random.Random(seed * 7 + 13)))
    return w


@pytest.fixture
def world():
    w = _build(0)
    run_tick(w)  # 初始化 agents / climate
    return w


def _module(world) -> AgentModule:
    return next(m for m in world.modules if m.name == "agents")


def _move_out(world, agent):
    """把 agent 迁出当前家庭单独建户（家庭模型：跨户继承才发生）。"""
    old = hh(world, agent)
    old.member_ids = [m for m in old.member_ids if m != agent.agent_id]
    old.head_id = old.member_ids[0] if old.member_ids else None
    new_id = f"hh_{agent.agent_id}_solo"
    world.state.human.households[new_id] = HouseholdState(
        household_id=new_id, member_ids=[agent.agent_id], head_id=agent.agent_id,
        home_node=old.home_node, work_node=old.work_node, formed_tick=world.current_tick,
    )
    agent.household_id = new_id
    return world.state.human.households[new_id]


# =========================================================================== #
# 3.1 失能 / 死亡生命周期
# =========================================================================== #
def test_incapacitation_event_written_once(world):
    """health 触底 → 写一次 agent_incapacitated；多 tick 不重复。"""
    lin = world.state.human.agents["lin_yuan"]
    lin.health = 0.0
    for _ in range(5):
        run_tick(world)
    events = world.event_log.by_type("agent_incapacitated")
    assert len(events) == 1
    p = events[0]["payload"]
    assert p["agent_id"] == "lin_yuan"
    assert p["reason"] == "health_bottomed"
    assert p["death_grace_ticks"] == world.config.agents.tuning.death.death_grace_ticks
    assert world.state.human.agents["lin_yuan"].incapacitated is True


def test_incapacitated_agent_stops_taking_actions(world):
    """失能后不再产生任何新的 agent_action_taken（停止感知/决策/执行）。"""
    lin = world.state.human.agents["lin_yuan"]
    baseline = len([e for e in world.event_log.by_type("agent_action_taken")
                    if e["payload"]["agent_id"] == "lin_yuan"])
    lin.health = 0.0
    for _ in range(4):
        run_tick(world)
    after = len([e for e in world.event_log.by_type("agent_action_taken")
                 if e["payload"]["agent_id"] == "lin_yuan"])
    assert after == baseline, "失能者不应有任何新的主动动作事件"


def test_death_after_grace_ticks_event_once(world):
    """失能满 death_grace_ticks → 写一次 agent_died，alive=False；事件幂等。"""
    grace = world.config.agents.tuning.death.death_grace_ticks
    lin = world.state.human.agents["lin_yuan"]
    lin.health = 0.0
    for _ in range(grace + 2):
        run_tick(world)
    died = world.event_log.by_type("agent_died")
    assert len(died) == 1
    p = died[0]["payload"]
    assert p["agent_id"] == "lin_yuan"
    assert p["died_tick"] == p["incapacitated_tick"] + grace
    st = world.state.human.agents["lin_yuan"]
    assert st.alive is False
    assert st.died_tick is not None
    for _ in range(5):  # 死者继续留在状态中但绝不再写事件
        run_tick(world)
    assert len(world.event_log.by_type("agent_died")) == 1
    assert len(world.event_log.by_type("agent_incapacitated")) == 1


def test_forgive_debts_traceable_no_grain_movement(world):
    """核销是坏账处理：逐笔 debt_forgiven 可追溯、列表清空、债主粮分文不动。

    端到端（失能→死亡→核销）由 test_death_after_grace_ticks_event_once 与
    test_death_reduces_world_debt_with_events 覆盖；此处单测核销本身不移动粮食。
    """
    module = _module(world)
    lin = world.state.human.agents["lin_yuan"]
    li_before = hh(world, world.state.human.agents["li_quan"]).grain
    zhao_before = hh(world, world.state.human.agents["zhao_cuilan"]).grain
    hh(world, lin).debts = [
        DebtRecord(debtor_household_id="hh_lin_yuan", creditor_household_id="hh_li_quan",
                   amount=5.0, originated_tick=0, due_tick=9999),
        DebtRecord(debtor_household_id="hh_lin_yuan", creditor_household_id="hh_zhao_cuilan",
                   amount=7.0, originated_tick=0, due_tick=9999),
    ]
    module._forgive_debts(world, hh(world, lin), cause="death")  # noqa: SLF001
    assert hh(world, lin).debts == []  # 债务列表清空
    forgiven = world.event_log.by_type("debt_forgiven")
    assert {e["payload"]["creditor_id"] for e in forgiven} == {"li_quan", "zhao_cuilan"}
    assert sum(e["payload"]["amount"] for e in forgiven) == pytest.approx(12.0)
    assert all(e["payload"]["cause"] == "death" for e in forgiven)
    # 核销不移动粮食：债主存粮分文不变（坏账由债主承担，非粮转移）
    assert hh(world, world.state.human.agents["li_quan"]).grain == pytest.approx(li_before)
    assert hh(world, world.state.human.agents["zhao_cuilan"]).grain == pytest.approx(zhao_before)


def test_incapacitated_skips_collection_and_recovery(world):
    """失能期间：不催收（无违约/催收事件）、不回血（health 保持 0）。"""
    lin = world.state.human.agents["lin_yuan"]
    lin.health = 0.0
    lin.hunger = 30.0
    lin.stamina = 80.0
    hh(world, lin).debts = [DebtRecord(debtor_household_id="hh_lin_yuan", creditor_household_id="hh_li_quan", amount=5.0,
                            originated_tick=0, due_tick=1)]  # 已到期（若催收将写违约）
    grace = world.config.agents.tuning.death.death_grace_ticks
    for _ in range(min(grace, 4)):
        run_tick(world)
    debt_evts = [e for t in ("debt_collected", "debt_defaulted", "debt_collection_attempt")
                 for e in world.event_log.by_type(t)
                 if e["payload"].get("debtor_id") == "lin_yuan"]
    assert not debt_evts, "失能者不参与催收，避免对垂死之人刷违约"
    assert world.state.human.agents["lin_yuan"].health == pytest.approx(0.0)


# =========================================================================== #
# 3.3 债务叙事分离：违约状态变更（一次） vs 催收尝试（可重复）
# =========================================================================== #
def test_defaulted_once_then_collection_attempts(world):
    """零粮首催写 debt_defaulted 一次；后续每周期写 debt_collection_attempt，违约不再重复。"""
    module = _module(world)
    tuning = world.config.agents.tuning
    interval = tuning.debt.collection_interval_days
    lin = world.state.human.agents["lin_yuan"]
    hh(world, lin).grain = 0.0
    hh(world, lin).debts = [DebtRecord(debtor_household_id="hh_lin_yuan", creditor_household_id="hh_li_quan", amount=6.0,
                            originated_tick=0, due_tick=0)]  # 已到期
    world.current_tick = 10
    module._collect_debts(world, lin, tuning)  # noqa: SLF001
    assert len(world.event_log.by_type("debt_defaulted")) == 1
    assert hh(world, lin).debts[0].overdue is True

    world.current_tick = 10 + interval
    module._collect_debts(world, lin, tuning)  # noqa: SLF001
    world.current_tick = 10 + 2 * interval
    module._collect_debts(world, lin, tuning)  # noqa: SLF001

    assert len(world.event_log.by_type("debt_defaulted")) == 1, "违约状态变更只写一次"
    attempts = world.event_log.by_type("debt_collection_attempt")
    assert len(attempts) == 2, "每个催收周期写一次催收尝试"
    assert attempts[-1]["payload"]["debtor_id"] == "lin_yuan"
    assert attempts[-1]["payload"]["interval_days"] == interval


def test_full_payment_writes_no_default_or_attempt(world):
    """有粮足额清偿 → 只写 debt_collected，无违约/催收尝试。"""
    module = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.human.agents["lin_yuan"]
    hh(world, lin).grain = 8.0
    hh(world, lin).debts = [DebtRecord(debtor_household_id="hh_lin_yuan", creditor_household_id="hh_li_quan", amount=6.0,
                            originated_tick=0, due_tick=0)]
    world.current_tick = 10
    module._collect_debts(world, lin, tuning)  # noqa: SLF001
    assert not world.event_log.by_type("debt_defaulted")
    assert not world.event_log.by_type("debt_collection_attempt")
    assert hh(world, lin).debt == pytest.approx(0.0)
    assert hh(world, lin).debts == []


# =========================================================================== #
# 3.4 渔业（配置驱动采集分支）
# =========================================================================== #
def test_fish_action_configured(world):
    """fish 配置齐全：目标翠溪镇前段、产出鱼字段、户外动作、走通用候选。"""
    tuning = world.config.agents.tuning
    fish = tuning.gathering.actions["fish"]
    assert fish.target_node == "river_town"
    assert fish.output_field == "fish"
    assert "fish" in tuning.action.outdoor
    assert "fish" in _candidate_actions(tuning)
    agent = next(iter(world.state.human.agents.values()))
    assert _target_node("fish", agent, world) == "river_town"


def test_fish_success_produces_fish(world):
    """成功率拉满时捕鱼必成功：fish 字段增加、写 gather_success。"""
    module = _module(world)
    tuning = world.config.agents.tuning
    cfg = tuning.gathering.actions["fish"]
    cfg.base_success_rate = 1.0
    cfg.season_modifier = {}
    cfg.injury_risk = 0.0
    agent = next(iter(world.state.human.agents.values()))
    p = module._perceive(world, agent)  # noqa: SLF001
    p = dataclasses.replace(p, is_raining=False)
    fish_before = hh(world, agent).fish
    module._execute_gather(world, agent, "fish", p, tuning)  # noqa: SLF001
    assert hh(world, agent).fish == pytest.approx(fish_before + cfg.output_amount)
    ev = [e for e in world.event_log.by_type("gather_success")
          if e["payload"]["action"] == "fish"][-1]
    assert ev["payload"]["output_field"] == "fish"


def test_fish_fail_no_output(world):
    """季节修正把成功率乘到 0 时必失败：无产出、写 gather_fail。"""
    module = _module(world)
    tuning = world.config.agents.tuning
    cfg = tuning.gathering.actions["fish"]
    cfg.base_success_rate = 1.0
    cfg.season_modifier = {"summer": 0.0}
    cfg.injury_risk = 0.0
    agent = next(iter(world.state.human.agents.values()))
    p = module._perceive(world, agent)  # noqa: SLF001
    p = dataclasses.replace(p, is_raining=False, season=Season.SUMMER)
    fish_before = hh(world, agent).fish
    module._execute_gather(world, agent, "fish", p, tuning)  # noqa: SLF001
    assert hh(world, agent).fish == pytest.approx(fish_before)
    fails = [e for e in world.event_log.by_type("gather_fail")
             if e["payload"]["action"] == "fish"]
    assert fails


def test_fish_season_and_weather_modify_success_rate(world):
    """成功率 = base × 季节修正 × 坏天气修正（事件载荷可复核，不硬编码）。"""
    module = _module(world)
    tuning = world.config.agents.tuning
    cfg = tuning.gathering.actions["fish"]
    cfg.base_success_rate = 0.5
    cfg.season_modifier = {"winter": 0.6}
    cfg.injury_risk = 0.0
    agent = next(iter(world.state.human.agents.values()))
    p = module._perceive(world, agent)  # noqa: SLF001
    p = dataclasses.replace(p, is_raining=True, season=Season.WINTER)
    module.rng = random.Random(0)  # 0.844 ≥ 0.12 → 失败
    module._execute_gather(world, agent, "fish", p, tuning)  # noqa: SLF001
    ev = world.event_log.by_type("gather_fail")[-1]["payload"]
    assert ev["action"] == "fish"
    assert ev["success_rate"] == pytest.approx(0.5 * 0.6 * cfg.bad_weather_success_mult)


# =========================================================================== #
# eat 多食物优先级（粮 > 肉 > 鱼）
# =========================================================================== #
def test_eat_consumes_fish_when_grain_meat_empty(world):
    agent = next(iter(world.state.human.agents.values()))
    hh(world, agent).grain = 0.0
    hh(world, agent).meat = 0.0
    hh(world, agent).vegetable = 0.0
    hh(world, agent).fish = 5.0
    agent.hunger = 90.0
    mod = _module(world)
    p = mod._perceive(world, agent)  # noqa: SLF001
    mod._execute(world, agent, "eat", p, world.config.agents.tuning)  # noqa: SLF001
    assert hh(world, agent).fish == pytest.approx(4.0)
    assert hh(world, agent).grain == 0.0 and hh(world, agent).meat == 0.0


def test_eat_prefers_meat_over_fish(world):
    """food_fields 优先级：grain(0) → meat；fish 不动。"""
    agent = next(iter(world.state.human.agents.values()))
    hh(world, agent).grain = 0.0
    hh(world, agent).meat = 2.0
    hh(world, agent).vegetable = 0.0
    hh(world, agent).fish = 5.0
    agent.hunger = 90.0
    mod = _module(world)
    p = mod._perceive(world, agent)  # noqa: SLF001
    mod._execute(world, agent, "eat", p, world.config.agents.tuning)  # noqa: SLF001
    assert hh(world, agent).meat == pytest.approx(1.0)
    assert hh(world, agent).fish == pytest.approx(5.0)


# =========================================================================== #
# 守恒 / 非负
# =========================================================================== #
def test_food_and_debt_non_negative_over_300_ticks(world):
    """300 tick：粮/肉/鱼/债非负、无 agent_error（错误隔离）。"""
    for _ in range(300):
        run_tick(world)
    for a in world.state.human.agents.values():
        assert hh(world, a).grain >= 0 and hh(world, a).meat >= 0 and hh(world, a).fish >= 0 and hh(world, a).debt >= 0
    assert not world.event_log.by_type("agent_error")


def _world_debt(world) -> float:
    """世界总债（按家庭去重；同户多存活成员只计一次）。"""
    households = {hh(world, a).household_id: hh(world, a) for a in world.state.human.agents.values()}
    return sum(h.debt for h in households.values())


def test_death_reduces_world_debt_with_events(world):
    """死亡使世界总债按继承比例减少：D11 = 0.5 转移给继承人、0.5 核销，两笔均有事件。"""
    tuning = world.config.agents.tuning
    lin = world.state.human.agents["lin_yuan"]
    zhao = world.state.human.agents["zhao_cuilan"]
    # 固定配偶关系，保证继承人有确定值（否则婚配结算会改变继承人）
    lin.spouse_id, zhao.spouse_id = zhao.agent_id, lin.agent_id
    _move_out(world, lin)  # 家庭模型：死者须为家庭最后成员，继承才发生
    _move_out(world, zhao)  # 继承人独立成户，避免与债权家庭重合
    hh(world, zhao).grain = 50.0  # 004：继承人新户补给存粮，隔离"日内多动作下借粮新增债务"的噪声
    hh(world, lin).debts = [DebtRecord(debtor_household_id="hh_lin_yuan", creditor_household_id="hh_li_quan", amount=5.0,
                            originated_tick=0, due_tick=9999)]
    debt_before = _world_debt(world)
    lin.health = 0.0
    grace = tuning.death.death_grace_ticks
    for _ in range(grace + 1):
        run_tick(world)
    debt_after = _world_debt(world)
    transferred = 5.0 * tuning.inheritance.debt_ratio
    assert debt_after == pytest.approx(debt_before - transferred)
    assert len(world.event_log.by_type("debt_transferred")) == 1
    assert len(world.event_log.by_type("debt_written_off")) == 1
    assert world.event_log.by_type("debt_written_off")[0]["payload"]["amount"] == pytest.approx(2.5)


# =========================================================================== #
# 观察层渲染
# =========================================================================== #
def test_render_life_events_chinese():
    inc = {"event_type": "agent_incapacitated", "payload": {
        "agent_id": "zhao_cuilan", "agent_name": "赵翠兰", "reason": "health_bottomed",
        "health": 0, "hunger": 100, "stamina": 0, "death_grace_ticks": 7}}
    r = render_event(inc)
    assert not r.degraded and "失能" in r.text and "赵翠兰" in r.text
    died = {"event_type": "agent_died", "payload": {
        "agent_id": "zhao_cuilan", "agent_name": "赵翠兰", "cause": "health_bottomed",
        "incapacitated_tick": 100, "died_tick": 107, "health": 0, "outstanding_debt": 3}}
    r = render_event(died)
    assert not r.degraded and "死亡" in r.text


def test_render_debt_narrative_events():
    attempt = {"event_type": "debt_collection_attempt", "payload": {
        "creditor_id": "li_quan", "creditor_name": "李全",
        "debtor_id": "lin_yuan", "debtor_name": "林远",
        "amount": 5.0, "overdue_ticks": 30, "interval_days": 30}}
    r = render_event(attempt)
    assert not r.degraded and "催收" in r.text
    forgiven = {"event_type": "debt_forgiven", "payload": {
        "creditor_id": "li_quan", "creditor_name": "李全",
        "debtor_id": "lin_yuan", "debtor_name": "林远", "amount": 5.0, "cause": "death"}}
    r = render_event(forgiven)
    assert not r.degraded and "核销" in r.text


def test_render_fish_events():
    act = {"event_type": "agent_action_taken", "payload": {
        "agent_name": "赵翠兰", "action": "fish", "target_node": "river_town",
        "fish_after": 4}}
    r = render_event(act, names={"river_town": "翠溪镇前段"})
    assert not r.degraded and "捕鱼" in r.text
    succ = {"event_type": "gather_success", "payload": {
        "agent_id": "zhao_cuilan", "agent_name": "赵翠兰", "action": "fish",
        "resource_node": "river_town", "output_field": "fish",
        "output_before": 2, "output_after": 4, "amount": 2, "success_rate": 0.45}}
    r = render_event(succ)
    assert not r.degraded and "捕鱼" in r.text and "鱼" in r.text


def test_render_unknown_event_fallback_preserved():
    """未知事件类型兜底不崩（观察层兼容性）。"""
    r = render_event({"event_type": "future_thing", "payload": {"x": 1}})
    assert r.degraded and r.reason == "unknown_event_type"


# =========================================================================== #
# 3.5 扩展点：新采集动作只加配置，不改核心结算
# =========================================================================== #
def test_new_gather_action_plugs_in_without_core_changes(world):
    """新增采集动作（割芦苇，产出写入 fish 字段）只靠配置即可接入。"""
    tuning = world.config.agents.tuning
    tuning.gathering.actions["cut_reed"] = GatheringActionTuning(
        target_node="river_downstream", output_field="fish", base_success_rate=1.0,
        output_amount=2, injury_risk=0.0, bad_weather_success_mult=1.0,
        bad_weather_injury_mult=1.0,
    )
    attach_test_resource_pools(world)
    assert "cut_reed" in _candidate_actions(tuning)
    mod = _module(world)
    agent = next(iter(world.state.human.agents.values()))
    p = mod._perceive(world, agent)  # noqa: SLF001
    before = hh(world, agent).fish
    mod._execute_gather(world, agent, "cut_reed", p, tuning)  # noqa: SLF001
    assert hh(world, agent).fish == pytest.approx(before + 2)
    evs = [e for e in world.event_log.by_type("gather_success")
           if e["payload"]["action"] == "cut_reed"]
    assert evs


# =========================================================================== #
# 长程：1800 tick × 5 种子不全员灭绝（任务 §6.14）
# =========================================================================== #
@pytest.mark.parametrize("seed", [0, 1, 7, 42, 123])
def test_1800_ticks_not_all_extinct_with_diverse_food(seed):
    """1800 tick 不全员灭绝（阶段三验收：技术债断言已恢复）。"""
    w = _build(seed)
    harvest_grain = 0.0
    fish_amount = 0.0
    curve: list[int] = []
    for tick in range(1, 1801):
        run_tick(w)
        if tick % 200 == 0:
            curve.append(sum(1 for a in w.state.human.agents.values() if a.alive))
    alive = sum(1 for a in w.state.human.agents.values() if a.alive)
    if not alive:
        events = w.event_log.all()
        deaths = [e for e in events if e["event_type"] == "agent_died"]
        actions = [e for e in events if e["event_type"] == "agent_action_taken"]
        first_death = min(deaths, key=lambda e: e["tick"]) if deaths else None
        action_counts = {
            action: sum(1 for e in actions if e["payload"].get("action") == action
                        and int(e.get("tick", -1)) <= 60)
            for action in sorted({e["payload"].get("action", "unknown") for e in actions})
        }
        stocks = {
            field: round(sum(float(getattr(h, field)) for h in w.state.human.households.values()), 2)
            for field in ("grain", "fish", "meat", "vegetable")
        }
        pytest.fail(
            f"seed={seed} 1800 tick 全员灭绝; first_death={first_death}; "
            f"actions_first_60_ticks={action_counts}; final_food={stocks}; population_curve={curve}"
        )
    assert len(curve) == 9
    assert all(count >= 0 for count in curve)
    for a in w.state.human.agents.values():
        assert hh(w, a).grain >= 0 and hh(w, a).meat >= 0 and hh(w, a).fish >= 0 and hh(w, a).debt >= 0
    assert not w.event_log.by_type("agent_error")
    # 事件幂等：每人失能/死亡至多一次
    for evt_type in ("agent_incapacitated", "agent_died"):
        ids = [e["payload"]["agent_id"] for e in w.event_log.by_type(evt_type)]
        assert len(ids) == len(set(ids))
    # 农业贡献：3 年+ 内秋收粮总产应显著（每年 ≥ 1 次秋收）
    for e in w.event_log.by_type("agent_action_taken"):
        p = e["payload"]
        if p.get("action") == "harvest":
            harvest_grain += p.get("grain_after", 0) - p.get("grain_before", 0)
    for e in w.event_log.by_type("gather_success"):
        if e["payload"].get("action") == "fish":
            fish_amount += e["payload"].get("amount", 0)
    assert harvest_grain > 0, "农业产出不应为 0"
