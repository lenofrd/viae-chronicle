"""资源获取命令的统一入口（P3c：契约只路由，结算在领域所有者）。

ADR 009 §2.4/§2.5：本契约是按资源类型路由到状态所有者的门面，不拥有库存、
不做结算——生态资源池按域分流（P4，2026-11-21 裁决）：植被类池归环境域
（``domains.environment.resources.harvest_from_pool``），鱼/猎物池归动物域
（``domains.wildlife.wildlife.harvest_from_wildlife``）；生活用水归水文库存
（``domains.environment.hydrology.withdraw_water``）。P3b 期间结算曾放在本契约内，P3c 按
裁决移交所有者；契约层不得出现在状态写入者集合（架构测试红线
``test_contracts_are_never_state_writers``）。
"""
from __future__ import annotations

from vale.domains.environment import hydrology
from vale.domains.environment.resources import harvest_from_pool
from vale.domains.wildlife import wildlife


class ResourceService:
    """资源获取命令的统一入口（采集/捕鱼/打猎/取水）。"""

    @staticmethod
    def harvest(world, node_id: str, requested: float, *, agent_id: str = "",
                household_id: str = "", action: str = "") -> float:
        """从节点资源池结算采集，返回实际给付量（0 表示被拒）。

        先查环境域池，miss 再查动物域池（P4 按域分流）。两者都未登记即抛错
        快速失败：无池目录不等于资源无限（2026-11-21 裁决），未登记资源一律
        拒绝，不做原额给付，否则资源守恒可被绕过。无采集行为的世界不会走到
        这里——启动校验已拦住「有采集动作却无池目录」的配置。
        """
        requested = max(0.0, float(requested))
        if world.state.environment.ecological_resources.get(node_id) is not None:
            return harvest_from_pool(
                world, node_id, requested,
                agent_id=agent_id, household_id=household_id, action=action,
            )
        if world.state.wildlife.pools.get(node_id) is not None:
            return wildlife.harvest_from_wildlife(
                world, node_id, requested,
                agent_id=agent_id, household_id=household_id, action=action,
            )
        raise ValueError(f"harvest targets unregistered resource pool: {node_id}")

    @staticmethod
    def is_resource_node(world, node_id: str) -> bool:
        """该节点是否登记了资源池（环境域或动物域；供调用方区分失败原因）。"""
        return (world.state.environment.ecological_resources.get(node_id) is not None
                or world.state.wildlife.pools.get(node_id) is not None)

    @staticmethod
    def withdraw_water(world, node_id: str, amount: float, *, requester_id: str = "") -> float:
        """生活用水：路由到环境域水文结算（``domains.environment.hydrology``）。"""
        return hydrology.withdraw_water(world, node_id, amount, requester_id=requester_id)
