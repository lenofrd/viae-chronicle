"""人类域 · 人物子系统。

对外入口：``AgentModule``（调度注册名 ``agents``）；其余为子系统内部实现，
测试与相邻模块可按需导入。
"""
from vale.domains.society.agents.constants import (
    CANDIDATE_ACTIONS,
    IMPOSSIBLE,
    RAIN_WEATHERS,
    _candidate_actions,
)
from vale.domains.society.agents.demographics import (
    age_years,
    apply_wildlife_attack,
    living_agents,
)
from vale.domains.society.agents.module import AgentModule
from vale.domains.society.agents.perception import (
    Perception,
    _food_lender_node,
    _lender_node,
    select_creditor,
    select_food_creditor,
)
from vale.domains.society.agents.production import (
    _floor_to_step,
    _node_crop_type,
    _target_node,
    expected_yield,
)
from vale.domains.society.agents.spatial import SpatialIndex

__all__ = [
    "AgentModule",
    "CANDIDATE_ACTIONS",
    "IMPOSSIBLE",
    "Perception",
    "RAIN_WEATHERS",
    "SpatialIndex",
    "_candidate_actions",
    "_floor_to_step",
    "_food_lender_node",
    "_lender_node",
    "_node_crop_type",
    "_target_node",
    "age_years",
    "apply_wildlife_attack",
    "expected_yield",
    "living_agents",
    "select_creditor",
    "select_food_creditor",
]
