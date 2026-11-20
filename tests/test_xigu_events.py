from types import SimpleNamespace

from vale.modules.xigu_events import XiguEventsModule


class EventSink:
    def __init__(self):
        self.events = []
    def append(self, tick, event_type, payload):
        self.events.append({"id": len(self.events)+1, "tick": tick, "event_type": event_type, "payload": payload})
    def all(self):
        return list(self.events)


def test_seasonal_ritual_and_flood_damage_are_emergent_events():
    field = SimpleNamespace(id="irrigated_field_01", type=SimpleNamespace(value="field"),
        attributes={"field_kind":"irrigated","flood_damage_threshold_mm":18,
                    "flood_damage_ratio":.12,"flood_risk":.7})
    world = SimpleNamespace(
        current_tick=10,
        config=SimpleNamespace(spatial=SimpleNamespace(nodes=[field]),
            agents=SimpleNamespace(tuning=SimpleNamespace(market=SimpleNamespace(
                market_day_interval=10, market_day_offset=0, market_node="market")))),
        state=SimpleNamespace(
            climate=SimpleNamespace(season=SimpleNamespace(value="spring"),season_progress=.01,
                year=1,day=1,precipitation_mm=30,drought_state=SimpleNamespace(value="none")),
            field_growth={"irrigated_field_01":50},field_fertility={},
            ecological_resources={},agents={}),
        event_log=EventSink(),
    )
    module=XiguEventsModule()
    module.step(world)
    kinds={e["event_type"] for e in world.event_log.events}
    assert "market_day_opened" in kinds
    assert "seasonal_ritual" in kinds
    assert "field_flood_damage" in kinds
    assert world.state.field_growth["irrigated_field_01"] < 50
