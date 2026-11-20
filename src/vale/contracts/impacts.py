"""灾害与野生动物影响的环境域写入契约（P3b，EcologicalImpact）。

ADR 009 §2.6：环境事件影响人类农业或个体时，由契约提交、状态所有者校验并结算，
调用方（``modules.xigu_events``）只决定"哪里、多大"，不再直接改写：
- ``field_growth`` / ``fertility_factor``：农事四字段按 ADR §2.3 归人类农业管理，
  契约是环境侧的唯一合法写入口；
- ``agents``：野生动物袭击由契约结算健康损失，人类模块不再被环境模块直接写。

结算规则：请求量先夹到当前值，再更新投影；每次变化先写事件（payload 与 P3b 前一致）。
"""
from __future__ import annotations


class EcologicalImpact:
    """洪涝 / 旱灾 / 滑坡 / 野遇的统一结算入口。"""

    @staticmethod
    def flood_damage(world, field_node: str, damage: float, *, precipitation_mm: float) -> float:
        """冲减田块长势，返回实际扣减量。"""
        growth = world.state.environment.field_growth
        before = float(growth.get(field_node, 0.0))
        actual = min(before, max(0.0, float(damage)))
        if actual <= 0:
            return 0.0
        after = round(max(0.0, before - actual), 4)
        growth[field_node] = after
        world.event_log.append(world.current_tick, "field_flood_damage", {
            "field_node": field_node, "before": round(before, 4),
            "damage": round(actual, 4), "after": after,
            "precipitation_mm": precipitation_mm,
        })
        return actual

    @staticmethod
    def drought_damage(world, field_node: str, damage: float, *, drought_state: str) -> float:
        """旱灾冲减田块长势，返回实际扣减量。"""
        growth = world.state.environment.field_growth
        before = float(growth.get(field_node, 0.0))
        actual = min(before, max(0.0, float(damage)))
        if actual <= 0:
            return 0.0
        after = round(max(0.0, before - actual), 4)
        growth[field_node] = after
        world.event_log.append(world.current_tick, "field_drought_damage", {
            "field_node": field_node, "before": round(before, 4),
            "damage": round(actual, 4), "after": after,
            "drought_state": drought_state,
        })
        return actual

    @staticmethod
    def landslide(world, field_node: str, *, amount: float, source_node: str,
                  resource_stock_ratio: float) -> float:
        """滑坡扣减田块地力，返回扣减后的地力。"""
        factors = world.state.environment.fertility_factor
        before = float(factors.get(field_node, 1.0))
        after = round(max(.1, before - max(0.0, float(amount))), 4)
        factors[field_node] = after
        world.event_log.append(world.current_tick, "landslide_damage", {
            "source_node": source_node, "field_node": field_node,
            "fertility_before": before, "fertility_after": after,
            "resource_stock_ratio": round(resource_stock_ratio, 4),
        })
        return after

    @staticmethod
    def wildlife_attack(world, agent_id: str, damage: float, *, location: str = "") -> bool:
        """野生动物袭击：结算人类个体健康损失，返回是否命中。"""
        agent = world.state.human.agents.get(agent_id)
        if agent is None or not agent.alive:
            return False
        before = agent.health
        agent.health = max(0.0, before - float(damage))
        agent.last_injury_tick = world.current_tick
        world.event_log.append(world.current_tick, "wildlife_attack", {
            "agent_id": agent.agent_id, "agent_name": agent.name,
            "health_before": round(before, 2), "health_after": round(agent.health, 2),
            "location": location, "injury": float(damage),
        })
        return True
