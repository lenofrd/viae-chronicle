"""世界元信息的 Pydantic Schema。"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from vale.config.schema.ecology_seed import EcologySeedConfig
from vale.config.schema.environment_seed import EnvironmentSeedConfig


class WorldStatus(str, Enum):
    ACTIVE = "active"
    FROZEN = "frozen"
    ARCHIVED = "archived"


class WorldConfig(BaseModel):
    world_id: str
    name: str
    status: WorldStatus = WorldStatus.ACTIVE
    start_tick: int = Field(0, ge=0)
    start_year: int = Field(1, ge=1, description="开局年份（用于日历换算）")
    enabled_subsystems: list[str] = Field(default_factory=list)
    # ADR 011 · P0：可选的 Environment Seed 冻结契约（外部数据包静态契约）。
    # 缺省 = 该世界不接外部地理数据；配置存在但结构非法时加载即报错。
    environment_seed: EnvironmentSeedConfig | None = None
    # EX-0（2026-11-26 裁决）：可选的 Ecology Seed 冻结契约（生态/群落数据线）。
    # 与 environment_seed 共用缓存根、包目录隔离；只冻结契约与静态校验，
    # E3/E4/E5 运行时消费暂缓。
    ecology_seed: EcologySeedConfig | None = None
