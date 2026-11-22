# 关系变化

## 1. 目的
定义关系如何随事件渐进变化。关系有方向、有类型、有强度，下降快于上升，单次事件变化有限。

## 2. 核心概念
- **方向性**：A→B 和 B→A 分别计算，不对称。
- **渐进性**：单次事件对 trust、interest、strength 的影响有限。
- **下降快于上升**：背叛导致 trust 大幅下降，帮助导致 trust 小幅上升。
- **滞后**：关系变化有 1–3 tick 滞后，人物需要时间消化。
- **可逆性**：关系可修复，但恢复速度远慢于下降速度。
- **累积效应**：多次小帮助累积成信任，多次小摩擦累积成恩怨。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| trust | float -1–1 | A 对 B 的信任 |
| interest_weight | float 0–1 | A 认为与 B 交往的利益重要度 |
| strength | float 0–1 | 关系紧密程度 |
| obligation | float | 人情债/义务 |
| relation_type | enum | 关系类型 |

## 4. 演化规则

### 4.1 信任变化
```
条件：帮助、背叛、守约、违约、欺骗、坦诚
效果：正向事件 → trust 上升（幅度小）
      负向事件 → trust 下降（幅度大）
      受 max_delta_per_tick 约束
      生成 trust_changed 事件
滞后：1–3 tick
影响范围：关系边（单向）
```

### 4.2 利益权重变化
```
条件：合作收益、利益冲突、地位变化
效果：合作 → interest_weight 上升
      冲突 → interest_weight 下降
      受 max_delta_per_tick 约束
      生成 interest_weight_changed 事件
滞后：渐进
影响范围：关系边（单向）
```

### 4.3 关系强度变化
```
条件：互动频率、共同经历、冲突
效果：高频正向互动 → strength 上升
      长期无互动 → strength 缓慢下降
      冲突 → strength 下降
      受 max_delta_per_tick 约束
      生成 strength_changed 事件
滞后：渐进
影响范围：关系边（双向分别计算）
```

### 4.4 义务变化
```
条件：借还、帮助、违约
效果：欠人情 → obligation 上升
      还人情 → obligation 下降
      生成 obligation_changed 事件
滞后：按事件
影响范围：关系边
```

### 4.5 关系类型变化
```
条件：婚嫁、拜师、结怨、分家
效果：relation_type 变化
      可能新增或结束关系边
      生成 relation_formed / relation_ended 事件
滞后：按事件
影响范围：关系边
```

### 4.6 不对称性
```
条件：任何关系变化
效果：A→B 和 B→A 分别计算
      一方 trust 上升不代表另一方也上升
      一方欠人情不代表另一方也欠
      生成对称性检查记录（诊断用）
滞后：无
影响范围：关系边
```

## 5. 事件类型
- `trust_changed`：{from_agent, to_agent, old, new, cause}
- `interest_weight_changed`：{from_agent, to_agent, old, new, cause}
- `strength_changed`：{from_agent, to_agent, old, new, cause}
- `obligation_changed`：{from_agent, to_agent, old, new, cause}
- `relation_formed` / `relation_ended`：{from_agent, to_agent, relation_type, cause}

## 6. 与其他系统的接口
- 读：03-relationships 的所有关系事件；07-conflicts 的冲突结果；05-education 的共同学习经历。
- 写：03-relationships 的关系状态；07-conflicts 的冲突可能性；04-information 的传播路径。
- 因果链：帮助事件 → trust 小幅上升 → 多次帮助 → trust 显著上升 → 未来请求更容易被接受。

## 7. 地点参数占位
- trust 上升和下降的速率（下降快于上升）
- interest_weight 变化速率
- strength 变化速率和衰减速率
- obligation 压力系数
- 关系变化的滞后 tick 范围
- 关系类型变化的条件