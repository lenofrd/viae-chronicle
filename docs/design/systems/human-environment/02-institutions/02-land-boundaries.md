# 地界

## 1. 目的
定义地界制度的规则、执行、违反、冲突和变迁。地界是田地的边界，边界模糊或越界是常见纠纷来源。

## 2. 核心概念
- **地界标志**：田埂、界石、树木、水沟。
- **地契**：记录田地归属和边界的文书（第一版可简化为里正记录和村民共识）。
- **越界**：犁过界、多占一垄、移动界石。
- **边界模糊**：年久失修、灾害冲毁、地界标志消失。
- **执行者**：里正、地契见证人、邻地双方。
- **惩罚**：恢复原界、赔粮、公开道歉、罚工。

## 3. 规则内容（地点参数可配）
| 字段 | 说明 |
|---|---|
| boundary_markers | 地界标志类型 |
| deed_records | 地契记录（第一版简化为里正记录） |
| violation_types | 越界类型（犁过界/移动界石/多占） |
| enforcement_authority | 执行者 |
| punishment_ladder | 惩罚阶梯 |

## 4. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| rule_content | dict | 地界规则 |
| enforcement_state | enum | 严格执行/宽松执行/名存实亡 |
| challenge_count | int | 被挑战次数 |
| looseness | float 0–1 | 松动程度 |
| disputed_boundaries | list | 当前有争议的地界 |
| violations_this_season | list | 本季违反记录 |

## 5. 演化规则

### 5.1 地界检查
```
条件：每季，或地界标志变化后
效果：检查地界标志是否完好
      若标志消失或模糊，标记 disputed_boundaries
      生成 boundary_marker_changed 事件
滞后：标志损坏后若干季才发现
影响范围：相邻田地
```

### 5.2 违反判定：越界
```
条件：人物犁地、种植、收割时越过地界
效果：生成 rule_violated 事件
      violation_type = 越界
      severity 按越界程度
      若被邻地发现，触发冲突
滞后：发现可能有滞后
影响范围：相邻田地双方
```

### 5.3 执行与惩罚
```
条件：rule_violated 事件被确认
效果：执行者按 punishment_ladder 惩罚
      要求恢复原界
      生成 rule_enforced 事件
      双方关系恶化或调解缓和
滞后：调解需要时间
影响范围：越界者、被越界者、执行者
```

### 5.4 制度挑战
```
条件：一方认为地界不公、或地契记录有误
效果：生成 rule_challenged 事件
      挑战可能成功（重新划界）或失败（维持原界）
滞后：反复挑战后才可能修改
影响范围：制度及相邻田地
```

### 5.5 灾害后地界模糊
```
条件：山洪冲毁田埂、滑坡掩埋界石
效果：地界标志消失
      disputed_boundaries 增加
      触发地界纠纷
滞后：灾害后立即
影响范围：受灾田地
```

## 6. 事件类型
- `boundary_marker_changed`：{field_id, marker_type, old, new, cause}
- `rule_violated`：{rule_id: land-boundaries, violator_id, violation_type: 越界, severity, witnesses}
- `rule_enforced`：{rule_id: land-boundaries, violator_id, enforcer_id, punishment, location}
- `rule_challenged`：{rule_id: land-boundaries, challenger_id, reason, outcome}
- `boundary_dispute_started` / `boundary_dispute_resolved`：{field_a, field_b, cause, outcome}

## 7. 与其他系统的接口
- 读：自然环境 05-soil-and-fields 的田地状态；08-hazards 的灾害后果（冲毁田埂）；03-relationships 的相邻关系；04-information 的越界是否被发现。
- 写：07-conflicts 的地界冲突；03-relationships 的结怨或调解；05-education 的地界规训；人物系统读规则约束做决策。
- 因果链：山洪冲毁田埂 → 地界模糊 → 双方各执一词 → 争执 → 里正调解 → 重新划界或维持原界 → 关系变化。

## 8. 地点参数占位
- boundary_markers 类型
- deed_records 的初始记录
- violation_types 和 severity 分级
- enforcement_authority
- punishment_ladder（恢复原界/赔粮/道歉/罚工）
- 初始 looseness 和 enforcement_state
- 灾害后地界模糊的概率