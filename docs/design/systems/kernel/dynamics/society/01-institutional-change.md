# 制度变迁

## 1. 目的
定义制度如何松动、被挑战、被修改。制度不会因一次纠纷就改，要反复冲突、有人推动、有人反对才可能变化。

## 2. 核心概念
- **松动度（looseness）**：0–1，制度被违反和执行不力的累积程度。
- **挑战（challenge）**：角色或群体公开质疑制度合理性。
- **推动者/反对者**：制度变迁有支持方和反对方。
- **阈值**：松动度或挑战次数超过阈值才可能修改。
- **滞后**：制度修改滞后于冲突累积，不是即时反应。
- **可逆性**：制度修改可逆（可以改回去），但需要再次累积冲突。
- **路径依赖**：制度修改受历史影响，不会完全推翻重来。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| looseness | float 0–1 | 松动度 |
| challenge_count | int | 累计挑战次数 |
| support_count | int | 支持修改的人数 |
| opposition_count | int | 反对修改的人数 |
| enforcement_state | enum | 严格执行/宽松执行/名存实亡 |

## 4. 演化规则

### 4.1 松动度累积
```
条件：每次违反未被有效惩罚，或执行不力
效果：looseness += violation_impact * (1 - enforcement_effect)
      受 max_delta_per_tick 约束
滞后：累积过程
影响范围：制度
```

### 4.2 松动度消退
```
条件：长期严格执行，无违反
效果：looseness -= recovery_rate
      looseness 不低于 0
滞后：长期过程
影响范围：制度
```

### 4.3 挑战累积
```
条件：角色公开质疑制度
效果：challenge_count += 1
      support_count 和 opposition_count 按角色立场变化
      生成 rule_challenged 事件
滞后：按挑战时机
影响范围：制度及社区
```

### 4.4 制度修改判定
```
条件：looseness > threshold 且 support_count > opposition_count
效果：生成 rule_modified 事件
      规则内容改变
      looseness 重置为较低值
      challenge_count 重置
滞后：条件满足后 3–7 tick
影响范围：制度及所有相关角色
```

### 4.5 制度强化
```
条件：looseness 超过阈值但 opposition_count > support_count
效果：制度不修改，反而强化执行
      enforcement_state 趋严
      生成 enforcement_state_changed 事件
滞后：按判定
影响范围：制度
```

### 4.6 路径依赖
```
条件：制度修改
效果：新规则受旧规则影响
      不会完全推翻，通常是在旧规则基础上调整
      生成 rule_modified（old_content, new_content）
滞后：无
影响范围：制度
```

## 5. 事件类型
- `looseness_changed`：{rule_id, old, new, cause}
- `rule_challenged`：{rule_id, challenger_id, reason, support, opposition}
- `rule_modified`：{rule_id, old_content, new_content, cause}
- `enforcement_state_changed`：{rule_id, old, new, cause}

## 6. 与其他系统的接口
- 读：02-institutions 的制度状态；07-conflicts 的冲突事件；03-relationships 的支持/反对网络。
- 写：02-institutions 的规则内容；07-conflicts 的冲突结果；人物系统的规则约束。
- 因果链：旱季截水反复发生 → 惩罚不力 → looseness 上升 → 多人挑战 → support > opposition → 轮灌规则修改。

## 7. 地点参数占位
- violation_impact（违反对松动度的影响）
- recovery_rate（严格执行时的恢复速率）
- 修改阈值
- 修改滞后的 tick 范围
- 支持/反对的判定规则