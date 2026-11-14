# 旱涝累积

## 1. 目的
定义旱情和涝情如何累积、如何成灾、如何恢复。旱涝不是二值开关，是连续累积量。

## 2. 核心概念
- **旱情累积量（drought_accumulation）**：降水持续低于常态的累积偏离量。
- **涝情累积量（flood_accumulation）**：降水持续高于常态的累积偏离量。
- **成灾阈值**：累积量超过阈值才触发旱灾/洪涝事件。
- **恢复速率**：累积量按日衰减，恢复慢于累积。
- **空间差异**：不同空间单元的累积量分别计算（上游/下游、山区/镇域）。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| drought_accumulation | float | 旱情累积量 |
| flood_accumulation | float | 涝情累积量 |
| drought_state | enum | normal / watch / warning / disaster |
| flood_state | enum | normal / watch / warning / disaster |

## 4. 演化规则
### 4.1 旱情累积
条件：每 tick
效果：若 precipitation < drought_threshold：
drought_accumulation += (drought_threshold - precipitation)
否则：
drought_accumulation -= recovery_rate
drought_accumulation 不低于 0
滞后：累积量超过成灾阈值后，第 3–7 天才触发 drought_triggered
影响范围：按空间单元分别计算

### 4.2 涝情累积
条件：每 tick
效果：若 precipitation > flood_threshold：
flood_accumulation += (precipitation - flood_threshold)
否则：
flood_accumulation -= recovery_rate
flood_accumulation 不低于 0
滞后：累积量超过成灾阈值后，第 1–3 天才触发 flood_triggered
影响范围：按空间单元分别计算

### 4.3 状态迁移
规则：旱涝状态更新
条件：累积量变化后
效果：根据阈值更新 drought_state / flood_state
状态迁移生成事件
滞后：无
影响范围：按空间单元

## 5. 事件类型
- `drought_accumulation_changed`：{old, new, cause}
- `flood_accumulation_changed`：{old, new, cause}
- `drought_triggered`：{severity, affected_units}
- `flood_triggered`：{severity, affected_units}
- `drought_ended` / `flood_ended`

## 6. 与其他系统的接口
- 读：weather 的降水数据。
- 写：
  - 03-hydrology 读旱涝状态，调整水位和流速。
  - 05-soil-and-fields 读旱涝状态，调整土壤湿度和作物。
  - 08-hazards 读旱涝状态，触发旱灾/洪涝事件。
- 因果链：旱涝累积是慢变量，成灾事件作为父事件影响后续所有子系统。

## 7. 地点参数占位
- 旱情阈值、涝情阈值
- 成灾阈值（watch/warning/disaster 三档）
- 恢复速率
- 成灾触发滞后（tick 数）
- 空间单元的累积量计算差异（如山区降水多、镇域蒸发强）