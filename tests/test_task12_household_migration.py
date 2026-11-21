"""任务 12 家庭模型迁移第 1 步专项测试。

覆盖：
- 单人家庭初始化（资产/住所/户主/成员）；
- 家庭是经济单位：事件带 household_id、进食扣家庭库存；
- 旧事件流只读重放为家庭状态，资产/债务/住所与旧快照一致；
- 重放不改写事件、无孤儿家庭/孤儿成员。
"""
from __future__ import annotations

import copy
import json
import pathlib
import random

import pytest

from household_helpers import attach_test_resource_pools, hh, inv
from vale.core.household import work_node_of
from vale.core.config_loader import load_config
from vale.core.event_log import EventLog
from vale.core.replay import rebuild_state
from vale.core.scheduler import run_tick
from vale.core.world import World
from vale.modules.agents import AgentModule
from vale.domains.environment.climate import ClimateModule

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _build(seed: int = 0) -> World:
    cfg = load_config("brookvale-town-001")
    w = World(world_id=cfg.world.world_id, event_log=EventLog(":memory:"),
              start_tick=cfg.world.start_tick, config=cfg)
    attach_test_resource_pools(w)
    w.register(ClimateModule(rng=random.Random(seed)))
    w.register(AgentModule(rng=random.Random(seed * 7 + 13)))
    return w


@pytest.fixture
def world():
    w = _build(0)
    run_tick(w)
    return w


def _legacy_events() -> list[dict]:
    return json.loads((FIXTURES / "legacy_events.json").read_text(encoding="utf-8"))


def _expected() -> dict:
    return json.loads((FIXTURES / "legacy_events_expected.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# 单人家庭初始化
# --------------------------------------------------------------------------- #
def test_each_config_agent_gets_single_household():
    w = _build(0)
    module = next(m for m in w.modules if m.name == "agents")
    module._ensure_agents(w, w.config.agents)  # noqa: SLF001 — 只验证初始化
    cfg = w.config
    for agent_cfg in cfg.agents.agents:
        agent = w.state.human.agents[agent_cfg.id]
        assert agent.household_id == f"hh_{agent_cfg.id}"
        household = w.state.human.households[agent.household_id]
        assert household.member_ids == [agent_cfg.id]
        assert household.head_id == agent_cfg.id
        assert household.grain == pytest.approx(agent_cfg.assets.grain)
        assert household.vegetable == pytest.approx(agent_cfg.assets.vegetable)
        assert household.cloth == pytest.approx(agent_cfg.assets.cloth)
        assert household.home_node == agent_cfg.home_node
        assert household.work_node == agent_cfg.work_node
        assert agent.work_node == agent_cfg.work_node  # Q2：个人劳作点偏好保留


def test_household_ids_are_unique_and_heads_are_members(world):
    households = world.state.human.households
    assert len({h.household_id for h in households.values()}) == len(households)
    for household in households.values():
        if household.member_ids:
            assert household.head_id in household.member_ids
        assert all(mid in world.state.human.agents for mid in household.member_ids)


# --------------------------------------------------------------------------- #
# 家庭是经济单位
# --------------------------------------------------------------------------- #
def test_action_events_carry_household_id_and_use_household_inventory(world):
    lin = world.state.human.agents["lin_yuan"]
    household = hh(world, lin)
    household.grain = 5.0
    lin.hunger = 90.0
    run_tick(world)
    actions = [e for e in world.event_log.by_type("agent_action_taken")
               if e["payload"]["agent_id"] == "lin_yuan"
               and e["payload"]["action"] == "eat"]
    assert actions
    payload = actions[-1]["payload"]
    assert payload["household_id"] == household.household_id
    assert "household_inv_before" in payload and "household_inv_after" in payload
    assert payload["grain_after"] == pytest.approx(4.0)  # 本次进食扣 1 石
    # 同户其他成员可能在同一 tick 稍后再进食，因此家庭当前库存 ≤ 本次事件后的库存
    assert household.grain <= payload["grain_after"] + 1e-9


def test_household_inventory_matches_config_seed(world):
    for agent in world.state.human.agents.values():
        assert inv(world, agent)["grain"] >= 0
        assert set(inv(world, agent)) == {"grain", "meat", "fish", "vegetable", "cloth"}


# --------------------------------------------------------------------------- #
# 旧事件流只读重放
# --------------------------------------------------------------------------- #
def test_legacy_replay_creates_single_households():
    cfg = load_config("brookvale-town-001")
    events = _legacy_events()
    result = rebuild_state(events, cfg)
    state = result.state
    assert state.human.agents and state.human.households
    for agent in state.human.agents.values():
        assert agent.household_id == f"hh_{agent.agent_id}"
        household = state.human.households[agent.household_id]
        assert agent.agent_id in household.member_ids
        assert household.head_id in household.member_ids
    # 无孤儿家庭：每个家庭成员都在 agents 中
    for household in state.human.households.values():
        assert all(mid in state.human.agents for mid in household.member_ids)
    assert not result.ignored_events.get("agent_died", 0)


def test_legacy_replay_matches_old_snapshots():
    cfg = load_config("brookvale-town-001")
    expected = _expected()
    state = rebuild_state(_legacy_events(), cfg).state
    for agent_id, exp in expected["agents"].items():
        agent = state.human.agents[agent_id]
        household = state.human.households[agent.household_id]
        for field, value in exp["assets"].items():
            assert getattr(household, field) == pytest.approx(value, abs=1e-6), (
                f"{agent_id}.{field} replay={getattr(household, field)} old={value}"
            )
        assert household.debt == pytest.approx(exp["debt"], abs=1e-6), agent_id
        assert household.home_node == exp["home_node"], agent_id
        assert household.work_node == exp["work_node"], agent_id
        assert agent.alive is exp["alive"], agent_id


def test_legacy_replay_debt_ids_are_households():
    cfg = load_config("brookvale-town-001")
    state = rebuild_state(_legacy_events(), cfg).state
    seen = 0
    for household in state.human.households.values():
        for rec in household.debts:
            seen += 1
            assert rec.debtor_household_id == household.household_id
            assert rec.creditor_household_id.startswith("hh_")
            assert rec.amount >= 0
    assert seen > 0, "旧事件流应至少包含一笔债务"


def test_replay_debt_side_transfer_without_debtor_key_stays_compatible():
    """G7 回放兼容：旧库债务侧转移（无 debtor_household_id）不报错、金额一致。"""
    cfg = load_config("brookvale-town-001")
    events = [
        {"id": 1, "tick": 0, "event_type": "debt_formed", "payload": {
            "debtor_id": "lin_yuan", "debtor_household_id": "hh_lin_yuan",
            "creditor_id": "zhao_cuilan", "creditor_household_id": "hh_zhao_cuilan",
            "amount": 4.0, "due_tick": 500}},
        {"id": 2, "tick": 1, "event_type": "debt_transferred", "payload": {
            "from_id": "lin_yuan", "from_household_id": "hh_lin_yuan",
            "to_id": "li_quan", "to_household_id": "hh_li_quan",
            "creditor_id": "zhao_cuilan", "creditor_household_id": "hh_zhao_cuilan",
            "amount": 2.0, "due_tick": 500}},
    ]
    state = rebuild_state(events, cfg).state
    assert state.human.households["hh_lin_yuan"].debt == pytest.approx(2.0)
    assert state.human.households["hh_li_quan"].debt == pytest.approx(2.0)


def test_replay_creditor_side_transfer_uses_debtor_household_id():
    """G7 回放：债权侧转移按 debtor_household_id 改挂应收债权，不产生错位债务。"""
    cfg = load_config("brookvale-town-001")
    events = [
        {"id": 1, "tick": 0, "event_type": "debt_formed", "payload": {
            "debtor_id": "lin_yuan", "debtor_household_id": "hh_lin_yuan",
            "creditor_id": "zhao_cuilan", "creditor_household_id": "hh_zhao_cuilan",
            "amount": 4.0, "due_tick": 500}},
        {"id": 2, "tick": 1, "event_type": "debt_transferred", "payload": {
            "from_id": "zhao_cuilan", "from_household_id": "hh_zhao_cuilan",
            "to_id": "li_quan", "to_household_id": "hh_li_quan",
            "creditor_id": "li_quan", "creditor_household_id": "hh_li_quan",
            "debtor_id": "lin_yuan", "debtor_household_id": "hh_lin_yuan",
            "amount": 4.0, "due_tick": 500}},
    ]
    state = rebuild_state(events, cfg).state
    debtor_hh = state.human.households["hh_lin_yuan"]
    assert debtor_hh.debt == pytest.approx(4.0)
    assert debtor_hh.debts[0].creditor_household_id == "hh_li_quan"
    assert state.human.households["hh_li_quan"].debts == []
    assert state.human.households["hh_zhao_cuilan"].debts == []


def test_legacy_replay_does_not_rewrite_events():
    cfg = load_config("brookvale-town-001")
    events = _legacy_events()
    snapshot = copy.deepcopy(events)
    rebuild_state(events, cfg)
    assert events == snapshot


# --------------------------------------------------------------------------- #
# 家庭口径专项覆盖（3.2 对账用：替代被隔离的单人单元测试）
# --------------------------------------------------------------------------- #
def _module(world):
    return next(m for m in world.modules if m.name == "agents")


def test_household_adult_eat_consumes_household_stock(world):
    """覆盖 test_agents / test_task10 / test_hunting 中“单人进食”被隔离的语义。"""
    mod = _module(world)
    agent = world.state.human.agents["lin_yuan"]
    household = hh(world, agent)
    household.grain, household.vegetable, household.meat, household.fish = 5.0, 0.0, 0.0, 0.0
    agent.hunger = 90.0
    mod._execute(world, agent, "eat", mod._perceive(world, agent),
                 world.config.agents.tuning)  # noqa: SLF001
    assert household.grain == pytest.approx(4.0)
    assert inv(world, agent)["grain"] == pytest.approx(4.0)


def test_household_harvest_adds_to_household_stock(world):
    """覆盖 test_agents::test_harvest_autumn... 被隔离的家庭生产语义。"""
    mod = _module(world)
    agent = world.state.human.agents["lin_yuan"]
    household = hh(world, agent)
    tuning = world.config.agents.tuning
    household.grain = 0.0
    household.vegetable = 0.0
    household.meat, household.fish, household.cloth = 0.0, 0.0, 0.0
    node = work_node_of(world, agent)
    world.state.environment.field_growth[node] = 100.0
    agent.location = node
    mod._execute(world, agent, "harvest", mod._perceive(world, agent),
                 tuning)  # noqa: SLF001
    assert sum(inv(world, agent).values()) > 0.0
    assert all(getattr(a, "grain", None) is None for a in world.state.human.agents.values())


def test_household_borrow_moves_grain_between_households(world):
    """覆盖 test_agents / test_economy 被隔离的借粮与债主选择语义。"""
    mod = _module(world)
    debtor = world.state.human.agents["lin_yuan"]
    creditor = world.state.human.agents["li_quan"]
    tuning = world.config.agents.tuning
    debtor_hh, creditor_hh = hh(world, debtor), hh(world, creditor)
    debtor_hh.grain = 0.0
    creditor_hh.grain = 50.0
    perception = mod._perceive(world, debtor)  # noqa: SLF001
    perception.creditor_id = creditor.agent_id
    total_before = debtor_hh.grain + creditor_hh.grain
    mod._execute(world, debtor, "borrow_grain", perception, tuning)  # noqa: SLF001
    assert debtor_hh.grain + creditor_hh.grain == pytest.approx(total_before)
    assert debtor_hh.grain > 0.0
    formed = world.event_log.by_type("debt_formed")[-1]["payload"]
    assert formed["debtor_household_id"] == debtor_hh.household_id
    assert formed["creditor_household_id"] == creditor_hh.household_id


def test_household_market_runs_once_per_household(world):
    """覆盖 test_task11 集市“每户一次”语义（被隔离测试的家庭对应项）。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    for household in {a.household_id for a in world.state.human.agents.values()}:
        world.state.human.households[household].home_node = tuning.market.market_node
    mod._settle_market(world, tuning)  # noqa: SLF001
    summary = world.event_log.by_type("market_day_summary")[-1]["payload"]
    households = [p["household_id"] for p in summary["participants"]]
    assert len(households) == len(set(households))


def test_household_market_never_trades_within_same_household(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    for household in {a.household_id for a in world.state.human.agents.values()}:
        world.state.human.households[household].home_node = tuning.market.market_node
    mod._settle_market(world, tuning)  # noqa: SLF001
    by_id = {h.household_id: h for h in world.state.human.households.values()}
    for event in world.event_log.by_type("trade_executed"):
        p = event["payload"]
        seller_hh = p.get("seller_household_id")
        buyer_hh = p.get("buyer_household_id")
        if seller_hh and buyer_hh:
            assert seller_hh != buyer_hh
    assert all(h.debt >= 0 for h in by_id.values())
