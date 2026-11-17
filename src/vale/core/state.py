"""世界状态模型：跨模块共享的结构化快照。

不允许模块往裸 dict 里乱塞。每个子系统的快照在此定义字段结构，
后续模块（水文、植被等）必须按对应结构读取。
气候快照的取值枚举复用 config.schema.natural_params，保持单一真相源。
"""
from __future__ import annotations

from enum import IntEnum
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
    """单笔粮食债务记录（任务 08 / 家庭模型迁移第 1 步）。

    事件溯源投影：债务的创建/变更/清偿都先写事件，再由此结构镜像。
    经济单位是家庭：借贷双方均为 household_id（事件流保留旧 agent 键兼容）。
    「总负债」由 HouseholdState.debt 派生求和，本结构是唯一真相源。
    """

    debtor_household_id: str
    creditor_household_id: str
    amount: float = Field(..., ge=0)
    originated_tick: int = Field(..., ge=0)
    due_tick: int = Field(..., ge=0)
    last_collected_tick: Optional[int] = Field(default=None, ge=0)
    overdue: bool = False
    # 任务15 阶段二：债务来源（None = 旧借粮；"market_credit" = 集市赊账）。
    # 只有赊账走 2 轮私下催收；借粮逻辑保持不变。
    origin: Optional[str] = Field(default=None)
    # 该笔债务是否已发起过催收会话；拒绝后不再重复发起（延期时清零，进入下一周期）
    dispute_started_tick: Optional[int] = Field(default=None, ge=0)


class HouseholdState(BaseModel):
    """家庭经济单位（任务 12 家庭模型迁移第 1 步）。

    资产、债务、住所、默认工作节点归家庭；单人家庭 = 旧个人账户语义。
    成员、户主为投影字段；家庭行为（合并/分家/接任）不在第 1 步实现。
    """

    household_id: str
    member_ids: list[str] = Field(default_factory=list)
    head_id: Optional[str] = None
    guardian_id: Optional[str] = Field(default=None, description="Q7 预留，本任务不实现外部监护")
    grain: float = Field(default=0.0, ge=0)
    meat: float = Field(default=0.0, ge=0)
    fish: float = Field(default=0.0, ge=0)
    vegetable: float = Field(default=0.0, ge=0)
    cloth: float = Field(default=0.0, ge=0)
    # 任务30：生活用水（水缸存量）；collect_water 产水，每日按成员数扣减
    water: float = Field(default=0.0, ge=0)
    debts: list[DebtRecord] = Field(default_factory=list)
    home_node: str
    work_node: str
    # 阶段二 C：家庭可分配田块（默认田优先，其余按距离/id 确定性排序；空 = 沿用 work_node）。
    # 户内按可劳作成员序对位接田（未成年/高龄不占劳作位），见 vale.core.household.work_node_of。
    work_nodes: list[str] = Field(default_factory=list)
    formed_tick: int = Field(..., ge=0)

    @computed_field  # type: ignore[misc]
    @property
    def debt(self) -> float:
        """总负债 = 各笔债务金额之和（派生值，只读；不可直接赋值）。"""
        return float(sum(d.amount for d in self.debts))


class AcquaintanceLevel(IntEnum):
    """认知级别（任务 16 阶段二）。两级切片，留五级扩展。

    比较一律用 ``>=``（如 ``level >= AcquaintanceLevel.KNOWN``），未来插入
    MET_AND_NAMED / CLOSE 等中间级别时，调用方比较逻辑不改。
    """

    UNKNOWN = 0  # 不知道
    MET = 1      # 记得样貌，可能不知名（本轮预留，交互即升 KNOWN，暂不产出 MET）
    KNOWN = 2    # 知道名字且对得上


class AcquaintanceEntry(BaseModel):
    """观察者对单个目标的认知条目（任务 16 阶段二）。

    ``level`` 用 int 存（值取自 AcquaintanceLevel），保证 JSON 序列化/反序列化
    无歧义；``last_seen_tick`` 供 TTL 遗忘判定。
    """

    level: int = Field(default=0, ge=0)
    last_seen_tick: int = Field(default=0, ge=0)


class MemoryEntry(BaseModel):
    """短期交互记忆条目（任务 16 阶段二）。

    容量 N 环形缓冲的元素；纯由现有事件投影，可由事件重建（裁决 §3.4）。
    """

    tick: int = Field(..., ge=0)
    target_id: str
    event_type: str
    outcome: Optional[str] = None


class ImpressionEntry(BaseModel):
    """观察者对单个目标的印象条目（任务 18 P1）。

    独立载体，不并入 ``AcquaintanceEntry``（避免被认知 TTL 连带删除）。
    counts 全部由记忆窗口派生（裁决 §3.5），不是独立累加计数器；
    ``label`` 由确定性规则从 counts 派生，规则为 ``vale.modules.social`` 内代码常量。
    """

    label: str = "unknown"
    contracts: int = Field(default=0, ge=0)
    defaults: int = Field(default=0, ge=0)
    repays: int = Field(default=0, ge=0)
    last_outcome: Optional[str] = None
    last_tick: int = Field(default=0, ge=0)


class AgentState(BaseModel):
    """单个人物的状态快照，写入 world.state.agents[agent_id]。

    年龄唯一真相源是 ``birth_tick``（允许负值：开局前出生），不存 ``age`` 字段，
    避免与 tick 双写漂移；年龄由 ``vale.modules.agents.age_years`` 实时派生。
    资产/债务/住所归家庭；``work_node`` 仅保存个人劳作点偏好（None = 家庭默认）。
    """

    agent_id: str
    name: str
    surname: str = ""
    sex: AgentSex
    birth_tick: int
    household_id: str
    location: str
    work_node: Optional[str] = Field(default=None, description="个人劳作点偏好；None 取家庭默认")
    health: float = Field(..., ge=0, le=100)
    hunger: float = Field(..., ge=0, le=100)
    stamina: float = Field(..., ge=0, le=100)
    fatigue: float = Field(default=0.0, ge=0, le=100)
    last_action: Optional[str] = None
    recent_actions: list[str] = Field(default_factory=list)
    # 生命状态（任务10）：alive=False 表示已死亡；incapacitated=True 表示失能（health 触底，
    # 停止一切主动动作，等待死亡宽限期满或不再发生）。状态变更各写一次事件，不重复刷。
    alive: bool = True
    incapacitated: bool = False
    incapacitated_tick: Optional[int] = Field(default=None, ge=0)
    died_tick: Optional[int] = Field(default=None, ge=0)
    # -- 生命历程与代际（任务12） ------------------------------------------- #
    life_stage: str = Field(default="", description="年龄分段名；由 birth_tick 重算的只读投影")
    spouse_id: Optional[str] = None  # 配偶死亡后保留原 id，用于判断鳏寡与再婚
    married_tick: Optional[int] = Field(default=None, ge=0)
    mother_id: Optional[str] = None
    father_id: Optional[str] = None
    children_ids: list[str] = Field(default_factory=list)
    last_birth_tick: Optional[int] = Field(default=None, ge=0)
    death_cause: Optional[str] = None  # starvation / aging / injury / illness
    last_injury_tick: Optional[int] = Field(default=None, ge=0)

    # ---- 任务 16 阶段二：社会认知与关系层（快照投影，可由事件重建）----
    # 认知：观察者侧 dict，key=target_id；同户/亲缘默认 known，交互升级 known，TTL 遗忘。
    acquaintances: dict[str, AcquaintanceEntry] = Field(default_factory=dict)
    # 记忆：容量 N 环形缓冲（N 见 SocialTuning.memory_capacity）；满了淘汰最旧，不写衰减事件。
    recent_interactions: list[MemoryEntry] = Field(default_factory=list)
    # 印象（任务 18 P1）：观察者侧 dict，key=target_id；counts 只由记忆窗口派生，
    # 仅在 label 变化时写 impression_formed / impression_changed 事件。
    impressions: dict[str, ImpressionEntry] = Field(default_factory=dict)


class WorldState(BaseModel):
    """跨模块共享状态。climate 由气候模块写入，其余子系统后续扩展。"""

    climate: Optional[ClimateSnapshot] = None
    # 任务30：水文单点状态（004 §2.7）。水位比例 0–1（1 = 基准）；
    # 灌溉档取 abundant/low/scarce/dry，由 ClimateModule 按配置阈值派生。
    water_level_ratio: float = Field(default=0.6, ge=0, le=1)
    irrigation_gear: str = Field(default="low")
    agents: dict[str, AgentState] = Field(default_factory=dict)
    households: dict[str, HouseholdState] = Field(default_factory=dict)
    # 田地长势：node_id -> 0-100；由 AgentModule 为 FIELD 节点初始化为 0
    field_growth: dict[str, float] = Field(default_factory=dict)
    # 田块地力（crops.md §4.5 fertility）：node_id -> 乘数；阶段二恒 1.0，衰减/恢复未启用
    field_fertility: dict[str, float] = Field(default_factory=dict)
