"""任务 12 测试：生命历程与代际。

覆盖裁决 A1–A5 与 D1–D16：
- A1 运行时新生儿下一 tick 参与模拟；A2 死者不进任何经济池；
- A3 死亡→继承顺序与守恒；A4 出生资产转移；A5 人口上下限；
- D1 birth_tick 唯一真相源、D2 衰老事件幂等、D3 健康上限、D4 自然死亡、D5 再婚、
  D6 生育间隔/概率、D7 新生儿属性、D8 work_node 兜底、D9 依赖者进食、D10 继承顺位、
  D11 债务转移/核销、D12 归公、D13 新事件、D14 timeline 参与人、D15 近亲禁止、D16 未成年人赴集；
- 观察层新事件渲染。
全部内存事件库。
"""
from __future__ import annotations

from household_helpers import hh
from vale.core.household import home_node_of, work_node_of

import random

import pytest

from config.schema.agents import AgentSex
from config.schema.natural_params import Season, WeatherType
from vale.core.calendar import DAYS_PER_YEAR
from vale.core.config_loader import load_config
from vale.core.event_log import EventLog
from vale.core.scheduler import run_tick
from vale.core.state import AgentState, DebtRecord, HouseholdState
from vale.core.world import World
from vale.modules.agents import (
    AgentModule,
    Perception,
    SpatialIndex,
    _lender_node,
    age_years,
    select_creditor,
)
from vale.modules.climate import ClimateModule
from vale.observability.query import EventFilter, apply_filter
from vale.observability.render import render_event


def _build(seed: int = 0) -> World:
    cfg = load_config("brookvale-town-001")
    w = World(world_id=cfg.world.world_id, event_log=EventLog(":memory:"),
              start_tick=cfg.world.start_tick, config=cfg)
    w.register(ClimateModule(rng=random.Random(seed)))
    w.register(AgentModule(rng=random.Random(seed * 7 + 13)))
    return w


@pytest.fixture
def world():
    w = _build(0)
    # 004：日内多动作改变 rng 流，首 tick 可能自发生育，干扰「child_1 = 本用例新生儿」的断言；
    # 初始化 tick 关闭生育，随后恢复配置
    b = w.config.agents.tuning.birth
    saved = b.chance_per_day
    b.chance_per_day = 0.0
    run_tick(w)  # 初始化 agents / climate
    b.chance_per_day = saved
    return w


def _module(world) -> AgentModule:
    mod = AgentModule(rng=random.Random(99))
    mod._spatial = SpatialIndex(world.config.spatial)  # noqa: SLF001
    return mod


def _add_child(world, *, agent_id="child_99", name="林小满", mother="zhao_cuilan",
               father="lin_yuan", health=60.0, hunger=50.0,
               home="common_district") -> AgentState:
    """加入母亲家庭（家庭模型第 1 步：新生儿随母）；无母亲则建单人家庭。"""
    mother_agent = world.state.agents.get(mother) if mother else None
    if mother_agent is not None:
        household = hh(world, mother_agent)
        household_id = household.household_id
        household.member_ids.append(agent_id)
        home = household.home_node
    else:
        household_id = f"hh_{agent_id}"
        world.state.households[household_id] = HouseholdState(
            household_id=household_id, member_ids=[agent_id], head_id=agent_id,
            home_node=home, work_node=home, formed_tick=world.current_tick,
        )
    child = AgentState(
        agent_id=agent_id, name=name, surname="林", sex=AgentSex.MALE,
        birth_tick=world.current_tick, life_stage="幼年",
        household_id=household_id, location=home, work_node=None,
        health=health, hunger=hunger, stamina=50.0,
        mother_id=mother, father_id=father,
    )
    world.state.agents[agent_id] = child
    return child


def _inventory(world, agent: AgentState, fields: list[str]) -> float:
    return sum(getattr(hh(world, agent), f, 0.0) for f in fields)


def _world_inventory(world, fields: list[str]) -> float:
    """按“家庭”去重统计世界库存（同户多人只算一次）。"""
    return sum(sum(getattr(h, f, 0.0) for f in fields)
               for h in world.state.households.values())


def _move_out(world, agent: AgentState, *, suffix: str = "solo"):
    """把 agent 迁出当前家庭，单独建户（用于跨户继承/债务转移用例）。"""
    old = hh(world, agent)
    old.member_ids = [m for m in old.member_ids if m != agent.agent_id]
    old.head_id = old.member_ids[0] if old.member_ids else None
    new_id = f"hh_{agent.agent_id}_{suffix}"
    world.state.households[new_id] = HouseholdState(
        household_id=new_id, member_ids=[agent.agent_id], head_id=agent.agent_id,
        home_node=old.home_node, work_node=old.work_node, formed_tick=world.current_tick,
    )
    agent.household_id = new_id
    return world.state.households[new_id]


def _food_fields(world) -> list[str]:
    return list(world.config.agents.tuning.physiology.food_fields)


# =========================================================================== #
# A1：运行时 NPC 以 WorldState.agents 为唯一真相源
# =========================================================================== #
def test_a1_runtime_newborn_participates_next_tick(world):
    child = _add_child(world)
    tick_before = world.current_tick
    run_tick(world)
    acts = [
        e for e in world.event_log.by_type("agent_action_taken")
        if e["payload"]["agent_id"] == child.agent_id and e["tick"] == tick_before
    ]
    assert acts, "运行时新增的新生儿必须在下一 tick 参与决策与结算"
    assert world.state.agents[child.agent_id].last_action is not None
    assert world.state.agents[child.agent_id].alive


# =========================================================================== #
# A2：死者不进任何经济池
# =========================================================================== #
def test_a2_dead_agent_never_creditor_or_lender(world):
    li = world.state.agents["li_quan"]
    lin = world.state.agents["lin_yuan"]
    li.alive = False
    hh(world, li).grain = 1000.0
    for aid, agent in world.state.agents.items():
        if aid != "lin_yuan":
            agent.alive = False
    assert select_creditor(world, "hh_lin_yuan", 10.0) is None
    assert _lender_node(world, lin) == home_node_of(world, lin)


def test_a2_dead_agent_not_marriage_candidate(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    li = world.state.agents["li_quan"]
    zhao = world.state.agents["zhao_cuilan"]
    li.spouse_id = zhao.spouse_id = None  # 清掉开场结算可能形成的婚姻
    li.alive = False
    assert mod._marriage_eligible(world, li, tuning) is False  # noqa: SLF001
    before = len(world.event_log.by_type("agent_married"))
    mod._settle_marriage(world, tuning)  # noqa: SLF001
    assert li.spouse_id is None
    new_events = world.event_log.by_type("agent_married")[before:]
    assert not any(
        e["payload"]["agent_id"] == "li_quan" or e["payload"].get("spouse_id") == "li_quan"
        for e in new_events
    )


# =========================================================================== #
# A3：死亡处理顺序与守恒
# =========================================================================== #
def test_a3_death_incapacitate_inherit_order_and_conservation(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    zhao = world.state.agents["zhao_cuilan"]
    lin.spouse_id, zhao.spouse_id = zhao.agent_id, lin.agent_id
    _move_out(world, lin)  # 家庭模型：死者须为最后成员，继承人才在另一户
    _move_out(world, zhao)  # 继承人独立成户，避免与债权家庭重合
    hh(world, lin).grain, hh(world, lin).cloth = 30.0, 2.0
    hh(world, lin).debts = [DebtRecord(debtor_household_id="hh_lin_yuan",
                                       creditor_household_id="hh_li_quan",
                                       amount=4.0, originated_tick=0, due_tick=9999)]
    fields = _food_fields(world) + ["cloth"]
    total_before = _world_inventory(world, fields)

    lin.health = 0.0
    assert mod._incapacitate_if_needed(world, lin, tuning) is True  # noqa: SLF001
    world.current_tick += tuning.death.death_grace_ticks
    mod._process_death(world, lin, tuning)  # noqa: SLF001
    assert not lin.alive
    mod._execute_inheritance(world, lin, tuning)  # noqa: SLF001

    total_after = _world_inventory(world, fields)
    assert total_after == pytest.approx(total_before)  # 有继承人：资产只转移不消失
    inc_id = world.event_log.by_type("agent_incapacitated")[-1]["id"]
    died_id = world.event_log.by_type("agent_died")[-1]["id"]
    inh_id = world.event_log.by_type("inheritance_executed")[0]["id"]
    assert inc_id < died_id < inh_id
    assert world.event_log.by_type("debt_transferred")[-1]["id"] > died_id


# =========================================================================== #
# A4（家庭模型改写）：出生不转移资产，新生儿加入母亲家庭
# =========================================================================== #
def test_a4_birth_does_not_transfer_assets(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    mother = world.state.agents["zhao_cuilan"]
    father = world.state.agents["lin_yuan"]
    hh(world, mother).grain, hh(world, mother).vegetable = 100.0, 10.0
    hh(world, father).grain, hh(world, father).fish = 50.0, 4.0
    fields = _food_fields(world)
    mother_before = _inventory(world, mother, fields)
    father_before = _inventory(world, father, fields)

    mod._give_birth(world, mother, father, tuning)  # noqa: SLF001
    child = world.state.agents["child_1"]
    assert _inventory(world, mother, fields) == pytest.approx(mother_before)
    assert _inventory(world, father, fields) == pytest.approx(father_before)
    assert child.household_id == mother.household_id
    assert not world.event_log.by_type("birth_asset_transfer")
    assert world.event_log.by_type("agent_born")[-1]["payload"]["household_id"] == mother.household_id


def test_a4_newborn_household_has_no_extra_inventory(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    mother = world.state.agents["zhao_cuilan"]
    father = world.state.agents["lin_yuan"]
    hh(world, mother).grain = 1.0
    hh(world, father).grain = 0.0
    before = hh(world, mother).grain
    mod._give_birth(world, mother, father, tuning)  # noqa: SLF001
    child = world.state.agents["child_1"]
    assert hh(world, child).grain == pytest.approx(before)
    assert hh(world, mother).grain >= 0


# =========================================================================== #
# A5：人口上下限
# =========================================================================== #
def test_a5_birth_not_stopped_by_population_count(world):
    """生育不读取全镇人口阈值；资源充足且配偶合格时继续生育。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    mother = world.state.agents["zhao_cuilan"]
    father = world.state.agents["lin_yuan"]
    mother.spouse_id, father.spouse_id = father.agent_id, mother.agent_id
    mother.health = father.health = 90.0
    household = hh(world, mother)
    household.grain = 1000.0
    household.water = 1000.0
    tuning.birth.chance_per_day = 1.0
    assert not hasattr(tuning.birth, "max_population")
    born_before = len(world.event_log.by_type("agent_born"))
    mod._settle_birth(world, tuning)  # noqa: SLF001
    assert len(world.event_log.by_type("agent_born")) == born_before + 1


def test_a5_low_population_boost(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    agents = world.state.agents
    # 004：首 tick 可能已有新生儿——只留这对夫妇，隔离「有未成年子女不提升」的干扰
    for aid in list(agents):
        if aid not in ("lin_yuan", "zhao_cuilan"):
            agents[aid].alive = False
    # 只有 2 个成年且无未成年：提升
    assert mod._fertility_boost(world, tuning) == pytest.approx(
        tuning.birth.low_population_fertility_boost
    )
    # 有未成年子女：不提升
    _add_child(world)
    assert mod._fertility_boost(world, tuning) == pytest.approx(1.0)  # noqa: SLF001


# =========================================================================== #
# D1–D3：年龄真相源、衰老、健康上限
# =========================================================================== #
def test_d1_birth_tick_is_single_source_of_age(world):
    assert "age" not in AgentState.model_fields
    lin = world.state.agents["lin_yuan"]
    assert age_years(lin.birth_tick, world.current_tick) == 18
    assert lin.life_stage == world.config.agents.tuning.aging.stage_for(18).name


def test_d2_one_aged_event_per_person_per_year(world):
    lin = world.state.agents["lin_yuan"]
    # 下一个 tick 恰好满 30 岁：青年 → 壮年
    lin.birth_tick = (world.current_tick + 1) - 30 * DAYS_PER_YEAR
    lin.health = 90.0
    run_tick(world)
    run_tick(world)
    aged = [e for e in world.event_log.by_type("agent_aged")
            if e["payload"]["agent_id"] == "lin_yuan"]
    assert len(aged) == 1
    assert aged[0]["payload"]["stage_changed"] is True
    assert aged[0]["payload"]["new_stage"] == "壮年"


def test_d3_health_cap_stage_multiplier_and_decline(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    assert mod._health_cap(20, tuning) == pytest.approx(100.0)  # noqa: SLF001
    assert mod._health_cap(50, tuning) == pytest.approx(65.0)  # noqa: SLF001
    assert mod._health_cap(55, tuning) == pytest.approx(50.0)  # noqa: SLF001
    assert mod._health_cap(200, tuning) == pytest.approx(15.0)  # noqa: SLF001


# =========================================================================== #
# D4/D5：自然死亡、鳏寡再婚
# =========================================================================== #
def test_d4_natural_death_requires_age_and_health(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    lin.birth_tick = world.current_tick - 60 * DAYS_PER_YEAR
    lin.health = tuning.aging.natural_death_health_threshold + 1
    mod._check_natural_death(world, lin, tuning)  # noqa: SLF001
    assert lin.health > 0
    lin.health = tuning.aging.natural_death_health_threshold
    mod._check_natural_death(world, lin, tuning)  # noqa: SLF001
    assert lin.health == 0 and lin.death_cause == "aging"
    assert mod._incapacitate_if_needed(world, lin, tuning) is True  # noqa: SLF001
    ev = world.event_log.by_type("agent_incapacitated")[-1]
    assert ev["payload"]["cause"] == "aging"


def test_d4_young_low_health_not_natural_death(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    zhao = world.state.agents["zhao_cuilan"]
    zhao.health = 10.0
    mod._check_natural_death(world, zhao, tuning)  # noqa: SLF001
    assert zhao.health == 10.0 and zhao.death_cause is None


def test_d5_widow_remarriage_eligibility(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    zhao = world.state.agents["zhao_cuilan"]
    zhao.spouse_id = "someone_dead"
    zhao.health, hh(world, zhao).grain = 90.0, 100.0
    assert mod._marriage_eligible(world, zhao, tuning) is True  # noqa: SLF001
    tuning.marriage.remarriage_allowed = False
    assert mod._marriage_eligible(world, zhao, tuning) is False  # noqa: SLF001


# =========================================================================== #
# D6–D8：生育与新生儿
# =========================================================================== #
def test_d6_birth_interval_and_probability(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    mother = world.state.agents["zhao_cuilan"]
    father = world.state.agents["lin_yuan"]
    mother.spouse_id, father.spouse_id = father.agent_id, mother.agent_id
    mother.health = father.health = 90.0
    interval = tuning.birth.interval_days
    mother.last_birth_tick = world.current_tick - (interval - 1)
    assert mod._birth_eligible(world, mother, father, tuning) is False  # noqa: SLF001
    mother.last_birth_tick = world.current_tick - interval
    assert mod._birth_eligible(world, mother, father, tuning) is True  # noqa: SLF001
    tuning.birth.chance_per_day = 1.0
    born_before = len(world.event_log.by_type("agent_born"))  # 004：首 tick 可能已有他户生育
    mod._settle_birth(world, tuning)  # noqa: SLF001
    assert len(world.event_log.by_type("agent_born")) == born_before + 1


def test_d7_newborn_attributes_use_parent_average_and_minimum(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    mother = world.state.agents["zhao_cuilan"]
    father = world.state.agents["lin_yuan"]
    mother.health, father.health = 80.0, 60.0
    mother.stamina, father.stamina = 60.0, 40.0
    mod._give_birth(world, mother, father, tuning)  # noqa: SLF001
    child = world.state.agents["child_1"]
    assert child.health == pytest.approx((80 + 60) / 2 * 0.8)
    assert child.stamina == pytest.approx((60 + 40) / 2 * 0.8)


def test_d8_newborn_uses_household_work_node(world):
    """D8 改写 + 阶段二 C：新生儿加入母亲家庭，劳作点取家庭可分配田块，源标注 household_allocation。

    阶段二 C 起 work_node 解析为「个人偏好 → 家庭 work_nodes（按可劳作成员序确定性对位分配）→ 家庭默认」，
    新生儿无个人偏好，故取家庭分配；work_nodes 为空（无田/非田默认点）时仍回退家庭默认。
    """
    mod = _module(world)
    tuning = world.config.agents.tuning
    mother = world.state.agents["zhao_cuilan"]
    father = world.state.agents["lin_yuan"]
    household = hh(world, mother)
    household.work_node = "south_field"
    mod._give_birth(world, mother, father, tuning)  # noqa: SLF001
    child = world.state.agents["child_1"]
    assert child.work_node is None
    assert work_node_of(world, child) in household.work_nodes
    payload = world.event_log.by_type("agent_born")[-1]["payload"]
    assert payload["work_node_source"] == "household_allocation"
    assert payload["work_node"] == work_node_of(world, child)


# =========================================================================== #
# D9：依赖者进食
# =========================================================================== #
def _eat_perception(child: AgentState, home: str) -> Perception:
    return Perception(
        agent=child, weather=WeatherType.SUNNY, temperature_c=10.0, is_raining=False,
        season=Season.SPRING, work_field_growth=0.0, lender_node=home, can_eat=True,
    )


def test_d9_dependent_consumes_household_stock(world):
    """D9 改写：未成年人直接消费家庭库存，不做跨家庭/跨个人转账。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    child = _add_child(world, health=90.0, hunger=80.0)
    mother = world.state.agents["zhao_cuilan"]
    father = world.state.agents["lin_yuan"]
    # 004：日内动作改变婚配配对，父方可能已并入母户——显式分户，隔离跨户断言
    if father.household_id == mother.household_id:
        _move_out(world, father)
    hh(world, mother).grain = 100.0
    hh(world, father).grain = 10.0
    # 阶段三第2轮：未成年口粮按 consumption.minor_food_share 扣减（成年不变）
    cost = tuning.physiology.eat_grain_cost * tuning.consumption.minor_food_share

    mod._execute(world, child, "eat", _eat_perception(child, home_node_of(world, child)), tuning)  # noqa: SLF001
    assert hh(world, mother).grain == pytest.approx(100.0 - cost)
    assert hh(world, father).grain == pytest.approx(10.0)  # 父方家庭不受影响
    ev = world.event_log.by_type("agent_action_taken")[-1]["payload"]
    assert ev["household_id"] == mother.household_id
    assert ev["fed_by"] == mother.name  # 仅叙事


def test_d9_adult_does_not_feed_from_parent(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    zhao = world.state.agents["zhao_cuilan"]
    lin.mother_id, lin.father_id = zhao.agent_id, None
    hh(world, lin).grain = 0.0
    hh(world, zhao).grain = 100.0
    assert mod._guardian(world, lin, tuning) is None  # noqa: SLF001


# =========================================================================== #
# D10–D13：继承
# =========================================================================== #
def test_d10_heir_priority_spouse_child_parent(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    zhao = world.state.agents["zhao_cuilan"]
    lin.spouse_id = zhao.agent_id
    assert mod._select_heir(world, lin, tuning) is zhao  # noqa: SLF001

    lin.spouse_id = None
    older = _add_child(world, agent_id="child_old", name="林甲")
    older.birth_tick = world.current_tick - 5 * DAYS_PER_YEAR
    younger = _add_child(world, agent_id="child_young", name="林乙")
    younger.birth_tick = world.current_tick - 2 * DAYS_PER_YEAR
    lin.children_ids = [younger.agent_id, older.agent_id]
    assert mod._select_heir(world, lin, tuning).agent_id == older.agent_id  # noqa: SLF001

    lin.children_ids = []
    lin.mother_id = zhao.agent_id
    assert mod._select_heir(world, lin, tuning) is zhao  # noqa: SLF001


def test_d11_debt_split_between_heir_and_forgiveness(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    zhao = world.state.agents["zhao_cuilan"]
    lin.spouse_id = zhao.agent_id
    _move_out(world, zhao)  # 跨户继承才转移债务
    hh(world, lin).debts = [DebtRecord(debtor_household_id="hh_lin_yuan",
                                       creditor_household_id="hh_li_quan",
                                       amount=10.0, originated_tick=0, due_tick=9999)]
    mod._execute_inheritance(world, lin, tuning)  # noqa: SLF001
    assert hh(world, zhao).debt == pytest.approx(5.0)
    assert hh(world, lin).debt == pytest.approx(0.0)
    assert world.event_log.by_type("debt_transferred")[-1]["payload"]["amount"] == pytest.approx(5.0)
    assert world.event_log.by_type("debt_written_off")[-1]["payload"]["amount"] == pytest.approx(5.0)


def test_q5_creditor_dissolution_transfer_carries_each_debtor_household():
    """G7：债权家庭消亡时，每位债务方的 debt_transferred 都带 debtor_household_id。"""
    world = _build(0)
    mod = next(m for m in world.modules if m.name == "agents")
    mod._ensure_agents(world, world.config.agents)  # noqa: SLF001 — 只验证结算事件
    tuning = world.config.agents.tuning
    zhao = world.state.agents["zhao_cuilan"]
    creditor_hh = hh(world, zhao)
    debtor_agents = [world.state.agents["lin_yuan"], world.state.agents["zhou_qiaoniang"]]
    heir = world.state.agents["li_quan"]
    amounts = [3.0, 1.5]

    for agent, amount in zip(debtor_agents, amounts):
        dhh = hh(world, agent)
        dhh.debts = [DebtRecord(debtor_household_id=dhh.household_id,
                                creditor_household_id=creditor_hh.household_id,
                                amount=amount, originated_tick=0, due_tick=9999)]

    zhao.spouse_id = zhao.mother_id = zhao.father_id = None
    zhao.children_ids = [heir.agent_id]
    heir_hh = mod._execute_inheritance(world, zhao, tuning)  # noqa: SLF001
    mod._settle_creditor_dissolution(world, creditor_hh, zhao, heir_hh)  # noqa: SLF001

    transfers = world.event_log.by_type("debt_transferred")
    assert len(transfers) == len(debtor_agents)
    got = {e["payload"]["debtor_household_id"]: e["payload"]["amount"] for e in transfers}
    assert got == {
        hh(world, agent).household_id: amount
        for agent, amount in zip(debtor_agents, amounts)
    }
    for agent, amount in zip(debtor_agents, amounts):
        assert hh(world, agent).debt == pytest.approx(amount)
        assert hh(world, agent).debts[0].creditor_household_id == heir_hh.household_id
    # 守恒：债权改挂不改变债务总额（转移 + 核销 = 原债务，此处无核销）
    assert sum(hh(world, a).debt for a in debtor_agents) == pytest.approx(sum(amounts))


def test_d12_no_heir_assets_escheated_with_event(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    lin.spouse_id = lin.mother_id = lin.father_id = None
    lin.children_ids = []
    hh(world, lin).grain, hh(world, lin).cloth = 20.0, 1.0
    hh(world, lin).water = 2.0  # 任务30：水也随继承/归公，保持守恒
    for f in _food_fields(world):
        if f != "grain":
            setattr(hh(world, lin), f, 0.0)
    mod._execute_inheritance(world, lin, tuning)  # noqa: SLF001
    assert hh(world, lin).grain == 0 and hh(world, lin).cloth == 0
    assert hh(world, lin).water == 0
    escheated = world.event_log.by_type("inheritance_escheated")
    assert {e["payload"]["item"] for e in escheated} == {"grain", "cloth", "water"}
    assert not world.event_log.by_type("inheritance_executed")


def test_d13_birth_and_debt_transfer_events_exist(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    mother = world.state.agents["zhao_cuilan"]
    father = world.state.agents["lin_yuan"]
    mother.spouse_id, father.spouse_id = father.agent_id, mother.agent_id
    hh(world, mother).grain, hh(world, father).grain = 100.0, 100.0
    mod._give_birth(world, mother, father, tuning)  # noqa: SLF001
    born = world.event_log.by_type("agent_born")[-1]["payload"]
    assert born["mother_id"] == mother.agent_id and born["father_id"] == father.agent_id
    assert born["child_id"] in mother.children_ids
    assert mother.last_birth_tick == world.current_tick

    lin = father
    _move_out(world, mother)  # 继承人（配偶）在另一户，债务转移事件才产生
    hh(world, lin).debts = [DebtRecord(debtor_household_id="hh_lin_yuan",
                                       creditor_household_id="hh_li_quan",
                                       amount=2.0, originated_tick=0, due_tick=9999)]
    mod._execute_inheritance(world, lin, tuning)  # noqa: SLF001
    assert world.event_log.by_type("debt_transferred")


# =========================================================================== #
# D14：timeline 参与人匹配
# =========================================================================== #
def test_d14_participants_only_matched_when_enabled():
    events = [{
        "id": 1, "tick": 1, "event_type": "agent_married",
        "payload": {
            "agent_name": "林远",
            "participants": [{"id": "lin_yuan", "name": "林远"},
                             {"id": "zhao_cuilan", "name": "赵翠兰"}],
        },
    }]
    assert apply_filter(events, EventFilter(agent="赵翠兰")) == []
    assert apply_filter(events, EventFilter(agent="赵翠兰", match_participants=True)) == events
    assert apply_filter(events, EventFilter(agent="lin_yuan", match_participants=True)) == events


# =========================================================================== #
# D15：近亲禁止
# =========================================================================== #
def test_d15_close_kin_mating_forbidden(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    child = _add_child(world, mother=lin.agent_id, father="li_quan")
    lin.children_ids.append(child.agent_id)
    assert mod._is_close_kin(lin, child) is True  # noqa: SLF001
    sibling_a = _add_child(world, agent_id="child_a", name="林甲", mother="zhao_cuilan")
    sibling_b = _add_child(world, agent_id="child_b", name="林乙", mother="zhou_qiaoniang")
    assert mod._is_close_kin(sibling_a, sibling_b) is True  # noqa: SLF001
    # 无亲缘关系：不禁止
    assert mod._is_close_kin(world.state.agents["lin_yuan"],
                             world.state.agents["zhou_qiaoniang"]) is False
    assert tuning.marriage.forbid_close_kin is True


# =========================================================================== #
# D16：未成年人赴集不受限，skipped 键不变
# =========================================================================== #
def test_d16_household_market_sends_adult_executor(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    child = _add_child(world, health=80.0)
    household = hh(world, child)
    household.home_node = tuning.market.market_node
    child.location = household.home_node
    mod._settle_market(world, tuning)  # noqa: SLF001
    summary = world.event_log.by_type("market_day_summary")[-1]["payload"]
    sent = [p for p in summary["participants"]
            if p["household_id"] == household.household_id]
    assert len(sent) == 1  # 每户每日一次
    assert sent[0]["agent_id"] != child.agent_id  # 未成年不单独赴集，由成年成员执行
    assert set(summary["skipped"]) == {"dead_or_incap", "too_far", "too_weak"}


# =========================================================================== #
# 观察层：新事件渲染
# =========================================================================== #
@pytest.mark.parametrize("evt,keyword", [
    ({"event_type": "agent_aged", "payload": {
        "agent_id": "li_quan", "agent_name": "李全", "age": 50, "old_stage": "壮年",
        "new_stage": "老年", "stage_changed": True, "health_cap_before": 95,
        "health_cap_after": 65}}, "入老年"),
    ({"event_type": "agent_married", "payload": {
        "agent_id": "lin_yuan", "agent_name": "林远", "spouse_id": "zhao_cuilan",
        "spouse_name": "赵翠兰", "distance_tu": 1.5}}, "结为夫妻"),
    ({"event_type": "agent_born", "payload": {
        "child_id": "child_1", "child_name": "林阿福", "mother_id": "zhao_cuilan",
        "mother_name": "赵翠兰", "father_id": "lin_yuan", "father_name": "林远",
        "population_after": 5}}, "出生"),
    ({"event_type": "birth_asset_transfer", "payload": {
        "parent_id": "zhao_cuilan", "parent_name": "赵翠兰", "child_id": "child_1",
        "child_name": "林阿福", "items": {"grain": 3.5}}}, "分给新生儿"),
    ({"event_type": "inheritance_executed", "payload": {
        "heir_id": "zhao_cuilan", "heir_name": "赵翠兰", "deceased_id": "li_quan",
        "deceased_name": "李全", "item": "grain", "amount": 80.0, "heir_after": 100.0}}, "继承"),
    ({"event_type": "inheritance_escheated", "payload": {
        "deceased_id": "li_quan", "deceased_name": "李全", "item": "cloth",
        "amount": 2.0}}, "归公"),
    ({"event_type": "debt_transferred", "payload": {
        "from_id": "li_quan", "from_name": "李全", "to_id": "lin_yuan", "to_name": "林远",
        "creditor_id": "zhao_cuilan", "creditor_name": "赵翠兰", "amount": 2.5}}, "承继"),
])
def test_render_life_course_events(evt, keyword):
    r = render_event(evt)
    assert not r.degraded
    assert keyword in r.text


def test_render_death_cause_chinese():
    evt = {"event_type": "agent_died", "payload": {
        "agent_id": "li_quan", "agent_name": "李全", "cause": "aging",
        "incapacitated_tick": 1500, "died_tick": 1507, "health": 0,
        "outstanding_debt": 0}}
    r = render_event(evt)
    assert not r.degraded and "衰老" in r.text
