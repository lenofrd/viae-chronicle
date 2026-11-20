"""灾害与野生动物影响的统一提交入口（P3c：契约只路由，结算在领域所有者）。

ADR 009 §2.6：环境事件影响人类农业或个体时，由契约提交请求、状态所有者校验
并结算，调用方（``modules.xigu_events``）只决定"哪里、多大"。结算归人类域：
``field_growth`` / ``fertility_factor``（农事四字段，ADR §2.3）与人物健康由
``modules.agents`` 的 ``apply_*`` 函数执行。P3b 期间结算曾放在本契约内，P3c
按裁决移交所有者；契约层不得出现在状态写入者集合（架构测试红线）。
"""
from __future__ import annotations

from vale.modules.agents import (
    apply_drought_damage,
    apply_flood_damage,
    apply_landslide,
    apply_wildlife_attack,
)


class EcologicalImpact:
    """洪涝 / 旱灾 / 滑坡 / 野遇的统一提交入口。"""

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
        return apply_wildlife_attack(world, agent_id, damage, location=location)
