# 水权轮灌

## 1. 目的
定义水权轮灌制度的规则、执行、违反、冲突和变迁。水权是 Brookvale 最核心的制度之一，因为旱季水少，上游和下游利益天然对立。

## 2. 核心概念
- **轮灌顺序**：谁先灌、灌多久、隔多久再灌。
- **水权依据**：地契、祖传约定、里正裁定、村民共识。
- **上游与下游**：上游人家有地理优势，下游人家依赖规则约束上游。
- **截水**：上游私自堵渠、多引水，是最常见的违反。
- **执行者**：里正、长老、轮灌约定的见证人。
- **惩罚**：公开批评、罚粮、罚工、限制下次灌水。

## 3. 规则内容（地点参数可配）
| 字段 | 说明 |
|---|---|
| rotation_order | 轮灌顺序（按地块/户） |
| rotation_interval | 轮灌间隔（tick） |
| water_quota_per_turn | 每轮灌水量或时长 |
| priority_rules | 特殊情况优先（如秧苗期优先） |
| enforcement_authority | 执行者 |
| punishment_ladder | 违反的惩罚阶梯 |

## 4. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| rule_content | dict | 轮灌顺序、间隔、配额 |
| enforcement_state | enum | 严格执行/宽松执行/名存实亡 |
| challenge_count | int | 被挑战次数 |
| looseness | float 0–1 | 松动程度 |
| current_rotation_position | int | 当前轮到谁 |
| violations_this_season | list | 本季违反记录 |

## 5. 演化规则

### 5.1 轮灌执行
```
条件：每 tick，水位低于灌溉阈值且进入轮灌期
效果：按 rotation_order 分配灌水
      当前轮到的人家获得 water_quota_per_turn
      生成 irrigation_turn_started / irrigation_turn_ended 事件
滞后：无
影响范围：依赖同一水源的田地
```

### 5.2 违反判定：截水
```
条件：上游人家在非自己轮次引水，或超过配额
效果：生成 rule_violated 事件
      violation_type = 截水
      severity 按超量程度
      若被下游发现（信息传播），触发冲突
滞后：发现可能有滞后（下游看到水少才发现）
影响范围：上游和下游人家
```

### 5.3 执行与惩罚
```
条件：rule_violated 事件被确认
效果：执行者按 punishment_ladder 惩罚
      生成 rule_enforced 事件
      惩罚公开或私下执行
      违反者关系恶化，执行者可能被记恨
滞后：调解和惩罚需要时间
影响范围：违反者、执行者、见证人
```

### 5.4 制度挑战
```
条件：违反者不服、或多人认为规则不公
效果：生成 rule_challenged 事件
      挑战可能成功（制度松动）或失败（制度强化）
      挑战成功则 looseness 上升
滞后：反复挑战后才可能修改
影响范围：制度及社区
```

### 5.5 制度松动与修改
```
条件：looseness 超过阈值，且多人支持修改
效果：生成 rule_modified 事件
      轮灌顺序、配额、惩罚方式可能改变
      改变后 looseness 重置
滞后：长期过程
影响范围：制度及所有依赖水源的人家
```

### 5.6 旱季强化执行
```
条件：旱情触发（08-hazards）
效果：enforcement_state 趋严
      违反惩罚加重
      生成 enforcement_state_changed 事件
滞后：旱情持续时
影响范围：制度及所有人家
```

## 6. 事件类型
- `irrigation_turn_started` / `irrigation_turn_ended`：{turn_holder, water_amount, tick}
- `rule_violated`：{rule_id: water-rights, violator_id, violation_type: 截水, severity, witnesses}
- `rule_enforced`：{rule_id: water-rights, violator_id, enforcer_id, punishment, location}
- `rule_challenged`：{rule_id: water-rights, challenger_id, reason, outcome}
- `rule_modified`：{rule_id: water-rights, old_content, new_content, cause}
- `enforcement_state_changed`：{rule_id: water-rights, old, new, cause}

## 7. 与其他系统的接口
- 读：03-hydrology 的水位和灌溉条件；08-hazards 的旱情；03-relationships 的上游下游关系；04-information 的违规是否被发现。
- 写：07-conflicts 的水权纠纷；03-relationships 的结怨或包庇；05-education 的水权规训；人物系统读规则约束做决策。
- 因果链：旱季水位下降 → 轮灌紧张 → 上游截水 → 下游发现 → 争执 → 里正调解 → 惩罚或包庇 → 关系变化 → 制度松动或强化。

## 8. 地点参数占位
- rotation_order、rotation_interval、water_quota_per_turn
- priority_rules
- enforcement_authority
- punishment_ladder（批评/罚粮/罚工/限制灌水）
- 初始 looseness 和 enforcement_state
- 挑战成功和制度修改的阈值
- 旱季执行强化的系数