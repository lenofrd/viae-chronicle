# 变化速率

## 1. 目的
定义每个状态变量的变化速率上限，保证环境不会瞬移，变化是渐进的。所有子系统的状态更新都受本机制约束。

## 2. 核心概念
- 变化速率上限（max_delta_per_tick）：一个变量在一个 tick 内允许的最大变化量。
- 速率上限可以是绝对值，也可以是相对值（如不超过当前值的 X%）。
- 分方向上限：部分变量上升和下降的上限不同（如山洪上涨快、消退慢）。
- 季节性上限：慢变量按季结算时，用 max_delta_per_season。
- 违反处理：若规则计算出的变化量超过上限，夹紧到上限，并记录 `rate_limited: true`。

## 3. 声明格式
每个子系统在自己的状态变量表里声明：
```
| 变量 | max_delta_per_tick | max_delta_per_season | 备注 |
```

## 4. 演化规则

### 4.1 应用速率上限
```
条件：每 tick，任一状态变量更新后
效果：delta = new_value - old_value
      若 |delta| > max_delta_per_tick：
        new_value = old_value + sign(delta) * max_delta_per_tick
        标记 rate_limited = true
      若变量有分方向上限：
        上升用 rise_limit，下降用 fall_limit
滞后：无
影响范围：所有状态变量
```

### 4.2 季节性变量
```
条件：每季结算的慢变量
效果：用 max_delta_per_season 替代 max_delta_per_tick
滞后：无
影响范围：地力、植被覆盖度、淤积等慢变量
```

### 4.3 违反记录
```
条件：速率上限被触发
效果：生成 rate_limited 标记，附在事件 payload 上
      开发模式下打印警告
      生产模式下静默夹紧，但记录次数供诊断
滞后：无
影响范围：所有状态变量
```

## 5. 事件类型
- 本机制不单独生成事件，只给其他事件附加 `rate_limited: bool` 字段。
- 诊断事件：`rate_limit_hit`：{unit_id, variable, attempted_delta, applied_delta}

## 6. 与其他系统的接口
- 所有子系统在更新状态后调用本机制。
- 10-state-and-records 的快照记录 `rate_limited` 标记。
- 实现时由 `core/dynamics.py` 提供 `apply_rate_limit(old, new, max_delta)` 函数。

## 7. 地点参数占位
- 各状态变量的 max_delta_per_tick、max_delta_per_season
- 分方向上限（若适用）
- 默认上限（未声明时使用）