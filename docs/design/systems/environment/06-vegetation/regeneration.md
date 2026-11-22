# 再生与退化

## 1. 目的
统一定义资源再生、采集压力累积、退化触发、恢复条件的通用机制，避免各资源类型各写一套。

## 2. 核心概念
- 再生：资源存量按再生速度恢复，受采集压力和季节影响。
- 采集压力：采集量累积形成的压力，降低再生速度。
- 退化：采集压力持续超过再生能力，资源存量下降，植被覆盖度下降，植被类型退化。
- 恢复：采集压力降低后，资源缓慢恢复；植被类型恢复需要更长时间。
- 不可逆/准不可逆：裸地恢复到阔叶林需要极长时间，视为准不可逆；古树被砍是真正不可逆。

## 3. 通用状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| resource_stock | float | 资源存量 |
| max_stock | float | 最大存量 |
| regeneration_rate | float | 基础再生速度 |
| current_regeneration | float | 当前实际再生速度（受压力影响） |
| gathering_pressure | float | 采集压力 |
| degradation_state | enum | 正常/轻度退化/重度退化/耗尽 |

## 4. 演化规则

### 4.1 当前再生速度
```
条件：每 tick
效果：current_regeneration = regeneration_rate
                            * pressure_factor(gathering_pressure)
                            * season_factor(season)
                            * vegetation_cover_factor(zone)
      采集压力越高、植被覆盖越低，再生越慢
滞后：无
影响范围：按资源点
```

### 4.2 资源存量更新
```
条件：每 tick
效果：stock += current_regeneration
      stock -= 本 tick 采集量
      stock 夹紧到 [0, max_stock]
滞后：再生渐进，不瞬移
影响范围：按资源点
```

### 4.3 采集压力更新
```
条件：每 tick
效果：gathering_pressure += 本 tick 采集量 * pressure_coefficient
      gathering_pressure -= decay_rate
      gathering_pressure 不低于 0
滞后：衰减慢于累积
影响范围：按资源点
```

### 4.4 退化状态迁移
```
条件：每季结算
效果：若 stock < max_stock * mild_threshold：
        degradation_state = 轻度退化
      若 stock < max_stock * severe_threshold：
        degradation_state = 重度退化
      若 stock = 0：
        degradation_state = 耗尽
      状态迁移生成 resource_degraded 事件
滞后：退化在持续采集若干季后显现
影响范围：按资源点
```

### 4.5 恢复状态迁移
```
条件：每季结算，采集压力低于恢复阈值
效果：若 stock > max_stock * recovery_threshold：
        degradation_state 恢复一级
      生成 resource_recovered 事件
滞后：恢复慢于退化
影响范围：按资源点
```

### 4.6 压力因子
```
压力因子 pressure_factor 是一个递减函数：
  gathering_pressure = 0        → 1.0（满再生）
  gathering_pressure = 阈值     → 0.5（再生减半）
  gathering_pressure = 2×阈值   → 0.1（几乎不再生）
具体曲线由地点参数提供。
```

### 4.7 植被覆盖对再生的影响
```
条件：所属分区 vegetation_cover 下降
效果：vegetation_cover_factor 下降
      资源再生速度进一步降低
      形成“植被退化 → 资源再生变慢 → 采集压力更大 → 植被更退化”的正反馈
滞后：按季
影响范围：按分区内所有资源点
```

## 5. 事件类型
- `resource_stock_changed`：{point_id, old, new, cause}
- `gathering_pressure_changed`：{point_id, old, new, cause}
- `regeneration_rate_changed`：{point_id, old, new, cause}
- `resource_degraded`：{point_id, old_state, new_state}
- `resource_recovered`：{point_id, old_state, new_state}
- `over_gathering_detected`：{point_id, pressure, threshold}

## 6. 与其他系统的接口
- 本文件是通用机制，herbs.md 和 firewood.md 引用它，不重复定义。
- forest-zones.md 提供 vegetation_cover_factor。
- 02-climate 提供 season_factor。
- 人物系统写入采集事件，本文件处理存量、压力、退化、恢复。
- 08-hazards 读退化状态触发滑坡和山洪风险上升。

## 7. 地点参数占位
- pressure_factor 曲线的参数（阈值、衰减系数）
- decay_rate（采集压力衰减速率）
- mild_threshold、severe_threshold（退化阈值）
- recovery_threshold（恢复阈值）
- season_factor（各季节对再生的影响）
- vegetation_cover_factor 曲线
- 各资源类型的 regeneration_rate、max_stock