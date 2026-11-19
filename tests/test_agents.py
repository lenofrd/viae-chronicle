"""里程碑 2 测试：人物模块（感知隔离 + 效用决策 + 动作执行 + 错误隔离）。

全部使用内存数据库。fixture 模式与 test_climate.py 对齐：
load_config → EventLog(":memory:") → World(...) → 注册 ClimateModule + AgentModule。
"""
from __future__ import annotations

import math

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
    # Isolate meal accounting from the separate public-granary redistribution system.
    world.state.community_reserves.clear()
    for building in world.state.buildings.values():
        if building.attributes.get("community_reserve"):
            building.status = "ruined"
    lin = world.state.agents["lin_yuan"]
    lin.hunger = 90.0
    hh(world, lin).grain = 5.0
    # 任务12：关闭生育，避免出生资产转移扰动本条「进食消耗」断言
    world.config.agents.tuning.birth.chance_per_day = 0.0

    executed_tick = world.current_tick
    run_tick(world)

    # 004：日内多动作——eat 发生在当天某一 slot，末动作可能是休整/闲时
    # 先 +15（A1，封顶 100）→ 100，再 eat −60（A2）→ 40
    lin_events = [
        e for e in world.event_log.by_type("agent_action_taken")
        if e["tick"] == executed_tick
        and e["payload"]["agent_name"] == "林远" and e["payload"]["action"] == "eat"
    ]
    assert lin_events, "当日必须至少进食一次"
    # 雨天户外劳作打折时可能再吃一口（40→0），按进食次数对账
    assert hh(world, lin).grain == pytest.approx(5.0 - len(lin_events))
    assert lin.hunger == pytest.approx(40.0 if len(lin_events) == 1 else 0.0)

    ev = lin_events[0]
    assert ev["payload"]["agent_name"] == "林远"
    assert ev["payload"]["hunger_before"] == pytest.approx(100.0)
    assert ev["payload"]["hunger_after"] == pytest.approx(40.0)
    assert ev["payload"]["grain_before"] == pytest.approx(5.0)
    assert ev["payload"]["grain_after"] == pytest.approx(4.0)


# --------------------------------------------------------------------------- #
# 效用决策：饱腹 + 低体力 → rest（stamina 需求驱动，farm 体力不足被过滤）
# --------------------------------------------------------------------------- #
def test_satiated_low_stamina_agent_rests(world):
    """饱腹 + 体力低于任何通勤成本 → 劳作全不可行，选 rest；rest 1 TU 回满（004）。"""
    run_tick(world)
    module = _agent_module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    hh(world, lin).grain = 5.0      # ≥ 借粮阈值 2，不会触发 borrow
    lin.hunger = 5.0     # 饱腹，eat 效用低
    lin.stamina = 1.0    # 低于农场/水井往返体力 → 移动闸不可行

    p = module._perceive(world, lin)  # noqa: SLF001
    assert module._decide(p, tuning, tu_remaining=10.0) == "rest"  # noqa: SLF001

    # rest = 1 TU 回满（004 分级模型：不再线性 +40）
    module._execute(world, lin, "rest", p, tuning)  # noqa: SLF001
    assert lin.stamina == pytest.approx(module._stamina_cap(lin, tuning))  # noqa: SLF001


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
    # 004：日内多动作——每人当日至少一条，4 个人物均参与
    assert {e["payload"]["agent_id"] for e in events} == set(world.state.agents.keys())
    for agent_id in world.state.agents:
        slots = [e["payload"]["slot"] for e in events if e["payload"]["agent_id"] == agent_id]
        assert slots == list(range(1, len(slots) + 1))  # 日内序号 1 起连续

    expected_keys = {
        "agent_id", "agent_name", "action", "target_node",
        "slot", "tu_spent", "tu_remaining",
        "round_trip_tu", "move_stamina", "labor_stamina",
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

    # 阶段二：粮田产出走 crops.md §4.5 公式；任务30 起 moisture 由灌溉档派生（初始 low=0.85）
    ev = world.event_log.by_type("agent_action_taken")[-1]["payload"]
    gain = ev["expected_yield"]
    assert ev["moisture"] == pytest.approx(
        world.config.natural_params.hydrology_evolution.moisture_by_gear[
            world.state.irrigation_gear
        ]
    )
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
    # Isolate the private-credit branch from the communal granary/cistern safety net.
    world.state.community_reserves.clear()
    for building in world.state.buildings.values():
        if building.attributes.get("community_reserve"):
            building.status = "ruined"
    world.config.agents.tuning.gathering.actions.clear()
    lin = world.state.agents["lin_yuan"]
    # The opening tick may have pooled the richest household's surplus; restore
    # a known private creditor after disabling the communal safety net.
    hh(world, world.state.agents["li_quan"]).grain = 100.0
    hh(world, lin).grain = 0.0      # 无任何食物 → eat 不可行
    hh(world, lin).meat = 0.0
    hh(world, lin).fish = 0.0
    hh(world, lin).vegetable = 0.0
    for field_node in world.state.field_growth:
        world.state.field_growth[field_node] = world.config.agents.tuning.agriculture.max_field_growth
    lin.stamina = 100.0  # 体力满：消除 rest 的体力紧缺项，借粮(1.8) > rest(1.5)
    lin.hunger = 95.0

    executed_tick = world.current_tick
    run_tick(world)

    # 004：日内多动作——借粮发生于当日某 slot，随后可能进食/劳作
    lin_events = [e for e in world.event_log.by_type("agent_action_taken")
                  if e["tick"] == executed_tick and e["payload"]["agent_name"] == "林远"]
    assert any(e["payload"]["action"] == "borrow_grain" for e in lin_events)
    # 借 5 石后饥饿触发生存门控进食；雨天「户外劳作打折」时可能再吃一口（饥饿 40→0），
    # 因此按当日 eat 次数对账（每次 1 石），而非钉死余量
    eats = sum(1 for e in lin_events if e["payload"]["action"] == "eat")
    assert eats >= 1
    assert hh(world, lin).grain == pytest.approx(5.0 - eats)
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

    def patched(self, w, agent, action, p, tuning, **kwargs):
        if agent.agent_id == "zhao_cuilan":
            raise RuntimeError("synthetic boom")
        return original(self, w, agent, action, p, tuning, **kwargs)

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


# --------------------------------------------------------------------------- #
# ADR 007：人口承载与婚姻
# --------------------------------------------------------------------------- #
def _prepare_marriage_pair(world):
    """准备一对可婚配的初始居民，并隔离其他候选人。"""
    from vale.core.calendar import DAYS_PER_YEAR

    run_tick(world)  # 初始化空间索引与人物投影；fixture 已关闭自动婚配
    module = _agent_module(world)
    # world fixture 默认关闭自动婚配；本测试显式恢复真实结算方法。
    module._settle_marriage = AgentModule._settle_marriage.__get__(module, AgentModule)  # noqa: SLF001
    wife = world.state.agents["zhao_cuilan"]
    husband = world.state.agents["lin_yuan"]
    for agent in world.state.agents.values():
        agent.acquaintances.clear()
        agent.recent_interactions.clear()
        if agent.agent_id not in {wife.agent_id, husband.agent_id}:
            agent.health = 1.0
            agent.spouse_id = None
    for agent in (wife, husband):
        agent.health = 90.0
        agent.incapacitated = False
        agent.birth_tick = world.current_tick - 25 * DAYS_PER_YEAR
        agent.spouse_id = None
        agent.married_tick = None
    # 测试只覆盖认知与家庭迁移；将两户放到同一可达地点，避免空间图距离干扰。
    world.state.households[wife.household_id].home_node = "common_district"
    world.state.households[husband.household_id].home_node = "common_district"
    wife.location = husband.location = "common_district"
    world.config.agents.tuning.marriage.max_distance_tu = 100.0
    return module, wife, husband


def _set_mutual_known(world, a, b):
    from vale.core.state import AcquaintanceEntry

    now = world.current_tick
    a.acquaintances[b.agent_id] = AcquaintanceEntry(level=2, last_seen_tick=now)
    b.acquaintances[a.agent_id] = AcquaintanceEntry(level=2, last_seen_tick=now)


def test_shared_place_contact_creates_mutual_known(world):
    """共同地点接触通过现有认知接口双向建立 known。"""
    module, wife, husband = _prepare_marriage_pair(world)
    wife.location = husband.location = "market"
    module._record_shared_location_interactions(world, world.config.agents.tuning)  # noqa: SLF001
    assert wife.acquaintances[husband.agent_id].level == 2
    assert husband.acquaintances[wife.agent_id].level == 2
    changes = [
        event for event in world.event_log.by_type("acquaintance_changed")
        if {event["payload"]["observer_id"], event["payload"]["target_id"]}
        == {wife.agent_id, husband.agent_id}
    ]
    assert len(changes) == 2
    assert {event["payload"]["observer_id"] for event in changes} == {
        wife.agent_id, husband.agent_id
    }
    from vale.core.replay import rebuild_state
    replayed = rebuild_state(world.event_log.all(), world.config).state
    assert replayed.agents[wife.agent_id].acquaintances[husband.agent_id].level == 2
    assert replayed.agents[husband.agent_id].acquaintances[wife.agent_id].level == 2


def test_marriage_age_health_and_distance_thresholds_are_unchanged(world):
    from vale.core.calendar import DAYS_PER_YEAR

    module, wife, husband = _prepare_marriage_pair(world)
    tuning = world.config.agents.tuning
    marriage = tuning.marriage

    wife.birth_tick = world.current_tick - 15 * DAYS_PER_YEAR
    assert module._marriage_eligible(world, wife, tuning) is False  # noqa: SLF001

    wife.birth_tick = world.current_tick - 16 * DAYS_PER_YEAR
    wife.health = 49.0
    assert module._marriage_eligible(world, wife, tuning) is False  # noqa: SLF001

    wife.health = 50.0
    assert module._marriage_eligible(world, wife, tuning) is True  # noqa: SLF001

    _set_mutual_known(world, wife, husband)
    world.state.households[wife.household_id].home_node = "common_district"
    world.state.households[husband.household_id].home_node = "market"
    distance = module._spatial.travel_tu("common_district", "market")
    assert math.isfinite(distance) and distance > 0
    marriage.max_distance_tu = distance - 0.01
    module._settle_marriage(world, tuning)  # noqa: SLF001
    assert wife.spouse_id is None and husband.spouse_id is None

    marriage.max_distance_tu = distance + 0.01
    module._settle_marriage(world, tuning)  # noqa: SLF001
    assert wife.spouse_id == husband.agent_id
    assert husband.spouse_id == wife.agent_id


def test_marriage_requires_mutual_known_and_not_recent_memory(world):
    """单向认识不能结婚；双方 known 即可，有限近期记忆为空不撤销资格。"""
    module, wife, husband = _prepare_marriage_pair(world)
    from vale.core.state import AcquaintanceEntry

    wife.acquaintances[husband.agent_id] = AcquaintanceEntry(
        level=2, last_seen_tick=world.current_tick
    )
    module._settle_marriage(world, world.config.agents.tuning)  # noqa: SLF001
    assert wife.spouse_id is None and husband.spouse_id is None

    _set_mutual_known(world, wife, husband)
    wife.recent_interactions.clear()
    husband.recent_interactions.clear()
    module._settle_marriage(world, world.config.agents.tuning)  # noqa: SLF001
    assert wife.spouse_id == husband.agent_id
    assert husband.spouse_id == wife.agent_id
    assert wife.household_id == husband.household_id
    assert not world.event_log.by_type("household_merged")


def test_marriage_moves_only_wife_and_keeps_two_households_independent(world):
    """女方原家庭的成年成员、既有子女、资产与债务留存；彩礼/陪嫁独立守恒。"""
    from vale.core.calendar import DAYS_PER_YEAR
    from config.schema.agents import AgentSex
    from vale.core.state import DebtRecord

    module, wife, husband = _prepare_marriage_pair(world)
    source = world.state.households[wife.household_id]
    target = world.state.households[husband.household_id]

    sibling = wife.model_copy(update={
        "agent_id": "marriage_adult_sibling", "name": "女方兄长",
        "household_id": source.household_id, "sex": AgentSex.MALE,
        "birth_tick": world.current_tick - 24 * DAYS_PER_YEAR,
        "health": 1.0, "spouse_id": None, "mother_id": None, "father_id": None,
        "children_ids": [], "acquaintances": {}, "recent_interactions": [],
        "impressions": {},
    })
    child = wife.model_copy(update={
        "agent_id": "marriage_existing_child", "name": "女方旧子",
        "household_id": source.household_id, "sex": AgentSex.FEMALE,
        "birth_tick": world.current_tick - 5 * DAYS_PER_YEAR,
        "health": 80.0, "spouse_id": None, "mother_id": wife.agent_id,
        "father_id": husband.agent_id, "children_ids": [],
        "acquaintances": {}, "recent_interactions": [], "impressions": {},
    })
    world.state.agents[sibling.agent_id] = sibling
    world.state.agents[child.agent_id] = child
    source.member_ids.extend([sibling.agent_id, child.agent_id])
    source.head_id = wife.agent_id
    world.event_log.append(world.current_tick, "household_member_registered", {
        "household_id": source.household_id, "agent_id": sibling.agent_id,
        "home_node": source.home_node, "work_node": source.work_node,
    })
    world.event_log.append(world.current_tick, "household_member_registered", {
        "household_id": source.household_id, "agent_id": child.agent_id,
        "home_node": source.home_node, "work_node": source.work_node,
    })

    source.grain, source.coin = 20.0, 20.0
    target.grain, target.coin = 100.0, 50.0
    source.debts = [DebtRecord(
        debtor_household_id=source.household_id,
        creditor_household_id=target.household_id,
        amount=2.0, originated_tick=world.current_tick, due_tick=world.current_tick + 90,
    )]
    debt_before = [record.model_dump() for record in source.debts]
    grain_total_before = source.grain + target.grain
    coin_total_before = source.coin + target.coin

    tuning = world.config.agents.tuning
    tuning.marriage.bride_price_surplus_ratio = 0.1
    tuning.marriage.dowry_surplus_ratio = 0.1
    _set_mutual_known(world, wife, husband)
    module._settle_marriage(world, tuning)  # noqa: SLF001

    assert wife.household_id == target.household_id
    assert sibling.household_id == source.household_id
    assert child.household_id == source.household_id  # 既有子女不自动随迁
    assert sibling.agent_id in source.member_ids and child.agent_id in source.member_ids
    assert wife.agent_id not in source.member_ids
    assert wife.agent_id in target.member_ids
    assert source.head_id == sibling.agent_id
    assert source.grain > 20.0  # 男方家庭支付彩礼后，女方原家庭收到资源
    assert source.debts[0].model_dump() == debt_before[0]
    assert source.grain + target.grain == pytest.approx(grain_total_before)
    assert source.coin + target.coin == pytest.approx(coin_total_before)
    transfers = world.event_log.by_type("marriage_assets_transferred")
    assert {event["payload"]["transfer_type"] for event in transfers} == {
        "bride_price", "dowry"
    }
    assert not world.event_log.by_type("household_merged")

    from vale.core.replay import rebuild_state
    replayed = rebuild_state(world.event_log.all(), world.config).state
    assert replayed.households[source.household_id].grain == pytest.approx(source.grain)
    assert replayed.households[target.household_id].grain == pytest.approx(target.grain)
    assert replayed.households[source.household_id].member_ids == source.member_ids
    assert replayed.households[target.household_id].member_ids == target.member_ids


def test_birth_has_no_population_or_household_member_cap(world):
    """存活人口超过 12、单户人数超过 8 后，符合条件的配偶仍可生育。"""
    import random
    from vale.core.calendar import DAYS_PER_YEAR

    run_tick(world)
    module = _agent_module(world)
    mother = world.state.agents["zhao_cuilan"]
    father = world.state.agents["lin_yuan"]
    household = world.state.households[mother.household_id]
    old_father_household = world.state.households[father.household_id]
    if father.agent_id in old_father_household.member_ids:
        old_father_household.member_ids.remove(father.agent_id)
    father.household_id = household.household_id
    if father.agent_id not in household.member_ids:
        household.member_ids.append(father.agent_id)
    father.spouse_id, mother.spouse_id = mother.agent_id, father.agent_id
    mother.health = father.health = 90.0
    mother.birth_tick = father.birth_tick = world.current_tick - 25 * DAYS_PER_YEAR
    mother.last_birth_tick = None

    for index in range(9):
        agent_id = f"uncapped_household_member_{index}"
        extra = father.model_copy(update={
            "agent_id": agent_id, "name": agent_id,
            "household_id": household.household_id, "spouse_id": None,
            "health": 1.0, "birth_tick": world.current_tick - 20 * DAYS_PER_YEAR,
            "children_ids": [], "mother_id": None, "father_id": None,
            "acquaintances": {}, "recent_interactions": [], "impressions": {},
        })
        world.state.agents[agent_id] = extra
        household.member_ids.append(agent_id)

    for agent in world.state.agents.values():
        if agent.agent_id != mother.agent_id and agent.sex.value == "female":
            agent.health = 1.0
    assert len([a for a in world.state.agents.values() if a.alive]) > 12
    assert len(household.member_ids) > 8

    household.grain = 1000.0
    household.water = 1000.0
    tuning = world.config.agents.tuning
    tuning.birth.chance_per_day = 1.0
    module.rng = random.Random(0)
    before = len(world.state.agents)
    module._settle_birth(world, tuning)  # noqa: SLF001
    assert len(world.state.agents) == before + 1
    assert any(
        event["payload"].get("mother_id") == mother.agent_id
        for event in world.event_log.by_type("agent_born")
    )
    assert not world.event_log.by_type("birth_skipped")


def test_birth_probability_responds_to_food_and_water_security(world):
    """食物/用水库存连续调节生育概率，不通过人口数或户人数硬截断。"""
    run_tick(world)
    module = _agent_module(world)
    mother = world.state.agents["zhao_cuilan"]
    household = world.state.households[mother.household_id]
    tuning = world.config.agents.tuning

    for field in tuning.physiology.food_fields:
        setattr(household, field, 0.0)
    household.grain = 100.0
    household.water = 100.0
    secure = module._birth_resource_factor(world, mother, tuning)  # noqa: SLF001
    assert secure == pytest.approx(1.0)

    household.grain = 1.5  # 单人家庭约 6 天粮食，低于 12 天安全目标
    constrained_food = module._birth_resource_factor(world, mother, tuning)  # noqa: SLF001
    assert 0.0 < constrained_food < secure

    household.grain = 100.0
    household.water = 0.0
    constrained_water = module._birth_resource_factor(world, mother, tuning)  # noqa: SLF001
    assert constrained_water == 0.0
