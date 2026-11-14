# 人文快照结构

## 1. 目的
定义角色和关系在某一 tick 的人文状态快照的格式，保证制度、关系、信息、阶层、仪式状态都能被记录和查询。

## 2. 核心概念
- **角色快照**：某一 tick 某角色的全部人文状态。
- **关系快照**：某一 tick 某条关系边的状态。
- **制度快照**：某一 tick 某制度的执行状态。
- **按子系统分组**：快照内的状态变量按所属子系统分组，便于查询和诊断。
- **趋势标记**：每个变量带趋势（变好/变差/稳定），供人物决策和查询使用。
- **累积量**：松动度、舆论强度、恩怨强度等累积量单独记录，带当前值和阈值。

## 3. 角色快照结构

### 3.1 顶层结构
```
{
  "world_id": "brookvale-town-001",
  "tick": 120,
  "agent_id": "agent-li-001",
  "subsystems": {
    "relationships": {...},
    "information": {...},
    "education": {...},
    "stratification": {...},
    "rituals_beliefs": {...}
  },
  "trends": {...},
  "accumulations": {...},
  "active_events": [...]
}
```

### 3.2 子系统状态示例
```
"relationships": {
  "outgoing": {
    "agent-wang-002": {
      "relation_type": "neighbor",
      "trust": 0.4,
      "interest_weight": 0.6,
      "strength": 0.5,
      "obligation": 2.0
    }
  },
  "incoming": {
    "agent-wang-002": {
      "relation_type": "neighbor",
      "trust": 0.3,
      "interest_weight": 0.5,
      "strength": 0.5,
      "obligation": -1.0
    }
  }
}
```

### 3.3 趋势标记
```
"trends": {
  "trust_agent-wang-002": "rising",
  "reputation": "stable",
  "upward_aspiration": "rising"
}
```

### 3.4 累积量
```
"accumulations": {
  "upward_aspiration": {"value": 0.7, "threshold": 0.8},
  "outward_aspiration": {"value": 0.3, "threshold": 0.8},
  "grudge_agent-zhao-003": {"value": 0.6, "threshold": 0.7}
}
```

### 3.5 活跃事件
```
"active_events": [
  {"event_id": "evt-0118-3", "type": "conflict_started", "parties": ["agent-li-001", "agent-zhao-003"]},
  {"event_id": "evt-0120-1", "type": "ritual_scheduled", "ritual_type": "mountain-god"}
]
```

## 4. 关系快照结构
```
{
  "world_id": "brookvale-town-001",
  "tick": 120,
  "from_agent": "agent-li-001",
  "to_agent": "agent-wang-002",
  "relation_type": "neighbor",
  "trust": 0.4,
  "interest_weight": 0.6,
  "strength": 0.5,
  "obligation": 2.0,
  "history": ["evt-0045-2", "evt-0089-1"],
  "last_interaction_tick": 118
}
```

## 5. 制度快照结构
```
{
  "world_id": "brookvale-town-001",
  "tick": 120,
  "rule_id": "water-rights",
  "rule_content": {...},
  "enforcement_state": "strict",
  "looseness": 0.3,
  "challenge_count": 2,
  "last_enforced_tick": 115,
  "recent_violations": [...]
}
```

## 6. 快照生成规则
```
条件：每 tick 结束，或关键事件前后
效果：对角色、关系、制度生成快照
      快照从事件流投影生成，不独立维护
      可配置快照频率
滞后：无
影响范围：所有角色、关系、制度
```

## 7. 快照存储
- 角色快照：每 N tick 全量，关键事件前后强制。
- 关系快照：按需生成，或每 N tick 全量。
- 制度快照：每次制度事件前后强制。
- 第一版建议：角色快照每 10 tick 一次，关系快照每 30 tick 一次，制度快照事件驱动。

## 8. 与其他系统的接口
- 各子系统声明自己的状态变量和趋势枚举，本文件只定义容器结构。
- 查询接口按 `agent_id` + `tick` 取角色快照，按 `from_agent` + `to_agent` + `tick` 取关系快照。
- 重放时从最近快照 + 后续事件还原当前状态。

## 9. 地点参数占位
- 快照频率
- 关键事件列表
- 是否记录派生量
- 趋势枚举（各子系统声明）