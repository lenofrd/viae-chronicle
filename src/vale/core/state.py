"""世界状态组合根（ADR 009 §2.1：基础设施持有 World、WorldState 组合根）。

本模块只做一件事：把三个领域的状态容器组合成 ``WorldState``。领域专属状态模型都由
各领域拥有，不在本模块定义：

- 环境域 ``vale.domains.environment.state``（地形/水源/生态与田块字段）
- 动物域 ``vale.domains.wildlife.state``（鱼/猎物存量池）
- 人文域 ``vale.domains.society.state``（人物/家庭/土地/建造/治理）

跨领域共享的只读值对象另置基础设施：气候快照见 ``vale.core.snapshots``，
资源池形状见 ``vale.core.pools``。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from vale.domains.environment.state import EnvironmentState
from vale.domains.society.state import HumanState
from vale.domains.wildlife.state import WildlifeState


class WorldState(BaseModel):
    """世界状态组合根：一域一容器，跨域不得直接写他人子容器。"""

    environment: EnvironmentState = Field(default_factory=EnvironmentState)
    human: HumanState = Field(default_factory=HumanState)
    wildlife: WildlifeState = Field(default_factory=WildlifeState)
