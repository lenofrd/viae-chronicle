"""盈余经济阶段二专项测试（裁决 13-verdict-surplus-economy-phase2）。

覆盖三项机制，全部只验机制、不验平衡参数：
- C：work_node 失效回收 + 家庭可分配田块（确定性距离）+ 新生儿取家庭分配 + east_field 不再零投入；
- A：crops.md §4.5 产量公式化（初始值与既有 75/55 逐项相等，area/fertility 乘数生效，守恒）；
- B：出生户容量校验（超限跳过、不写 agent_born、事件可计数）+ 分娩健康代价（设计值 −10）。

全部内存事件库，seeded rng。
"""
from __future__ import annotations

import random

import pytest

from household_helpers import attach_test_resource_pools, hh
from vale.core.calendar import DAYS_PER_YEAR
from vale.core.config_loader import load_config
from vale.core.event_log import EventLog
from vale.core.household import work_node_of
from vale.core.scheduler import run_tick
from vale.core.state import AgentState, HouseholdState
from vale.core.world import World
from vale.config.schema.agents import AgentSex
from vale.config.schema.natural_params import Season
from vale.modules.agents import AgentModule, SpatialIndex, expected_yield
from vale.modules.climate import ClimateModule
from vale.observability.render import render_event


# --------------------------------------------------------------------------- #
# 基础设施
# --------------------------------------------------------------------------- #
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
    run_tick(w)  # 初始化 agents / climate / 家庭劳作点
    return w


def _module(world) -> AgentModule:
    mod = AgentModule(rng=random.Random(99))
    mod._spatial = SpatialIndex(world.config.spatial)  # noqa: SLF001
    return mod


def _moisture(world) -> float:
    """任务30：当前灌溉档对应的 moisture 系数（初始 low=0.85）。"""
    return world.config.natural_params.hydrology_evolution.moisture_by_gear[
        world.state.environment.irrigation_gear
    ]


def _add_agent(world, agent_id: str, *, sex: AgentSex, age: int, household_id: str,
               home: str, health: float = 90.0, hunger: float = 30.0,
               stamina: float = 80.0) -> AgentState:
    agent = AgentState(
        agent_id=agent_id, name=agent_id, sex=sex,
        birth_tick=world.current_tick - age * DAYS_PER_YEAR,
        life_stage="青年", household_id=household_id, location=home,
        work_node=None, health=health, hunger=hunger, stamina=stamina,
    )
    world.state.human.agents[agent_id] = agent
    return agent


def _add_household(world, household_id: str, member_ids: list[str], *,
                   home: str, work: str) -> HouseholdState:
    household = HouseholdState(
        household_id=household_id, member_ids=list(member_ids), head_id=member_ids[0],
        home_node=home, work_node=work, formed_tick=world.current_tick,
    )
    world.state.human.households[household_id] = household
    return household


def _isolated_couple(world, fillers: int) -> tuple[AgentState, AgentState, HouseholdState]:
    """清场后建一户：母亲 m1 + 父亲 f1 + 若干未成年填充，便于精确控制户容量。"""
    for agent in world.state.human.agents.values():
        agent.alive = False
    home, work = "rich_district", "south_field"
    members = ["m1", "f1"] + [f"k{i}" for i in range(1, fillers + 1)]
    household = _add_household(world, "hh_test", members, home=home, work=work)
    mother = _add_agent(world, "m1", sex=AgentSex.FEMALE, age=25,
                        household_id="hh_test", home=home)
    father = _add_agent(world, "f1", sex=AgentSex.MALE, age=30,
                        household_id="hh_test", home=home)
    mother.spouse_id, father.spouse_id = "f1", "m1"
    for i in range(1, fillers + 1):
        _add_agent(world, f"k{i}", sex=AgentSex.MALE, age=5,
                   household_id="hh_test", home=home)
    return mother, father, household


# --------------------------------------------------------------------------- #
# C：劳作点失效回收与家庭可分配田块
# --------------------------------------------------------------------------- #
def test_c_invalid_preference_is_released(world):
    """个人偏好指向不存在的节点 → 置 None，写 agent_work_node_changed(preference_invalid)。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.human.agents["lin_yuan"]
    lin.work_node = "ghost_field"

    mod._reconcile_work_nodes(world, tuning)  # noqa: SLF001

    assert lin.work_node is None
    event = world.event_log.by_type("agent_work_node_changed")[-1]["payload"]
    assert event["agent_id"] == "lin_yuan"
    assert event["before"] == "ghost_field"
    assert event["after"] is None
    assert event["reason"] == "preference_invalid"


def test_c_household_work_nodes_distance_order(world):
    """可分配田块：默认田优先，其余按家→田距离升序；户内按可劳作成员序对位接田（确定性）。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    mother, father, household = _isolated_couple(world, fillers=0)

    mod._reconcile_work_nodes(world, tuning)  # noqa: SLF001

    # rich_district → south/east 均 2.5 TU（并列按节点 id），west 3.5 TU
    assert household.work_nodes == ["south_field", "east_field"]
    assert work_node_of(world, mother) == "south_field"   # 可劳作序 0
    assert work_node_of(world, father) == "east_field"    # 可劳作序 1
    event = world.event_log.by_type("household_work_nodes_changed")[-1]["payload"]
    assert event["household_id"] == "hh_test"
    assert event["before"] == []
    assert event["after"] == ["south_field", "east_field"]
    assert event["reason"] == "reassigned"


def test_c_capable_members_get_distinct_fields(world):
    """回归：不可劳作成员穿插在 member_ids 中间时，可劳作成员不得撞同一块田。

    旧实现按原始 member_ids 下标取模（长度=可劳作人数），[m1, 未成年, f1, 未成年]
    时 m1@0、f1@2 → 2%2=0 两人同上 south_field，east_field 闲置。
    """
    mod = _module(world)
    tuning = world.config.agents.tuning
    mother, father, household = _isolated_couple(world, fillers=0)
    _add_agent(world, "k9", sex=AgentSex.MALE, age=5,
               household_id="hh_test", home="rich_district")
    _add_agent(world, "k8", sex=AgentSex.MALE, age=5,
               household_id="hh_test", home="rich_district")
    household.member_ids = [mother.agent_id, "k9", father.agent_id, "k8"]

    mod._reconcile_work_nodes(world, tuning)  # noqa: SLF001

    # 可劳作成员仍只有夫妻 2 人，列表长度 2；两人按可劳作序对位不同田
    assert household.work_nodes == ["south_field", "east_field"]
    assert work_node_of(world, mother) == "south_field"   # 可劳作序 0
    assert work_node_of(world, father) == "east_field"    # 可劳作序 1，不再撞车
    # 不可劳作成员不占劳作位，取默认田
    assert work_node_of(world, world.state.human.agents["k9"]) == "south_field"


def test_c_single_member_household_keeps_default_field(world):
    """单人户列表只有默认田，work_node_of 与既有语义逐项相等。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    for agent in world.state.human.agents.values():
        agent.alive = False
    _add_household(world, "hh_solo", ["solo"], home="common_district", work="west_field")
    solo = _add_agent(world, "solo", sex=AgentSex.MALE, age=20,
                      household_id="hh_solo", home="common_district")

    mod._reconcile_work_nodes(world, tuning)  # noqa: SLF001

    assert hh(world, solo).work_nodes == ["west_field"]
    assert work_node_of(world, solo) == "west_field"


def test_c_newborn_takes_household_allocation(world):
    """新生儿不继承个人偏好，取家庭分配（按成员序），事件标注 household_allocation。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    mother, father, household = _isolated_couple(world, fillers=0)
    mod._reconcile_work_nodes(world, tuning)  # noqa: SLF001

    mod._give_birth(world, mother, father, tuning)  # noqa: SLF001

    child = world.state.human.agents["child_1"]
    assert child.work_node is None
    assert household.work_nodes == ["south_field", "east_field"]
    assert work_node_of(world, child) == "south_field"  # 不可劳作不占位 → 默认田
    payload = world.event_log.by_type("agent_born")[-1]["payload"]
    assert payload["work_node_source"] == "household_allocation"
    assert payload["work_node"] == "south_field"


def test_c_east_field_is_worked_within_1800_ticks():
    """验收：seed 0 × 1800 tick 内 east_field 至少被耕作一次（阶段一为 0）。"""
    world = _build(0)
    for _ in range(1800):
        run_tick(world)

    acts = [
        e["payload"] for e in world.event_log.by_type("agent_action_taken")
        if e["payload"].get("work_node") == "east_field"
        and e["payload"].get("action") in ("farm", "harvest")
    ]
    assert acts, "east_field 在 1800 tick 内仍零投入"
    assert any(a["action"] == "farm" for a in acts)
    assert not world.event_log.by_type("agent_error")


# --------------------------------------------------------------------------- #
# A：田产公式化（crops.md §4.5）
# --------------------------------------------------------------------------- #
def test_a_expected_yield_equals_legacy_values(world):
    """公式产出 = base_yield(config) × moisture（任务30 起 moisture 由灌溉档派生）。"""
    tuning = world.config.agents.tuning
    moisture = _moisture(world)
    assert expected_yield(world, "south_field", "grain", tuning) == pytest.approx(
        tuning.agriculture.base_yield["grain"] * moisture
    )
    assert expected_yield(world, "east_field", "grain", tuning) == pytest.approx(
        tuning.agriculture.base_yield["grain"] * moisture
    )
    assert expected_yield(world, "west_field", "vegetable", tuning) == pytest.approx(
        tuning.agriculture.base_yield["vegetable"] * moisture
    )


def test_a_area_and_fertility_scale_yield(world):
    """area 取自 spatial 节点、fertility 取自 WorldState，均为乘数。"""
    tuning = world.config.agents.tuning
    moisture = _moisture(world)
    base = tuning.agriculture.base_yield["grain"]
    node = next(n for n in world.config.spatial.nodes if n.id == "south_field")
    node.area = 2.0
    assert expected_yield(world, "south_field", "grain", tuning) == pytest.approx(base * 2.0 * moisture)
    node.area = 1.0

    world.state.environment.fertility_factor["south_field"] = 0.5
    assert expected_yield(world, "south_field", "grain", tuning) == pytest.approx(base * 0.5 * moisture)


def test_a_harvest_uses_formula_and_conserves(world):
    """harvest 产出入家庭库存 = 公式值；事件载荷带公式因子；无债务时逐项守恒。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.human.agents["lin_yuan"]
    world.state.environment.climate.season = Season.AUTUMN
    world.state.environment.field_growth["west_field"] = 90.0
    grain_before = hh(world, lin).grain
    vegetable_before = hh(world, lin).vegetable

    mod._execute(world, lin, "harvest", mod._perceive(world, lin), tuning)  # noqa: SLF001

    gain = expected_yield(world, "west_field", "vegetable", tuning)
    assert gain == pytest.approx(tuning.agriculture.base_yield["vegetable"] * _moisture(world))
    assert hh(world, lin).vegetable == pytest.approx(vegetable_before + gain)
    assert hh(world, lin).grain == pytest.approx(grain_before)
    payload = world.event_log.by_type("agent_action_taken")[-1]["payload"]
    assert payload["crop"] == "vegetable"
    assert payload["base_yield"] == pytest.approx(tuning.agriculture.base_yield["vegetable"])
    assert payload["field_area"] == pytest.approx(1.0)
    assert payload["field_fertility"] == pytest.approx(1.0)
    assert payload["moisture"] == pytest.approx(_moisture(world))
    assert payload["expected_yield"] == pytest.approx(
        tuning.agriculture.base_yield["vegetable"] * _moisture(world)
    )


# --------------------------------------------------------------------------- #
# B：出生户容量校验 + 分娩健康代价
# --------------------------------------------------------------------------- #
def test_b_birth_not_blocked_by_household_size(world):
    """家庭成员超过旧上限时仍可生育；是否生育由资源供给和生育条件决定。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    mother, _father, household = _isolated_couple(world, fillers=6)
    assert len(household.member_ids) == 8
    household.grain = 1000.0
    household.water = 1000.0
    tuning.birth.chance_per_day = 1.0
    born_before = len(world.event_log.by_type("agent_born"))
    skipped_before = len(world.event_log.by_type("birth_skipped"))

    mod._settle_birth(world, tuning)  # noqa: SLF001

    assert len(world.event_log.by_type("agent_born")) == born_before + 1
    assert len(world.event_log.by_type("birth_skipped")) == skipped_before
    assert len(household.member_ids) == 9


def test_b_birth_allowed_below_capacity(world):
    """户内 7 人（上限 8）→ 正常出生，不写 birth_skipped。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    _mother, _father, household = _isolated_couple(world, fillers=5)
    household.grain = 1000.0
    household.water = 1000.0
    tuning.birth.chance_per_day = 1.0
    born_before = len(world.event_log.by_type("agent_born"))
    skipped_before = len(world.event_log.by_type("birth_skipped"))

    mod._settle_birth(world, tuning)  # noqa: SLF001

    assert len(world.event_log.by_type("agent_born")) == born_before + 1
    assert len(world.event_log.by_type("birth_skipped")) == skipped_before


def test_birth_capacity_is_not_a_configurable_hard_gate(world):
    """配置不再暴露 household capacity 开关；家庭规模不是出生硬门槛。"""
    tuning = world.config.agents.tuning
    assert not hasattr(tuning.birth, "respect_house_capacity")
    assert not hasattr(tuning, "household")


def test_birth_applies_mother_health_cost(world):
    """分娩健康代价：设计值 −10，事件记录 before/after（§3.0 有设计分支）。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    mother, father, _household = _isolated_couple(world, fillers=0)
    mother.health = 90.0

    mod._give_birth(world, mother, father, tuning)  # noqa: SLF001

    assert mother.health == pytest.approx(90.0 - tuning.birth.mother_health_cost)
    payload = world.event_log.by_type("agent_born")[-1]["payload"]
    assert payload["mother_health_before"] == pytest.approx(90.0)
    assert payload["mother_health_after"] == pytest.approx(80.0)


# --------------------------------------------------------------------------- #
# 观察层：新增三类事件可渲染
# --------------------------------------------------------------------------- #
def test_new_events_render_without_degradation():
    cases = [
        ("household_work_nodes_changed", {
            "household_id": "hh_x", "before": ["south_field"],
            "after": ["south_field", "east_field"], "work_capable_members": 2,
        }),
        ("agent_work_node_changed", {
            "agent_id": "a1", "agent_name": "甲", "before": "ghost_field",
            "after": None, "reason": "preference_invalid",
        }),
        ("birth_skipped", {
            "agent_id": "a1", "agent_name": "甲", "household_id": "hh_x",
            "member_count": 8, "house_max_members": 8, "reason": "capacity",
        }),
    ]
    for event_type, payload in cases:
        result = render_event({"id": 1, "tick": 1, "event_type": event_type, "payload": payload})
        assert not result.degraded, event_type
        assert result.text
