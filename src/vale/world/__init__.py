"""Procedural world generation helpers for Vale Chronicle.

P4 分段：自然段（nature）产地形/池目录/植被描述；聚落段（settlement）布点、
路网与距离矩阵；xigu 为组合门面。资源池参数经 LoadedConfig.resources 进运行时。
"""
from .nature import (
    NatureResult,
    ResourcePoolSpec,
    TerrainCell,
    VegetationProfile,
    VEGETATION_PROFILES,
    generate_nature,
    harvest_resource,
    regenerate_resource,
)
from .xigu import (
    XiguGenerationConfig,
    XiguGenerationResult,
    build_xigu_agents_config,
    generate_xigu_town,
    validate_xigu_town,
)

__all__ = [
    "NatureResult", "ResourcePoolSpec", "TerrainCell", "VegetationProfile",
    "VEGETATION_PROFILES", "XiguGenerationConfig", "XiguGenerationResult",
    "build_xigu_agents_config", "generate_nature", "generate_xigu_town",
    "harvest_resource", "regenerate_resource", "validate_xigu_town",
]
