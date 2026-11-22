# 可渡性与渡口

## 1. 目的
定义河段的可渡性如何随水位变化，渡口和浅滩如何影响通行，以及渡河风险如何计算。

## 2. 核心概念
- **可渡性（crossing_state）**：可涉水 / 需渡船 / 不可渡 三档。
- **渡口**：渡船点，需要船和人，有通行时间和风险。
- **浅滩**：可涉水点，水位低时可直接过，水位高时不可过。
- **渡河风险**：随水位、流速上升而增加，可能触发溺水、失足、货物损失事件。
- **渡口关闭**：水位超过阈值时渡口关闭，生成事件。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| crossing_state | enum | 可涉水/需渡船/不可渡 |
| crossing_points_status | dict | 各渡口/浅滩状态（开放/受限/关闭） |
| crossing_risk | float | 渡河风险 |

## 4. 演化规则
### 4.1 可渡性判定
规则：可渡性随水位变化
条件：水位变化后
效果：若 water_level < wade_threshold：
crossing_state = 可涉水
若 wade_threshold <= water_level < boat_threshold：
crossing_state = 需渡船
若 water_level >= boat_threshold：
crossing_state = 不可渡
滞后：crossing_state 切换有 1 tick 滞后（避免抖动）
影响范围：按河段

### 4.2 渡口状态
规则：渡口开放/关闭
条件：水位变化后
效果：浅滩：水位超过 wade_threshold 则关闭
渡船：水位超过 boat_threshold 或流速超过 threshold 则关闭
生成 crossing_point_status_changed 事件
滞后：无
影响范围：按渡口

### 4.3 渡河风险
规则：渡河风险计算
条件：人物尝试渡河时
效果：crossing_risk = f(water_level, flow_velocity, crossing_type)
浅滩风险高于渡船；汛期风险高于平时
风险作为人物决策输入，也作为事件触发概率
滞后：无
影响范围：按渡口

### 4.4 渡河事件
规则：渡河遭遇
条件：人物渡河且随机通过风险判定
效果：生成渡河遭遇事件：溺水、失足、货物损失、延误
事件成为人物心理迁移和后续事件的父事件
滞后：无
影响范围：按人物和渡口

## 5. 事件类型
- `crossing_state_changed`：{segment_id, old, new, cause}
- `crossing_point_status_changed`：{segment_id, point_id, old, new, cause}
- `crossing_risk_changed`：{segment_id, old, new}
- `river_crossed`：{agent_id, segment_id, point_id, success, encounters}
- `crossing_incident`：{agent_id, segment_id, incident_type, severity}

## 6. 与其他系统的接口
- 读：water-level.md 的水位和流速。
- 写：02-distance-and-time 读可渡性和渡口状态，计算通行时间和风险；人物系统读渡河风险做决策。
- 因果链：水位上升 → 渡口关闭 → 人物绕行或冒险 → 渡河事件 → 心理变化。

## 7. 地点参数占位
- wade_threshold（可涉水上限水位）
- boat_threshold（渡船上限水位）
- 各渡口类型（渡船/浅滩）、通行时间、风险系数
- 流速对渡船关闭的阈值
- 渡河风险公式的参数
- 各类渡河事件的触发概率