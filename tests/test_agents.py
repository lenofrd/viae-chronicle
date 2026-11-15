"""里程碑 2 测试：人物模块（感知隔离 + 效用决策 + 动作执行 + 错误隔离）。

全部使用内存数据库。fixture 模式与 test_climate.py 对齐：
load_config → EventLog(":memory:") → World(...) → 注册 ClimateModule + AgentModule。
"""
from __future__ import annotations

from household_helpers import hh
from vale.core.household import home_node_of, work_node_of

import dataclasses

import pytest

from config.schema.natural_params import Season
from vale.core.config_loader import load_config
from vale.core.event_log import EventLog
from vale.core.scheduler import run_tick
from vale.core.state import DebtRecord
from vale.core.world import World
from vale.modules.agents import AgentModule
from vale.modules.climate import ClimateModule


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
    # 任务12：单人消费/债务单元测试，禁用婚配结算以隔离“配偶同户共同进食”
    for m in w.modules:
        if m.name == "agents":
            m._settle_marriage = lambda *a, **k: None  # noqa: SLF001
    return w


def _agent_module(world) -> AgentModule:
    return next(m for m in world.modules if m.name == "agents")


# --------------------------------------------------------------------------- #
# 加载与初始状态
# --------------------------------------------------------------------------- #
def test_agents_loaded_from_config(world):
    """agents.yaml 的 4 个人物应在首次 step 后投影进 WorldState.agents。"""
    run_tick(world)
    ids = set(world.state.agents.keys())
    assert ids == {"lin_yuan", "zhao_cuilan", "li_quan", "zhou_qiaoniang"}

    # 配置层：初始存粮正确加载（不受首 tick 行为影响）。任务10 [调参]：林远 15→30、
    # 赵翠兰 3→35（开春缓冲撑到首次秋收），李全 100 不变
    cfg_by_id = {a.id: a for a in world.config.agents.agents}
    assert cfg_by_id["lin_yuan"].assets.grain == pytest.approx(30.0)
    assert cfg_by_id["zhao_cuilan"].assets.grain == pytest.approx(35.0)
    assert cfg_by_id["li_quan"].assets.grain == pytest.approx(100.0)

    lin = world.state.agents["lin_yuan"]
    assert lin.name == "林远"
    assert home_node_of(world, lin) == "common_district"
    assert work_node_of(world, lin) == "west_field"
    # 投影字段在合法范围（首 tick 已发生 eat，故只校验范围）
    assert 0 <= lin.hunger <= 100
    assert 0 <= lin.stamina <= 100
    assert 0 <= lin.health <= 100


# --------------------------------------------------------------------------- #
# 效用决策：饥饿 → eat
# --------------------------------------------------------------------------- #
def test_hungry_agent_eats_and_state_updates(world):
    """高饥饿 + 有粮 → 选 eat；饥饿降低、存粮减少、last_action 更新。"""
    run_tick(world)  # 初始化气候 + 空间索引 + 人物投影
    lin = world.state.agents["lin_yuan"]
    lin.hunger = 90.0
    hh(world, lin).grain = 5.0
    # 任务12：关闭生育，避免出生资产转移扰动本条「进食消耗」断言
    world.config.agents.tuning.birth.chance_per_day = 0.0

    run_tick(world)

    assert lin.last_action == "eat"
    # 先 +15（A1，封顶 100）→ 100，再 eat −60（A2）→ 40
    assert lin.hunger == pytest.approx(40.0)
    # A3：每次进食消耗 1 石
    assert hh(world, lin).grain == pytest.approx(4.0)

    # 取林远最近一次动作事件（第二个 tick；by_type 按 id 升序，最后一条即最近）
    lin_events = [
        e for e in world.event_log.by_type("agent_action_taken")
        if e["payload"]["agent_name"] == "林远"
    ]
    ev = lin_events[-1]
    assert ev["payload"]["agent_name"] == "林远"
    assert ev["payload"]["action"] == "eat"
    assert ev["payload"]["hunger_before"] == pytest.approx(100.0)
    assert ev["payload"]["hunger_after"] == pytest.approx(40.0)
    assert ev["payload"]["grain_before"] == pytest.approx(5.0)
    assert ev["payload"]["grain_after"] == pytest.approx(4.0)


# --------------------------------------------------------------------------- #
# 效用决策：饱腹 + 低体力 → rest（stamina 需求驱动，farm 体力不足被过滤）
# --------------------------------------------------------------------------- #
def test_satiated_low_stamina_agent_rests(world):
    """饱腹（eat 不迫切）+ 体力不足以 farm / collect_water + 存粮充足（不借粮）→ rest，体力回升。"""
    run_tick(world)
    lin = world.state.agents["lin_yuan"]
    hh(world, lin).grain = 5.0      # ≥ 借粮阈值 2，不会触发 borrow
    lin.hunger = 5.0     # 饱腹，eat 效用低
    lin.stamina = 10.0   # < farm 的 ~50，也 < collect_water 的 15

    run_tick(world)

    assert lin.last_action == "rest"
    # A5：rest 恢复 40 体力（封顶 100）
    assert lin.stamina == pytest.approx(50.0)


# --------------------------------------------------------------------------- #
# B9：天气对户外动作效用的影响（机制层校验乘数接线，不依赖分数正负）
# --------------------------------------------------------------------------- #
def test_rain_multiplies_outdoor_score_and_leaves_indoor_unchanged(world):
    """雨天：户外动作得分 × rain_outdoor_score_multiplier；室内动作（eat）不受影响。"""
    run_tick(world)  # 确保气候与空间索引就绪
    module = _agent_module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    lin.stamina = 80.0  # 保证 farm 可行（首 tick 后体力可能已被消耗）
    p = module._perceive(world, lin)  # noqa: SLF001 — 测试需要构造感知
    p = dataclasses.replace(p, is_raining=False)  # 强制晴天基线，与随机气候解耦

    multiplier = tuning.utility.rain_outdoor_score_multiplier

    # 户外：farm
    sunny_farm = module.score_action("farm", p, tuning)
    rainy_p = dataclasses.replace(p, is_raining=True)
    rainy_farm = module.score_action("farm", rainy_p, tuning)
    assert rainy_farm == pytest.approx(sunny_farm * multiplier)

    # 室内：eat 不在 outdoor 列表，雨天得分不变
    sunny_eat = module.score_action("eat", p, tuning)
    rainy_eat = module.score_action("eat", rainy_p, tuning)
    assert rainy_eat == pytest.approx(sunny_eat)


# --------------------------------------------------------------------------- #
# 事件载荷结构
# --------------------------------------------------------------------------- #
def test_action_event_payload_has_expected_fields(world):
    """agent_action_taken 事件应携带完整载荷，便于 CLI 叙事与后续分析。"""
    run_tick(world)
    events = world.event_log.by_type("agent_action_taken")
    assert len(events) == 4  # 4 个人物各一条

    expected_keys = {
        "agent_id", "agent_name", "action", "target_node",
        "round_trip_tu", "stamina_cost",
        "hunger_before", "hunger_after",
        "grain_before", "grain_after",
        "debt_before", "debt_after",
        "field_growth_before", "field_growth_after",
        "stamina_after", "weather",
    }
    for ev in events:
        assert expected_keys <= set(ev["payload"].keys())
    # 快照投影与事件一致
    for a in world.state.agents.values():
        assert a.last_action is not None
        assert a.recent_actions  # 非空


# --------------------------------------------------------------------------- #
# 农业周期：farm 只涨长势不产粮；harvest 秋季产粮并偿债
# --------------------------------------------------------------------------- #
def test_farm_raises_growth_does_not_produce_grain(world):
    """farm 只提升对应田地长势，绝不直接增加存粮。"""
    run_tick(world)
    module = _agent_module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    lin.stamina = 80.0
    world.state.field_growth[work_node_of(world, lin)] = 10.0
    grain_before = hh(world, lin).grain
    p = module._perceive(world, lin)  # noqa: SLF001

    module._execute(world, lin, "farm", p, tuning)

    expected_growth = 10.0 + tuning.agriculture.field_growth_per_farm
    assert world.state.field_growth[work_node_of(world, lin)] == pytest.approx(expected_growth)
    assert hh(world, lin).grain == grain_before  # 不直接产粮
    assert lin.stamina < 80.0         # 消耗体力


def test_harvest_autumn_grains_growth_and_redeems_debt(world):
    """秋季 harvest：长势清零、按田块作物 +base_yield 公式产出，并按债务记录还给债主（粮守恒，不凭空消债）。

    任务11 起 west_field 种菜，这里改用 east_field 的赵翠兰验证粮田路径。
    """
    run_tick(world)
    module = _agent_module(world)
    tuning = world.config.agents.tuning
    zhao = world.state.agents["zhao_cuilan"]
    li_quan = world.state.agents["li_quan"]
    zhao.stamina = 80.0
    hh(world, zhao).grain = 10.0
    hh(world, zhao).debts = [DebtRecord(debtor_household_id="hh_zhao_cuilan",
                                         creditor_household_id="hh_li_quan",
                                         amount=20.0, originated_tick=0, due_tick=90)]
    lq_grain_before = hh(world, li_quan).grain
    world.state.climate.season = Season.AUTUMN
    world.state.field_growth[work_node_of(world, zhao)] = 90.0
    p = module._perceive(world, zhao)  # noqa: SLF001

    module._execute(world, zhao, "harvest", p, tuning)

    gain = tuning.agriculture.base_yield["grain"]  # 阶段二：粮田产出走 crops.md §4.5 公式（初始值等价 75）
    assert hh(world, zhao).grain == pytest.approx(10.0 + gain - 10.0)  # 10 + 秋收gain - 10(还债给李全)
    assert hh(world, zhao).debt == pytest.approx(10.0)    # 20 - 10（派生聚合）
    assert hh(world, li_quan).grain == pytest.approx(lq_grain_before + 10.0)  # 债主收粮，总粮守恒
    assert world.state.field_growth[work_node_of(world, zhao)] == pytest.approx(0.0)
    repaid = world.event_log.by_type("debt_repaid")
    assert repaid and repaid[-1]["payload"]["creditor_id"] == "li_quan"
    assert repaid[-1]["payload"]["amount"] == pytest.approx(10.0)


def test_harvest_feasibility_gated_by_season_and_growth(world):
    """harvest 仅在秋季且长势 ≥ 阈值时可行。"""
    run_tick(world)
    module = _agent_module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    lin.stamina = 80.0
    world.state.field_growth[work_node_of(world, lin)] = 90.0
    world.state.climate.season = Season.AUTUMN
    p = module._perceive(world, lin)  # noqa: SLF001

    assert module.score_action("harvest", p, tuning) != float("-inf")
    # 非秋季 → 不可行
    assert module.score_action("harvest", dataclasses.replace(p, season=Season.SPRING), tuning) == float("-inf")
    # 秋季但长势不足 → 不可行
    assert module.score_action("harvest", dataclasses.replace(p, work_field_growth=50.0), tuning) == float("-inf")


# --------------------------------------------------------------------------- #
# 借粮：存粮 < 阈值触发 borrow_grain，存粮与债务同步增加
# --------------------------------------------------------------------------- #
def test_borrow_grain_triggers_when_low_grain(world):
    """断粮（所有食物字段为 0）且无采集可选时，饥饿驱动借粮。

    任务10 调参后：borrow fulfill survival 0.8 < eat 1.0（有食物先吃），
    且渔业/打猎作为断粮觅食路径优先于借粮（survival 驱动）。故此用例清空采集动作，
    隔离出「无任何食物、无采集」的决策分支。
    """
    run_tick(world)
    world.config.agents.tuning.gathering.actions.clear()
    lin = world.state.agents["lin_yuan"]
    hh(world, lin).grain = 0.0      # 无任何食物 → eat 不可行
    hh(world, lin).meat = 0.0
    hh(world, lin).fish = 0.0
    hh(world, lin).vegetable = 0.0
    lin.stamina = 100.0  # 体力满：消除 rest 的体力紧缺项，借粮(1.8) > rest(1.5)
    lin.hunger = 95.0

    run_tick(world)

    lin_events = [e for e in world.event_log.by_type("agent_action_taken")
                  if e["payload"]["agent_name"] == "林远"]
    assert lin_events[-1]["payload"]["action"] == "borrow_grain"
    assert hh(world, lin).grain == pytest.approx(5.0)  # 0 + 5
    assert hh(world, lin).debt == pytest.approx(5.0)   # 等额计入债务（派生聚合）

    # 借粮闭合：债主扣粮、借粮者加粮，总粮不变；事件载荷足以重建债务记录
    formed = [e for e in world.event_log.by_type("debt_formed")
              if e["payload"]["debtor_name"] == "林远"]
    assert formed, "应产生 debt_formed 事件"
    payload = formed[-1]["payload"]
    assert payload["amount"] == pytest.approx(5.0)
    assert payload["creditor_id"]  # 非空
    assert payload["debtor_grain_after"] - payload["debtor_grain_before"] == pytest.approx(5.0)
    assert payload["creditor_grain_after"] - payload["creditor_grain_before"] == pytest.approx(-5.0)


def test_borrow_not_feasible_when_grain_sufficient(world):
    run_tick(world)
    module = _agent_module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    hh(world, lin).grain = 3.0  # ≥ 阈值 2
    lin.stamina = 80.0
    p = module._perceive(world, lin)  # noqa: SLF001
    assert module.score_action("borrow_grain", p, tuning) == float("-inf")


# --------------------------------------------------------------------------- #
# 模块隔离：单个人物抛错 → 其余人物正常动作 + 写 agent_error，世界不崩溃
# --------------------------------------------------------------------------- #
def test_single_agent_failure_isolated(world, monkeypatch):
    """让赵翠兰的 _execute 抛异常：林远/李全仍产生动作事件，并写一条 agent_error。"""
    run_tick(world)  # 初始化

    original = AgentModule._execute

    def patched(self, w, agent, action, p, tuning):
        if agent.agent_id == "zhao_cuilan":
            raise RuntimeError("synthetic boom")
        return original(self, w, agent, action, p, tuning)

    monkeypatch.setattr(AgentModule, "_execute", patched)

    # 不应抛出
    run_tick(world)

    actions = world.event_log.by_type("agent_action_taken")
    # 第二个 tick：林远、李全各 1 条（赵翠兰失败无动作事件）
    second_tick_actions = [e for e in actions if e["tick"] == world.current_tick - 1]
    names = {e["payload"]["agent_name"] for e in second_tick_actions}
    assert names - {"赵翠兰"}  # 其他人物仍产生动作（允许运行时新生儿）
    assert "赵翠兰" not in names

    errors = world.event_log.by_type("agent_error")
    assert len(errors) == 1
    assert errors[0]["payload"]["agent_name"] == "赵翠兰"
    assert "synthetic boom" in errors[0]["payload"]["error"]

    # 世界仍在推进，人物投影仍完整
    assert world.current_tick > 0
    assert set(world.state.agents.keys()) == {"lin_yuan", "zhao_cuilan", "li_quan", "zhou_qiaoniang"}
