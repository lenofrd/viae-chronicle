"""环境域资源池所有者：植被类池的引导、再生与采集结算（P4/P5 归口）。

``EnvironmentState.ecological_resources`` 的唯一所有者是环境域：池的初始化与
再生由 ``EcologyModule.step`` 驱动，采集结算由本模块的 ``harvest_from_pool``
执行；人类模块经写入契约（``contracts.resources.ResourceService.harvest``）
提交请求，契约只路由、不写状态。

边界（2026-11-21 裁决）：

- 池参数唯一真相源是生成器产出的池目录（``LoadedConfig.resources``，
  ``ResourcePoolSpec``），节点 attributes 不携带 ``resource_*`` 副本；
- ``resource_type`` 为 fish/game 的池归动物域（``domains.wildlife.wildlife``），
  其余归本模块；初始化 / 再生 / 结算的共享机制在 ``core.pools``；
- 地形栅格由 ``domains.environment.terrain`` 引导，田块生态归
  ``domains.environment.fields``；
- 未登记池的原额给付 fallback 取消（采集指向未登记池启动即报错，运行期直达则抛错）。
"""
from __future__ import annotations

from vale.contracts.queries import EnvironmentQuery
from vale.core.pools import bootstrap_pool, pool_specs, regenerate_pool, settle_pool_harvest
from vale.domains.wildlife.state import WILDLIFE_RESOURCE_TYPES
from vale.domains.environment.terrain import ensure_terrain_cells


def owns_resource_type(resource_type: str) -> bool:
    """池类型是否归环境域（fish / game 归动物域，2026-11-21 P4 裁决）。"""
    return resource_type not in WILDLIFE_RESOURCE_TYPES


class EcologyModule:
    name = "ecology"
    depends_on = ["climate"]

    def step(self, world) -> None:
        ensure_terrain_cells(world)
        season = EnvironmentQuery.season(world).value
        pools = world.state.environment.ecological_resources
        for node_id, spec in pool_specs(world).items():
            if not owns_resource_type(spec.resource_type):
                continue  # 鱼/猎物池归动物域（domains.wildlife.wildlife 拥有并结算）
            pool = pools.get(node_id)
            if pool is None:
                pools[node_id] = bootstrap_pool(world, node_id, spec)
                continue
            regenerate_pool(world, pool, node_id, season)


def harvest_from_pool(world, node_id: str, requested: float, *, agent_id: str = "",
                      household_id: str = "", action: str = "") -> float:
    """环境域采集结算（植被类池），返回实际给付量（0 表示被拒）。

    P4 收敛：目标节点未登记资源池不再原额给付，直接抛错（采集目标必须在
    池目录登记，启动校验拦截坏配置；运行期直达此处即状态异常，快速失败）。
    """
    pool = world.state.environment.ecological_resources.get(node_id)
    if pool is None:
        raise ValueError(f"harvest targets unregistered resource pool: {node_id}")
    return settle_pool_harvest(world, pool, node_id, requested,
                               agent_id=agent_id, household_id=household_id,
                               action=action)
