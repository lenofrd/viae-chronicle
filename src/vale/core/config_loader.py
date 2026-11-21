"""配置加载器：读 YAML 并用 Pydantic Schema 校验，聚合成一个 config 对象。

聚合对象暴露：
  - config.world           （WorldConfig 元信息）
  - config.natural_params  （NaturalConfig 气候/水文）
  - config.spatial         （SpatialConfig 空间节点）
供模块通过 world.config.<...> 读取，代码中不写死任何具体数值。
"""
from __future__ import annotations

import os

import yaml

from vale.config.schema.agents import AgentsConfig
from vale.config.schema.natural_params import NaturalConfig
from vale.config.schema.spatial_units import SpatialConfig
from vale.config.schema.world_config import WorldConfig


class LoadedConfig:
    def __init__(
        self,
        world: WorldConfig,
        natural_params: NaturalConfig,
        spatial: SpatialConfig,
        agents: AgentsConfig,
        terrain: list | None = None,
        resources: dict | None = None,
    ) -> None:
        self.world = world
        self.natural_params = natural_params
        self.spatial = spatial
        self.agents = agents
        self.terrain = list(terrain or [])
        # P4：资源池目录（键 = 资源节点 id，值 = vale.core.state.ResourcePoolSpec）。
        # 生成器自然段产出，领域所有者（ecology/wildlife）首 tick 引导建池；
        # 池参数唯一真相源（节点 attributes 不再携带 resource_* 副本）。
        self.resources = dict(resources or {})


def load_config(world_id: str, config_root: str = "config/worlds") -> LoadedConfig:
    base = os.path.join(config_root, world_id)

    def _load(filename: str, schema):
        with open(os.path.join(base, filename), encoding="utf-8") as f:
            return schema(**yaml.safe_load(f))

    return LoadedConfig(
        world=_load("world.yaml", WorldConfig),
        natural_params=_load("natural-params.yaml", NaturalConfig),
        spatial=_load("spatial-units.yaml", SpatialConfig),
        agents=_load("agents.yaml", AgentsConfig),
    )
