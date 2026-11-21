"""跨领域影响意图的统一提交入口（契约只路由，结算在领域所有者）。

ADR 009 §2.5/§2.6（2026-11-21 修订）：调用方只决定"哪里、多大"，结算、校验
与事件由状态所有者执行。

- 田块生态状态（``field_growth`` / ``fertility_factor``）：环境域所有者
  ``domains.environment.fields`` 结算——农事长势增量、收获复位、洪涝 / 旱灾 / 滑坡冲减；
- 人类个体健康（野遇）：人文域所有者结算（``domains.society.agents.apply_wildlife_attack``，
  函数内延迟导入以避免人物子系统 ↔ impacts 模块级循环导入）。

契约层不得出现在状态写入者集合（架构测试红线）。
"""
from __future__ import annotations

from vale.domains.environment.fields import (
    apply_drought_damage,
    apply_farm_growth,
    apply_flood_damage,
    apply_landslide,
    ensure_field_states,
    reset_field_growth,
)


class EcologicalImpact:
    """洪涝 / 旱灾 / 滑坡 / 野遇 / 农事对田块生态与个体的统一提交入口。"""

    @staticmethod
    def flood_damage(world, field_node: str, damage: float, *, precipitation_mm: float) -> float:
        """冲减田块长势，返回实际扣减量。"""
        return apply_flood_damage(world, field_node, damage, precipitation_mm=precipitation_mm)

    @staticmethod
    def drought_damage(world, field_node: str, damage: float, *, drought_state: str) -> float:
        """旱灾冲减田块长势，返回实际扣减量。"""
        return apply_drought_damage(world, field_node, damage, drought_state=drought_state)

    @staticmethod
    def landslide(world, field_node: str, *, amount: float, source_node: str,
                  resource_stock_ratio: float) -> float:
        """滑坡扣减田块地力，返回扣减后的地力。"""
        return apply_landslide(
            world, field_node, amount=amount, source_node=source_node,
            resource_stock_ratio=resource_stock_ratio,
        )

    @staticmethod
    def wildlife_attack(world, agent_id: str, damage: float, *, location: str = "") -> bool:
        """野生动物袭击：结算人类个体健康损失，返回是否命中。"""
        # 延迟导入：人物子系统模块级引用本契约（农事意图），避免模块级循环导入。
        from vale.domains.society.agents import apply_wildlife_attack
        return apply_wildlife_attack(world, agent_id, damage, location=location)

    # -- 农事意图（2026-11-21 裁决：田块生态归环境域，意图携带增量）--------- #

    @staticmethod
    def ensure_field_states(world) -> None:
        """田块生态状态引导（环境所有者执行；调用方仅按既有触发时序路由）。"""
        ensure_field_states(world)

    @staticmethod
    def farm_growth(world, field_node: str, delta: float, *,
                    agent_id: str = "", household_id: str = "") -> float:
        """提交农事长势增量意图，环境所有者校验边界并结算，返回结算后长势。"""
        return apply_farm_growth(
            world, field_node, delta, agent_id=agent_id, household_id=household_id,
        )

    @staticmethod
    def harvest_reset(world, field_node: str, *,
                      agent_id: str = "", household_id: str = "") -> float:
        """提交收获复位意图（长势归零），返回复位前长势。"""
        return reset_field_growth(
            world, field_node, agent_id=agent_id, household_id=household_id,
        )
