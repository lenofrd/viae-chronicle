from types import SimpleNamespace

from vale.modules.ecology import EcologyModule


class EventSink:
    def __init__(self):
        self.events = []

    def append(self, tick, event_type, payload):
        self.events.append((tick, event_type, payload))


def test_ecology_initializes_resource_pools_and_regenerates_with_caps():
    node = SimpleNamespace(id="river_town", attributes={
        "resource_stock": 9, "resource_max_stock": 10,
        "resource_regeneration_per_tick": 5,
        "resource_extraction_limit_per_tick": 3,
        "resource_seasonal_weights": {"winter": .2},
        "resource_type": "fish",
    })
    world = SimpleNamespace(
        config=SimpleNamespace(spatial=SimpleNamespace(nodes=[node])),
        state=SimpleNamespace(environment=SimpleNamespace(
            climate=SimpleNamespace(season=SimpleNamespace(value="winter")),
            ecological_resources={})),
        event_log=EventSink(), current_tick=0,
    )
    module = EcologyModule()
    module.step(world)
    assert world.state.environment.ecological_resources["river_town"]["current_stock"] == 9
    assert world.event_log.events[-1][1] == "resource_pool_initialized"
    world.current_tick = 1
    module.step(world)
    assert world.state.environment.ecological_resources["river_town"]["current_stock"] == 10
    assert world.event_log.events[-1][1] == "resource_regenerated"
    assert world.state.environment.ecological_resources["river_town"]["harvested_this_tick"] == 0
