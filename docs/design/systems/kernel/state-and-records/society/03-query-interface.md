# 人文查询接口

## 1. 目的
定义按角色、关系、制度、信息、时间范围检索人文快照和事件的接口，供人物系统、记录系统、API 层调用。本文件定义接口语义，不定义具体传输格式。

## 2. 核心概念
- **查询维度**：角色、关系、制度、信息、时间范围、事件类型、子系统。
- **角色快照查询**：取某一 tick 某角色的人文状态。
- **关系快照查询**：取某一 tick 某条关系边的状态。
- **人生查询**：取某角色从出生到当前的所有人文事件。
- **关系历史查询**：取某对角色之间的关系变化历史。
- **制度历史查询**：取某制度的执行、违反、挑战、修改历史。
- **信息查询**：取某条信息的产生、传播、变形、消散历史。
- **增量查询**：从某个 tick 之后的新事件。

## 3. 查询接口清单

### 3.1 角色快照查询
```
get_agent_snapshot(world_id, agent_id, tick) -> AgentSnapshot
```
返回指定 tick 的角色人文快照。

```
get_current_agent_snapshot(world_id, agent_id) -> AgentSnapshot
```
返回当前 tick 的角色快照。

### 3.2 关系查询
```
get_relation_snapshot(world_id, from_agent, to_agent, tick) -> RelationSnapshot
```
返回指定 tick 的关系快照。

```
get_relation_history(world_id, from_agent, to_agent,
                     since_tick=None, until_tick=None) -> List[Event]
```
返回某对角色之间的关系变化历史。

```
get_all_relations(world_id, agent_id) -> List[RelationSnapshot]
```
返回某角色的所有出边和入边关系。

### 3.3 人生查询
```
get_agent_life(world_id, agent_id, since_tick=None, until_tick=None) -> List[Event]
```
返回该角色作为主体或受体的所有人文事件，按时间排序。

```
get_agent_life_summary(world_id, agent_id) -> LifeSummary
```
返回人生摘要：关键转折、关系变化、制度冲突、意图暗线。

### 3.4 制度查询
```
get_rule_history(world_id, rule_id, since_tick=None, until_tick=None) -> List[Event]
```
返回某制度的执行、违反、挑战、修改历史。

```
get_rule_snapshot(world_id, rule_id, tick) -> RuleSnapshot
```
返回某制度在指定 tick 的快照。

### 3.5 信息查询
```
get_info_history(world_id, info_id, since_tick=None, until_tick=None) -> List[Event]
```
返回某条信息的产生、传播、变形、验证、消散历史。

```
get_agent_known_info(world_id, agent_id, tick) -> List[InfoItem]
```
返回某角色在指定 tick 掌握的所有信息。

### 3.6 因果链查询
```
get_causal_chain(world_id, event_id, depth=5) -> CausalTree
```
返回该事件的父事件链和子事件树，跨人文和自然领域。

### 3.7 增量查询
```
get_events_incremental(world_id, since_tick, since_sequence=0) -> List[Event]
```
增量拉取，用于流式消费。

### 3.8 聚合查询
```
aggregate_events(world_id, agent_id=None, rule_id=None,
                 event_type=None, since_tick=None, until_tick=None,
                 group_by="tick" | "event_type",
                 metric="count" | "sum" | "avg") -> AggregationResult
```
按时间窗口或事件类型聚合统计。

## 4. 查询规则
- 所有查询必须带 `world_id`。
- 事件查询默认按 `tick` + `sequence` 升序。
- 时间范围 `since_tick` 包含，`until_tick` 不包含。
- 人生查询返回该角色作为 `agent_id`、`from_agent`、`to_agent` 或出现在 payload 的 `affected_agents` 中的所有事件。
- 关系查询必须指定方向（`from_agent` → `to_agent`）。
- 因果链查询有深度限制，防止无限递归。

## 5. 查询性能约定
- 事件流按 `world_id` + `tick` 索引。
- 角色查询按 `agent_id` 索引。
- 关系查询按 `from_agent` + `to_agent` 索引。
- 制度查询按 `rule_id` 索引。
- 信息查询按 `info_id` 索引。
- 快照按 `world_id` + `agent_id` + `tick` 索引。

## 6. 与其他系统的接口
- 人物系统调用 `get_current_agent_snapshot` 获取人文状态，调用 `get_agent_known_info` 获取信息。
- 记录系统调用 `get_agent_life` 和 `get_agent_life_summary` 生成人生档案。
- API 层把本接口暴露为 HTTP 端点，路径带 `world_id`。
- 诊断系统调用 `get_causal_chain` 追溯异常。

## 7. 地点参数占位
- 查询默认 limit
- 因果链最大深度
- 聚合查询的时间窗口粒度
- 索引配置