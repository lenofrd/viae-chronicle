# 空间传播

## 1. 目的
定义一个空间单元的变化如何沿连接传播到其他单元，有时滞和衰减。所有跨单元影响都受本机制约束。

## 2. 核心概念
- 传播路径：沿空间骨架的连接（河段上下游、山层深度、邻接田地、邻接分区）。
- 传播时滞（propagation_delay）：变化从源单元传到目标单元需要的 tick。
- 传播衰减（propagation_attenuation）：变化强度在传播中减弱，0–1 之间。
- 传播方向：单向（上游→下游）或双向（邻接田地）。
- 传播停止条件：衰减到阈值以下、目标单元不满足接收条件、源变化消失。
- 多路径叠加：一个单元可能同时从多个上游接收影响，叠加计算。

## 3. 声明格式
每条连接声明：
```
propagation_delay: int
propagation_attenuation: float 0–1
propagation_direction: one-way / two-way
propagation_condition: 可选，满足才传播
```

## 4. 演化规则

### 4.1 传播调度
```
条件：源单元状态变化
效果：对每条出边：
        scheduled_tick = 当前 tick + propagation_delay
        scheduled_delta = source_delta * propagation_attenuation
        记录到目标单元的 pending_influence
滞后：propagation_delay
影响范围：沿连接传播
```

### 4.2 目标单元接收
```
条件：到达 scheduled_tick
效果：target_value += scheduled_delta
      受目标单元的 max_delta_per_tick 约束
      若多个上游同时传播，叠加计算
滞后：已由调度处理
影响范围：目标单元
```

### 4.3 多路径叠加
```
条件：目标单元有多个上游
效果：所有 pending_influence 在到期 tick 叠加
      叠加后应用速率上限
      若叠加导致超阈值，触发目标单元的事件
滞后：各路径分别按自己的 delay
影响范围：目标单元
```

### 4.4 传播条件
```
条件：连接声明了 propagation_condition
效果：仅当条件满足时传播
      如“只有水位超过阈值才向下游传播”
      条件不满足则丢弃 scheduled_influence
滞后：无
影响范围：按连接
```

### 4.5 传播停止
```
条件：衰减后影响低于阈值
效果：停止继续传播
      不生成事件
滞后：无
影响范围：按路径
```

### 4.6 传播与因果关系
```
条件：传播导致目标单元变化
效果：目标单元的变化事件 cause 字段指向源事件
      形成可追溯的因果链
滞后：无
影响范围：所有传播
```

## 5. 事件类型
- 传播本身不单独生成事件，目标单元的变化事件带上 `cause_event_id`。
- 诊断事件：`propagation_scheduled`：{source_unit, target_unit, variable, delta, arrive_tick}

## 6. 与其他系统的接口
- 03-hydrology 的上游→下游水位传播、04-terrain 的滑坡向下传播、06-vegetation 的退化沿分区传播、08-hazards 的山洪/火灾传播，都引用本机制。
- 实现时由 `core/dynamics.py` 提供 `schedule_propagation()`、`apply_pending_influences()` 函数。

## 7. 地点参数占位
- 各连接的 propagation_delay、propagation_attenuation、propagation_direction
- 各连接的 propagation_condition（若适用）
- 传播停止阈值