"""动物域所有者（P4，2026-11-21 裁决）：鱼/猎物存量池的引导、再生与捕获结算。

``WildlifeState.pools`` 的唯一所有者是本模块：目录中 ``resource_type`` 命中
``WILDLIFE_RESOURCE_TYPES``（fish / game）的池由 ``WildlifeModule.step`` 引导
并再生，捕获结算由 ``harvest_from_wildlife`` 执行（复用 ``modules.ecology``
的池结算机制，同一口径）；人类模块经写入契约
（``contracts.resources.ResourceService.harvest``）提交请求。动物个体与种群
行为留给 P5；环境域只提供栖息地条件（worldgen.nature 静态植被/栖息地描述）。
"""
from __future__ import annotations

from vale.contracts.queries import EnvironmentQuery
from vale.core.state import WILDLIFE_RESOURCE_TYPES
from vale.modules import ecology


class WildlifeModule:
    name = "wildlife"
    depends_on = ["climate"]

    def step(self, world) -> None:
        season = EnvironmentQuery.season(world).value
        pools = world.state.wildlife.pools
        for node_id, spec in ecology.pool_specs(world).items():
            if spec.resource_type not in WILDLIFE_RESOURCE_TYPES:
                continue  # 植被类池归环境域（modules.ecology）
            pool = pools.get(node_id)
            if pool is None:
                pools[node_id] = ecology.bootstrap_pool(world, node_id, spec)
                continue
            ecology.regenerate_pool(world, pool, node_id, season)


def harvest_from_wildlife(world, node_id: str, requested: float, *, agent_id: str = "",
                          household_id: str = "", action: str = "") -> float:
    """动物域捕获结算（鱼/猎物池），返回实际给付量（0 表示被拒）。

    未登记池抛错（与 ``ecology.harvest_from_pool`` 同一收敛口径）。
    """
    pool = world.state.wildlife.pools.get(node_id)
    if pool is None:
        raise ValueError(f"harvest targets unregistered wildlife pool: {node_id}")
    return ecology.settle_pool_harvest(world, pool, node_id, requested,
                                       agent_id=agent_id, household_id=household_id,
                                       action=action)
