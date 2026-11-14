# 空间之间的移动

## 1. 目的
定义人物在不同社会空间之间移动时的社会约束、移动决策、移动记录。移动不只是物理位移，还涉及“是否合适去”“去了会遇到谁”“去了会被怎么看”。

## 2. 核心概念
- **移动意图**：人物为什么去某场所（日常劳作、取水、议事、找人、看热闹、逃避）。
- **社会约束**：去某场所是否合适、是否需要身份许可、是否会被议论。
- **在场人物**：到场所后遇到谁，影响人物行为和心理。
- **移动记录**：移动事件带出发地、目的地、原因、途中遭遇、到达后的场景。
- **移动失败**：访问被拒、场所关闭、人物改变主意。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| current_space | string | 当前所在场所 |
| movement_intent | string? | 当前移动意图 |
| last_movement_tick | int? | 上次移动 tick |
| movement_history | list | 近期移动记录（用于决策和叙事） |

## 4. 演化规则

### 4.1 移动意图生成
```
条件：每 tick，人物决策
效果：根据需求、制度、关系、信息，生成移动意图
      意图包含：目的地、原因、预期活动
      生成 movement_intent_formed 事件
滞后：无
影响范围：人物
```

### 4.2 社会约束检查
```
条件：人物有移动意图
效果：检查目的地 access_rules
      检查人物身份、关系、时段是否合适
      检查是否会遇到不想见的人
      检查是否会被议论
      不满足则移动失败或改变目的地
      生成 movement_blocked_social 事件
滞后：无
影响范围：人物和目的地
```

### 4.3 移动执行
```
条件：社会约束通过
效果：人物从当前场所移动到目的地
      更新 current_space
      更新目的地的 current_occupants
      生成 movement_completed 事件
      事件带出发地、目的地、原因、途中遭遇
滞后：按距离和时间成本
影响范围：人物和两个场所
```

### 4.4 到达后的场景
```
条件：移动完成
效果：记录到达时的场景快照
      在场人物、正在发生的事、场所状态
      作为人物后续行动的上下文
滞后：无
影响范围：人物和目的地
```

### 4.5 移动失败
```
条件：社会约束不满足或途中遭遇阻断
效果：移动失败，人物留在原地或改去别处
      生成 movement_failed 事件
      记录原因（访问被拒/场所关闭/遇到不想见的人/途中遭遇）
滞后：无
影响范围：人物
```

### 4.6 移动与信息
```
条件：人物移动
效果：人物携带自己的知识、传闻、意图到新场所
      在新场所可能传播信息
      见 04-information
滞后：无
影响范围：人物和两个场所
```

## 5. 事件类型
- `movement_intent_formed`：{agent_id, destination, reason, expected_activity}
- `movement_blocked_social`：{agent_id, destination, reason}
- `movement_completed`：{agent_id, from_space, to_space, reason, scene_snapshot}
- `movement_failed`：{agent_id, destination, reason}
- `arrival`：{agent_id, space_id, occupants, ongoing_activity}

## 6. 与其他系统的接口
- 读：01-buildings 的 access_rules 和 state；02-institutions 的制度约束；03-relationships 的关系状态；04-information 的信息携带。
- 写：01-buildings 更新 current_occupants；04-information 读信息传播；人物系统读移动结果更新状态；记录系统读移动事件作为人生场景锚点。
- 因果链：移动意图 → 社会约束检查 → 移动执行/失败 → 到达场景 → 人物行动 → 信息传播。

## 7. 地点参数占位
- 各场所之间的移动时间和路径
- 社会约束的具体规则（谁能去哪、什么时候能去）
- 移动意图的生成规则（需求、制度、关系、信息的权重）
- 移动失败后的替代行为规则