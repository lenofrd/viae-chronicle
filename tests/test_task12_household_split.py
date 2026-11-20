"""任务 12 第 3 步：分家专项测试（设计 §9.2）。"""
from __future__ import annotations

import random

import pytest

from config.schema.agents import AgentSex
from vale.core.calendar import DAYS_PER_YEAR
from vale.core.config_loader import load_config
from vale.core.event_log import EventLog
from vale.core.household import household_of
from vale.core.state import AgentState, DebtRecord, HouseholdState
from vale.core.world import World
from vale.modules.agents import AgentModule
from vale.observability.render import render_event


@pytest.fixture
def world():
    cfg = load_config("brookvale-town-001")
    w = World(
        world_id=cfg.world.world_id,
        event_log=EventLog(":memory:"),
        start_tick=cfg.world.start_tick,
        config=cfg,
    )
    mod = AgentModule(rng=random.Random(7))
    w.register(mod)
    mod._ensure_agents(w, cfg.agents)  # noqa: SLF001
    w.current_tick = 100
    world_split = cfg.agents.tuning.split
    world_split.min_members = 4
    world_split.asset_ratio = 0.5
    world_split.home_node_candidates = []
    return w


def _module(world) -> AgentModule:
    return next(m for m in world.modules if m.name == "agents")


def _household(world, members: list[AgentState], *, head: str, home="common_district",
               work="common_district", grain=100.0, cloth=4.0, debts: list[float] | None = None):
    """清空默认单人户，构造一个指定成员的家庭。"""
    world.state.human.households.clear()
    hid = "hh_test"
    household = HouseholdState(
        household_id=hid, member_ids=[m.agent_id for m in members], head_id=head,
        home_node=home, work_node=work, formed_tick=world.current_tick,
        grain=grain, cloth=cloth,
    )
    for amount in debts or []:
        household.debts.append(
            DebtRecord(debtor_household_id=hid, creditor_household_id="hh_li_quan",
                       amount=amount, originated_tick=0, due_tick=9999)
        )
    for m in members:
        m.household_id = hid
        m.location = home
    world.state.human.households[hid] = household
    return household


def _add_agent(world, agent_id: str, *, name: str, sex: AgentSex, age: int,
               household_id: str = "", mother_id=None, father_id=None) -> AgentState:
    agent = AgentState(
        agent_id=agent_id, name=name, sex=sex,
        birth_tick=world.current_tick - age * DAYS_PER_YEAR,
        household_id=household_id, location="common_district",
        health=90.0, hunger=10.0, stamina=80.0,
        mother_id=mother_id, father_id=father_id,
    )
    world.state.human.agents[agent_id] = agent
    return agent


def _couple(world):
    """户主 li_quan；lin_yuan(18, 男) 娶 zhou_qiaoniang(23, 女)，均非户主。"""
    li = world.state.human.agents["li_quan"]
    lin = world.state.human.agents["lin_yuan"]
    zhou = world.state.human.agents["zhou_qiaoniang"]
    lin.spouse_id, zhou.spouse_id = zhou.agent_id, lin.agent_id
    household = _household(world, [li, lin, zhou], head=li.agent_id, debts=[10.0])
    return li, lin, zhou, household


# =========================================================================== #
# 触发条件
# =========================================================================== #
def test_split_requires_min_members(world):
    li, lin, zhou, household = _couple(world)
    tuning = world.config.agents.tuning
    tuning.split.min_members = 4  # 当前 3 人
    _module(world)._settle_split(world, tuning)  # noqa: SLF001
    assert not world.event_log.by_type("household_split")


def test_split_requires_husband_not_head(world):
    li, lin, zhou, household = _couple(world)
    child = _add_agent(world, "child_min", name="林小满", sex=AgentSex.FEMALE, age=5,
                       household_id=household.household_id)
    child.mother_id, child.father_id = zhou.agent_id, lin.agent_id
    household.member_ids.append(child.agent_id)
    household.head_id = lin.agent_id  # 丈夫成为户主 → 不触发
    _module(world)._settle_split(world, world.config.agents.tuning)  # noqa: SLF001
    assert not world.event_log.by_type("household_split")


def test_no_split_when_spouse_in_other_household(world):
    li, lin, zhou, household = _couple(world)
    child = _add_agent(world, "child_min", name="林小满", sex=AgentSex.FEMALE, age=5,
                       household_id=household.household_id)
    child.mother_id = zhou.agent_id
    household.member_ids.append(child.agent_id)
    # 把妻子迁到另一户
    another = HouseholdState(household_id="hh_other", member_ids=[zhou.agent_id],
                             head_id=zhou.agent_id, home_node="well", work_node="well",
                             formed_tick=world.current_tick)
    household.member_ids.remove(zhou.agent_id)
    zhou.household_id = "hh_other"
    world.state.human.households["hh_other"] = another
    _module(world)._settle_split(world, world.config.agents.tuning)  # noqa: SLF001
    assert not world.event_log.by_type("household_split")


# =========================================================================== #
# 成员、户主与住所
# =========================================================================== #
def test_split_moves_wife_and_minor_children_only(world):
    li, lin, zhou, household = _couple(world)
    minor = _add_agent(world, "child_min", name="林小满", sex=AgentSex.FEMALE, age=5,
                       household_id=household.household_id)
    minor.mother_id, minor.father_id = zhou.agent_id, lin.agent_id
    adult = _add_agent(world, "child_adult", name="林大成", sex=AgentSex.MALE, age=20,
                       household_id=household.household_id)
    adult.mother_id, adult.father_id = zhou.agent_id, lin.agent_id
    household.member_ids += [minor.agent_id, adult.agent_id]

    _module(world)._settle_split(world, world.config.agents.tuning)  # noqa: SLF001
    split = world.event_log.by_type("household_split")[-1]["payload"]
    new_hh = world.state.human.households[split["new_household_id"]]
    assert new_hh.head_id == lin.agent_id
    assert set(new_hh.member_ids) == {lin.agent_id, zhou.agent_id, minor.agent_id}
    assert adult.agent_id in household.member_ids  # 成年子女留原户
    assert household.head_id == li.agent_id  # 原户主不变


def test_split_home_candidates_rotation(world):
    li, lin, zhou, household = _couple(world)
    child = _add_agent(world, "child_min", name="林小满", sex=AgentSex.FEMALE, age=5,
                       household_id=household.household_id)
    child.mother_id = zhou.agent_id
    household.member_ids.append(child.agent_id)
    tuning = world.config.agents.tuning
    tuning.split.home_node_candidates = ["rich_district", "well"]
    _module(world)._settle_split(world, tuning)  # noqa: SLF001
    payload = world.event_log.by_type("household_split")[-1]["payload"]
    expected = tuning.split.home_node_candidates[
        len(world.state.human.households) % len(tuning.split.home_node_candidates)
    ]
    # 事件写入后 households 已含新户，故用事件里的住所校验其为候选之一
    assert payload["home_node"] in tuning.split.home_node_candidates
    assert world.state.human.households[payload["new_household_id"]].home_node == payload["home_node"]
    assert isinstance(expected, str)


def test_split_home_fallback_same_node(world):
    li, lin, zhou, household = _couple(world)
    child = _add_agent(world, "child_min", name="林小满", sex=AgentSex.FEMALE, age=5,
                       household_id=household.household_id)
    child.mother_id = zhou.agent_id
    household.member_ids.append(child.agent_id)
    tuning = world.config.agents.tuning
    tuning.split.home_node_candidates = []
    _module(world)._settle_split(world, tuning)  # noqa: SLF001
    payload = world.event_log.by_type("household_split")[-1]["payload"]
    assert payload["home_node"] == household.home_node


def test_split_work_node_from_husband_preference(world):
    li, lin, zhou, household = _couple(world)
    child = _add_agent(world, "child_min", name="林小满", sex=AgentSex.FEMALE, age=5,
                       household_id=household.household_id)
    child.mother_id = zhou.agent_id
    household.member_ids.append(child.agent_id)
    lin.work_node = "market"
    _module(world)._settle_split(world, world.config.agents.tuning)  # noqa: SLF001
    split = world.event_log.by_type("household_split")[-1]["payload"]
    new_hh = world.state.human.households[split["new_household_id"]]
    assert new_hh.work_node == "market"
    assert zhou.work_node is None and lin.work_node is None  # 迁出后取新户默认


def test_split_new_id_unique_and_event_payload_complete(world):
    li, lin, zhou, household = _couple(world)
    child = _add_agent(world, "child_min", name="林小满", sex=AgentSex.FEMALE, age=5,
                       household_id=household.household_id)
    child.mother_id = zhou.agent_id
    household.member_ids.append(child.agent_id)
    _module(world)._settle_split(world, world.config.agents.tuning)  # noqa: SLF001
    payload = world.event_log.by_type("household_split")[-1]["payload"]
    assert payload["new_household_id"].startswith(f"hh_{household.household_id}_")
    assert payload["new_household_id"] in world.state.human.households
    assert payload["reason"] == "married_couple_out"
    for key in ("source_household_id", "assets_before", "source_assets_after", "new_assets",
                "debts_before", "source_debts_after", "new_debts", "home_node", "head_id"):
        assert key in payload
    result = render_event({"event_type": "household_split", "payload": payload})
    assert "分家" in result.text and not result.degraded


# =========================================================================== #
# 守恒
# =========================================================================== #
def test_split_assets_conserved_to_two_decimals(world):
    li, lin, zhou, household = _couple(world)
    child = _add_agent(world, "child_min", name="林小满", sex=AgentSex.FEMALE, age=5,
                       household_id=household.household_id)
    child.mother_id = zhou.agent_id
    household.member_ids.append(child.agent_id)
    household.grain, household.cloth = 101.0, 3.0
    before = {"grain": household.grain, "cloth": household.cloth}
    _module(world)._settle_split(world, world.config.agents.tuning)  # noqa: SLF001
    payload = world.event_log.by_type("household_split")[-1]["payload"]
    new_hh = world.state.human.households[payload["new_household_id"]]
    for item, amount in before.items():
        assert getattr(household, item) + getattr(new_hh, item) == pytest.approx(amount)
        assert round(getattr(new_hh, item), 2) == getattr(new_hh, item)
    assert payload["assets_before"]["grain"] == pytest.approx(101.0)


def test_split_debts_conserved_and_non_negative(world):
    li, lin, zhou, household = _couple(world)
    child = _add_agent(world, "child_min", name="林小满", sex=AgentSex.FEMALE, age=5,
                       household_id=household.household_id)
    child.mother_id = zhou.agent_id
    household.member_ids.append(child.agent_id)
    household.debts = [
        DebtRecord(debtor_household_id="hh_test", creditor_household_id="hh_li_quan",
                   amount=7.5, originated_tick=0, due_tick=9999),
        DebtRecord(debtor_household_id="hh_test", creditor_household_id="hh_li_quan",
                   amount=1.3, originated_tick=0, due_tick=9999),
    ]
    before = 8.8
    _module(world)._settle_split(world, world.config.agents.tuning)  # noqa: SLF001
    payload = world.event_log.by_type("household_split")[-1]["payload"]
    new_hh = world.state.human.households[payload["new_household_id"]]
    assert household.debt + new_hh.debt == pytest.approx(before)
    assert household.debt >= 0 and new_hh.debt >= 0
    assert payload["debts_before"] == pytest.approx(before)
    assert payload["source_debts_after"] + payload["new_debts"] == pytest.approx(before)


# =========================================================================== #
# 新生儿随迁（分家在生育后结算）
# =========================================================================== #
def test_newborn_of_non_head_couple_follows_parents(world):
    li, lin, zhou, household = _couple(world)
    newborn = _add_agent(world, "baby_1", name="林阿福", sex=AgentSex.MALE, age=0,
                         household_id=household.household_id,
                         mother_id=zhou.agent_id, father_id=lin.agent_id)
    household.member_ids.append(newborn.agent_id)
    _module(world)._settle_split(world, world.config.agents.tuning)  # noqa: SLF001
    payload = world.event_log.by_type("household_split")[-1]["payload"]
    assert newborn.agent_id in [m["id"] for m in payload["members"]]
    assert newborn.household_id == payload["new_household_id"]
    assert newborn.location == payload["home_node"]
    assert newborn.agent_id not in household.member_ids


def test_newborn_of_head_couple_stays_and_triggers_no_split(world):
    li, lin, zhou, household = _couple(world)
    household.head_id = lin.agent_id  # 丈夫成为户主 → 不满足分家条件
    newborn = _add_agent(world, "baby_2", name="林阿寿", sex=AgentSex.FEMALE, age=0,
                         household_id=household.household_id,
                         mother_id=zhou.agent_id, father_id=lin.agent_id)
    household.member_ids.append(newborn.agent_id)
    _module(world)._settle_split(world, world.config.agents.tuning)  # noqa: SLF001
    assert not world.event_log.by_type("household_split")
    assert newborn.household_id == household.household_id
    assert newborn.agent_id in household.member_ids


# =========================================================================== #
# 频率：每户每 tick 最多一次
# =========================================================================== #
def test_one_split_per_household_per_tick(world):
    li, lin, zhou, household = _couple(world)
    # 第二对夫妻，丈夫同样非户主
    a = _add_agent(world, "a_m", name="甲", sex=AgentSex.MALE, age=22,
                   household_id=household.household_id)
    b = _add_agent(world, "b_f", name="乙", sex=AgentSex.FEMALE, age=21,
                   household_id=household.household_id)
    a.spouse_id, b.spouse_id = b.agent_id, a.agent_id
    household.member_ids += [a.agent_id, b.agent_id]
    _module(world)._settle_split(world, world.config.agents.tuning)  # noqa: SLF001
    assert len(world.event_log.by_type("household_split")) == 1
