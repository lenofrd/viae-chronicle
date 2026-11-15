"""任务11 阶段二机制验收：移动校准 / 赶集交易 / 纺织保暖 / 蔬菜作物 / 第 4 NPC / 观察层。

只验证机制正确性（配置驱动、守恒、门控、事件可复现），不做生态平衡调参。
"""
from __future__ import annotations

import random

import pytest
from pydantic import ValidationError

from config.schema.agents import MarketTuning
from config.schema.natural_params import Season
from vale.core.config_loader import load_config
from vale.core.event_log import EventLog
from vale.core.scheduler import run_tick
from vale.core.world import World
from vale.modules.agents import IMPOSSIBLE, AgentModule, SpatialIndex
from vale.modules.climate import ClimateModule
from vale.observability.render import render_event

INITIAL_STAMINA = 80.0  # 配置 initial_stamina；锚点百分比以其为分母（与 STATUS 校准表一致）
MOVE_RATE = 3.0


def _build(seed: int = 0) -> World:
    cfg = load_config("brookvale-town-001")
    log = EventLog(":memory:")
    w = World(world_id=cfg.world.world_id, event_log=log,
              start_tick=cfg.world.start_tick, config=cfg)
    w.register(ClimateModule(rng=random.Random(seed)))
    w.register(AgentModule(rng=random.Random(seed * 7 + 13)))
    return w


@pytest.fixture
def world():
    w = _build(0)
    run_tick(w)  # 初始化 agents / climate / spatial
    return w


def _module(world) -> AgentModule:
    return next(m for m in world.modules if m.name == "agents")  # type: ignore[return-value]


def _rt_percent(world, home: str, node: str) -> float:
    """往返一次某节点的体力占体力上限百分比。"""
    idx = SpatialIndex(world.config.spatial)
    return 2.0 * idx.travel_tu(home, node) * MOVE_RATE / INITIAL_STAMINA * 100.0


def _set_inventory(agent, **kw) -> None:
    for field in ("grain", "vegetable", "meat", "fish", "cloth"):
        setattr(agent, field, kw.get(field, 0.0))


# --------------------------------------------------------------------------- #
# 一、移动体力校准（裁决：move_stamina_per_tu 5→3）
# --------------------------------------------------------------------------- #
def test_move_rate_is_calibrated(world):
    assert world.config.agents.tuning.utility.move_stamina_per_tu == pytest.approx(MOVE_RATE)


@pytest.mark.parametrize(
    "home,node,label",
    [
        ("common_district", "west_field", "平民区→西片田"),
        ("poor_district", "east_field", "贫民区→东片田"),
        ("rich_district", "south_field", "富户区→南片田"),
        ("common_district", "river_town", "平民区→河边"),
        ("poor_district", "river_town", "贫民区→河边"),
        ("rich_district", "market", "富户区→集市"),
        ("poor_district", "market", "贫民区→集市"),
    ],
)
def test_daily_trips_within_daily_band(world, home, node, label):
    """下地 / 捕鱼 / 赶集：往返 ≤30% 体力，且单程不耗尽体力。"""
    pct = _rt_percent(world, home, node)
    idx = SpatialIndex(world.config.spatial)
    one_way_cost = idx.travel_tu(home, node) * MOVE_RATE
    assert pct <= 30.0, f"{label} 往返体力占比 {pct:.1f}% 超出日常档上限"
    assert one_way_cost <= 0.8 * INITIAL_STAMINA, f"{label} 单程即接近耗尽体力"


def test_close_market_trip_is_documented_low_exception(world):
    """平民区→集市仅 8.25%，低于日常档 10% 下限：market 距水井仅 0.6 TU 所致。

    裁决值（0.6 TU）与 3.0 体力系数共同决定该例外；不构成"单程耗尽"或"远行过轻"，
    在设计文档与 STATUS 中登记，阶段三若要抬到 10% 以上需改白名单参数。
    """
    pct = _rt_percent(world, "common_district", "market")
    assert pct == pytest.approx(8.25, abs=0.05)
    assert pct < 10.0


@pytest.mark.parametrize(
    "home,label",
    [
        ("common_district", "平民区→浅山"),
        ("poor_district", "贫民区→浅山"),
        ("rich_district", "富户区→浅山"),
    ],
)
def test_far_mountain_trips_within_far_band(world, home, label):
    """进山（≥13 TU 往返）落在 40–60% 远行档，且单程不耗尽。"""
    pct = _rt_percent(world, home, "low_mountain")
    assert 40.0 <= pct <= 60.0, f"{label} 往返体力占比 {pct:.1f}% 不在远行档"
    idx = SpatialIndex(world.config.spatial)
    assert idx.travel_tu(home, "low_mountain") * MOVE_RATE <= 0.8 * INITIAL_STAMINA


def test_market_node_is_reachable_from_all_districts(world):
    """裁决：market 补 0.6 TU 后，四区（含富户区）赶集在空间图上均可达。"""
    idx = SpatialIndex(world.config.spatial)
    for home in ("common_district", "poor_district", "rich_district"):
        assert idx.travel_tu(home, "market") < float("inf")


# --------------------------------------------------------------------------- #
# 二、赶集日结算与撮合
# --------------------------------------------------------------------------- #
def test_market_day_trigger_and_single_summary(world):
    while world.current_tick <= 10:  # tick 递增发生在 step 之后，处理到 tick 10 即可
        run_tick(world)
    assert world.current_tick == 11
    summaries = world.event_log.by_type("market_day_summary")
    assert len(summaries) == 1
    assert summaries[0]["tick"] == 10
    assert summaries[0]["payload"]["participant_count"] >= 1
    assert set(summaries[0]["payload"]["skipped"]) == {"dead_or_incap", "too_far", "too_weak"}

    run_tick(world)
    assert world.current_tick == 12
    assert len(world.event_log.by_type("market_day_summary")) == 1  # 非集市日不再写


def test_market_travel_deducts_round_trip_stamina(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    idx = SpatialIndex(world.config.spatial)
    for a in world.state.agents.values():
        a.stamina = 80.0
    expected = {
        a.agent_id: 2.0 * idx.travel_tu(a.home_node, "market") * MOVE_RATE
        for a in world.state.agents.values()
        if a.alive and not a.incapacitated
    }
    mod._settle_market(world, tuning)  # noqa: SLF001
    for a in world.state.agents.values():
        if a.agent_id in expected:
            assert a.stamina == pytest.approx(80.0 - expected[a.agent_id])
    summary = world.event_log.by_type("market_day_summary")[-1]["payload"]
    by_id = {p["agent_id"]: p["travel_stamina_cost"] for p in summary["participants"]}
    for aid, cost in expected.items():
        assert by_id[aid] == pytest.approx(round(cost, 2))


def test_too_far_agents_skipped_without_stamina_loss(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    tuning.market.market_max_distance_tu = 2.0  # 贫民区单程 2.6 TU → 过远
    zhao = world.state.agents["zhao_cuilan"]
    zhao.stamina = 90.0
    mod._settle_market(world, tuning)  # noqa: SLF001
    summary = world.event_log.by_type("market_day_summary")[-1]["payload"]
    assert summary["skipped"]["too_far"] == 1
    assert zhao.stamina == pytest.approx(90.0)
    assert "zhao_cuilan" not in {p["agent_id"] for p in summary["participants"]}


def test_too_weak_agents_skipped_without_stamina_loss(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    zhao = world.state.agents["zhao_cuilan"]
    zhao.stamina = 20.0  # 往返 15.6 → 余 4.4 < market_min_stamina 15
    mod._settle_market(world, tuning)  # noqa: SLF001
    summary = world.event_log.by_type("market_day_summary")[-1]["payload"]
    assert summary["skipped"]["too_weak"] == 1
    assert zhao.stamina == pytest.approx(20.0)


def test_dead_or_incapacitated_skipped(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    zhao = world.state.agents["zhao_cuilan"]
    zhao.incapacitated = True
    zhao.stamina = 90.0
    mod._settle_market(world, tuning)  # noqa: SLF001
    summary = world.event_log.by_type("market_day_summary")[-1]["payload"]
    assert summary["skipped"]["dead_or_incap"] == 1
    assert zhao.stamina == pytest.approx(90.0)


def _prepare_single_pair(world):
    """只保留「林远卖粮 ↔ 赵翠兰卖鱼」一对可成交关系，避免其他人抢单。"""
    li = world.state.agents["li_quan"]
    lin = world.state.agents["lin_yuan"]
    zhao = world.state.agents["zhao_cuilan"]
    zhou = world.state.agents["zhou_qiaoniang"]
    _set_inventory(li, grain=20, cloth=0)
    _set_inventory(lin, grain=40)
    _set_inventory(zhao, grain=0, fish=20)
    _set_inventory(zhou, grain=10, cloth=0)
    for a in (li, lin, zhao, zhou):
        a.stamina = 100.0
    return lin, zhao


def test_trade_executes_and_conserves_items(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin, zhao = _prepare_single_pair(world)
    mod._settle_market(world, tuning)  # noqa: SLF001

    trades = world.event_log.by_type("trade_executed")
    assert len(trades) == 1
    p = trades[0]["payload"]
    assert {p["seller_id"], p["buyer_id"]} == {"lin_yuan", "zhao_cuilan"}
    assert p["give_item"] == "grain" and p["take_item"] == "fish"
    # 总量守恒：粮 40+0、鱼 0+20
    assert lin.grain + zhao.grain == pytest.approx(40.0)
    assert lin.fish + zhao.fish == pytest.approx(20.0)
    # 只卖富余、只补短缺：卖方粮不低于 surplus=20，买方粮不超过 deficit=10，成交量为正
    assert p["give_qty"] > 0
    assert lin.grain >= tuning.market.surplus_threshold["grain"] - 1e-9
    assert zhao.grain <= tuning.market.deficit_threshold["grain"] + 1e-9
    assert zhao.grain == pytest.approx(p["give_qty"], abs=0.01)
    assert lin.grain == pytest.approx(40.0 - p["give_qty"], abs=0.01)
    assert p["take_qty"] == pytest.approx(p["give_qty"] * 1.0 / 1.5, abs=0.02)


def test_trade_basis_matches_value_ratio(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    _prepare_single_pair(world)
    mod._settle_market(world, tuning)  # noqa: SLF001
    p = world.event_log.by_type("trade_executed")[0]["payload"]
    assert p["trade_value_ratio"] == pytest.approx(
        tuning.market.trade_values["grain"] / tuning.market.trade_values["fish"], abs=0.01
    )
    assert p["give_qty"] * tuning.market.trade_values["grain"] == pytest.approx(
        p["take_qty"] * tuning.market.trade_values["fish"], abs=0.2
    )  # 价值相对误差在容忍度内（步长取整带来微小偏差）


def test_no_trade_when_all_at_thresholds(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    for a in world.state.agents.values():
        _set_inventory(
            a,
            grain=tuning.market.surplus_threshold["grain"],
            cloth=tuning.market.surplus_threshold["cloth"],
        )
        a.stamina = 100.0
    mod._settle_market(world, tuning)  # noqa: SLF001
    assert not world.event_log.by_type("trade_executed")
    assert world.event_log.by_type("market_day_summary")[-1]["payload"]["trade_count"] == 0


def test_trade_pairs_are_stable_and_unique(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin, zhao = _prepare_single_pair(world)
    # 再加一个同样富余粮的卖家（数量低于阈值，确保不抢单）
    world.state.agents["li_quan"].grain = 20.0
    mod._settle_market(world, tuning)  # noqa: SLF001
    seen = set()
    for ev in world.event_log.by_type("trade_executed"):
        p = ev["payload"]
        assert p["seller_id"] < p["buyer_id"]  # 按 id 升序只撮合一次
        key = (p["seller_id"], p["buyer_id"])
        assert key not in seen
        seen.add(key)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"market_day_interval": 10, "market_day_offset": 10},        # 偏移不得 ≥ 周期
        {"trade_values": {"grain": 0.0}},                           # 价值必须为正
        {"trade_values": {"grain": 1.0}, "surplus_threshold": {}},  # 缺富余阈值
        {"surplus_threshold": {}},                                  # 缺富余阈值
        {"trade_values": {"grain": 1.0}, "surplus_threshold": {"grain": 5.0},
         "deficit_threshold": {"grain": 5.0}},                      # 短缺 ≥ 富余（倒挂）
        {"trade_unit_step": 0.0},                                   # 步长必须为正
    ],
)
def test_market_bad_config_rejected(kwargs):
    base = {
        "trade_values": {"grain": 1.0},
        "surplus_threshold": {"grain": 20.0},
        "deficit_threshold": {"grain": 10.0},
    }
    base.update(kwargs)
    with pytest.raises(ValidationError):
        MarketTuning(**base)


# --------------------------------------------------------------------------- #
# 三、纺织与冬季保暖
# --------------------------------------------------------------------------- #
def test_weave_success_adds_cloth(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    zhou = world.state.agents["zhou_qiaoniang"]
    tuning.textile.base_success_rate = 1.0
    tuning.textile.season_modifier = {}
    before = zhou.cloth
    p = mod._perceive(world, zhou)  # noqa: SLF001
    mod._execute(world, zhou, "weave", p, tuning)  # noqa: SLF001
    assert zhou.cloth == pytest.approx(before + tuning.textile.cloth_per_weave)
    ev = world.event_log.by_type("weave_success")[-1]["payload"]
    assert ev["amount"] == pytest.approx(tuning.textile.cloth_per_weave)


def test_weave_failure_produces_nothing(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    zhou = world.state.agents["zhou_qiaoniang"]
    tuning.textile.base_success_rate = 0.0
    before = zhou.cloth
    p = mod._perceive(world, zhou)  # noqa: SLF001
    mod._execute(world, zhou, "weave", p, tuning)  # noqa: SLF001
    assert zhou.cloth == pytest.approx(before)
    assert world.event_log.by_type("weave_fail")


def test_weave_impossible_without_stamina(world):
    mod = _module(world)
    zhou = world.state.agents["zhou_qiaoniang"]
    zhou.stamina = 0.0
    p = mod._perceive(world, zhou)  # noqa: SLF001
    assert mod.score_action("weave", p, world.config.agents.tuning) == IMPOSSIBLE


def test_cloth_is_not_food(world):
    mod = _module(world)
    lin = world.state.agents["lin_yuan"]
    _set_inventory(lin, cloth=3)
    lin.hunger = 90.0
    p = mod._perceive(world, lin)  # noqa: SLF001
    assert mod.score_action("eat", p, world.config.agents.tuning) == IMPOSSIBLE


def test_winter_cold_penalty_without_cloth(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    _set_inventory(lin, cloth=0)
    lin.health = 60.0
    mod._apply_cold_exposure(world, lin, tuning, Season.WINTER)  # noqa: SLF001
    assert lin.health == pytest.approx(60.0 - tuning.textile.cold_health_loss)
    ev = world.event_log.by_type("cold_exposure")[-1]["payload"]
    assert ev["agent_id"] == "lin_yuan"
    assert ev["loss"] == pytest.approx(tuning.textile.cold_health_loss)


def test_winter_cold_penalty_waived_when_cloth_enough(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    lin.cloth = tuning.textile.warmth_cloth_threshold
    lin.health = 60.0
    mod._apply_cold_exposure(world, lin, tuning, Season.WINTER)  # noqa: SLF001
    assert lin.health == pytest.approx(60.0)
    assert not any(e["payload"].get("agent_id") == "lin_yuan"
                   for e in world.event_log.by_type("cold_exposure"))


def test_cold_penalty_only_in_winter(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    _set_inventory(lin, cloth=0)
    lin.health = 60.0
    mod._apply_cold_exposure(world, lin, tuning, Season.SUMMER)  # noqa: SLF001
    assert lin.health == pytest.approx(60.0)
    assert not world.event_log.by_type("cold_exposure")


def test_one_cold_event_per_agent_per_day(world):
    """_process_one 是每日每人的结算单元，单次调用至多产生一条 cold_exposure。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    world.state.climate.season = Season.WINTER
    lin = world.state.agents["lin_yuan"]
    lin_cfg = next(a for a in world.config.agents.agents if a.id == "lin_yuan")
    _set_inventory(lin, cloth=0)
    mod._process_one(world, lin_cfg, tuning)  # noqa: SLF001
    evs = [e for e in world.event_log.by_type("cold_exposure")
           if e["payload"]["agent_id"] == "lin_yuan" and e["tick"] == world.current_tick]
    assert len(evs) == 1


# --------------------------------------------------------------------------- #
# 四、蔬菜作物（crop_type 驱动，不写死 grain）
# --------------------------------------------------------------------------- #
def test_west_field_yields_vegetable_not_grain(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    assert lin.work_node == "west_field"
    lin.stamina = 90.0
    lin.grain = 10.0
    lin.vegetable = 0.0
    world.state.climate.season = Season.AUTUMN
    world.state.field_growth["west_field"] = 90.0
    p = mod._perceive(world, lin)  # noqa: SLF001
    mod._execute(world, lin, "harvest", p, tuning)  # noqa: SLF001
    assert lin.vegetable == pytest.approx(tuning.agriculture.crop_gain["vegetable"])
    assert lin.grain == pytest.approx(10.0)  # 菜田不产粮
    ev = world.event_log.by_type("agent_action_taken")[-1]["payload"]
    assert ev["crop"] == "vegetable"


def test_vegetable_is_edible_after_grain_runs_out(world):
    mod = _module(world)
    tuning = world.config.agents.tuning
    lin = world.state.agents["lin_yuan"]
    _set_inventory(lin, vegetable=3.0)
    lin.hunger = 80.0
    p = mod._perceive(world, lin)  # noqa: SLF001
    mod._execute(world, lin, "eat", p, tuning)  # noqa: SLF001
    assert lin.vegetable == pytest.approx(3.0 - tuning.physiology.eat_grain_cost)
    assert lin.grain == pytest.approx(0.0)


def test_crop_type_is_configurable_without_core_change(world):
    """扩展点：把东片田改种蔬菜，harvest 自动产出 vegetable，核心结算不改。"""
    for n in world.config.spatial.nodes:
        if n.id == "east_field":
            n.crop_type = "vegetable"
    mod = _module(world)
    tuning = world.config.agents.tuning
    zhao = world.state.agents["zhao_cuilan"]
    zhao.stamina = 90.0
    zhao.vegetable = 0.0
    world.state.climate.season = Season.AUTUMN
    world.state.field_growth["east_field"] = 90.0
    p = mod._perceive(world, zhao)  # noqa: SLF001
    mod._execute(world, zhao, "harvest", p, tuning)  # noqa: SLF001
    assert zhao.vegetable == pytest.approx(tuning.agriculture.crop_gain["vegetable"])


# --------------------------------------------------------------------------- #
# 五、第 4 个 NPC（织户）
# --------------------------------------------------------------------------- #
def test_fourth_npc_loaded_with_assets(world):
    zhou = world.state.agents["zhou_qiaoniang"]
    cfg_zhou = next(a for a in world.config.agents.agents if a.id == "zhou_qiaoniang")
    assert zhou.name == "周巧娘"
    assert zhou.work_node == "market"
    assert cfg_zhou.assets.cloth == pytest.approx(8.0)
    assert cfg_zhou.assets.vegetable == pytest.approx(5.0)


def test_non_field_worker_cannot_farm_or_harvest(world):
    mod = _module(world)
    zhou = world.state.agents["zhou_qiaoniang"]
    zhou.stamina = 100.0
    p = mod._perceive(world, zhou)  # noqa: SLF001
    assert not p.work_node_is_field
    assert mod.score_action("farm", p, world.config.agents.tuning) == IMPOSSIBLE
    assert mod.score_action("harvest", p, world.config.agents.tuning) == IMPOSSIBLE


def test_weaver_can_weave(world):
    mod = _module(world)
    zhou = world.state.agents["zhou_qiaoniang"]
    zhou.stamina = 100.0
    p = mod._perceive(world, zhou)  # noqa: SLF001
    assert mod.score_action("weave", p, world.config.agents.tuning) > IMPOSSIBLE


# --------------------------------------------------------------------------- #
# 六、观察层：5 类新事件 + 蔬菜秋收渲染
# --------------------------------------------------------------------------- #
def _render(event_type: str, payload: dict):
    return render_event({"id": 1, "tick": 10, "event_type": event_type, "payload": payload})


def test_render_trade_executed():
    r = _render("trade_executed", {
        "buyer_id": "b", "buyer_name": "赵翠兰", "seller_id": "s", "seller_name": "林远",
        "give_item": "grain", "give_qty": 10.0, "take_item": "cloth", "take_qty": 3.5,
    })
    assert "换得" in r.text and "粮" in r.text and "布" in r.text
    assert not r.degraded


def test_render_market_day_summary():
    r = _render("market_day_summary", {
        "participant_count": 3, "trade_count": 2,
        "skipped": {"too_weak": 1, "too_far": 0, "dead_or_incap": 0},
    })
    assert "集市日" in r.text and "体力不足 1 人" in r.text
    assert not r.degraded


def test_render_weave_events():
    ok = _render("weave_success", {"agent_id": "z", "agent_name": "周巧娘",
                                   "amount": 2.0, "cloth_after": 10.0})
    fail = _render("weave_fail", {"agent_id": "z", "agent_name": "周巧娘",
                                  "reason": "织机未成布"})
    assert "织成 2 匹布" in ok.text and not ok.degraded
    assert "织布未成" in fail.text and not fail.degraded


def test_render_cold_exposure():
    r = _render("cold_exposure", {"agent_id": "l", "agent_name": "林远",
                                  "cloth": 0.0, "health_before": 60.0, "health_after": 58.0})
    assert "御寒" in r.text and "60" in r.text and "58" in r.text
    assert not r.degraded


def test_render_vegetable_harvest_uses_dan_unit():
    r = _render("agent_action_taken", {
        "agent_id": "l", "agent_name": "林远", "action": "harvest", "target_node": "west_field",
        "crop": "vegetable", "vegetable_before": 0.0, "vegetable_after": 55.0,
        "grain_before": 10.0, "grain_after": 10.0, "debt_before": 0.0, "debt_after": 0.0,
    })
    assert "55 担" in r.text and "存菜" in r.text
    assert not r.degraded


# --------------------------------------------------------------------------- #
# 七、生存必要性门控（阶段二裁决附条件）
# --------------------------------------------------------------------------- #
def test_survival_gate_forces_eat_when_hunger_would_cross_threshold(world):
    """有粮 + 次日饥饿将跨伤害阈值 → 直接 eat，不参与效用竞争，且不写事件。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    phys = tuning.physiology
    lin = world.state.agents["lin_yuan"]
    _set_inventory(lin, grain=3.0)
    lin.hunger = phys.hunger_health_damage_threshold - 1.0  # +hunger_gain 必跨阈值
    lin.stamina = 10.0  # 若按打分，rest 会赢
    events_before = len(world.event_log.by_type("agent_action_taken"))
    p = mod._perceive(world, lin)  # noqa: SLF001
    assert mod._decide(p, tuning) == "eat"  # noqa: SLF001
    # 门控本身不写事件（动作事件由后续 _execute 负责）
    assert len(world.event_log.by_type("agent_action_taken")) == events_before
    assert not world.event_log.by_type("agent_error")


def test_survival_gate_not_triggered_without_food(world):
    """无粮可吃 → 门控不触发，仍走效用竞争（不制造食物、不掩盖饿死）。"""
    mod = _module(world)
    tuning = world.config.agents.tuning
    phys = tuning.physiology
    lin = world.state.agents["lin_yuan"]
    _set_inventory(lin)  # 所有食物字段为 0
    lin.hunger = 99.0
    lin.stamina = 100.0
    p = mod._perceive(world, lin)  # noqa: SLF001
    action = mod._decide(p, tuning)  # noqa: SLF001
    assert action != "eat"
    assert mod.score_action("eat", p, tuning) == IMPOSSIBLE
    assert all(getattr(lin, f) == 0 for f in phys.food_fields)


# --------------------------------------------------------------------------- #
# 八、阶段二长程自检（2 种子 × 1080 tick）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("seed", [0, 7])
def test_phase_two_long_run_has_survivors_and_no_errors(seed):
    w = _build(seed)
    for _ in range(1080):
        run_tick(w)
    assert [a for a in w.state.agents.values() if a.alive]
    assert not w.event_log.by_type("agent_error")
    assert w.event_log.by_type("market_day_summary")  # 集市机制确实在跑
    for a in w.state.agents.values():
        for field in ("grain", "vegetable", "meat", "fish", "cloth", "debt", "stamina", "health"):
            assert getattr(a, field) >= 0.0, f"{a.name}.{field} 为负"
