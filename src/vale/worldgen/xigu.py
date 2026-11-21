"""Deterministic procedural generator for 溪谷镇 — 组合门面（P4 分段）。

自然段（worldgen.nature）产出地形栅格、资源池目录与静态植被/栖息地描述；
聚落段（worldgen.settlement）读取自然结果，在其上布点、建路网与距离矩阵、
派发家庭候选田块；本模块只做组合与整体校验（ADR 009 §3）。

This is an edge adapter: runtime output uses the existing SpatialConfig schema.
Coordinates: x west->east, y south->north. The north-south river is at x~=0;
all residences and fields are on its east bank. Farms, settlement, woodland,
shallow forest, and the Qingming mountain extend eastward in that order.

Resource pool parameters live in the pool catalogue (ResourcePoolSpec) and are
passed to the runtime via LoadedConfig.resources; node attributes no longer
carry resource_* copies (P4 ruling, 2026-11-21).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from config.schema.agents import AgentAssets, AgentConfig, AgentSex, AgentsConfig, GatheringActionTuning
from config.schema.spatial_units import NodeType, SpatialConfig, SpatialNode

from vale.worldgen import settlement
from vale.worldgen.nature import ResourcePoolSpec, TerrainCell, VegetationProfile, generate_nature
from vale.worldgen.settlement import RoadSegment


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


@dataclass
class XiguGenerationResult:
    spatial: SpatialConfig
    terrain: list[TerrainCell]
    resources: dict[str, ResourcePoolSpec]
    roads: list[RoadSegment]
    distances_from_well: dict[str, float]
    pairwise_travel_tu: dict[str, dict[str, float]]
    household_work_nodes: dict[str, list[str]]
    seed: int
    # P4：静态植被与栖息地描述（纯数据表达，无行为；P5 种群系统消费）。
    vegetation: dict[str, VegetationProfile] = field(default_factory=dict)

    def node(self, node_id: str) -> SpatialNode:
        for node in self.spatial.nodes:
            if node.id == node_id:
                return node
        raise KeyError(node_id)


def generate_xigu_town(config: XiguGenerationConfig | None = None, base_spatial: SpatialConfig | None = None):
    """Generate geography, seasonal resource pools, least-cost roads and route matrices."""
    cfg = config or XiguGenerationConfig()
    nature = generate_nature(cfg)
    nodes = settlement.make_nodes(cfg, base_spatial)
    roads = settlement.make_roads(nodes, cfg)
    routable_ids = {n.id for n in nodes if not n.attributes.get("restricted")}
    matrix = settlement.distance_matrix(routable_ids, roads)
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
    edges = settlement.build_distance_edges(roads)
    return XiguGenerationResult(SpatialConfig(nodes=nodes, distance_edges=edges),
                                nature.terrain, nature.resources, roads, distances, matrix,
                                household_work_nodes, cfg.seed, nature.vegetation)


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
                    # 开局口粮 50–70 石：覆盖全镇约 180 天到首个秋收（tick 181+），
                    # 消除第一年春荒死潮 [调参][临时值，待长期方案复核]
                    grain=round(rng.uniform(50, 70), 2) if first_member else 0.0,
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
