"""地形栅格引导（环境域所有者）。

P4 归口：``EnvironmentState.terrain_cells`` 只承载生成器产出的静态地形副本，
由环境域从 ``LoadedConfig.terrain`` 引导，不由人文域土地模块跨域写入；
静默初始化，不写事件（与既有行为一致）。
"""
from __future__ import annotations

from vale.domains.environment.state import TerrainCellState


def ensure_terrain_cells(world) -> None:
    """地形栅格引导（P4 归口）：生成结果经引导路径写入环境域，静默不写事件。"""
    if world.state.environment.terrain_cells:
        return
    for cell in getattr(world.config, "terrain", []) or []:
        cell_id = f"terrain:{cell.x}:{cell.y}"
        world.state.environment.terrain_cells[cell_id] = TerrainCellState(
            cell_id=cell_id,
            x=cell.x,
            y=cell.y,
            terrain=cell.terrain,
            elevation=cell.elevation,
            slope=cell.slope,
            flood_risk=cell.flood_risk,
            soil_fertility=cell.soil_fertility,
        )
