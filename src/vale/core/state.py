"""世界状态模型：跨模块共享的结构化快照。

不允许模块往裸 dict 里乱塞。每个子系统的快照在此定义字段结构，
后续模块（水文、植被等）必须按对应结构读取。
气候快照的取值枚举复用 config.schema.natural_params，保持单一真相源。
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, computed_field

from config.schema.agents import AgentSex
from config.schema.natural_params import (
    DroughtState,
    FloodState,
    Season,
    WeatherType,
)


class ClimateSnapshot(BaseModel):
    """单个 Tick 的气候快照，写入 world.state.climate。

    年/月/日/节气由绝对 tick 换算（见 vale.core.calendar），季节也由月份派生，
    保证「日期」与「季节」是同一真相源，互不漂移。
    """

    season: Season
    season_progress: float = Field(..., ge=0, le=1)
    year: int = Field(..., ge=1)
    month: int = Field(..., ge=1, le=12)
    day: int = Field(..., ge=1, le=30)
    solar_term: str
    current_weather: WeatherType
    temperature_c: float
    precipitation_mm: float = 0.0
    humidity_pct: float
    wind_level: float = 0.0
    drought_state: DroughtState = DroughtState.NONE
    drought_accumulation: float = 0.0
    flood_state: FloodState = FloodState.NONE
    flood_accumulation: float = 0.0
    days_no_soaking_rain: int = 0
    weather_trend: list[str] = Field(default_factory=list)


class DebtRecord(BaseModel):
    """单笔粮食债务记录（任务 08）。

    事件溯源投影：债务的创建/变更/清偿都先写事件，再由此结构镜像。
    「总负债」由 AgentState.debt 派生求和（computed_field），本结构是唯一真相源，避免双写不一致。
    """

    creditor_id: str
    amount: float = Field(..., ge=0)
    originated_tick: int = Field(..., ge=0)
    due_tick: int = Field(..., ge=0)
    last_collected_tick: Optional[int] = Field(default=None, ge=0)
    overdue: bool = False


class AgentState(BaseModel):
    """单个人物的状态快照，写入 world.state.agents[agent_id]。"""

    agent_id: str
    name: str
    sex: AgentSex
    age: int
    location: str
    home_node: str
    work_node: str
    health: float = Field(..., ge=0, le=100)
    hunger: float = Field(..., ge=0, le=100)
    stamina: float = Field(..., ge=0, le=100)
    fatigue: float = Field(default=0.0, ge=0, le=100)
    grain: float = Field(default=0.0, ge=0)
    # 债务列表为唯一真相源；debt 为派生聚合（见下方 computed_field）
    debts: list[DebtRecord] = Field(default_factory=list)
    last_action: Optional[str] = None
    recent_actions: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[misc]
    @property
    def debt(self) -> float:
        """总负债 = 各笔债务金额之和（派生值，只读；不可直接赋值）。"""
        return float(sum(d.amount for d in self.debts))


class WorldState(BaseModel):
    """跨模块共享状态。climate 由气候模块写入，其余子系统后续扩展。"""

    climate: Optional[ClimateSnapshot] = None
    agents: dict[str, AgentState] = Field(default_factory=dict)
    # 田地长势：node_id -> 0-100；由 AgentModule 为 FIELD 节点初始化为 0
    field_growth: dict[str, float] = Field(default_factory=dict)
