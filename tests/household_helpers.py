"""测试共用 helper。

经济单位已从 Agent 迁到 Household；测试通过这里读写家庭资产，避免逐处散落 household_id 查找。
另提供基础 YAML 世界的测试资源池夹具（2026-11-21 裁决：无池目录不再原额给付）。
"""
from __future__ import annotations

from vale.core.household import (
    home_node_of,
    household_of,
    inventory_of,
    work_node_of,
)
from vale.core.state import ResourcePoolSpec
from vale.modules.ecology import bootstrap_pool

ITEMS = ("grain", "meat", "fish", "vegetable", "cloth")

# 测试池额度：足够大以保证给付量等于请求量，不参与任何平衡口径。
TEST_POOL_STOCK = 1e9


def attach_test_resource_pools(world) -> None:
    """为以基础 YAML 世界为夹具的世界补测试资源池并建运行时池。

    2026-11-21 裁决取消了「无池目录原额给付」：配置了采集动作的世界必须有池目录
    且目标节点已登记。单元测试不读世界生成的池数值，这里按 `gathering.actions`
    的目标节点补大额度测试池，保持与旧夹具相同的给付行为；生产池数值仍只来自
    世界生成（`config.resources` 由生成器注入）。
    """
    cfg = world.config
    actions = cfg.agents.tuning.gathering.actions
    specs = dict(getattr(cfg, "resources", None) or {})
    for node in sorted({g.target_node for g in actions.values()}):
        specs.setdefault(node, ResourcePoolSpec(
            resource_id=node,
            resource_type="test",
            current_stock=TEST_POOL_STOCK,
            max_stock=TEST_POOL_STOCK,
            regeneration_per_tick=0.0,
            extraction_limit_per_tick=TEST_POOL_STOCK,
        ))
    cfg.resources = specs
    pools = world.state.environment.ecological_resources
    for node, spec in specs.items():
        if node not in pools:
            pools[node] = bootstrap_pool(world, node, spec)


def hh(world, agent):
    """agent 所属家庭。"""
    return household_of(world, agent)


def inv(world, agent) -> dict[str, float]:
    """家庭库存快照。"""
    return inventory_of(world, agent, list(ITEMS))


def set_inv(world, agent, **kwargs) -> None:
    """设置家庭资产（只允许 ITEMS 内的键）。"""
    household = household_of(world, agent)
    for key, value in kwargs.items():
        if key not in ITEMS:
            raise ValueError(f"not an asset field: {key}")
        setattr(household, key, value)


def home(agent, world):
    return home_node_of(world, agent)


def work(agent, world):
    return work_node_of(world, agent)
