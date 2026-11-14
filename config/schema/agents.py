"""人物配置的 Pydantic Schema（机制层）。

具体数值（生理速率、效用权重、动作消耗）全部由 agents.yaml 提供，
本文件只定义结构与校验，不在代码里写死任何规则参数。
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AgentSex(str, Enum):
    MALE = "male"
    FEMALE = "female"


class PhysiologyTuning(BaseModel):
    hunger_gain_per_tick: float = Field(15.0, ge=0)
    eat_hunger_reduction: float = Field(60.0, ge=0)
    eat_grain_cost: float = Field(1.0, ge=0)
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
    """农田生长周期（里程碑 2 扩展）。"""

    field_growth_per_farm: float = Field(5.0, ge=0, description="每次 farm 提升的长势")
    max_field_growth: float = Field(100.0, gt=0)
    harvest_growth_threshold: float = Field(80.0, ge=0, description="可秋收的最低长势")
    harvest_grain_gain: float = Field(30.0, ge=0, description="秋收获得的存粮（石）")
    harvest_debt_repayment: float = Field(10.0, ge=0, description="秋收时偿还的债务（石）")


class BorrowTuning(BaseModel):
    """借粮生存（里程碑 2 扩展，第一版极简）。"""

    borrow_grain_threshold: float = Field(2.0, ge=0, description="存粮低于此值才会触发借粮")
    borrow_grain_amount: float = Field(5.0, ge=0, description="每次借粮数量（石），同时计入等额债务")


class TimeTuning(BaseModel):
    tu_per_tick: float = Field(10.0, ge=0)
    farm_tu: float = Field(5.0, ge=0)


class AgentTuning(BaseModel):
    physiology: PhysiologyTuning = Field(default_factory=PhysiologyTuning)
    utility: UtilityTuning = Field(default_factory=UtilityTuning)
    action: ActionTuning = Field(default_factory=ActionTuning)
    agriculture: AgricultureTuning = Field(default_factory=AgricultureTuning)
    borrow: BorrowTuning = Field(default_factory=BorrowTuning)
    time: TimeTuning = Field(default_factory=TimeTuning)


class AgentAssets(BaseModel):
    grain: float = Field(..., ge=0, description="存粮（石）")


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
