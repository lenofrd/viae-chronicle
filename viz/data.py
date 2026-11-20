"""只读事件加载、筛选与面向 GUI 的事件投影。

这里只依赖公开观察层和事件 payload，不读取或导入内部状态模型。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

from vale.core.config_loader import load_config
from vale.observability.query import EventFilter, apply_filter
from vale.observability.render import ACTION_VERB, GATHER_DESC, payload_preview, render_event
from vale.observability.viewer import ReadonlyEventStore, date_str

WORLD_ID = "brookvale-town-001"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "legacy_events.json"
UNKNOWN = "事件未记录"

_PERSON_PREFIXES = (
    "agent", "child", "mother", "father", "spouse", "parent", "feeder",
    "debtor", "creditor", "deceased", "heir", "buyer", "seller",
    "from", "to", "head", "old_head", "new_head", "last_member",
    # 任务17 裁决 4.3：acquaintance_changed 的 observer/target 人名映射（payload 已带 *_name）
    "observer", "target",
)
_MEMBER_FIELDS = ("members", "members_after", "members_before")
# conflict_negotiation_round 用裸 id（initiator/responder），无 _id/_name 后缀，单独提取；
# 不并入 _PERSON_PREFIXES 循环，以免给前缀循环加裸字段兜底时误伤 season_changed 的裸 from/to。
_PERSON_BARE_ID_FIELDS = ("initiator", "responder")
# 人物索引键字段：payload.items() 一次遍历 + 集合成员检查即可提取，比 event_people 逐前缀 get 快
_PERSON_KEY_FIELDS = frozenset(
    ["agent_id", "agent_name", "participants", *_MEMBER_FIELDS]
    + [f"{prefix}_{suffix}" for prefix in _PERSON_PREFIXES for suffix in ("id", "name")]
    + list(_PERSON_BARE_ID_FIELDS)
)
_FOCUS_WORK = {"gather_success", "gather_fail", "gather_injury", "weave_success", "weave_fail"}
_FOCUS_SOCIAL = {
    "agent_born", "agent_married", "agent_died", "agent_incapacitated",
    "household_merged", "household_split", "household_head_changed",
    "household_dissolved", "birth_asset_transfer",
    # 任务15 债务纠纷：人与人的拉扯，归入关系与生命；交涉轮次也入 tab，避免会话完全消失。
    "conflict_started", "conflict_negotiation_round", "conflict_resolved", "conflict_broken",
    # 任务17 裁决 4.5：认知变化入关系 tab；量可控（每对最多一次 + 低频 forgot 清理）。
    "acquaintance_changed",
}
_FOCUS_ECONOMY = {
    "trade_executed", "market_day_summary", "inheritance_executed",
    "inheritance_escheated", "debt_formed", "debt_collected", "debt_repaid",
    "debt_defaulted", "debt_transferred", "debt_written_off", "debt_forgiven",
    "debt_collection_attempt", "birth_asset_transfer",
    "debt_deferred",  # 任务15：债务延期是经济行为
}
_WORK_ACTIONS = {"farm", "harvest", "collect_water", "hunt", "fish", "gather", "weave"}
_ECONOMY_ACTIONS = {"eat", "harvest", "borrow_grain", "trade", "buy", "sell"}
# 活动区间聚合：同一活动两次出现间隔 <= 该 tick 数则合并为一段（约一周）
DEFAULT_SPAN_GAP = 20
_TURNING_POINTS = {
    "agent_born": "出生 / 生育",
    "agent_married": "婚配",
    "agent_died": "死亡",
    "inheritance_executed": "继承",
    "inheritance_escheated": "继承",
    "debt_defaulted": "债务违约",
    "agent_migrated": "迁徙",
    "agent_relocated": "迁徙",
    "migration_completed": "迁徙",
    "household_moved": "迁徙",
    "household_split": "分家 / 迁徙",
    # 任务15 债务纠纷：交涉始末为关键转折；negotiation_round 轮次不加，避免每笔两次轮次刷屏。
    "conflict_started": "债务交涉",
    "conflict_resolved": "债务议和",
    "conflict_broken": "交涉破裂",
    "debt_deferred": "债务延期",
}


@dataclass(frozen=True)
class EventSource:
    """一个 fixture 或 SQLite 只读数据源。"""

    path: Path
    kind: str = "fixture"

    @classmethod
    def fixture(cls, path: Optional[str | Path] = None) -> "EventSource":
        return cls(Path(path) if path is not None else DEFAULT_FIXTURE, "fixture")

    @classmethod
    def database(cls, path: str | Path) -> "EventSource":
        return cls(Path(path), "db")

    @property
    def label(self) -> str:
        return f"{'事件库' if self.kind == 'db' else '样本'}：{self.path}"

    def load(self, since_id: Optional[int] = None) -> list[dict[str, Any]]:
        """加载全部事件；db 源可传 since_id 只取 id 更大的新增事件（增量跟随）。"""
        if self.kind == "db":
            store = ReadonlyEventStore(str(self.path))
            try:
                return store.after(since_id) if since_id is not None else store.all()
            finally:
                store.close()
        if self.kind != "fixture":
            raise ValueError(f"未知数据源类型：{self.kind}")
        events = _load_fixture(self.path)
        if since_id is not None:
            events = [event for event in events if int(event["id"]) > since_id]
        return events


@dataclass
class EventGroup:
    key: str
    label: str
    tick: int
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def event_ids(self) -> list[int]:
        return [int(e["id"]) for e in self.events]


@dataclass
class ActivitySpan:
    """同一主体同一活动的连续区间：「从 X 到 Y 一直在做某事」。"""

    subject: str
    subject_label: str
    label: str
    from_tick: int
    to_tick: int
    count: int
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def first_event_id(self) -> int:
        return int(self.events[0]["id"])


@dataclass
class AgentProfile:
    selector: str
    agent_id: str = ""
    name: str = ""
    birth_tick: Optional[int] = None
    death_tick: Optional[int] = None
    spouse_id: str = ""
    spouse_name: str = ""
    household_id: str = ""
    timeline: list[dict[str, Any]] = field(default_factory=list)

    @property
    def recent_events(self) -> list[dict[str, Any]]:
        return list(reversed(self.timeline[-10:]))


@dataclass
class HouseholdProfile:
    household_id: str
    head_id: str = ""
    head_name: str = ""
    home_node: str = ""
    work_node: str = ""
    members: list[dict[str, str]] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)

    @property
    def recent_events(self) -> list[dict[str, Any]]:
        return list(reversed(self.timeline[-10:]))


def _load_fixture(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, list):
        raise ValueError(f"样本文件必须是 JSON 事件数组：{path}")

    events: list[dict[str, Any]] = []
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ValueError(f"样本第 {index} 项不是事件对象")
        event = dict(item)
        try:
            event["id"] = int(event.get("id", index))
        except (TypeError, ValueError):
            event["id"] = index
        payload = event.get("payload", {})
        if isinstance(payload, str):
            try:
                event["payload"] = json.loads(payload) if payload else {}
                event["_payload_broken"] = False
                event["_raw_payload"] = None
            except json.JSONDecodeError:
                event["payload"] = {}
                event["_payload_broken"] = True
                event["_raw_payload"] = payload
        elif isinstance(payload, dict):
            event["_payload_broken"] = False
            event["_raw_payload"] = None
        else:
            event["payload"] = {}
            event["_payload_broken"] = True
            event["_raw_payload"] = json.dumps(payload, ensure_ascii=False)
        events.append(event)
    return events


@lru_cache(maxsize=1)
def world_config():
    return load_config(WORLD_ID)


def location_names(cfg=None) -> dict[str, str]:
    cfg = cfg or world_config()
    spatial = getattr(cfg, "spatial", None)
    return {node.id: node.name for node in getattr(spatial, "nodes", [])}


def calendar_label(tick: int, cfg=None) -> str:
    if cfg is None:
        return f"Tick {tick}"
    return date_str(tick, cfg)


def event_summary(event: dict[str, Any], names: Optional[dict[str, str]] = None) -> str:
    return render_event(event, names=names).text


def event_details(event: dict[str, Any]) -> str:
    """完整字段 JSON；坏 payload 同时保留原始片段。"""
    detail = {k: v for k, v in event.items() if not k.startswith("_")}
    if event.get("_payload_broken"):
        detail["payload_error"] = "JSON 解析失败"
        detail["raw_payload"] = event.get("_raw_payload")
    try:
        return json.dumps(detail, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return payload_preview(event, max_len=10000)


def _add_person(people: list[dict[str, str]], seen: set[str], id_value=None, name_value=None) -> None:
    person_id = "" if id_value is None else str(id_value)
    name = "" if name_value is None else str(name_value)
    if not person_id and not name:
        return
    key = person_id or f"name:{name}"
    if key in seen:
        if name:
            for person in people:
                if (person.get("id") or f"name:{person.get('name', '')}") == key and not person.get("name"):
                    person["name"] = name
        return
    seen.add(key)
    person: dict[str, str] = {}
    if person_id:
        person["id"] = person_id
    if name:
        person["name"] = name
    people.append(person)


def _add_person_value(people: list[dict[str, str]], seen: set[str], value: Any) -> None:
    if isinstance(value, dict):
        _add_person(people, seen, value.get("id") or value.get("agent_id"), value.get("name") or value.get("agent_name"))
    elif isinstance(value, (str, int)) and str(value):
        _add_person(people, seen, id_value=value)


def event_people(event: dict[str, Any]) -> list[dict[str, str]]:
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return []
    people: list[dict[str, str]] = []
    seen: set[str] = set()
    _add_person(people, seen, payload.get("agent_id"), payload.get("agent_name"))
    participants = payload.get("participants")
    if isinstance(participants, list):
        for participant in participants:
            _add_person_value(people, seen, participant)
    for prefix in _PERSON_PREFIXES:
        _add_person(
            people, seen, payload.get(f"{prefix}_id"), payload.get(f"{prefix}_name")
        )
    for bare in _PERSON_BARE_ID_FIELDS:
        _add_person_value(people, seen, payload.get(bare))
    for field_name in _MEMBER_FIELDS:
        members = payload.get(field_name)
        if isinstance(members, list):
            for member in members:
                _add_person_value(people, seen, member)
    return people


def event_households(event: dict[str, Any]) -> list[str]:
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return []
    return [
        str(value) for key, value in payload.items()
        if (key == "household_id" or key.endswith("_household_id"))
        and isinstance(value, (str, int)) and str(value)
    ]


def person_keys(event: dict[str, Any]) -> set[str]:
    """人物索引键：只收集 id/name 字符串，不构造 event_people 的字典列表（性能路径）。

    键覆盖 _matches_person 的匹配语义（人物 id 与 name 均作键）；供人物索引与增量追加使用。
    """
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return set()
    keys: set[str] = set()
    for key, value in payload.items():
        if key not in _PERSON_KEY_FIELDS:
            continue
        if isinstance(value, (str, int)):
            if str(value):
                keys.add(str(value))
        elif isinstance(value, dict):
            for nested in (value.get("id") or value.get("agent_id"),
                           value.get("name") or value.get("agent_name")):
                if nested:
                    keys.add(str(nested))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, (str, int)) and str(item):
                    keys.add(str(item))
                elif isinstance(item, dict):
                    for nested in (item.get("id") or item.get("agent_id"),
                                   item.get("name") or item.get("agent_name")):
                        if nested:
                            keys.add(str(nested))
    return keys


def build_person_index(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """一次遍历建「人物键 → 事件列表」索引；键为人物 id 或 name，覆盖 _matches_person 的匹配语义。

    供角色档案查询替代全库逐事件人物匹配；列表保持传入顺序（即事件 id 升序）。
    """
    index: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        for key in person_keys(event):
            bucket = index.get(key)
            if bucket is None:
                index[key] = [event]
            else:
                bucket.append(event)
    return index


def event_locations(event: dict[str, Any]) -> list[str]:
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return []
    direct = {"home", "work", "target", "resource", "market"}
    return [
        str(value) for key, value in payload.items()
        if (key in direct or key == "node" or key.endswith("_node"))
        and isinstance(value, (str, int)) and str(value)
    ]


def person_label(person: dict[str, str]) -> str:
    name = person.get("name", "")
    person_id = person.get("id", "")
    if name and person_id and name != person_id:
        return f"{name}（{person_id}）"
    return name or person_id or UNKNOWN


def _matches_person(event: dict[str, Any], selector: str) -> bool:
    return any(selector in (p.get("id"), p.get("name")) for p in event_people(event))


def filter_events(
    events: list[dict[str, Any]],
    *,
    agent: Optional[str] = None,
    event_types: Optional[Iterable[str]] = None,
    household: Optional[str] = None,
    location: Optional[str] = None,
    tick_from: Optional[int] = None,
    tick_to: Optional[int] = None,
) -> list[dict[str, Any]]:
    """组合筛选；tick 下界和上界均包含。"""
    if isinstance(event_types, str):
        event_types = [event_types]
    filtered = apply_filter(
        events,
        EventFilter(
            event_types=list(event_types) if event_types else None,
            tick_from=tick_from,
            tick_to=tick_to,
        ),
    )
    if agent:
        filtered = [event for event in filtered if _matches_person(event, agent)]
    if household:
        filtered = [event for event in filtered if household in event_households(event)]
    if location:
        filtered = [event for event in filtered if location in event_locations(event)]
    return filtered


def group_events(
    events: list[dict[str, Any]], granularity: str = "event", cfg=None, gap: int = DEFAULT_SPAN_GAP
) -> list[EventGroup]:
    """按逐事件、按天（tick）、按 tick/类型/主体事件簇或按主体活动区间分组。"""
    if granularity == "activity":
        groups: list[EventGroup] = []
        for index, span in enumerate(activity_spans(events, gap=gap)):
            label = (
                f"{span.subject_label} · {span.label} · "
                f"{calendar_label(span.from_tick, cfg)} – {calendar_label(span.to_tick, cfg)}"
            )
            groups.append(EventGroup(f"span:{index}", label, span.from_tick, span.events))
        return groups

    groups_by_key: dict[Any, EventGroup] = {}
    for event in sorted(events, key=lambda item: item.get("id", 0)):
        tick = int(event.get("tick", 0))
        event_type = str(event.get("event_type", "unknown"))
        if granularity == "event":
            key: Any = f"event:{event.get('id')}"
            label = f"#{event.get('id')} · {calendar_label(tick, cfg)}"
        elif granularity == "day":
            key = f"day:{tick}"
            label = calendar_label(tick, cfg)
        elif granularity == "cluster":
            people = event_people(event)
            person = people[0].get("id") or people[0].get("name", "") if people else ""
            households = event_households(event)
            household = households[0] if households else ""
            key = (tick, event_type, person, household)
            subject = person or household or "世界"
            label = f"{calendar_label(tick, cfg)} · {event_type} · {subject}"
        else:
            raise ValueError(f"未知时间粒度：{granularity}")
        group_key = key if granularity == "cluster" else str(key)
        if group_key not in groups_by_key:
            groups_by_key[group_key] = EventGroup(str(group_key), label, tick)
        groups_by_key[group_key].events.append(event)
    return list(groups_by_key.values())


# 活动区间聚合 ------------------------------------------------------------
# 非 agent_action_taken 事件的中文活动标签；未列出的类型直接用事件类型名。
_EVENT_ACTIVITY_LABELS = {
    "agent_born": "出生",
    "agent_died": "去世",
    "agent_married": "婚配",
    "agent_incapacitated": "失能",
    "agent_aged": "年长一阶",
    "health_recovered": "康复",
    "market_day_summary": "集市日",
    "weave_success": "织布",
    "weave_fail": "织布",
    "debt_formed": "举债",
    "debt_collected": "被催收",
    "debt_repaid": "还债",
    "debt_defaulted": "债务违约",
    "debt_deferred": "债务延期",
    "debt_collection_attempt": "被催收",
    "trade_executed": "交易",
    "acquaintance_changed": "结识",
    "impression_formed": "印象",
    "household_merged": "合户",
    "household_split": "分家",
    "household_head_changed": "换户主",
    "household_dissolved": "户绝",
    "conflict_started": "债务交涉",
    "conflict_negotiation_round": "债务交涉",
    "conflict_resolved": "债务议和",
    "conflict_broken": "交涉破裂",
}
# gather_* 事件按 payload.action 借用采集动词，与 agent_action_taken 的同动词合并成同一段
_GATHER_EVENT_TYPES = {"gather_success", "gather_fail", "gather_injury"}


def activity_label(event: dict[str, Any]) -> str:
    """事件的活动标签：动作走渲染层 ACTION_VERB，其余用事件类型映射。"""
    event_type = str(event.get("event_type", ""))
    payload = event.get("payload")
    if event_type == "agent_action_taken" and isinstance(payload, dict):
        action = str(payload.get("action", "") or "")
        return ACTION_VERB.get(action, action or "动作")
    if event_type in _GATHER_EVENT_TYPES and isinstance(payload, dict):
        gather = GATHER_DESC.get(str(payload.get("action", "") or ""))
        if gather:
            return gather[0]
    return _EVENT_ACTIVITY_LABELS.get(event_type, event_type or "未知")


def activity_spans(
    events: list[dict[str, Any]],
    subject: Optional[str] = None,
    gap: int = DEFAULT_SPAN_GAP,
) -> list[ActivitySpan]:
    """把时间线聚合成活动区间：同主体同活动、间隔 <= gap tick 合并为一段。

    - subject 给定：只聚合该人物的事件（人物档案「生平阶段」用）。
    - subject 为空：所有事件按首要人物（无人物则家庭，两者皆无则跳过）混排聚合。
    - 穿插的其他活动（如 rest/eat）不会打断一段；间隔超过 gap 才断段。
    """
    spans: list[ActivitySpan] = []
    open_spans: dict[tuple[str, str], ActivitySpan] = {}
    last_tick: dict[tuple[str, str], int] = {}
    for event in sorted(events, key=lambda item: item.get("id", 0)):
        people = event_people(event)
        if subject is not None:
            if not _matches_person(event, subject):
                continue
            person = _selector_person(event, subject)
            who = person.get("id") or subject
            display = person_label(person) if person else subject
        else:
            if people:
                who = people[0].get("id") or people[0].get("name", "")
                display = person_label(people[0])
            else:
                households = event_households(event)
                if not households:
                    continue  # 世界级事件（如天气）不进活动时间线，避免刷屏
                who = f"hh:{households[0]}"
                display = households[0]
            if not who:
                continue
        key = (str(who), activity_label(event))
        tick = int(event.get("tick", 0))
        previous = last_tick.get(key)
        if previous is not None and tick - previous <= gap:
            span = open_spans[key]
            span.to_tick = tick
            span.count += 1
            span.events.append(event)
        else:
            span = ActivitySpan(
                subject=str(who), subject_label=display, label=key[1],
                from_tick=tick, to_tick=tick, count=1, events=[event],
            )
            spans.append(span)
            open_spans[key] = span
        last_tick[key] = tick
    spans.sort(key=lambda span: (span.from_tick, span.to_tick, span.subject))
    return spans


def agent_activity_spans(
    events: list[dict[str, Any]], selector: str, gap: int = DEFAULT_SPAN_GAP
) -> list[ActivitySpan]:
    """单个人物的活动区间（角色档案「生平阶段」数据源）。"""
    return activity_spans(events, subject=selector, gap=gap)


def turning_point(event: dict[str, Any]) -> str:
    return _TURNING_POINTS.get(str(event.get("event_type", "")), "")


@dataclass
class BiographyEntry:
    """传记条目：人物一生的一件大事（关键转折或子女出生）。"""

    tick: int
    label: str
    text: str
    event_id: int


def biography(
    profile: AgentProfile, names: Optional[dict[str, str]] = None
) -> list[BiographyEntry]:
    """从人物时间线提取传记：关键转折 + 子女出生，按 tick、事件 id 排序。

    - 本人出生记为「出生」；timeline 中子女的出生事件记为「生育」。
    - 其余条目类别沿用 turning_point 映射（婚配/死亡/迁徙/继承/债务违约/交涉等）。
    """
    entries: list[BiographyEntry] = []
    agent_id = profile.agent_id or (profile.selector if not profile.selector.startswith("name:") else "")
    for event in profile.timeline:
        event_type = str(event.get("event_type", ""))
        label = turning_point(event)
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event_type == "agent_born":
            child_id = str(payload.get("child_id", "") or "")
            if agent_id and child_id == agent_id:
                label = "出生"
            else:
                label = "生育"
        if not label:
            continue
        entries.append(
            BiographyEntry(
                tick=int(event.get("tick", 0)),
                label=label,
                text=event_summary(event, names),
                event_id=int(event.get("id", 0)),
            )
        )
    entries.sort(key=lambda entry: (entry.tick, entry.event_id))
    return entries


def focus_category(event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type", ""))
    if event_type in _FOCUS_WORK:
        return "work"
    if event_type in _FOCUS_SOCIAL:
        return "social"
    if event_type in _FOCUS_ECONOMY:
        return "economy"
    if event_type == "agent_action_taken":
        payload = event.get("payload")
        action = payload.get("action", "") if isinstance(payload, dict) else ""
        if action in _WORK_ACTIONS:
            return "work"
        if action in _ECONOMY_ACTIONS:
            return "economy"
    return ""


def focus_events(events: list[dict[str, Any]], category: str) -> list[dict[str, Any]]:
    if category not in {"work", "social", "economy"}:
        raise ValueError(f"未知关注点类别：{category}")
    return [event for event in events if focus_category(event) == category]


def _selector_person(event: dict[str, Any], selector: str) -> dict[str, str]:
    return next(
        (person for person in event_people(event) if selector in (person.get("id"), person.get("name"))),
        {},
    )


def _members(payload: dict[str, Any], field_name: str) -> list[dict[str, str]]:
    people: list[dict[str, str]] = []
    seen: set[str] = set()
    value = payload.get(field_name)
    if isinstance(value, list):
        for member in value:
            _add_person_value(people, seen, member)
    return people


def agent_profile(
    events: list[dict[str, Any]],
    selector: str,
    index: Optional[dict[str, list[dict[str, Any]]]] = None,
) -> AgentProfile:
    """人物档案。index 为 build_person_index 产物时直接查索引，免去全库逐事件人物匹配。"""
    if index is not None:
        timeline = sorted(index.get(selector, []), key=lambda e: e.get("id", 0))
    else:
        timeline = [event for event in sorted(events, key=lambda e: e.get("id", 0)) if _matches_person(event, selector)]
    profile = AgentProfile(selector=selector, timeline=timeline)
    for event in timeline:
        if not profile.agent_id or not profile.name:
            # 仅头部信息未定时才做完整人物提取；时间线主体是十万条级，逐条提取代价高
            person = _selector_person(event, selector)
            profile.agent_id = profile.agent_id or person.get("id", "")
            profile.name = profile.name or person.get("name", "")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        event_type = event.get("event_type")
        if event_type == "agent_born" and profile.birth_tick is None:
            profile.birth_tick = int(payload.get("birth_tick", event.get("tick", 0)))
        if event_type == "agent_died":
            profile.death_tick = int(payload.get("died_tick", event.get("tick", 0)))
        if event_type == "agent_married":
            if selector in (payload.get("agent_id"), payload.get("agent_name")):
                profile.spouse_id = str(payload.get("spouse_id", ""))
                profile.spouse_name = str(payload.get("spouse_name", ""))
            elif selector in (payload.get("spouse_id"), payload.get("spouse_name")):
                profile.spouse_id = str(payload.get("agent_id", ""))
                profile.spouse_name = str(payload.get("agent_name", ""))
        households = event_households(event)
        if households:
            for key in ("new_household_id", "target_household_id", "household_id", "source_household_id"):
                if payload.get(key):
                    profile.household_id = str(payload[key])
                    break
            else:
                profile.household_id = households[-1]
    if not profile.name:
        profile.name = profile.agent_id or selector
    return profile


def household_profile(events: list[dict[str, Any]], household_id: str) -> HouseholdProfile:
    timeline = [
        event for event in sorted(events, key=lambda e: e.get("id", 0))
        if household_id in event_households(event)
    ]
    profile = HouseholdProfile(household_id=household_id, timeline=timeline)
    members: list[dict[str, str]] = []
    seen: set[str] = set()
    for event in timeline:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        for field_name in _MEMBER_FIELDS:
            for member in _members(payload, field_name):
                _add_person(members, seen, member.get("id"), member.get("name"))
        if payload.get("head_id"):
            profile.head_id = str(payload["head_id"])
            profile.head_name = str(payload.get("head_name", ""))
        if payload.get("new_head_id"):
            profile.head_id = str(payload["new_head_id"])
            profile.head_name = str(payload.get("new_head_name", ""))
        profile.home_node = str(payload.get("home_node", profile.home_node) or "")
        profile.work_node = str(payload.get("work_node", profile.work_node) or "")
    profile.members = members
    return profile


def unique_values(events: list[dict[str, Any]], extractor) -> list[str]:
    """供筛选框使用，保持首次出现顺序并去重。"""
    values: list[str] = []
    seen: set[str] = set()
    for event in events:
        for value in extractor(event):
            if value not in seen:
                seen.add(value)
                values.append(value)
    return values
