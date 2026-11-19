"""Deterministic procedural generator for 溪谷镇.

This is an edge adapter: runtime output uses the existing SpatialConfig schema.
Coordinates: x west->east, y south->north. The north-south river is at x~=0;
all residences and fields are on its east bank. Farms, settlement, woodland,
shallow forest, and the Qingming mountain extend eastward in that order.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import heapq
from functools import lru_cache
import math
import random
from typing import Iterable

from config.schema.spatial_units import DistanceEdge, NodeType, SpatialConfig, SpatialNode
from config.schema.agents import AgentAssets, AgentConfig, AgentSex, AgentsConfig, GatheringActionTuning


@dataclass(frozen=True)
class XiguGenerationConfig:
    seed: int = 20261118
    residence_count: int = 40
    poor_households: int = 21
    common_households: int = 14
    wealthy_households: int = 5
    irrigated_field_count: int = 12
    dry_field_count: int = 9
    map_width: int = 64
    map_height: int = 40
    road_tu_per_unit: float = 0.16
    road_base_tu: float = 0.12
    footpath_multiplier: float = 1.35
    slope_multiplier: float = 1.8
    forest_multiplier: float = 2.2
    mountain_multiplier: float = 3.4
    neighbor_count: int = 3

    def __post_init__(self) -> None:
        if self.residence_count != self.poor_households + self.common_households + self.wealthy_households:
            raise ValueError("residence_count must equal the sum of district counts")
        if min(self.residence_count, self.irrigated_field_count, self.dry_field_count,
               self.map_width, self.map_height, self.neighbor_count) <= 0:
            raise ValueError("counts and map dimensions must be positive")
        if min(self.road_tu_per_unit, self.road_base_tu) <= 0:
            raise ValueError("road TU parameters must be positive")


@dataclass(frozen=True)
class TerrainCell:
    x: int
    y: int
    terrain: str
    elevation: float
    slope: float
    flood_risk: float
    soil_fertility: float


@dataclass
class ResourcePool:
    resource_id: str
    resource_type: str
    current_stock: float
    max_stock: float
    regeneration_per_tick: float
    extraction_limit_per_tick: float
    seasonal_weights: dict[str, float] = field(default_factory=dict)
    degradation: float = 0.0
    restricted: bool = False


@dataclass(frozen=True)
class RoadSegment:
    from_id: str
    to_id: str
    distance_units: float
    surface: str
    multiplier: float
    one_way_tu: float
    path: tuple[tuple[int, int], ...] = ()


@dataclass
class XiguGenerationResult:
    spatial: SpatialConfig
    terrain: list[TerrainCell]
    resources: dict[str, ResourcePool]
    roads: list[RoadSegment]
    distances_from_well: dict[str, float]
    pairwise_travel_tu: dict[str, dict[str, float]]
    household_work_nodes: dict[str, list[str]]
    seed: int

    def node(self, node_id: str) -> SpatialNode:
        for node in self.spatial.nodes:
            if node.id == node_id:
                return node
        raise KeyError(node_id)


def _terrain_at(x: float, y: float) -> tuple[str, float, float, float, float]:
    if x < 9:
        return "river_bank", 1 + abs(y) * .015, .08, .78, .72
    if x < 18.5:
        return "irrigated_lowland", 1.5 + abs(y) * .02, .05, .66, .98
    if x < 30:
        return ("settlement_edge" if abs(y) > 13 else "settlement",
                3.0, .12 if abs(y) > 13 else .06, .22 if abs(y) > 13 else .12, .76)
    if x < 38:
        return "foothill", 5 + (x - 23) * .7, .24, .08, .66
    if x < 50:
        return "shallow_forest", 12 + (x - 31) * 1.4, .42, .03, .48
    return "deep_mountain", 30 + (x - 43) * 2, .72, .01, .28


def _make_terrain(config: XiguGenerationConfig) -> list[TerrainCell]:
    cells = []
    for x in range(0, config.map_width, 2):
        for y in range(-config.map_height // 2, config.map_height // 2, 2):
            terrain, elevation, slope, flood, fertility = _terrain_at(x, y)
            cells.append(TerrainCell(x, y, terrain, round(elevation, 3), round(slope, 3),
                                     round(flood, 3), round(fertility, 3)))
    return cells


def _add_node(nodes: list[SpatialNode], node_id: str, name: str, kind: NodeType,
              x: float, y: float, district: str, description: str, **attrs: object) -> None:
    terrain, elevation, slope, flood, fertility = _terrain_at(x, y)
    nodes.append(SpatialNode(
        id=node_id, name=name, type=kind, district=district, description=description,
        attributes={"x": round(x, 3), "y": round(y, 3), "terrain": terrain,
                    "elevation": round(elevation, 3), "slope": round(slope, 3),
                    "flood_risk": round(flood, 3), "soil_fertility": round(fertility, 3),
                    **attrs},
    ))


def _make_nodes(config: XiguGenerationConfig, base_spatial: SpatialConfig | None = None) -> tuple[list[SpatialNode], dict[str, ResourcePool]]:
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
        _add_node(nodes, nid, name, kind, x, y, district, desc, landmark=True, protected=(nid == "sacred_oak"))

    _add_node(nodes, "cui_river", "翠溪主河道", NodeType.WATER, 8, 0, "riverside",
              "南北向宽河；村庄与田地均位于东岸", water_body="river")
    _add_node(nodes, "irrigation_intake", "引水渠取水口", NodeType.WATER, 11, 14, "farmland",
              "春汛时有漫溢风险", water_body="canal", flood_exposure="high")
    _add_node(nodes, "irrigation_canal", "东岸引水渠", NodeType.WATER, 12, 0, "farmland",
              "向水浇田分配灌溉水", water_body="canal")
    _add_node(nodes, "river_town", "翠溪镇前段", NodeType.WATER, 9.5, -2, "riverside",
              "季节性鱼群活动水域", resource_type="fishery", livelihood_zone="river")
    _add_node(nodes, "foothill_woodland", "山脚林地", NodeType.RESOURCE, 34, -5, "foothill",
              "柴薪与常见草药来源", resource_type="woodland", livelihood_zone="woodland")
    _add_node(nodes, "low_mountain", "浅山密林", NodeType.RESOURCE, 43, 3, "shallow_mountain",
              "硬木、草药与猎物来源；存在野兽风险", resource_type="forest", livelihood_zone="woodland")
    _add_node(nodes, "deep_mountain", "青冥山深山禁区", NodeType.RESOURCE, 59, 12, "deep_mountain",
              "常规居民不可进入，仅特殊事件开放", restricted=True, resource_type="restricted", resource_stock=0, resource_max_stock=0, resource_regeneration_per_tick=0, resource_extraction_limit_per_tick=0)
    _add_node(nodes, "game_trail", "兽径", NodeType.RESOURCE, 40, -10, "shallow_mountain",
              "猎物迁徙路径", resource_type="game", livelihood_zone="woodland")

    resources = {
        "river_town": ResourcePool("river_town", "fish", 90, 140, 5, 12,
            {"spring": .8, "summer": 1, "autumn": 1.2, "winter": .35}),
        "foothill_woodland": ResourcePool("foothill_woodland", "firewood", 120, 180, 3, 8),
        "low_mountain": ResourcePool("low_mountain", "herbs_and_hardwood", 70, 100, 1.2, 4,
            {"spring": 1.4, "summer": 1.2, "autumn": .8, "winter": .3}),
        "game_trail": ResourcePool("game_trail", "game", 45, 70, 1.8, 5,
            {"spring": .7, "summer": .9, "autumn": 1.3, "winter": .8}),
        "deep_mountain": ResourcePool("deep_mountain", "rare_medicinal_and_event", 0, 0, 0, 0,
            restricted=True),
    }
    # EcologyModule consumes resource metadata from spatial nodes. Keep the returned
    # ResourcePool catalogue and the runtime world projection on the same source data.
    for node in nodes:
        pool = resources.get(node.id)
        if pool is None:
            continue
        node.attributes.update({
            "resource_type": pool.resource_type,
            "resource_stock": pool.current_stock,
            "resource_max_stock": pool.max_stock,
            "resource_regeneration_per_tick": pool.regeneration_per_tick,
            "resource_extraction_limit_per_tick": pool.extraction_limit_per_tick,
            "resource_seasonal_weights": dict(pool.seasonal_weights),
            "restricted": pool.restricted,
        })

    for i in range(config.irrigated_field_count):
        y = -11 + i * 22 / max(1, config.irrigated_field_count - 1)
        x = 14 + rng.uniform(-.7, .7)
        _add_node(nodes, f"irrigated_field_{i+1:02d}", f"水浇田{i+1:02d}", NodeType.FIELD,
            x, y, "irrigated_farmland", "近引水渠的低地水浇田",
            irrigation="canal", flood_exposure="seasonal_spring_flood",
            crop_type="grain", area=round(rng.uniform(.85, 1.2), 3), field_kind="irrigated", livelihood_zone="farming", rotation_required=False)
    for i in range(config.dry_field_count):
        y = -12 + i * 24 / max(1, config.dry_field_count - 1)
        x = 21 + rng.uniform(-1, 1)
        _add_node(nodes, f"dry_field_{i+1:02d}", f"坡旱地{i+1:02d}", NodeType.FIELD,
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
            _add_node(nodes, f"home_{district}_{i+1:02d}", f"{district}宅院{i+1:02d}",
                NodeType.RESIDENTIAL, x, y, f"{district}_district", desc,
                residence=True, household_slot=i+1, district_class=district,
                livelihood_options=["farming", "river", "woodland"])
    if base_spatial is not None:
        nodes = _merge_base_spatial_nodes(nodes, base_spatial)
    return nodes, resources


def _merge_base_spatial_nodes(
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
            terrain, elevation, slope, flood, fertility = _terrain_at(x, y)
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


def _surface(a: SpatialNode, b: SpatialNode, cfg: XiguGenerationConfig) -> tuple[str, float]:
    terrains = {a.attributes.get("terrain"), b.attributes.get("terrain")}
    if "deep_mountain" in terrains:
        return "mountain_track", cfg.mountain_multiplier
    if terrains & {"shallow_forest", "foothill"}:
        return "forest_path", cfg.forest_multiplier
    if terrains & {"river_bank", "irrigated_lowland"}:
        return "earth_track", cfg.footpath_multiplier
    return "compacted_earth", 1.0


@lru_cache(maxsize=12000)
def _grid_route(start: tuple[float, float], goal: tuple[float, float], cfg: XiguGenerationConfig):
    """Least-cost 8-neighbour route on the terrain raster; deep mountain is impassable."""
    source, target = (round(start[0]), round(start[1])), (round(goal[0]), round(goal[1]))
    if source == target:
        return 0.0, (source,)
    def inside(x, y):
        return 0 <= x < cfg.map_width and -cfg.map_height // 2 <= y < cfg.map_height // 2
    def multiplier(x, y):
        terrain = _terrain_at(x, y)[0]
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


def _make_roads(nodes: list[SpatialNode], cfg: XiguGenerationConfig) -> list[RoadSegment]:
    """Build a least-cost raster MST and local branches; deep mountain stays closed."""
    by_id = {n.id: n for n in nodes}
    routable = [n for n in nodes if not n.attributes.get("restricted")]
    candidates = []
    for i, a in enumerate(routable):
        for b in routable[i + 1:]:
            cost, path = _grid_route((a.attributes["x"], a.attributes["y"]),
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


def _shortest_paths(start: str, roads: Iterable[RoadSegment]) -> dict[str, float]:
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


def _distance_matrix(node_ids: set[str], roads: list[RoadSegment]) -> dict[str, dict[str, float]]:
    graph = {nid: [] for nid in node_ids}
    for edge in roads:
        graph[edge.from_id].append((edge.to_id, edge.one_way_tu))
        graph[edge.to_id].append((edge.from_id, edge.one_way_tu))
    matrix = {}
    for source in node_ids:
        matrix[source] = _shortest_paths(source, roads)
    return matrix


def regenerate_resource(pool: ResourcePool, season: str, ticks: int = 1) -> float:
    """Capped seasonal regeneration; returns the amount added."""
    if pool.restricted or ticks <= 0:
        return 0.0
    amount = min(max(0.0, pool.max_stock - pool.current_stock),
                 max(0.0, pool.regeneration_per_tick * pool.seasonal_weights.get(season, 1.0) * ticks))
    pool.current_stock = round(pool.current_stock + amount, 6)
    return amount


def harvest_resource(pool: ResourcePool, requested: float) -> float:
    """Enforce per-tick extraction limit and stock conservation."""
    if pool.restricted or requested <= 0:
        return 0.0
    amount = min(requested, pool.extraction_limit_per_tick, pool.current_stock)
    pool.current_stock = round(max(0.0, pool.current_stock - amount), 6)
    if amount >= pool.extraction_limit_per_tick > 0:
        pool.degradation = min(1.0, pool.degradation + amount / max(pool.max_stock, 1.0) * 0.01)
    return amount


def generate_xigu_town(config: XiguGenerationConfig | None = None, base_spatial: SpatialConfig | None = None):
    """Generate geography, seasonal resource pools, least-cost roads and route matrices."""
    cfg = config or XiguGenerationConfig()
    terrain = _make_terrain(cfg)
    nodes, resources = _make_nodes(cfg, base_spatial)
    roads = _make_roads(nodes, cfg)
    routable_ids = {n.id for n in nodes if not n.attributes.get("restricted")}
    matrix = _distance_matrix(routable_ids, roads)
    distances = matrix["well"]
    for node in nodes:
        node.travel_cost_from_well_tu = round(distances[node.id], 3) if node.id in distances else None
    field_ids = [n.id for n in nodes if n.type == NodeType.FIELD and not n.attributes.get("abstract_zone")]
    household_work_nodes = {}
    for home in (n for n in nodes if n.attributes.get("residence")):
        # Retain every reachable field in true route-cost order. The first few
        # are preferred candidates, while the full list allows the town seeder
        # to spread households across the available land instead of overloading
        # the same nearest handful of fields.
        household_work_nodes[home.id] = sorted(
            field_ids, key=lambda field_id: (matrix[home.id].get(field_id, math.inf), field_id)
        )
    edges = [DistanceEdge(
        from_id=r.from_id, to_id=r.to_id, one_way_tu=round(r.one_way_tu, 3),
        difficulty=r.surface,
        risk="wildlife" if r.surface == "forest_path" else
             "slope_fall" if r.surface == "slope_path" else "spring_flood",
    ) for r in roads]
    return XiguGenerationResult(SpatialConfig(nodes=nodes, distance_edges=edges),
                                terrain, resources, roads, distances, matrix,
                                household_work_nodes, cfg.seed)


def build_xigu_agents_config(
    result: XiguGenerationResult, base_tuning,
    base_agents: AgentsConfig | None = None,
) -> AgentsConfig:
    """Build the 40-person/30-household seed while retaining Brookvale's named residents.

    The four established residents keep their IDs, names, ages and assets. Their
    homes are mapped into concrete generated residences inside their original
    district; Zhou Qiaoniang retains the market as her weaving workplace.
    """
    tuning = base_tuning.model_copy(deep=True)
    tuning.birth.low_population_adults = max(2, tuning.birth.low_population_adults)
    new_actions = {
        "gather_firewood": GatheringActionTuning(
            target_node="foothill_woodland", output_field="firewood",
            base_success_rate=.72, output_amount=3, injury_risk=.005,
            injury_health_loss=8, season_modifier={"winter": .8},
        ),
        "gather_herbs": GatheringActionTuning(
            target_node="low_mountain", output_field="herbs",
            base_success_rate=.48, output_amount=2, injury_risk=.025,
            injury_health_loss=10, season_modifier={"spring": 1.4, "winter": .5},
        ),
        "gather_hardwood": GatheringActionTuning(
            target_node="low_mountain", output_field="hardwood",
            base_success_rate=.55, output_amount=2, injury_risk=.035,
            injury_health_loss=12, season_modifier={"winter": .7},
        ),
    }
    tuning.gathering.actions.update(new_actions)
    tuning.action.fulfill.update({
        "gather_firewood": {"economy": 1.0},
        "gather_herbs": {"economy": 1.1},
        "gather_hardwood": {"economy": 1.0},
    })
    tuning.action.tu_cost.update({"gather_firewood": 2, "gather_herbs": 3, "gather_hardwood": 4})
    tuning.action.heavy_actions.extend(["gather_herbs", "gather_hardwood"])
    tuning.action.outdoor = list(dict.fromkeys(tuning.action.outdoor + list(new_actions)))
    for item, value in (("firewood", .8), ("herbs", 2.2), ("hardwood", 2.0)):
        tuning.market.trade_values[item] = value
        tuning.market.surplus_threshold[item] = 8
        tuning.market.deficit_threshold[item] = 2

    by_district = {
        "poor_district": sorted(
            (n for n in result.spatial.nodes
             if n.attributes.get("residence") and n.district == "poor_district"),
            key=lambda n: n.id,
        )[:16],
        "common_district": sorted(
            (n for n in result.spatial.nodes
             if n.attributes.get("residence") and n.district == "common_district"),
            key=lambda n: n.id,
        )[:10],
        "wealthy_district": sorted(
            (n for n in result.spatial.nodes
             if n.attributes.get("residence") and n.district == "wealthy_district"),
            key=lambda n: n.id,
        )[:4],
    }
    if any(len(by_district[key]) != expected for key, expected in (
        ("poor_district", 16), ("common_district", 10), ("wealthy_district", 4)
    )):
        raise ValueError("generated Brookvale residences do not match the configured district split")

    agents: list[AgentConfig] = []
    occupied_home_ids: set[str] = set()
    base_by_id = {agent.id: agent for agent in (base_agents.agents if base_agents else [])}
    field_nodes = [
        node for node in result.spatial.nodes
        if node.type == NodeType.FIELD and not node.attributes.get("abstract_zone")
    ]
    node_by_id = {node.id: node for node in result.spatial.nodes}

    field_loads = {node.id: 0 for node in field_nodes}

    def balanced_work_field(home_id: str) -> str:
        candidates = result.household_work_nodes[home_id][:5]
        chosen = min(
            candidates,
            key=lambda field_id: (
                field_loads[field_id],
                result.pairwise_travel_tu[home_id].get(field_id, math.inf),
                field_id,
            ),
        )
        field_loads[chosen] += 1
        return chosen

    legacy_specs = (
        ("zhao_cuilan", "poor_district", -1, "east_field"),
        ("lin_yuan", "common_district", -2, "west_field"),
        ("zhou_qiaoniang", "common_district", -1, "market"),
        ("li_quan", "wealthy_district", -1, "south_field"),
    )
    for agent_id, district, home_index, work_zone in legacy_specs:
        legacy = base_by_id.get(agent_id)
        if legacy is None:
            continue
        home = by_district[district][home_index]
        if work_zone == "market":
            work_node = "market"
        else:
            anchor = node_by_id.get(work_zone)
            if anchor is None:
                work_node = result.household_work_nodes[home.id][0]
            else:
                ax = float(anchor.attributes.get("x", 0.0))
                ay = float(anchor.attributes.get("y", 0.0))
                household_candidates = [
                    node_by_id[node_id] for node_id in result.household_work_nodes[home.id]
                ]
                work_node = min(
                    household_candidates,
                    key=lambda node: (
                        (float(node.attributes.get("x", 0.0)) - ax) ** 2
                        + (float(node.attributes.get("y", 0.0)) - ay) ** 2,
                        field_loads[node.id],
                        node.id,
                    ),
                ).id
                field_loads[work_node] += 1
        household_id = f"hh_{home.id}"
        agents.append(legacy.model_copy(update={
            "household_id": household_id,
            "home_node": home.id,
            "work_node": work_node,
        }))
        occupied_home_ids.add(home.id)
        if agent_id == "li_quan":
            # The existing south-field holding becomes one explicit private parcel.
            node_by_id[work_node].attributes["initial_owner_agent_id"] = agent_id

    # Keep the established 16/10/4 occupied district split. The four named
    # residents above occupy four singleton households; the remaining 26 homes
    # form 10 two-person and 16 one-person households (36 generated residents).
    paired_count = {"poor_district": 6, "common_district": 3, "wealthy_district": 1}
    households: list[tuple[SpatialNode, int]] = []
    for district, homes in by_district.items():
        remaining = [home for home in homes if home.id not in occupied_home_ids]
        for index, home in enumerate(remaining):
            households.append((home, 2 if index < paired_count[district] else 1))

    tuning.split.home_node_candidates = sorted(
        n.id for n in result.spatial.nodes if n.attributes.get("residence")
    )
    surnames = ["林", "赵", "李", "周", "陈", "王", "孙", "吴", "郑", "冯",
                "褚", "卫", "蒋", "沈", "韩", "杨", "朱", "秦", "尤", "许"]
    given = ["安", "宁"]
    rng = random.Random(result.seed)
    person_index = 0
    for home, household_size in households:
        household_id = f"hh_{home.id}"
        work_node = balanced_work_field(home.id)
        for member_index in range(household_size):
            surname = surnames[person_index // 2]
            given_name = given[person_index % 2]
            first_member = member_index == 0
            agents.append(AgentConfig(
                id=f"resident_{person_index + 1:02d}",
                household_id=household_id,
                name=surname + given_name,
                surname=surname,
                sex=AgentSex.MALE if person_index % 2 == 0 else AgentSex.FEMALE,
                age=rng.randint(18, 48),
                home_node=home.id,
                work_node=work_node,
                assets=AgentAssets(
                    grain=round(rng.uniform(5, 12), 2) if first_member else 0.0,
                    coin=round(rng.uniform(1, 6), 2) if first_member else 0.0,
                    vegetable=round(rng.uniform(0, 2), 2) if first_member else 0.0,
                    cloth=round(rng.uniform(0, 2), 2) if first_member else 0.0,
                ),
            ))
            person_index += 1

    if len(agents) != 40 or len({agent.household_id for agent in agents}) != 30:
        raise ValueError(
            f"Brookvale seed must contain 40 residents in 30 households; "
            f"got {len(agents)} residents in {len({agent.household_id for agent in agents})} households"
        )
    return AgentsConfig(tuning=tuning, agents=agents)


def validate_xigu_town(result: XiguGenerationResult,
                        config: XiguGenerationConfig | None = None) -> list[str]:
    """Return structural errors; an empty list means all invariants passed."""
    cfg = config or XiguGenerationConfig(seed=result.seed)
    errors, nodes = [], result.spatial.nodes
    by_id = {n.id: n for n in nodes}
    homes = [n for n in nodes if n.attributes.get("residence")]
    fields = [n for n in nodes if n.type == NodeType.FIELD and not n.attributes.get("abstract_zone")]
    irrigated = [n for n in fields if n.attributes.get("field_kind") == "irrigated"]
    dry = [n for n in fields if n.attributes.get("field_kind") == "dry"]
    if len(homes) != cfg.residence_count:
        errors.append(f"expected {cfg.residence_count} residences, got {len(homes)}")
    unreachable_water_homes = [
        (home.id, round(result.distances_from_well.get(home.id, math.inf), 3))
        for home in homes
        if result.distances_from_well.get(home.id, math.inf) > 4.5
    ]
    if unreachable_water_homes:
        errors.append(
            f"residences must be reachable from the sole public well within the spring work window: "
            f"{unreachable_water_homes}"
        )
    if len(irrigated) != cfg.irrigated_field_count:
        errors.append(f"expected {cfg.irrigated_field_count} irrigated fields, got {len(irrigated)}")
    if len(dry) != cfg.dry_field_count:
        errors.append(f"expected {cfg.dry_field_count} dry fields, got {len(dry)}")
    for district, count in (("poor_district", cfg.poor_households),
                            ("common_district", cfg.common_households),
                            ("wealthy_district", cfg.wealthy_households)):
        actual = sum(n.district == district for n in homes)
        if actual != count:
            errors.append(f"{district}: expected {count}, got {actual}")
    landmarks = {"well", "market", "shrine", "elder_house",
                 "herbalist", "ferry", "mountain_shrine", "sacred_oak"}
    if landmarks - set(by_id):
        errors.append(f"missing landmarks: {sorted(landmarks - set(by_id))}")
    if len(result.distances_from_well) != len(nodes) - 1:
        errors.append("routable road graph is disconnected or deep mountain is exposed")
    if "deep_mountain" in result.distances_from_well:
        errors.append("deep mountain must not be routable during ordinary travel")
    if set(result.household_work_nodes) != {n.id for n in homes}:
        errors.append("every household must have candidate field assignments")
    if not by_id.get("deep_mountain") or not by_id["deep_mountain"].attributes.get("restricted"):
        errors.append("deep mountain must remain restricted")
    if "deep_mountain" not in result.resources or not result.resources["deep_mountain"].restricted:
        errors.append("deep mountain resource pool must remain restricted")
    return errors
