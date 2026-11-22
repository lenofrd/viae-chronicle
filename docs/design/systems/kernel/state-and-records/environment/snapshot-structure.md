# 快照结构

## 1. 目的
定义每个空间单元在某一 tick 的完整状态快照的格式，保证任何子系统的状态都能被记录和查询。

## 2. 核心概念
- 快照：某一 tick 某空间单元的全部状态变量值。
- 按子系统分组：快照内的状态变量按所属子系统分组，便于查询和诊断。
- 派生量：部分状态变量是派生量（如 expected_yield），快照可选择性记录，减少冗余。
- 趋势标记：每个变量带趋势（变好/变差/稳定），供人物决策和查询使用。
- 累积量：累积量单独记录，带当前值和阈值，便于判断是否接近触发。

## 3. 快照结构

### 3.1 顶层结构
```
{
  "world_id": "brookvale-town-001",
  "tick": 120,
  "unit_id": "field-east-1",
  "unit_type": "field",
  "subsystems": {
    "climate": {...},
    "hydrology": {...},
    "terrain": {...},
    "soil_and_fields": {...},
    "vegetation": {...},
    "fauna": {...},
    "hazards": {...}
  },
  "trends": {...},
  "accumulations": {...},
  "active_events": [...]
}
```

### 3.2 子系统状态
每个子系统的状态按该子系统声明的状态变量填充。示例：
```
"soil_and_fields": {
  "soil_moisture": 0.45,
  "fertility": 0.62,
  "crop_type": "rice",
  "growth_stage": "growth",
  "growth_health": 0.78,
  "pest_risk": 0.15,
  "irrigation_state": "adequate"
}
```

### 3.3 趋势标记
```
"trends": {
  "soil_moisture": "drying",
  "fertility": "stable",
  "pest_risk": "rising"
}
```
趋势取值：improving / stable / worsening / rising / falling / drying / wetting，具体枚举由子系统声明。

### 3.4 累积量
```
"accumulations": {
  "drought_accumulation": {"value": 12.5, "threshold": 20, "trend": "rising"},
  "flood_accumulation": {"value": 3.0, "threshold": 15, "trend": "stable"},
  "gathering_pressure_near_hill": {"value": 8.0, "threshold": 10, "trend": "rising"}
}
```

### 3.5 活跃事件
```
"active_events": [
  {"event_id": "evt-0456", "type": "drought_triggered", "severity": "mild"},
  {"event_id": "evt-0470", "type": "pest_outbreak", "severity": "moderate"}
]
```

### 3.6 不可逆标记
```
"irreversible_flags": {
  "ancient_tree_cut": false,
  "channel_form_changed": true,
  "fertility_degraded": false
}
```

## 4. 快照生成规则
```
条件：每 tick 结束
效果：对每个空间单元生成快照
      快照从事件流投影生成，不独立维护
      可配置快照频率（每 tick / 每 N tick / 仅关键 tick）
滞后：无
影响范围：所有空间单元
```

## 5. 快照存储
- 快照可按 tick 存，也可只存关键 tick（如灾害前后、人物行动前后）。
- 全量快照用于回放和诊断；增量快照用于节省存储。
- 第一版建议：全量快照每 N tick 存一次，关键事件前后强制存一次。

## 6. 与其他系统的接口
- 各子系统声明自己的状态变量和趋势枚举，本文件只定义容器结构。
- 查询接口按 `unit_id` + `tick` 取快照。
- 重放时从最近快照 + 后续事件还原当前状态。

## 7. 地点参数占位
- 快照频率（每 tick / 每 N tick）
- 关键事件列表（哪些事件前后强制存快照）
- 是否记录派生量
- 趋势枚举（各子系统声明）