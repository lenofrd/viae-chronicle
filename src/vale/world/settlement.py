"""溪谷镇世界生成·聚落段（P4，ADR 009 §3.2/§3.5）。

读取自然段公开结果（world.nature），在地理骨架上布点：地标、水系、
资源节点占位、田块与住宅，随后建道路网与距离矩阵、派发家庭候选田块。
不覆盖自然地理骨架；资源池参数不投影进节点 attributes（P4 裁决：池目录
是唯一真相源，由 LoadedConfig.resources 传入运行时）。
"""
from __future__ import annotations

import heapq
import math
import random
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

from vale.config.schema.spatial_units import DistanceEdge, NodeType, SpatialConfig, SpatialNode

from vale.world.nature import terrain_at


@dataclass(frozen=True)
class RoadSegment:
    from_id: str
    to_id: str
    distance_units: float
    surface: str
    multiplier: float
    one_way_tu: float
    path: tuple[tuple[int, int], ...] = ()


def add_node(nodes: list[SpatialNode], node_id: str, name: str, kind: NodeType,
             x: float, y: float, district: str, description: str, **attrs: object) -> None:
    terrain, elevation, slope, flood, fertility = terrain_at(x, y)
    nodes.append(SpatialNode(
        id=node_id, name=name, type=kind, district=district, description=description,
        attributes={"x": round(x, 3), "y": round(y, 3), "terrain": terrain,
                    "elevation": round(elevation, 3), "slope": round(slope, 3),
                    "flood_risk": round(flood, 3), "soil_fertility": round(fertility, 3),
                    **attrs},
    ))


def make_nodes(config, base_spatial: SpatialConfig | None = None) -> list[SpatialNode]:
    rng, nodes = random.Random(config.seed), []
    landmarks = [
        ("well", "主水井", NodeType.RESOURCE, 24, 1, "central", "日常取水与消息交换中心"),
        ("market", "集市", NodeType.SOCIAL, 23, -5, "central", "定期交易与货郎集散地"),
        ("shrine", "祠堂", NodeType.SOCIAL, 27, 8, "north", "祭祀、议事与宗族公共空间"),
        ("elder_house", "里正家", NodeType.RESIDENTIAL, 28, 6, "north", "户籍登记与纠纷调解"),
        ("herbalist", "药铺", NodeType.RESIDENTIAL, 31, 1, "central", "草药收购与诊疗"),
        ("ferry", "渡口", NodeType.WATER, 9, -17, "riverside", "河岸渡运与渔获装卸点"),
        ("mountain_shrine", "山神庙", NodeType.SOCIAL, 36, 12, "foothill", "进山前祭祀点"),
        ("sacred_oak", "神树古栎", NodeType.MOUNTAIN, 38, 9, "foothill", "浅山边缘受敬畏的古栎"),
    ]
    for nid, name, kind, x, y, district, desc in landmarks:
        add_node(nodes, nid, name, kind, x, y, district, desc, landmark=True, protected=(nid == "sacred_oak"))

    add_node(nodes, "cui_river", "翠溪主河道", NodeType.WATER, 8, 0, "riverside",
             "南北向宽河；村庄与田地均位于东岸", water_body="river")
    add_node(nodes, "irrigation_intake", "引水渠取水口", NodeType.WATER, 11, 14, "farmland",
             "春汛时有漫溢风险", water_body="canal", flood_exposure="high")
    add_node(nodes, "irrigation_canal", "东岸引水渠", NodeType.WATER, 12, 0, "farmland",
             "向水浇田分配灌溉水", water_body="canal")
    add_node(nodes, "river_town", "翠溪镇前段", NodeType.WATER, 9.5, -2, "riverside",
             "季节性鱼群活动水域", livelihood_zone="river")
    add_node(nodes, "foothill_woodland", "山脚林地", NodeType.RESOURCE, 34, -5, "foothill",
             "柴薪与常见草药来源", livelihood_zone="woodland")
    add_node(nodes, "low_mountain", "浅山密林", NodeType.RESOURCE, 43, 3, "shallow_mountain",
             "硬木、草药与猎物来源；存在野兽风险", livelihood_zone="woodland")
    add_node(nodes, "deep_mountain", "青冥山深山禁区", NodeType.RESOURCE, 59, 12, "deep_mountain",
             "常规居民不可进入，仅特殊事件开放", restricted=True)
    add_node(nodes, "game_trail", "兽径", NodeType.RESOURCE, 40, -10, "shallow_mountain",
             "猎物迁徙路径", livelihood_zone="woodland")

    for i in range(config.irrigated_field_count):
        y = -11 + i * 22 / max(1, config.irrigated_field_count - 1)
        x = 14 + rng.uniform(-.7, .7)
        add_node(nodes, f"irrigated_field_{i+1:02d}", f"水浇田{i+1:02d}", NodeType.FIELD,
            x, y, "irrigated_farmland", "近引水渠的低地水浇田",
            irrigation="canal", flood_exposure="seasonal_spring_flood",
            crop_type="grain", area=round(rng.uniform(.85, 1.2), 3), field_kind="irrigated", livelihood_zone="farming", rotation_required=False)
    for i in range(config.dry_field_count):
        y = -12 + i * 24 / max(1, config.dry_field_count - 1)
        x = 21 + rng.uniform(-1, 1)
        add_node(nodes, f"dry_field_{i+1:02d}", f"坡旱地{i+1:02d}", NodeType.FIELD,
            x, y, "dry_farmland", "依赖降雨的坡地旱田，需轮作",
            irrigation="rainfed", flood_exposure="low", crop_type="grain",
            area=round(rng.uniform(.65, 1), 3), field_kind="dry", livelihood_zone="farming", rotation_required=True)

    districts = [
        ("poor", config.poor_households, 22, -12, -3, "南部贫民区，近渡口且远离优质水浇田"),
        ("common", config.common_households, 17, -3, 7, "中部平民区，围绕水井与集市"),
        ("wealthy", config.wealthy_households, 17.0, 10, 18, "北部富户区，靠近渠口与水浇田"),
    ]
    for district, count, base_x, ymin, ymax, desc in districts:
        for i in range(count):
            y = ymin + (i + .5) * (ymax - ymin) / count
            x = base_x + rng.uniform(-1.8, 1.8)
            add_node(nodes, f"home_{district}_{i+1:02d}", f"{district}宅院{i+1:02d}",
                NodeType.RESIDENTIAL, x, y, f"{district}_district", desc,
                residence=True, household_slot=i+1, district_class=district,
                livelihood_options=["farming", "river", "woodland"])
    if base_spatial is not None:
        nodes = merge_base_spatial_nodes(nodes, base_spatial)
    return nodes


def merge_base_spatial_nodes(
    generated_nodes: list[SpatialNode], base_spatial: SpatialConfig,
) -> list[SpatialNode]:
    """Keep Brookvale's established node IDs and descriptions while enriching them
    with generated coordinates and terrain metadata. Existing district/field nodes
    remain zone anchors; generated home/field nodes are the concrete parcels.
    """
    generated = {node.id: node for node in generated_nodes}
    base_nodes = list(base_spatial.nodes)
    base_ids = {node.id for node in base_nodes}
    abstract_zones = {
        "poor_district", "common_district", "rich_district",
        "east_field", "west_field", "south_field",
    }
    anchors = {
        "poor_district": (24, -10),
        "common_district": (21, 2),
        "rich_district": (16, 14),
        "foothill": (34, 0),
        "east_field": (14, 12),
        "west_field": (21, -8),
        "south_field": (14, -15),
        "river_upstream": (8, 14),
        "river_downstream": (8, -16),
    }
    merged: list[SpatialNode] = []
    for legacy in base_nodes:
        attrs = dict(legacy.attributes or {})
        current = generated.get(legacy.id)
        updates = {}
        if current is not None:
            # Keep legacy identity, type, display name and description. Generated
            # terrain coordinates enrich the existing node rather than replacing it.
            attrs.update(current.attributes or {})
            updates["travel_cost_from_well_tu"] = (
                current.travel_cost_from_well_tu
                if current.travel_cost_from_well_tu is not None
                else legacy.travel_cost_from_well_tu
            )
        elif legacy.id in anchors:
            x, y = anchors[legacy.id]
            terrain, elevation, slope, flood, fertility = terrain_at(x, y)
            attrs.update({
                "x": x, "y": y, "terrain": terrain, "elevation": round(elevation, 3),
                "slope": round(slope, 3), "flood_risk": round(flood, 3),
                "soil_fertility": round(fertility, 3),
            })
        if legacy.id in abstract_zones:
            attrs["abstract_zone"] = True
            attrs["district_zone"] = legacy.id.endswith("_district")
        if legacy.id in {"river_upstream", "river_downstream"}:
            attrs["water_body"] = "river"
        updates["attributes"] = attrs
        merged.append(legacy.model_copy(update=updates))
    merged.extend(node for node in generated_nodes if node.id not in base_ids)
    return merged


def surface_between(a: SpatialNode, b: SpatialNode, cfg) -> tuple[str, float]:
    terrains = {a.attributes.get("terrain"), b.attributes.get("terrain")}
    if "deep_mountain" in terrains:
        return "mountain_track", cfg.mountain_multiplier
    if terrains & {"shallow_forest", "foothill"}:
        return "forest_path", cfg.forest_multiplier
    if terrains & {"river_bank", "irrigated_lowland"}:
        return "earth_track", cfg.footpath_multiplier
    return "compacted_earth", 1.0


@lru_cache(maxsize=12000)
def grid_route(start: tuple[float, float], goal: tuple[float, float], cfg):
    """Least-cost 8-neighbour route on the terrain raster; deep mountain is impassable."""
    source, target = (round(start[0]), round(start[1])), (round(goal[0]), round(goal[1]))
    if source == target:
        return 0.0, (source,)
    def inside(x, y):
        return 0 <= x < cfg.map_width and -cfg.map_height // 2 <= y < cfg.map_height // 2
    def multiplier(x, y):
        terrain = terrain_at(x, y)[0]
        if terrain == "deep_mountain":
            return math.inf
        if terrain == "shallow_forest":
            return cfg.forest_multiplier
        if terrain == "foothill":
            return cfg.slope_multiplier
        if terrain == "river_bank":
            return cfg.footpath_multiplier
        return 1.0
    queue, distances, previous = [(0.0, source)], {source: 0.0}, {}
    while queue:
        cost, point = heapq.heappop(queue)
        if cost != distances.get(point):
            continue
        if point == target:
            path, cursor = [target], target
            while cursor in previous:
                cursor = previous[cursor]
                path.append(cursor)
            path.reverse()
            return cost, tuple(path)
        x, y = point
        for dx, dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
            nx, ny = x + dx, y + dy
            if not inside(nx, ny):
                continue
            mult = multiplier(nx, ny)
            if not math.isfinite(mult):
                continue
            candidate = cost + math.hypot(dx, dy) * cfg.road_tu_per_unit * mult
            if candidate < distances.get((nx, ny), math.inf):
                distances[(nx, ny)] = candidate
                previous[(nx, ny)] = point
                heapq.heappush(queue, (candidate, (nx, ny)))
    return math.inf, ()


def make_roads(nodes: list[SpatialNode], cfg) -> list[RoadSegment]:
    """Build a least-cost raster MST and local branches; deep mountain stays closed."""
    routable = [n for n in nodes if not n.attributes.get("restricted")]
    candidates = []
    for i, a in enumerate(routable):
        for b in routable[i + 1:]:
            cost, path = grid_route((a.attributes["x"], a.attributes["y"]),
                                     (b.attributes["x"], b.attributes["y"]), cfg)
            if not path:
                continue
            distance = math.hypot(a.attributes["x"] - b.attributes["x"],
                                  a.attributes["y"] - b.attributes["y"])
            terrains = {a.attributes.get("terrain"), b.attributes.get("terrain")}
            surface = ("forest_path" if "shallow_forest" in terrains else
                       "slope_path" if "foothill" in terrains else "earth_track")
            mult = (cfg.forest_multiplier if surface == "forest_path" else
                    cfg.slope_multiplier if surface == "slope_path" else cfg.footpath_multiplier)
            candidates.append((cost + cfg.road_base_tu, a.id, b.id, distance, surface, mult, path))
    candidates.sort()
    ids = sorted(n.id for n in routable)
    parent = {nid: nid for nid in ids}
    def find(nid):
        while parent[nid] != nid:
            parent[nid] = parent[parent[nid]]
            nid = parent[nid]
        return nid
    selected = {}
    for cost, aid, bid, distance, surface, mult, path in candidates:
        ra, rb = find(aid), find(bid)
        if ra != rb:
            parent[ra] = rb
            selected[(aid, bid)] = (cost, distance, surface, mult, path)
        if len(selected) == len(ids) - 1:
            break
    for nid in ids:
        nearest = [c for c in candidates if nid in c[1:3]][:cfg.neighbor_count]
        for cost, aid, bid, distance, surface, mult, path in nearest:
            selected[(aid, bid)] = (cost, distance, surface, mult, path)
    return [RoadSegment(a, b, distance, surface, mult, cost, path)
            for (a, b), (cost, distance, surface, mult, path) in sorted(selected.items())]


def shortest_paths(start: str, roads: Iterable[RoadSegment]) -> dict[str, float]:
    graph: dict[str, list[tuple[str, float]]] = {}
    for edge in roads:
        graph.setdefault(edge.from_id, []).append((edge.to_id, edge.one_way_tu))
        graph.setdefault(edge.to_id, []).append((edge.from_id, edge.one_way_tu))
    distances, queue = {start: 0.0}, [(0.0, start)]
    while queue:
        cost, nid = heapq.heappop(queue)
        if cost != distances.get(nid):
            continue
        for neighbor, weight in graph.get(nid, []):
            candidate = cost + weight
            if candidate < distances.get(neighbor, math.inf):
                distances[neighbor] = candidate
                heapq.heappush(queue, (candidate, neighbor))
    return distances


def distance_matrix(node_ids: set[str], roads: list[RoadSegment]) -> dict[str, dict[str, float]]:
    graph = {nid: [] for nid in node_ids}
    for edge in roads:
        graph[edge.from_id].append((edge.to_id, edge.one_way_tu))
        graph[edge.to_id].append((edge.from_id, edge.one_way_tu))
    matrix = {}
    for source in node_ids:
        matrix[source] = shortest_paths(source, roads)
    return matrix


def build_distance_edges(roads: list[RoadSegment]) -> list[DistanceEdge]:
    return [DistanceEdge(
        from_id=r.from_id, to_id=r.to_id, one_way_tu=round(r.one_way_tu, 3),
        difficulty=r.surface,
        risk="wildlife" if r.surface == "forest_path" else
             "slope_fall" if r.surface == "slope_path" else "spring_flood",
    ) for r in roads]
