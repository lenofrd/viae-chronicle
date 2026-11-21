from types import SimpleNamespace

from vale.core.pools import ResourcePoolSpec, ResourcePoolState
from vale.domains.environment.resources import EcologyModule
from vale.domains.wildlife.wildlife import WildlifeModule


class EventSink:
    def __init__(self):
        self.events = []

    def append(self, tick, event_type, payload):
        self.events.append((tick, event_type, payload))


def _world(specs: dict[str, ResourcePoolSpec]):
    node = SimpleNamespace(id="foothill_woodland", attributes={})
    return SimpleNamespace(
        config=SimpleNamespace(
            spatial=SimpleNamespace(nodes=[node]),
            resources=dict(specs),
        ),
        state=SimpleNamespace(
            environment=SimpleNamespace(
                climate=SimpleNamespace(season=SimpleNamespace(value="winter")),
                terrain_cells={},
                ecological_resources={}),
            wildlife=SimpleNamespace(pools={}),
        ),
        event_log=EventSink(), current_tick=0,
    )


def test_ecology_initializes_resource_pools_and_regenerates_with_caps():
    world = _world({"foothill_woodland": ResourcePoolSpec(
        resource_id="foothill_woodland", resource_type="firewood",
        current_stock=9, max_stock=10,
        regeneration_per_tick=5, extraction_limit_per_tick=3,
        seasonal_weights={"winter": .2},
    )})
    module = EcologyModule()
    module.step(world)
    pool = world.state.environment.ecological_resources["foothill_woodland"]
    assert isinstance(pool, ResourcePoolState)
    assert pool.current_stock == 9
    assert world.event_log.events[-1][1] == "resource_pool_initialized"
    world.current_tick = 1
    module.step(world)
    assert pool.current_stock == 10  # 再生封顶到 max_stock
    assert world.event_log.events[-1][1] == "resource_regenerated"
    assert pool.harvested_this_tick == 0


def test_wildlife_pools_are_routed_to_the_wildlife_owner():
    """P4 裁决①：fish/game 池由动物域引导与再生，环境域不碰。"""
    world = _world({
        "foothill_woodland": ResourcePoolSpec(
            resource_id="foothill_woodland", resource_type="firewood",
            current_stock=9, max_stock=10, regeneration_per_tick=1),
        "river_town": ResourcePoolSpec(
            resource_id="river_town", resource_type="fish",
            current_stock=90, max_stock=140, regeneration_per_tick=5,
            seasonal_weights={"winter": .35}),
        "game_trail": ResourcePoolSpec(
            resource_id="game_trail", resource_type="game",
            current_stock=45, max_stock=70, regeneration_per_tick=1.8),
    })
    EcologyModule().step(world)
    WildlifeModule().step(world)
    assert set(world.state.environment.ecological_resources) == {"foothill_woodland"}
    assert set(world.state.wildlife.pools) == {"river_town", "game_trail"}
    assert world.state.wildlife.pools["river_town"].current_stock == 90
    # 初始化事件载荷字段序与 ResourcePoolState 字段序一致（等价口径）
    init_events = [e for e in world.event_log.events if e[1] == "resource_pool_initialized"]
    assert [e[2]["resource_node"] for e in init_events] == [
        "foothill_woodland", "river_town", "game_trail"]
    assert list(init_events[1][2]["pool"]) == list(
        ResourcePoolState.model_fields)
    world.current_tick = 1
    EcologyModule().step(world)
    WildlifeModule().step(world)
    regen = {e[2]["resource_node"]: e[2]["amount"] for e in world.event_log.events
             if e[1] == "resource_regenerated" and e[0] == 1}
    assert regen["river_town"] == round(5 * .35, 6)  # 冬季权重再生
    assert world.state.wildlife.pools["river_town"].current_stock == round(90 + 5 * .35, 6)


def test_restricted_pool_never_regenerates_or_pays_out():
    from vale.contracts.resources import ResourceService

    world = _world({"deep_mountain": ResourcePoolSpec(
        resource_id="deep_mountain", resource_type="rare_medicinal_and_event",
        current_stock=0, max_stock=0, regeneration_per_tick=0,
        extraction_limit_per_tick=0, restricted=True)})
    EcologyModule().step(world)
    pool = world.state.environment.ecological_resources["deep_mountain"]
    assert pool.restricted
    granted = ResourceService.harvest(world, "deep_mountain", 5.0, agent_id="a1")
    assert granted == 0.0
    refused = world.event_log.events[-1][2]
    assert refused["reason"] == "restricted"  # P4：受限拒绝 reason 专列
    assert not [e for e in world.event_log.events if e[1] == "resource_regenerated"]


def test_harvest_on_unregistered_pool_raises_in_catalog_world():
    """P4 收敛：有池目录的世界，未登记池不再原额给付（直接调用所有者即抛错）。"""
    import pytest

    from vale.domains.environment.resources import harvest_from_pool

    world = _world({"foothill_woodland": ResourcePoolSpec(
        resource_id="foothill_woodland", resource_type="firewood",
        current_stock=5, max_stock=10)})
    EcologyModule().step(world)
    with pytest.raises(ValueError, match="unregistered"):
        harvest_from_pool(world, "well", 3.0)
