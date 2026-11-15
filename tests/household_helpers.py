"""测试用家庭访问 helper（任务 12 家庭模型迁移第 1 步）。

经济单位已从 Agent 迁到 Household；测试通过这里读写家庭资产，避免逐处散落 household_id 查找。
"""
from __future__ import annotations

from vale.core.household import (
    home_node_of,
    household_of,
    inventory_of,
    work_node_of,
)

ITEMS = ("grain", "meat", "fish", "vegetable", "cloth")


def hh(world, agent):
    """agent 所属家庭。"""
    return household_of(world, agent)


def inv(world, agent) -> dict[str, float]:
    """家庭库存快照。"""
    return inventory_of(world, agent, list(ITEMS))


def set_inv(world, agent, **kwargs) -> None:
    """设置家庭资产（只允许 ITEMS 内的键）。"""
    household = household_of(world, agent)
    for key, value in kwargs.items():
        if key not in ITEMS:
            raise ValueError(f"not an asset field: {key}")
        setattr(household, key, value)


def home(agent, world):
    return home_node_of(world, agent)


def work(agent, world):
    return work_node_of(world, agent)
