"""动物领域状态（ADR 009 §2.2B）：鱼/猎物存量池容器。

资源类型归属 ``WILDLIFE_RESOURCE_TYPES`` 是跨领域共享定义，位于 ``core.pools``。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from vale.core.pools import ResourcePoolState



class WildlifeState(BaseModel):
    """动物领域状态容器（ADR 009 §2.2B）。

    P4（2026-11-21 裁决）：鱼/猎物存量池迁入动物域（河流不拥有鱼），由
    ``domains.wildlife.wildlife`` 拥有并结算；P5 再填入个体与种群状态。
    """

    pools: dict[str, ResourcePoolState] = Field(default_factory=dict)
