"""资源获取命令的统一入口（P3c：契约只路由，结算在领域所有者）。

ADR 009 §2.4/§2.5：本契约是按资源类型路由到状态所有者的门面，不拥有库存、
不做结算——生态资源池归环境域（``modules.ecology.harvest_from_pool``），
生活用水归水文库存（``modules.hydrology.withdraw_water``）。P3b 期间结算曾
放在本契约内，P3c 按裁决移交所有者；契约层不得出现在状态写入者集合
（架构测试红线 ``test_contracts_are_never_state_writers``）。
"""
from __future__ import annotations

from vale.modules import ecology, hydrology


class ResourceService:
    """资源获取命令的统一入口（采集/捕鱼/打猎/取水）。"""

    @staticmethod
    def harvest(world, node_id: str, requested: float, *, agent_id: str = "",
                household_id: str = "", action: str = "") -> float:
        """从节点资源池结算采集，返回实际给付量（0 表示被拒）。"""
        return ecology.harvest_from_pool(
            world, node_id, requested,
            agent_id=agent_id, household_id=household_id, action=action,
        )

    @staticmethod
    def is_resource_node(world, node_id: str) -> bool:
        """该节点是否登记了生态资源池（供调用方区分失败原因）。"""
        return world.state.environment.ecological_resources.get(node_id) is not None

    @staticmethod
    def withdraw_water(world, node_id: str, amount: float, *, requester_id: str = "") -> float:
        """生活用水：路由到环境域水文结算（``modules.hydrology``）。"""
        return hydrology.withdraw_water(world, node_id, amount, requester_id=requester_id)
