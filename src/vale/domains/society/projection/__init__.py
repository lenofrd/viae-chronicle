"""人文领域事件投影（ADR 009 §2.2C；2026-11-21 裁决归属修正）。

``SocietyProjection`` 是统一注册入口，由四个职责投影组合而成：

- ``people``：人物状态、生命周期、劳作簿记、认知与印象；
- ``households``：家庭注册/分户/并户/迁移/户主、资产与继承；
- ``economy``：借贷、交易、共享仓储、社区储备、债务与纠纷；
- ``land_governance``：租约产权、建筑与建造项目、村庄治理。

拆分只改变代码组织，不改变事件投影语义与派发顺序（同一事件仍只有一个处理器）。
"""
from __future__ import annotations

from .economy import EconomyProjection
from .households import HouseholdProjection
from .land_governance import LandGovernanceProjection
from .people import PeopleProjection


class SocietyProjection(
    PeopleProjection,
    HouseholdProjection,
    EconomyProjection,
    LandGovernanceProjection,
):
    """人文领域统一投影：四类职责合并为一个可注册投影。"""


__all__ = ["SocietyProjection"]
