"""人物配置的 Pydantic Schema（机制层）。

具体数值（生理速率、效用权重、动作消耗）全部由 agents.yaml 提供，
本文件只定义结构与校验，不在代码里写死任何规则参数。
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

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
    rest_stamina_recovery: float = Field(40.0, ge=0)
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
    # action -> {need: fulfill_value}
    fulfill: dict[str, dict[str, float]] = Field(default_factory=dict)
    # action -> flat stamina cost（move 的消耗按 TU 另行计算）
    stamina_cost: dict[str, float] = Field(default_factory=dict)
    # action -> TU 占用
    tu_cost: dict[str, float] = Field(default_factory=dict)
    # 受天气影响的户外动作名
    outdoor: list[str] = Field(default_factory=list)


class AgricultureTuning(BaseModel):
    """农田生长周期（里程碑 2 扩展；任务 11 起作物可配置）。"""

    field_growth_per_farm: float = Field(5.0, ge=0, description="每次 farm 提升的长势")
    max_field_growth: float = Field(100.0, gt=0)
    harvest_growth_threshold: float = Field(80.0, ge=0, description="可秋收的最低长势")
    # 作物名 -> 秋收产出量。作物名同时是 AgentState 的字段名（grain / vegetable / 未来 fruit），
    # 与 spatial 节点上的 crop_type 对齐；新增作物只加配置，不改 harvest 核心结算。
    crop_gain: dict[str, float] = Field(
        default_factory=lambda: {"grain": 30.0}, description="各作物秋收产出量"
    )
    harvest_debt_repayment: float = Field(10.0, ge=0, description="秋收时偿还的债务（石）")

    @model_validator(mode="after")
    def _crop_gain_valid(self) -> "AgricultureTuning":
        if not self.crop_gain:
            raise ValueError("agriculture.crop_gain must not be empty")
        for crop, gain in self.crop_gain.items():
            if gain < 0:
                raise ValueError(f"crop_gain[{crop}] must be >= 0")
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
      agent_incapacitated；失能满 death_grace_ticks 仍未恢复 → 死亡，写一次 agent_died，
      并按 forgive_debt_on_death 核销剩余债务（写 debt_forgiven，可追溯，不静默消失）。
    """

    incapacitation_health_threshold: float = Field(
        0.0, ge=0, le=100, description="health 低于等于此值进入失能"
    )
    death_grace_ticks: int = Field(
        7, ge=0, description="失能后多少 tick 仍未恢复则死亡（0 = 立即死亡）"
    )
    forgive_debt_on_death: bool = Field(
        True, description="死亡时是否核销剩余债务（写 debt_forgiven 事件，可追溯）"
    )


class TimeTuning(BaseModel):
    tu_per_tick: float = Field(10.0, ge=0)
    farm_tu: float = Field(5.0, ge=0)


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
        return self


class TextileTuning(BaseModel):
    """纺织与冬季保暖（任务11）。布是耐用品：达到门槛即免寒冷惩罚，不每日消耗。"""

    cloth_per_weave: float = Field(2.0, ge=0, description="一次成功织布的产量（匹）")
    base_success_rate: float = Field(0.9, ge=0, le=1, description="基础织布成功率")
    season_modifier: dict[str, float] = Field(default_factory=dict, description="季节成功率乘数")
    warmth_cloth_threshold: float = Field(3.0, ge=0, description="冬季御寒所需布量门槛")
    cold_health_loss: float = Field(2.0, ge=0, description="无布御寒时每日健康损失")


class AgentTuning(BaseModel):
    physiology: PhysiologyTuning = Field(default_factory=PhysiologyTuning)
    utility: UtilityTuning = Field(default_factory=UtilityTuning)
    action: ActionTuning = Field(default_factory=ActionTuning)
    agriculture: AgricultureTuning = Field(default_factory=AgricultureTuning)
    borrow: BorrowTuning = Field(default_factory=BorrowTuning)
    debt: DebtTuning = Field(default_factory=DebtTuning)
    health: HealthTuning = Field(default_factory=HealthTuning)
    death: DeathTuning = Field(default_factory=DeathTuning)
    gathering: GatheringTuning = Field(default_factory=GatheringTuning)
    market: MarketTuning = Field(default_factory=MarketTuning)
    textile: TextileTuning = Field(default_factory=TextileTuning)
    time: TimeTuning = Field(default_factory=TimeTuning)


class AgentAssets(BaseModel):
    grain: float = Field(..., ge=0, description="存粮（石）")
    vegetable: float = Field(0.0, ge=0, description="存菜（担）")
    cloth: float = Field(0.0, ge=0, description="存布（匹）")


class AgentConfig(BaseModel):
    id: str
    name: str
    sex: AgentSex
    age: int = Field(..., ge=0)
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
