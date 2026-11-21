"""人物子系统的动作目录与公共常量。"""

from __future__ import annotations

from vale.config.schema.agents import AgentTuning
from vale.config.schema.natural_params import WeatherType

# 视为降雨的天气（B9：影响户外劳作）
RAIN_WEATHERS = {WeatherType.LIGHT_RAIN, WeatherType.MODERATE_RAIN, WeatherType.HEAVY_RAIN}
# 不可行动作的得分（体力不足 / 无粮等），保证不会被选中
IMPOSSIBLE = float("-inf")

# 候选动作集合（内容外置：动作→目标节点的映射在 production._target_node）
CANDIDATE_ACTIONS = ["eat", "rest", "farm", "collect_water", "harvest", "borrow_grain", "borrow_food", "weave", "construct", "court", "try_for_child"]

def _candidate_actions(tuning: AgentTuning) -> list[str]:
    """基础候选动作 + 配置声明的采集类动作（hunt / 未来 fish）。

    新增第二生计只需在 agents.yaml 的 gathering.actions 下加一项，此处自动纳入候选，
    核心决策循环不改、不出现 ``if action == "hunt"`` 式散落硬编码。
    """
    return CANDIDATE_ACTIONS + list(tuning.gathering.actions.keys())
