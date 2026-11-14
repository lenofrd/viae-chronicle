# 查询接口

## 1. 目的
定义按人物、空间单元、资源、时间范围检索快照和事件的接口，供人物系统、记录系统、API 层调用。本文件定义接口语义，不定义具体传输格式（HTTP/函数调用由 api 层决定）。

## 2. 核心概念
- 查询维度：人物、空间单元、资源点、时间范围、事件类型、子系统。
- 快照查询：取某一 tick 某单元的状态。
- 事件查询：取某单元/人物/资源在时间范围内的事件流。
- 人生查询：取某人物从出生到当前的所有相关事件。
- 聚合查询：按时间窗口聚合统计（如“某片田过去一年的收成”）。
- 增量查询：从某个 tick 之后的新事件，用于流式消费。

## 3. 查询接口清单

### 3.1 快照查询
```
get_snapshot(world_id, unit_id, tick) -> Snapshot
```
返回指定 tick 的快照。若该 tick 无快照，从最近快照 + 事件重放生成。

```
get_current_snapshot(world_id, unit_id) -> Snapshot
```
返回当前 tick 的快照。

### 3.2 事件查询
```
get_events(world_id, unit_id=None, agent_id=None, event_type=None,
           subsystem=None, since_tick=None, until_tick=None,
           limit=None) -> List[Event]
```
按条件过滤事件，按 tick + sequence 排序。

```
get_events_incremental(world_id, since_tick, since_sequence=0) -> List[Event]
```
增量拉取，用于流式消费。

### 3.3 人物人生查询
```
get_agent_life(world_id, agent_id, since_tick=None, until_tick=None) -> List[Event]
```
返回该人物作为主体或受体的所有事件，按时间排序。

```
get_agent_life_summary(world_id, agent_id) -> LifeSummary
```
返回人生摘要：关键转折、里程碑、统计（如“一生经历 3 次旱灾、2 次迁徙”）。

### 3.4 空间单元历史查询
```
get_unit_history(world_id, unit_id, variable=None,
                 since_tick=None, until_tick=None) -> List[Event]
```
返回某空间单元的状态变化事件，可按变量过滤。

### 3.5 资源查询
```
get_resource_history(world_id, point_id, since_tick=None, until_tick=None) -> List[Event]
```
返回资源点的存量、采集压力、退化/恢复事件。

### 3.6 因果链查询
```
get_causal_chain(world_id, event_id, depth=5) -> CausalTree
```
返回该事件的父事件链和子事件树，用于追溯“这件事为什么发生、导致了什么”。

### 3.7 聚合查询
```
aggregate_events(world_id, unit_id=None, agent_id=None,
                 event_type=None, since_tick=None, until_tick=None,
                 group_by="tick" | "season" | "event_type",
                 metric="count" | "sum" | "avg") -> AggregationResult
```
按时间窗口或事件类型聚合统计。

## 4. 查询规则
- 所有查询必须带 `world_id`，不允许跨世界查询。
- 事件查询默认按 `tick` + `sequence` 升序。
- 时间范围 `since_tick` 包含，`until_tick` 不包含。
- 人物人生查询返回该人物作为 `agent_id` 或出现在 payload 的 `affected_agents` 中的所有事件。
- 因果链查询有深度限制，防止无限递归。
- 聚合查询只对数值型 payload 字段做 sum/avg。

## 5. 查询性能约定
- 事件流按 `world_id` + `tick` 索引。
- 人物查询按 `agent_id` 索引。
- 空间单元查询按 `unit_id` 索引。
- 资源查询按 `point_id` 索引。
- 快照按 `world_id` + `unit_id` + `tick` 索引。

## 6. 与其他系统的接口
- 人物系统调用 `get_current_snapshot` 感知环境，调用 `get_events` 感知近期事件。
- 记录系统调用 `get_agent_life` 和 `get_agent_life_summary` 生成人生档案。
- API 层把本接口暴露为 HTTP 端点，路径带 `world_id`。
- 诊断系统调用 `get_causal_chain` 追溯异常。

## 7. 地点参数占位
- 查询默认 limit
- 因果链最大深度
- 聚合查询的时间窗口粒度（tick / season）
- 索引配置（存储层实现）