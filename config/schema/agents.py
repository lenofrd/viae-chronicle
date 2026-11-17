"""人物配置的 Pydantic Schema（机制层）。

具体数值（生理速率、效用权重、动作消耗）全部由 agents.yaml 提供，
本文件只定义结构与校验，不在代码里写死任何规则参数。
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class AgentSex(str, Enum):
    MALE = "male"
    FEMALE = "female"


class PhysiologyTuning(BaseModel):
    hunger_gain_per_tick: float = Field(15.0, ge=0)
    eat_hunger_reduction: float = Field(60.0, ge=0)
    eat_grain_cost: float = Field(1.0, ge=0)
    # eat 消耗的食物字段优先级（任务09）：粮不足时依次吃后续字段（如 meat）。
    # 未来加渔业只需在此追加 "fish" 并在 AgentState 加字段，eat 代码不变。
    food_fields: list[str] = Field(default_factory=lambda: ["grain"])
    hunger_health_damage_threshold: float = Field(80.0, ge=0, le=100)
    hunger_health_damage: float = Field(8.0, ge=0)
    # 004：rest_stamina_recovery（rest +40）已废弃——rest 动作改为 1 TU 回满（见 ActionTuning）。
    initial_health: float = Field(90.0, ge=0, le=100)
    initial_hunger: float = Field(40.0, ge=0, le=100)
    initial_stamina: float = Field(80.0, ge=0, le=100)
    initial_fatigue: float = Field(0.0, ge=0, le=100)


class UtilityTuning(BaseModel):
    need_weights: dict[str, float] = Field(default_factory=dict)
    economy_urgency_grain_zero: float = Field(1.0, ge=0)
    economy_urgency_grain_positive: float = Field(0.3, ge=0)
    move_stamina_per_tu: float = Field(5.0, ge=0)
    # 打分时体力惩罚的归一化除数：raw_stamina_cost 为 0-100 量级，
    # gross 为 0-3 量级，故除以该值使两者可比（机制修正，非内容数值）。
    stamina_score_divisor: float = Field(100.0, gt=0)
    distance_penalty_per_tu: float = Field(0.15, ge=0)
    rain_outdoor_score_multiplier: float = Field(0.5, ge=0)


class ActionTuning(BaseModel):
    """动作的时间与体力成本（004 裁决：动作 = {TU 时长, 体力速率} 二元组）。

    - 重活（heavy_actions）：按 heavy_stamina_per_tu × tu_cost 结算体力，
      连续纯劳作 4 TU 归零（25/TU）；体力不足移动消耗时不可行，否则可开工、收尾归零。
    - 轻活（不在 heavy_actions 内）：固定体力 0，只占 TU。
    - 移动消耗另按 TU 计（utility.move_stamina_per_tu）。
    - rest：1 TU 回满体力（裁决值，机制常量）；闲时（无可行动作的剩余 TU）同样回满。
    旧 stamina_cost 平表已废弃（004），本结构为唯一来源，不留双源。
    """

    # action -> {need: fulfill_value}
    fulfill: dict[str, dict[str, float]] = Field(default_factory=dict)
    # action -> TU 占用（含 eat/borrow/rest 至少 1 TU，防日内零成本动作无限循环）
    tu_cost: dict[str, float] = Field(default_factory=dict)
    heavy_actions: list[str] = Field(
        default_factory=lambda: ["farm", "harvest", "hunt"],
        description="重活名单：体力按速率 × TU 结算",
    )
    heavy_stamina_per_tu: float = Field(
        25.0, ge=0, description="重活体力速率（连续 4 TU 归零 = 100）"
    )
    # 受天气影响的户外动作名
    outdoor: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _heavy_has_tu(self) -> "ActionTuning":
        for action in self.heavy_actions:
            if action not in self.tu_cost:
                raise ValueError(
                    f"action.heavy_actions[{action}] 缺少 action.tu_cost 条目（重活必须有 TU 时长）"
                )
        return self


class AgricultureTuning(BaseModel):
    """农田生长周期（里程碑 2 扩展；任务 11 起作物可配置）。"""

    field_growth_per_farm: float = Field(5.0, ge=0, description="每次 farm 提升的长势")
    max_field_growth: float = Field(100.0, gt=0)
    harvest_growth_threshold: float = Field(80.0, ge=0, description="可秋收的最低长势")
    # crops.md §4.5 基准产量：expected_yield = base_yield × area × fertility × moisture
    #   × growth_health × (1 − disaster_damage)。作物名同时是家庭库存字段名（grain / vegetable /
    #   未来 fruit），与 spatial 节点上的 crop_type 对齐；新增作物只加配置，不改 harvest 核心结算。
    # 阶段二其余因子取中性值（area=1、fertility=1、moisture=1、growth_health=1、disaster=0），
    # 故产出与既有 crop_gain 逐项相等。
    base_yield: dict[str, float] = Field(
        default_factory=lambda: {"grain": 30.0}, description="各作物基准产量（crops.md §4.5 base_yield）"
    )
    harvest_debt_repayment: float = Field(10.0, ge=0, description="秋收时偿还的债务（石）")

    @model_validator(mode="after")
    def _base_yield_valid(self) -> "AgricultureTuning":
        if not self.base_yield:
            raise ValueError("agriculture.base_yield must not be empty")
        for crop, gain in self.base_yield.items():
            if gain < 0:
                raise ValueError(f"base_yield[{crop}] must be >= 0")
        return self


class BorrowTuning(BaseModel):
    """借粮生存（里程碑 2 扩展，第一版极简）。"""

    borrow_grain_threshold: float = Field(2.0, ge=0, description="存粮低于此值才会触发借粮")
    borrow_grain_amount: float = Field(5.0, ge=0, description="每次借粮数量（石），同时计入等额债务")


class DebtTuning(BaseModel):
    """债务到期与催收节奏（任务 08 新增）。数值全部来自 agents.yaml，代码不写死。"""

    due_days: int = Field(90, ge=1, description="借粮后多少天到期（1 tick = 1 天）")
    collection_interval_days: int = Field(30, ge=1, description="到期后每隔多少天催收一次")
    # 秋收还款上限复用 AgricultureTuning.harvest_debt_repayment（已批准参数），避免双源


class HealthTuning(BaseModel):
    """健康回血（任务 08 新增）。数值全部来自 agents.yaml，代码不写死。"""

    health_recovery_per_day: float = Field(0.5, ge=0, description="每日健康回血速率")
    health_recovery_hunger_threshold: float = Field(
        40.0, ge=0, le=100, description="饥饿低于此值才允许回血"
    )
    health_recovery_stamina_threshold: float = Field(
        50.0, ge=0, le=100, description="体力高于此值才允许回血"
    )


class DeathTuning(BaseModel):
    """死亡与失能生命周期（任务 10 新增）。数值全部来自 agents.yaml，代码不写死。

    - health 触底（<= incapacitation_health_threshold）→ 失能，停止一切主动动作，写一次
      agent_incapacitated；失能满 death_grace_ticks 仍未恢复 → 死亡，写一次 agent_died。
    - 债务核销统一由继承结算完成（debt_written_off）；``forgive_debt_on_death`` 无调用点，
      任务 15 阶段二删除（见 03-debt.md §11）。
    """

    incapacitation_health_threshold: float = Field(
        0.0, ge=0, le=100, description="health 低于等于此值进入失能"
    )
    death_grace_ticks: int = Field(
        7, ge=0, description="失能后多少 tick 仍未恢复则死亡（0 = 立即死亡）"
    )


class LifeStageTuning(BaseModel):
    """单个年龄分段（任务12）：体力/健康上限乘数与劳作许可，全部由配置提供。"""

    name: str
    min_age: int = Field(..., ge=0)
    max_age: Optional[int] = Field(None, ge=0, description="不含上界；None = 无上限")
    stamina_max_mult: float = Field(1.0, gt=0)
    stamina_recovery_mult: float = Field(1.0, gt=0)
    health_max_mult: float = Field(1.0, gt=0)
    work_allowed: bool = Field(True, description="是否允许劳作类候选动作")
    allowed_actions: Optional[list[str]] = Field(
        None,
        description=(
            "劳作动作白名单（任务23）；None=按 work_allowed 放开全部候选动作。"
            "仅对 work_allowed=true 的分段生效，eat/rest 始终保留"
        ),
    )
    injury_risk_mult: float = Field(1.0, ge=0, description="受伤概率乘数")


def _default_life_stages() -> list[LifeStageTuning]:
    return [
        LifeStageTuning(name="幼年", min_age=0, max_age=8, stamina_max_mult=0.4,
                        stamina_recovery_mult=0.8, health_max_mult=0.7,
                        work_allowed=False, injury_risk_mult=0.5),
        LifeStageTuning(name="少年", min_age=8, max_age=12, stamina_max_mult=0.6,
                        stamina_recovery_mult=0.8, health_max_mult=0.7,
                        work_allowed=True, allowed_actions=["farm", "harvest", "weave"],
                        injury_risk_mult=0.5),
        LifeStageTuning(name="青年", min_age=12, max_age=30, stamina_max_mult=1.0,
                        stamina_recovery_mult=1.0, health_max_mult=1.0,
                        work_allowed=True, injury_risk_mult=1.0),
        LifeStageTuning(name="壮年", min_age=30, max_age=50, stamina_max_mult=0.95,
                        stamina_recovery_mult=0.85, health_max_mult=0.95,
                        work_allowed=True, injury_risk_mult=1.0),
        LifeStageTuning(name="老年", min_age=50, max_age=None, stamina_max_mult=0.6,
                        stamina_recovery_mult=0.55, health_max_mult=0.65,
                        work_allowed=True, injury_risk_mult=1.5),
    ]


class AgingTuning(BaseModel):
    """年龄分段、健康上限衰减与自然死亡（任务12，全部 [调参]）。"""

    life_stages: list[LifeStageTuning] = Field(default_factory=_default_life_stages)
    health_cap_decline_start_age: int = Field(50, ge=0)
    health_cap_decline_per_year: float = Field(3.0, ge=0)
    min_health_cap: float = Field(15.0, ge=0, le=100)
    natural_death_min_age: int = Field(55, ge=0)
    natural_death_health_threshold: float = Field(40.0, ge=0, le=100)
    injury_cause_window_days: int = Field(30, ge=0)

    @model_validator(mode="after")
    def _stages_valid(self) -> "AgingTuning":
        stages = self.life_stages
        if not stages:
            raise ValueError("aging.life_stages must not be empty")
        if stages[0].min_age != 0:
            raise ValueError("aging.life_stages must start at min_age=0")
        for prev, cur in zip(stages, stages[1:]):
            if cur.min_age != prev.max_age:
                raise ValueError("aging.life_stages must be contiguous (prev.max_age == cur.min_age)")
        if stages[-1].max_age is not None:
            raise ValueError("aging.life_stages last stage must have max_age=null")
        return self

    def stage_for(self, age: int) -> LifeStageTuning:
        for stage in self.life_stages:
            if stage.max_age is None or age < stage.max_age:
                return stage
        return self.life_stages[-1]

    def stage_by_name(self, name: str) -> Optional[LifeStageTuning]:
        return next((s for s in self.life_stages if s.name == name), None)


class HouseholdTuning(BaseModel):
    """家庭规模与住所（任务12 迁移第2步；分家参数留第3步）。"""

    house_max_members: int = Field(8, ge=2, description="单户成员上限；婚配并入前校验")


class LaborTuning(BaseModel):
    """劳作点分配（阶段二 C，修缺陷、不调参）。

    家庭可分配田块 = 默认田优先，其余按「家→田距离升序、节点 id 升序」；
    户内按可劳作成员序对位接田（未成年/高龄不占劳作位；确定性，禁止随机）。
    """

    allocation_policy: Literal["deterministic_distance"] = Field(
        "deterministic_distance",
        description="田块分配策略；阶段二只有确定性距离一种，非法值启动即报错",
    )


class SplitTuning(BaseModel):
    """分家（任务12 第3步，[调参]）。

    触发：户内人数 ≥ min_members 且存在“丈夫非户主”的已婚成年夫妻。
    新户按 asset_ratio 带走资产/债务，余额留原户。
    """

    min_members: int = Field(4, ge=3, description="可触发分家的最大家庭人数")
    asset_ratio: float = Field(0.5, gt=0, lt=1, description="新户带走的资产/债务比例")
    home_node_candidates: list[str] = Field(
        default_factory=list, description="新户住所候选（按新户 id 稳定轮转）；空则同节点分户"
    )


class MarriageTuning(BaseModel):
    """婚配资格与居所制（任务12，[调参]）。"""

    min_age: int = Field(16, ge=0)
    min_health: float = Field(50.0, ge=0, le=100)
    min_grain: float = Field(20.0, ge=0)
    max_distance_tu: float = Field(3.0, gt=0)
    allow_same_sex: bool = False
    remarriage_allowed: bool = True
    forbid_close_kin: bool = True
    residence: Literal["patrilocal"] = Field(
        "patrilocal", description="居所制；第2步只实现从夫居，其他枚举不实现/启动报错"
    )


class BirthTuning(BaseModel):
    """生育与新生儿（任务12，[调参]）。"""

    min_age_female: int = Field(16, ge=0)
    max_age_female: int = Field(45, ge=0)
    max_age_male: int = Field(60, ge=0)
    min_health: float = Field(50.0, ge=0, le=100)
    interval_days: int = Field(360, ge=1)
    chance_per_day: float = Field(0.02, ge=0, le=1)
    max_population: int = Field(12, ge=1)
    low_population_adults: int = Field(2, ge=0)
    low_population_fertility_boost: float = Field(2.0, ge=1)
    male_ratio: float = Field(0.5, ge=0, le=1)
    newborn_health_parent_ratio: float = Field(0.8, ge=0)
    newborn_stamina_parent_ratio: float = Field(0.8, ge=0)
    newborn_min_health: float = Field(30.0, ge=0, le=100)
    newborn_min_stamina: float = Field(20.0, ge=0, le=100)
    initial_hunger: float = Field(40.0, ge=0, le=100)
    home_node_from: str = "mother"
    work_node_from: str = "mother"
    surname_from: str = "father"
    given_names: list[str] = Field(
        default_factory=lambda: ["阿福", "阿寿", "小满", "春生", "秋生", "冬生"]
    )
    default_surname: str = "某"
    name_fallback_suffix: str = "{name}{n}"
    asset_transfer_ratio: float = Field(0.1, ge=0, le=1, description="出生时父母各转移的存量比例")
    # 阶段二 B：出生前校验户容量。原值 false = 旧行为（出生不看容量）；新值 true = 超限跳过本次生育。
    # 理由：诊断显示最大户 10–11 人、超容 tick 占 3%–30%，出生路径完全绕过 house_max_members。
    # 影响：只压需求峰值，不自动分家；婚配容量（Q6）语义不变。
    respect_house_capacity: bool = Field(
        True, description="出生前校验 len(member_ids)+1 <= house_max_members；超限跳过本次生育"
    )
    # 阶段二 §3.0「有设计」分支：01-physical-state.md §4.4 普通分娩 health −10。
    # 难产（−40 + 死亡风险）设计未给概率，孕期体力限制依赖未实现的 pregnancy_stage，均登记缺口。
    mother_health_cost: float = Field(
        10.0, ge=0, le=100, description="分娩健康代价（设计值 −10；难产分支待设计）"
    )

    @model_validator(mode="after")
    def _birth_valid(self) -> "BirthTuning":
        if not self.given_names:
            raise ValueError("birth.given_names must not be empty")
        if self.max_age_female < self.min_age_female:
            raise ValueError("birth.max_age_female must be >= min_age_female")
        if self.home_node_from not in ("mother", "father"):
            raise ValueError("birth.home_node_from must be mother|father")
        if self.work_node_from not in ("mother", "father"):
            raise ValueError("birth.work_node_from must be mother|father")
        if self.surname_from not in ("mother", "father"):
            raise ValueError("birth.surname_from must be mother|father")
        return self


class InheritanceTuning(BaseModel):
    """继承顺位与比例（任务12，[调参]）。"""

    asset_ratio: float = Field(1.0, ge=0, le=1)
    debt_ratio: float = Field(0.5, ge=0, le=1)
    priority: list[str] = Field(default_factory=lambda: ["spouse", "children", "parents"])
    escheat: bool = True

    @model_validator(mode="after")
    def _priority_valid(self) -> "InheritanceTuning":
        if not self.priority:
            raise ValueError("inheritance.priority must not be empty")
        allowed = {"spouse", "children", "parents"}
        bad = [p for p in self.priority if p not in allowed]
        if bad:
            raise ValueError(f"inheritance.priority has invalid entries: {bad}")
        return self


class DependencyTuning(BaseModel):
    """依赖者进食（任务12，[调参]）。"""

    max_age: int = Field(16, ge=0)
    feed_from_parent: bool = True


class ConsumptionTuning(BaseModel):
    """食物消费端系数（阶段三第2轮，[调参]）。

    只作用于 ``eat`` 的库存扣减量：未成年人单次进食按 ``minor_food_share`` 扣减，
    成年恒为 1.0；饥饿降低量、动作评分与效用公式均不变。
    """

    minor_food_share: float = Field(
        0.7, ge=0, le=1, description="未成年人单次进食的库存消耗系数（1.0 = 与成年同量）"
    )


class GatheringActionTuning(BaseModel):
    """单个采集类动作（打猎/未来捕鱼）的配置（任务09）。

    机制层只定义结构；具体数值（成功率、产出、风险、季节修正）来自 agents.yaml。
    新增第二生计只需在 agents.yaml 的 gathering.actions 下加一项 + AgentState 加产出字段，
    核心结算（_score / _execute 的通用采集分支）不改。
    """

    target_node: str = Field(..., description="采集目标空间节点 id（如 low_mountain）")
    output_field: str = Field(..., description="产出写入 AgentState 的字段名（如 meat）")
    base_success_rate: float = Field(0.5, ge=0, le=1, description="基础成功率")
    output_amount: float = Field(4.0, ge=0, description="成功产出量")
    injury_risk: float = Field(0.1, ge=0, le=1, description="每次采集的受伤概率")
    injury_health_loss: float = Field(15.0, ge=0, le=100, description="受伤健康损失")
    # 季节 -> 成功率乘数；未列出的季节取 1.0
    season_modifier: dict[str, float] = Field(default_factory=dict)
    bad_weather_success_mult: float = Field(0.5, ge=0, description="坏天气成功率乘数")
    bad_weather_injury_mult: float = Field(2.0, ge=0, description="坏天气受伤概率乘数")


class GatheringTuning(BaseModel):
    """采集类生计集合（任务09）：action_name -> 配置。代码不写死具体动作名。"""

    actions: dict[str, GatheringActionTuning] = Field(default_factory=dict)


class MarketCreditTuning(BaseModel):
    """集市赊账（任务15 阶段二，全部 [调参]）。

    仅集市日、仅 ``eligible_items`` 内物品；零利息；当期交粮、到期还粮。
    单户未清偿赊账总额 ≤ ``max_per_household``，已有赊账逾期未清时不新增（防雪球）。
    阈值按物品统一取值（首切片只有 grain，与裁决 §3.3 一致）。
    """

    enabled: bool = Field(True, description="是否开启集市赊账")
    eligible_items: list[str] = Field(
        default_factory=lambda: ["grain"], description="可赊账物品（须在 market.trade_values 内）"
    )
    max_per_household: float = Field(
        10.0, ge=0, description="单户未清偿赊账总额上限"
    )
    due_days: int = Field(60, ge=1, description="赊账到期天数（1 tick = 1 天）")
    min_surplus: float = Field(10.0, ge=0, description="卖方至少余此库存才可赊出")
    min_shortage: float = Field(5.0, ge=0, description="买方库存低于此值才可赊入")

    @model_validator(mode="after")
    def _credit_valid(self) -> "MarketCreditTuning":
        if not self.eligible_items:
            raise ValueError("market.credit.eligible_items must not be empty")
        if self.min_shortage >= self.min_surplus:
            raise ValueError("market.credit.min_shortage must be < min_surplus")
        return self


class DebtDisputeTuning(BaseModel):
    """债务纠纷 2 轮私下催收（任务15 阶段二，除 max_rounds 外均为 [调参]）。

    ``max_rounds`` 固定为 2（裁决：不做通用会话框架、不悬置），非法值启动即报错。
    """

    trigger_overdue_days: int = Field(
        30, ge=0, description="赊账逾期满多少天且存粮处于「有粮赖账」窗口时触发催收会话"
    )
    trigger_max_grain: float = Field(
        5.0, ge=0, description="有粮上限：refusal_threshold < 存粮 ≤ 此值才进催收会话（阶段三语义修正）"
    )
    max_rounds: Literal[2] = Field(2, description="固定 2 轮：债权人提诉求 → 债务人回应")
    partial_ratio: float = Field(0.5, gt=0, le=1, description="部分还款比例")
    deferral_days: int = Field(60, ge=1, description="延期天数")
    refusal_threshold: float = Field(
        2.0, ge=0, description="债务家庭库存不高于此值时拒绝（阶段三第1轮 0→2）"
    )

    @model_validator(mode="after")
    def _window_valid(self) -> "DebtDisputeTuning":
        if self.refusal_threshold >= self.trigger_max_grain:
            raise ValueError(
                "conflict.debt_dispute.refusal_threshold must be < trigger_max_grain"
            )
        return self


class ConflictTuning(BaseModel):
    """冲突系统配置（任务15 阶段二只实现债务纠纷）。"""

    debt_dispute: DebtDisputeTuning = Field(default_factory=DebtDisputeTuning)


class MarketTuning(BaseModel):
    """赶集交易（任务11）：集市日结算、以物易物、固定相对价格。

    撮合不是在动作层抢效用分，而是在每日结算阶段统一处理；物品集合由 ``trade_values``
    的键决定（v1：grain / vegetable / meat / fish / cloth）。坏配置在启动时直接报错。
    """

    market_node: str = Field("market", description="集市空间节点 id")
    market_day_interval: int = Field(10, ge=1, description="每多少天一次集市")
    market_day_offset: int = Field(0, ge=0, description="集市日偏移（tick % interval == offset）")
    market_min_stamina: float = Field(
        15.0, ge=0, le=100, description="扣完往返赶路体力后仍需保留的最低体力"
    )
    market_max_distance_tu: float = Field(
        3.0, gt=0, description="可赴集的单程上限（TU），排除深山/远山类"
    )
    trade_values: dict[str, float] = Field(default_factory=dict, description="物品相对价值")
    surplus_threshold: dict[str, float] = Field(default_factory=dict, description="富余阈值")
    deficit_threshold: dict[str, float] = Field(default_factory=dict, description="短缺阈值")
    max_trade_units: float = Field(10.0, gt=0, description="单次成交的 give 侧上限")
    trade_unit_step: float = Field(0.5, gt=0, description="成交量的最小步长")
    trade_value_tolerance: float = Field(
        0.2, ge=0, le=1, description="交换价值相对误差容忍度"
    )
    # 任务15 阶段二：集市赊账（非断粮型债务来源，见 conflicts/03-debt-disputes）
    credit: MarketCreditTuning = Field(default_factory=MarketCreditTuning)

    @model_validator(mode="after")
    def _validate_rules(self) -> "MarketTuning":
        if self.market_day_offset >= self.market_day_interval:
            raise ValueError("market_day_offset must be < market_day_interval")
        if not self.trade_values:
            raise ValueError("market.trade_values must not be empty")
        for item, value in self.trade_values.items():
            if value <= 0:
                raise ValueError(f"trade_values[{item}] must be > 0")
            if item not in self.surplus_threshold:
                raise ValueError(f"missing surplus_threshold[{item}]")
            if item not in self.deficit_threshold:
                raise ValueError(f"missing deficit_threshold[{item}]")
            if self.deficit_threshold[item] >= self.surplus_threshold[item]:
                raise ValueError(
                    f"threshold inverted for {item}: deficit >= surplus"
                )
        for item in self.credit.eligible_items:
            if item not in self.trade_values:
                raise ValueError(f"market.credit.eligible_items[{item}] not in trade_values")
        return self


class TextileTuning(BaseModel):
    """纺织与冬季保暖（任务11）。布是耐用品：达到门槛即免寒冷惩罚，不每日消耗。"""

    cloth_per_weave: float = Field(2.0, ge=0, description="一次成功织布的产量（匹）")
    base_success_rate: float = Field(0.9, ge=0, le=1, description="基础织布成功率")
    season_modifier: dict[str, float] = Field(default_factory=dict, description="季节成功率乘数")
    warmth_cloth_threshold: float = Field(3.0, ge=0, description="冬季御寒所需布量门槛")
    cold_health_loss: float = Field(2.0, ge=0, description="无布御寒时每日健康损失")


class SocialTuning(BaseModel):
    """社会认知与关系层参数（任务 16 阶段二）。

    临时初值，待长期方案复核（裁决 §四）。
    """

    memory_capacity: int = Field(5, ge=1, description="每人短期记忆环形缓冲容量")
    acquaintance_ttl: int = Field(360, ge=1, description="认知遗忘阈值（tick）；now-last_seen_tick 超过则遗忘")
    cleanup_interval: int = Field(360, ge=1, description="低频遗忘清理周期（tick）")
    # 任务 18 P1：印象合成读取的最近交互窗口（与记忆容量对齐；临时值待复核，本任务不调）
    impression_window: int = Field(
        5, ge=1, description="印象合成读取的最近 K 条债争记忆窗口"
    )
    # 任务 25 P2：印象是否参与债争诉求决策（独立开关，默认关闭 = 行为与 P1 完全一致）
    impression_in_decision: bool = Field(
        False, description="是否让印象档位参与债争诉求决策（关闭时零行为变化）"
    )


class WaterTuning(BaseModel):
    """生活用水最小切片（004 §2.7，任务 30）。

    水有两个去处：每日生活消耗（按成员数）与烹饪/佐餐（每次进食）。
    不建模饮水对健康的影响；产量、日耗、每餐用水均为 [调参]。
    """

    collect_amount: float = Field(5.0, ge=0, description="每次 collect_water 的产水量")
    daily_consumption_per_member: float = Field(
        1.0, ge=0, description="每名存活成员每日耗水（家庭结算时扣减）"
    )
    water_per_meal: float = Field(
        0.5, ge=0, description="每次进食所需用水（烹饪/佐餐）；水不足则该次无法进食"
    )
    household_stock_target: float = Field(
        5.0, ge=0, description="家庭存水目标；低于此值时 collect_water 紧迫度线性上升"
    )
    scarcity_weight: float = Field(
        2.0, ge=0, description="打水紧迫度权重（缺水时加到 collect_water 的毛效用上）"
    )


class AgentTuning(BaseModel):
    physiology: PhysiologyTuning = Field(default_factory=PhysiologyTuning)
    utility: UtilityTuning = Field(default_factory=UtilityTuning)
    action: ActionTuning = Field(default_factory=ActionTuning)
    water: WaterTuning = Field(default_factory=WaterTuning)
    agriculture: AgricultureTuning = Field(default_factory=AgricultureTuning)
    borrow: BorrowTuning = Field(default_factory=BorrowTuning)
    debt: DebtTuning = Field(default_factory=DebtTuning)
    health: HealthTuning = Field(default_factory=HealthTuning)
    death: DeathTuning = Field(default_factory=DeathTuning)
    gathering: GatheringTuning = Field(default_factory=GatheringTuning)
    market: MarketTuning = Field(default_factory=MarketTuning)
    # 任务15 阶段二：债务纠纷（2 轮私下催收），其余冲突类型仍在设计层
    conflict: ConflictTuning = Field(default_factory=ConflictTuning)
    textile: TextileTuning = Field(default_factory=TextileTuning)
    aging: AgingTuning = Field(default_factory=AgingTuning)
    marriage: MarriageTuning = Field(default_factory=MarriageTuning)
    birth: BirthTuning = Field(default_factory=BirthTuning)
    inheritance: InheritanceTuning = Field(default_factory=InheritanceTuning)
    dependency: DependencyTuning = Field(default_factory=DependencyTuning)
    consumption: ConsumptionTuning = Field(default_factory=ConsumptionTuning)
    household: HouseholdTuning = Field(default_factory=HouseholdTuning)
    labor: LaborTuning = Field(default_factory=LaborTuning)
    split: SplitTuning = Field(default_factory=SplitTuning)
    # 004：TimeTuning（tu_per_tick/farm_tu 死配置）已删除——工作窗在
    # natural-params 的 seasons.*.work_window_tu，动作 TU 在 action.tu_cost。
    # 任务16 阶段二：社会认知与关系层（临时初值，待长期方案复核）
    social: SocialTuning = Field(default_factory=SocialTuning)


class AgentAssets(BaseModel):
    grain: float = Field(..., ge=0, description="存粮（石）")
    vegetable: float = Field(0.0, ge=0, description="存菜（担）")
    cloth: float = Field(0.0, ge=0, description="存布（匹）")


class AgentConfig(BaseModel):
    id: str
    name: str
    sex: AgentSex
    age: int = Field(..., ge=0, description="开局年龄；运行时以 birth_tick 为唯一真相源")
    surname: Optional[str] = Field(None, description="姓氏（任务12：子代取名用）")
    home_node: str
    work_node: str
    assets: AgentAssets
    # 留空则采用 tuning.physiology 的全局初始值
    initial_health: Optional[float] = Field(None, ge=0, le=100)
    initial_hunger: Optional[float] = Field(None, ge=0, le=100)
    initial_stamina: Optional[float] = Field(None, ge=0, le=100)


class AgentsConfig(BaseModel):
    tuning: AgentTuning = Field(default_factory=AgentTuning)
    agents: list[AgentConfig] = Field(..., min_length=1)
