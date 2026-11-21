"""任务 18 P1 测试：印象沉淀层（进档案不接决策）。

覆盖裁决 18-impression §五：
- 载体默认空、旧库回放印象为空（§5.1/§5.7）；
- 合成幂等、counts 只由记忆窗口派生（§5.2/§5.4）；
- 运行时 vs replay 逐项一致（§5.3）；
- label 四类边界（§5.5）；
- 事件只在 label 变化时写（§5.6）；
- 渲染降级（§5.9）。
全部内存事件库，seeded rng，可复现。
"""
from __future__ import annotations

import json
import pathlib
import random

import pytest

from household_helpers import attach_test_resource_pools
from vale.core.config_loader import load_config
from vale.core.event_log import EventLog
from vale.core.replay import rebuild_state
from vale.core.scheduler import run_tick
from vale.core.state import AgentState, ImpressionEntry
from vale.core.world import World
from vale.modules import social
from vale.modules.agents import AgentModule
from vale.domains.environment.climate import ClimateModule
from vale.observability.render import render_event

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
OBSERVER = "li_quan"
TARGET = "lin_yuan"


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


def _module(world) -> AgentModule:
    return next(m for m in world.modules if m.name == "agents")  # type: ignore[return-value]


def _window(world) -> int:
    return world.config.agents.tuning.social.impression_window


def _record(world, observer_id: str, target_id: str, outcome: str, tick: int) -> None:
    social.record_memory(
        world.state.human.agents[observer_id], target_id, "debt_dispute", outcome, tick,
        world.config.agents.tuning.social.memory_capacity,
    )


def _bare_agent(agent_id="x") -> AgentState:
    return AgentState(agent_id=agent_id, name=agent_id, sex="male", birth_tick=0,
                      household_id=f"hh_{agent_id}", location="well",
                      health=100.0, hunger=0.0, stamina=100.0)


# --------------------------------------------------------------------------- #
# 载体与配置（§5.1）
# --------------------------------------------------------------------------- #
def test_impression_window_defaults_to_memory_capacity(world):
    soc = world.config.agents.tuning.social
    assert soc.impression_window == 5          # 临时值待复核，本任务不调
    assert soc.impression_window == soc.memory_capacity


def test_impressions_default_empty(world):
    for agent in world.state.human.agents.values():
        assert agent.impressions == {}
    assert _bare_agent().impressions == {}


# --------------------------------------------------------------------------- #
# label 规则边界（§5.5）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("counts,expected", [
    ({"contracts": 0, "defaults": 0, "repays": 0}, "unknown"),
    ({"contracts": 1, "defaults": 1, "repays": 0}, "defaulting"),   # 1/1 ≥ 0.5
    ({"contracts": 2, "defaults": 1, "repays": 1}, "defaulting"),   # 1/2 = 0.5
    ({"contracts": 3, "defaults": 1, "repays": 2}, "unknown"),      # 违约占比不足且非零
    ({"contracts": 4, "defaults": 2, "repays": 0}, "defaulting"),   # defaults ≥ 2
    ({"contracts": 10, "defaults": 4, "repays": 0}, "defaulting"),  # defaults ≥ 2
    ({"contracts": 1, "defaults": 0, "repays": 1}, "unknown"),      # 守约不足 2 次
    ({"contracts": 2, "defaults": 0, "repays": 2}, "reliable"),
    ({"contracts": 5, "defaults": 0, "repays": 5}, "reliable"),
])
def test_impression_label_boundaries(counts, expected):
    assert social.impression_label(counts) == expected


# --------------------------------------------------------------------------- #
# 合成门槛与幂等（§5.2/§5.4）
# --------------------------------------------------------------------------- #
def test_synthesize_requires_threshold(world):
    assert social.synthesize_impression(world.state, OBSERVER, TARGET, _window(world)) is None

    # 单次延期：未达门槛（不足 2 次交互、非违约/守约）
    _record(world, OBSERVER, TARGET, "deferred", 1)
    assert social.synthesize_impression(world.state, OBSERVER, TARGET, _window(world)) is None

    # 单次违约：出现违约即合成
    world.state.human.agents[OBSERVER].recent_interactions = []
    _record(world, OBSERVER, TARGET, "broken", 2)
    entry = social.synthesize_impression(world.state, OBSERVER, TARGET, _window(world))
    assert entry is not None and entry.label == "defaulting"
    assert (entry.contracts, entry.defaults, entry.repays) == (1, 1, 0)
    assert entry.last_outcome == "broken" and entry.last_tick == 2

    # 两次延期：够 2 次交互，合成 unknown
    world.state.human.agents[OBSERVER].recent_interactions = []
    _record(world, OBSERVER, TARGET, "deferred", 3)
    _record(world, OBSERVER, TARGET, "deferred", 4)
    entry = social.synthesize_impression(world.state, OBSERVER, TARGET, _window(world))
    assert entry is not None and entry.label == "unknown"
    assert (entry.contracts, entry.defaults, entry.repays) == (2, 0, 0)
    assert social.synthesize_impression(world.state, OBSERVER, OBSERVER,
                                        _window(world)) is None


def test_synthesize_idempotent_same_sequence(world):
    for tick, outcome in ((1, "deferred"), (2, "broken"), (3, "repaid")):
        _record(world, OBSERVER, TARGET, outcome, tick)
    first = social.synthesize_impression(world.state, OBSERVER, TARGET, _window(world))
    second = social.synthesize_impression(world.state, OBSERVER, TARGET, _window(world))
    assert first is not None and first == second


def test_synthesize_ignores_injected_counts(world):
    """counts 只由记忆窗口派生：注入不一致条目不影响重算（§5.4）。"""
    _record(world, OBSERVER, TARGET, "broken", 1)
    _record(world, OBSERVER, TARGET, "broken", 2)
    world.state.human.agents[OBSERVER].impressions[TARGET] = ImpressionEntry(
        label="reliable", contracts=99, defaults=0, repays=99, last_tick=999,
    )
    derived = social.synthesize_impression(world.state, OBSERVER, TARGET, _window(world))
    assert derived is not None
    assert (derived.label, derived.contracts, derived.defaults, derived.repays) == (
        "defaulting", 2, 2, 0)
    assert derived.last_tick == 2

    # label 翻转时写回，注入值被覆盖为派生值
    social.update_impression(world, OBSERVER, TARGET, _window(world))
    stored = world.state.human.agents[OBSERVER].impressions[TARGET]
    assert (stored.label, stored.contracts, stored.repays) == ("defaulting", 2, 0)


# --------------------------------------------------------------------------- #
# 事件只在 label 变化时写（§5.6）
# --------------------------------------------------------------------------- #
def test_events_only_on_label_change(world):
    created = []
    # 1) 单次延期：不合成、不写事件
    _record(world, OBSERVER, TARGET, "deferred", 1)
    assert social.update_impression(world, OBSERVER, TARGET, _window(world)) is None
    # 2) 第二次延期：首次形成（unknown）
    _record(world, OBSERVER, TARGET, "deferred", 2)
    assert social.update_impression(world, OBSERVER, TARGET, _window(world)) == "unknown"
    # 3) 一次违约：仍是 unknown，不写事件
    _record(world, OBSERVER, TARGET, "broken", 3)
    assert social.update_impression(world, OBSERVER, TARGET, _window(world)) == "unknown"
    # 4) 第二次违约：翻转为 defaulting，写 changed
    _record(world, OBSERVER, TARGET, "broken", 4)
    assert social.update_impression(world, OBSERVER, TARGET, _window(world)) == "defaulting"
    # 5) 重复调用（同一记忆窗口）：label 不变，不写重复事件
    social.update_impression(world, OBSERVER, TARGET, _window(world))

    created = [e["event_type"] for e in world.event_log.all()
               if e["event_type"].startswith("impression_")]
    assert created == ["impression_formed", "impression_changed"]
    changed = world.event_log.by_type("impression_changed")[0]["payload"]
    assert changed["old_label"] == "unknown" and changed["label"] == "defaulting"
    assert (changed["contracts"], changed["defaults"], changed["repays"]) == (4, 2, 0)

    stored = world.state.human.agents[OBSERVER].impressions[TARGET]
    assert stored.label == "defaulting" and stored.contracts == 4


def test_impression_formed_both_sides_on_broken(world):
    module = _module(world)
    module._remember_dispute(  # noqa: SLF001
        world, world.config.agents.tuning, OBSERVER, TARGET, "broken")
    for observer_id, target_id in ((OBSERVER, TARGET), (TARGET, OBSERVER)):
        entry = social.get_impression(world.state, observer_id, target_id)
        assert entry is not None and entry.label == "defaulting"
        assert (entry.contracts, entry.defaults) == (1, 1)
    events = world.event_log.by_type("impression_formed")
    assert len(events) == 2
    assert {e["payload"]["observer_id"] for e in events} == {OBSERVER, TARGET}


def test_get_social_view_includes_impression(world):
    module = _module(world)
    module._remember_dispute(  # noqa: SLF001
        world, world.config.agents.tuning, OBSERVER, TARGET, "repaid")
    view = social.get_social_view(
        world.state, OBSERVER, TARGET, world.current_tick,
        world.config.agents.tuning.social.acquaintance_ttl,
    )
    assert view["impression"] is not None
    assert view["impression"].label == "unknown"   # 单次守约：尚未形成可靠印象
    assert social.get_impression(world.state, OBSERVER, "nobody") is None


# --------------------------------------------------------------------------- #
# 运行时 vs replay 逐项一致（§5.3）
# --------------------------------------------------------------------------- #
def test_runtime_replay_impressions_equal(world):
    module = _module(world)
    for outcome in ("deferred", "deferred", "broken", "broken"):
        module._remember_dispute(  # noqa: SLF001
            world, world.config.agents.tuning, OBSERVER, TARGET, outcome)
    for _ in range(11):
        run_tick(world)

    events = world.event_log.all()
    assert events
    final_tick = max(int(e["tick"]) for e in events)
    social.apply_kin_defaults(world.state, final_tick)

    replayed = rebuild_state(events, world.config).state
    assert set(replayed.human.agents) == set(world.state.human.agents)
    for agent_id, rt in world.state.human.agents.items():
        assert replayed.human.agents[agent_id].impressions == rt.impressions, agent_id

    types = [e["event_type"] for e in events]
    assert "impression_formed" in types and "impression_changed" in types
    # 双方都被合成过
    assert world.state.human.agents[OBSERVER].impressions[TARGET].label == "defaulting"
    assert world.state.human.agents[TARGET].impressions[OBSERVER].label == "defaulting"


# --------------------------------------------------------------------------- #
# 旧库回放（§5.1/§5.7）
# --------------------------------------------------------------------------- #
def test_legacy_replay_leaves_impressions_empty():
    cfg = load_config("brookvale-town-001")
    events = json.loads((FIXTURES / "legacy_events.json").read_text(encoding="utf-8"))
    state = rebuild_state(events, cfg).state
    assert state.human.agents
    for agent in state.human.agents.values():
        assert agent.impressions == {}


# --------------------------------------------------------------------------- #
# 渲染（§5.9）
# --------------------------------------------------------------------------- #
def test_render_impression_formed():
    result = render_event({"event_type": "impression_formed", "tick": 5, "payload": {
        "observer_id": OBSERVER, "observer_name": "李全",
        "target_id": TARGET, "target_name": "林远",
        "label": "defaulting", "contracts": 2, "defaults": 2, "repays": 0,
        "last_outcome": "broken", "last_tick": 5,
    }})
    assert not result.degraded
    assert "李全" in result.text and "林远" in result.text and "屡次违约" in result.text


def test_render_impression_changed():
    result = render_event({"event_type": "impression_changed", "tick": 9, "payload": {
        "observer_id": OBSERVER, "observer_name": "李全",
        "target_id": TARGET, "target_name": "林远",
        "old_label": "unknown", "label": "reliable",
        "contracts": 3, "defaults": 0, "repays": 3,
        "last_outcome": "repaid", "last_tick": 9,
    }})
    assert not result.degraded
    assert "尚且说不准" in result.text and "向来守约" in result.text


def test_render_impression_degraded_without_missing_crash():
    forged = render_event({"event_type": "impression_formed", "tick": 5,
                           "payload": {"observer_id": OBSERVER}})
    assert forged.degraded and forged.reason == "missing_social_field"
    changed = render_event({"event_type": "impression_changed", "tick": 5,
                            "payload": {"observer_id": OBSERVER, "target_id": TARGET,
                                        "label": "unknown"}})
    assert changed.degraded and changed.reason == "missing_social_field"
    # 未知 label：降级为原样显示，不崩
    unknown_label = render_event({"event_type": "impression_formed", "tick": 5, "payload": {
        "observer_id": OBSERVER, "target_id": TARGET, "label": "someday",
    }})
    assert "someday" in unknown_label.text
