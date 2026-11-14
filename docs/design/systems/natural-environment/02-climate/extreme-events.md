# 极端天气

## 1. 目的
定义暴雨、连阴雨、霜冻、酷热等极端天气的触发条件、持续时间和影响范围。极端天气是事件，不是常驻状态。

## 2. 核心概念
- **极端天气类型**：暴雨、连阴雨、霜冻、酷热。
- **触发条件**：依赖前期累积状态（如湿度、温度、旱涝累积），不是纯随机。
- **持续时间**：每种极端天气有最短/最长持续 tick。
- **影响范围**：全局或局部（如山区暴雨、镇域霜冻）。
- **叠加效应**：极端天气可以叠加旱涝累积，加速成灾。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| active_extreme_events | list | 当前活跃的极端天气事件 |
| event_duration | int | 已持续 tick |
| event_intensity | float | 强度 |

## 4. 演化规则
### 4.1 触发
规则：极端天气触发
条件：每 tick 检查
暴雨：humidity > 阈值 且 flood_accumulation > 阈值 且 随机通过
连阴雨：连续 N tick 降水 > 阈值
霜冻：季节为冬/春 且 temperature < 阈值
酷热：季节为夏 且 temperature > 阈值 且 湿度 < 阈值
效果：生成 extreme_weather_started 事件
设置持续时间和强度
滞后：触发条件依赖前期累积，不是瞬时
影响范围：按配置，全局或局部

### 4.2 持续与结束
条件：每 tick
效果：event_duration += 1
若 event_duration >= max_duration 或 结束条件满足：
生成 extreme_weather_ended 事件
移除活跃事件
滞后：无
影响范围：同触发

### 4.3 叠加影响
规则：极端天气叠加旱涝
条件：极端天气活跃期间
效果：暴雨加速 flood_accumulation
酷热/连阴雨加速 drought_accumulation
霜冻影响作物状态
滞后：见旱涝累积规则
影响范围：按空间单元

## 5. 事件类型
- `extreme_weather_started`：{type, intensity, duration, affected_units}
- `extreme_weather_ended`：{type, duration}
- `extreme_weather_impact`：{type, affected_subsystem, effect}

## 6. 与其他系统的接口
- 读：weather 的温度、降水、湿度；drought-flood 的累积量。
- 写：
  - 03-hydrology 读暴雨，调整水位和流速。
  - 05-soil-and-fields 读霜冻/酷热，调整作物状态。
  - 04-terrain 读暴雨，调整滑坡风险。
  - 08-hazards 读极端天气，触发山洪、火灾等。
  - 02-distance-and-time 读极端天气，修正通行条件。
- 因果链：极端天气事件作为父事件，影响后续环境事件和人物事件。

## 7. 地点参数占位
- 各极端天气的触发条件（湿度/温度/累积量阈值）
- 持续时间范围（min/max tick）
- 强度范围
- 影响范围（全局/局部）
- 叠加系数（对旱涝累积的加速倍率）
- 空间单元的触发差异（如山区更容易暴雨）