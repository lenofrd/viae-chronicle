# 事件流规范

## 1. 目的
定义事件流中每个事件的统一格式、字段、因果链、排序规则，保证任何子系统的事件都能被记录、查询、重放。

## 2. 核心概念
- 事件：一个不可变的状态变化记录。
- 事件 ID：全局唯一，按 tick 和 sequence 生成。
- 因果链：每个事件带 `cause_event_id`，指向父事件。
- 事件类型：由各子系统声明，本子系统不枚举。
- payload：事件特有字段，按事件类型不同而不同。
- 外部注入：标记 `external: true`，没有父事件。

## 3. 事件统一格式
```
{
  "event_id": "evt-000123",
  "world_id": "brookvale-town-001",
  "tick": 120,
  "sequence": 5,
  "event_type": "soil_moisture_changed",
  "subsystem": "soil_and_fields",
  "unit_id": "field-east-1",
  "agent_id": null,
  "cause_event_id": "evt-000118",
  "external": false,
  "reversibility_class": "reversible",
  "rate_limited": false,
  "payload": {
    "old_value": 0.50,
    "new_value": 0.45,
    "reason": "evaporation"
  },
  "timestamp": "2026-11-14T10:00:00Z"
}
```

## 4. 字段说明

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| event_id | string | 是 | 全局唯一，格式 `evt-{tick}-{sequence}` |
| world_id | string | 是 | 世界标识 |
| tick | int | 是 | 逻辑时间 |
| sequence | int | 是 | 同 tick 内排序，从 0 递增 |
| event_type | string | 是 | 事件类型，由子系统声明 |
| subsystem | string | 是 | 所属子系统 |
| unit_id | string? | 条件 | 空间单元 ID，环境事件必填 |
| agent_id | string? | 条件 | 人物 ID，人物相关事件必填 |
| cause_event_id | string? | 条件 | 父事件 ID，外部注入为 null |
| external | bool | 是 | 是否外部注入 |
| reversibility_class | enum | 是 | reversible / quasi-irreversible / irreversible |
| rate_limited | bool | 是 | 是否被速率上限夹紧 |
| payload | dict | 是 | 事件特有字段 |
| timestamp | string | 是 | 写入时的机器时间，用于诊断，不参与逻辑 |

## 5. 排序规则
- 按 `tick` 升序。
- 同 tick 内按 `sequence` 升序。
- `sequence` 由事件写入顺序决定，保证同 tick 内因果顺序可追溯。

## 6. 因果链规则
- 每个事件（外部注入除外）必须有 `cause_event_id`。
- 父事件必须在子事件之前写入（同 tick 内 sequence 更小，或 tick 更早）。
- 因果链可跨 tick、跨子系统。
- 外部注入事件 `external: true`，`cause_event_id: null`，作为新因果链的起点。

## 7. 事件写入规则
```
条件：任何子系统产生事件
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
- 事件流不可修改。若需修正，写入新事件 `correction`，带 `corrects_event_id` 指向被修正事件。
- 查询时以最新修正为准，但原始事件仍保留。

## 9. 与其他系统的接口
- 01–09 各子系统产生事件时调用本规范。
- 查询接口按 `tick`、`unit_id`、`agent_id`、`event_type`、`subsystem` 过滤。
- 重放时按 `tick` + `sequence` 顺序回放事件。

## 10. 地点参数占位
- 事件流存储后端（SQLite / PostgreSQL / 文件）
- 事件保留策略（全量保留 / 冷热分离）
- 事件归档规则