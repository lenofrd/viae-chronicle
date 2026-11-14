# 人文事件流规范

## 1. 目的
定义人文事件流中每个事件的统一格式、字段、因果链、排序规则，保证制度、关系、信息、阶层、仪式事件都能被记录、查询、重放。

## 2. 核心概念
- **人文事件**：一个不可变的人文状态变化记录。
- **事件 ID**：全局唯一，按 tick 和 sequence 生成，与自然事件共享 ID 空间。
- **因果链**：每个事件带 `cause_event_id`，指向父事件。
- **方向性**：关系事件带 `from_agent` 和 `to_agent`。
- **外部注入**：标记 `external: true`，没有父事件。

## 3. 人文事件统一格式
```
{
  "event_id": "evt-0120-5",
  "world_id": "brookvale-town-001",
  "tick": 120,
  "sequence": 5,
  "event_type": "trust_changed",
  "subsystem": "relationships",
  "agent_id": "agent-li-001",
  "from_agent": "agent-li-001",
  "to_agent": "agent-wang-002",
  "rule_id": null,
  "info_id": null,
  "cause_event_id": "evt-0118-3",
  "external": false,
  "reversibility_class": "reversible",
  "payload": {
    "old_value": 0.3,
    "new_value": 0.4,
    "reason": "helped_with_harvest"
  },
  "timestamp": "2026-11-14T10:00:00Z"
}
```

## 4. 字段说明

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| event_id | string | 是 | 全局唯一，与自然事件共享 ID 空间 |
| world_id | string | 是 | 世界标识 |
| tick | int | 是 | 逻辑时间 |
| sequence | int | 是 | 同 tick 内排序 |
| event_type | string | 是 | 事件类型 |
| subsystem | string | 是 | 所属人文子系统 |
| agent_id | string? | 条件 | 主体角色，角色相关事件必填 |
| from_agent | string? | 条件 | 关系事件的方向起点 |
| to_agent | string? | 条件 | 关系事件的方向终点 |
| rule_id | string? | 条件 | 制度事件必填 |
| info_id | string? | 条件 | 信息事件必填 |
| cause_event_id | string? | 条件 | 父事件，外部注入为 null |
| external | bool | 是 | 是否外部注入 |
| reversibility_class | enum | 是 | reversible / quasi-irreversible / irreversible |
| payload | dict | 是 | 事件特有字段 |
| timestamp | string | 是 | 写入时的机器时间 |

> observer_id 等角色相关标识不列入顶层统一字段，按事件类型放入 payload（如 07-conflicts 的 observer_learning 事件在 payload 中带 observer_id）。

## 5. 排序规则
- 按 `tick` 升序。
- 同 tick 内按 `sequence` 升序。
- `sequence` 由事件写入顺序决定。
- 人文事件和自然事件共享同一个 sequence 空间，保证跨领域因果顺序可追溯。

## 6. 因果链规则
- 每个事件（外部注入除外）必须有 `cause_event_id`。
- 父事件必须在子事件之前写入。
- 因果链可跨子系统、跨领域（人文事件可以是自然事件的子事件，反之亦然）。
- 外部注入事件 `external: true`，作为新因果链起点。

## 7. 事件写入规则
```
条件：任何人文子系统产生事件
效果：分配 event_id（tick + sequence）
      填写统一字段
      填写 payload
      标记 reversibility_class
      标记 external
      追加到事件流
      不可修改、不可删除
滞后：无
影响范围：全局事件流
```

## 8. 事件修正
- 事件流不可修改。若需修正，写入新事件 `correction`，带 `corrects_event_id`。
- 查询时以最新修正为准，原始事件保留。

## 9. 与其他系统的接口
- 01–08 各人文子系统产生事件时调用本规范。
- 查询接口按 `tick`、`agent_id`、`from_agent`、`to_agent`、`rule_id`、`info_id`、`event_type`、`subsystem` 过滤。
- 重放时按 `tick` + `sequence` 顺序回放。

## 10. 地点参数占位
- 事件流存储后端
- 事件保留策略
- 事件归档规则