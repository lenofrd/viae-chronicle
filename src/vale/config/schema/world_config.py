"""世界元信息的 Pydantic Schema。"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


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
