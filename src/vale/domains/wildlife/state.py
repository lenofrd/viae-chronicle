"""动物领域状态（ADR 009 §2.2B）：鱼/猎物存量池容器与资源类型归属。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from vale.core.pools import ResourcePoolState



class WildlifeState(BaseModel):
    """动物领域状态容器（ADR 009 §2.2B）。

    P4（2026-11-21 裁决）：鱼/猎物存量池迁入动物域（河流不拥有鱼），由
    ``domains.wildlife.wildlife`` 拥有并结算；P5 再填入个体与种群状态。
    """

    pools: dict[str, ResourcePoolState] = Field(default_factory=dict)


# 归动物域的资源类型（P4 裁决）：目录中 resource_type 命中此集合的池由
# domains.wildlife.wildlife 拥有并结算，其余归 domains.environment.resources。P5 扩种群时再扩集合。
WILDLIFE_RESOURCE_TYPES = frozenset({"fish", "game"})
