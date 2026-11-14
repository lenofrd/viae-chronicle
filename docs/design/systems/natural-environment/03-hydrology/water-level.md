# 水位与流速

## 1. 目的
定义水位和流速如何随降水、季节、上游来水、人类取水变化，以及上下游如何传播。

## 2. 核心概念
- **水位（water_level）**：相对基准水位的偏离量，可正可负。
- **平衡水位（equilibrium_level）**：当前气候和上游来水条件下，水位趋向的目标值。
- **变化速率上限**：水位每 tick 的变化量有上限，禁止瞬移。
- **流速**：随水位上升而增大，随淤积增加而减小。
- **传播**：上游水位变化向下游传播，有时滞和衰减。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| water_level | float | 当前水位偏离 |
| equilibrium_level | float | 平衡水位（派生量，不单独存也可） |
| flow_velocity | float | 当前流速 |
| turbidity | float | 浑浊度 |

## 4. 演化规则
### 4.1 平衡水位计算
规则：平衡水位
条件：每 tick
输入：降水量、季节系数、上游来水、人类取水量、蒸发量
效果：equilibrium_level = base_level

- precipitation_effect
- season_effect
- upstream_inflow_effect
- withdrawal_effect
- evaporation_effect

滞后：降水对平衡水位的影响有 1–2 tick 滞后
影响范围：按河段分别计算

### 4.2 水位向平衡回归
规则：水位变化
条件：每 tick
效果：delta = (equilibrium_level - water_level) * recovery_rate
若 |delta| > max_delta_per_tick：
delta = sign(delta) * max_delta_per_tick
water_level += delta
滞后：无（速率上限保证不瞬移）
影响范围：按河段

### 4.3 暴雨快速上升
规则：暴雨响应
条件：02-climate 产生暴雨极端天气事件
效果：equilibrium_level 快速上升
water_level 按 max_delta_per_tick 上限上升
若上游河段先涨，下游通过传播规则滞后上涨
滞后：上游→下游 propagation_delay tick
影响范围：受暴雨影响的河段及其下游

### 4.4 流速计算
规则：流速随水位和淤积调整
条件：水位或淤积变化后
效果：flow_velocity = base_velocity

- (1 + water_level_factor)
- (1 - siltation_factor)

受 max_delta_per_tick 约束
滞后：无
影响范围：按河段


### 4.5 上下游传播
规则：水位传播
条件：上游河段水位变化后
效果：下游河段在 propagation_delay tick 后
受到 upstream_level_change * propagation_attenuation 的影响
作为下游 equilibrium_level 的一部分
滞后：propagation_delay
影响范围：沿下游逐段传播

## 5. 事件类型
- `water_level_changed`：{segment_id, old, new, cause, rate_limited}
- `flow_velocity_changed`：{segment_id, old, new, cause}
- `turbidity_changed`：{segment_id, old, new, cause}
- `equilibrium_level_shifted`：{segment_id, old, new, cause}（可选，用于诊断）

## 6. 与其他系统的接口
- 读：02-climate 的降水、温度、季节系数、暴雨；人物系统的截水事件。
- 写：crossing.md 读水位判断可渡性；irrigation.md 读水位判断取水；siltation.md 读流速判断淤积；08-hazards 读水位和流速判断山洪风险。
- 因果链：暴雨 → 水位上升 → 流速上升 → 可渡性变化 → 山洪风险。

## 7. 地点参数占位
- 各河段 base_level、base_velocity
- max_delta_per_tick（水位、流速）
- recovery_rate（向平衡水位回归速率）
- 降水对平衡水位的影响系数
- 季节对平衡水位的影响系数
- 蒸发系数（温度相关）
- propagation_delay、propagation_attenuation
- water_level_factor（水位对流速的影响系数）
- siltation_factor（淤积对流速的影响系数）