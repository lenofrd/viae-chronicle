# 天气机制

## 1. 目的
定义温度、降水、湿度、风力如何按日推进，以及天气如何影响下游子系统。

## 2. 核心概念
- **温度**：日变化 + 季节趋势 + 随机波动，有变化速率上限。
- **降水**：按日生成，有概率和强度，受季节和湿度影响。
- **湿度**：受降水和温度影响，慢变。
- **风力**：慢变，有波动，影响蒸发和火灾风险。
- **天气趋势**：滑动窗口计算的近期趋势（转好/转差/稳定）。

## 3. 状态变量
| 变量 | 类型 | 说明 | 变化速率上限 |
|---|---|---|---|
| temperature | float | 温度 | 每 tick 变化不超过 X |
| precipitation | float | 当日降水量 | 按日生成，不累积 |
| humidity | float | 湿度 | 每 tick 变化不超过 Y |
| wind | float | 风力 | 每 tick 变化不超过 Z |
| weather_trend | enum | 近期趋势 | 按滑动窗口计算 |

## 4. 演化规则
### 4.1 tick 驱动：温度日变化
条件：每 tick
效果：temperature = base_temp(season) + daily_variation + random_fluctuation
变化量受 rate_limit 约束
滞后：无
影响范围：全局，但空间单元可有微调（如山区温度偏低）

### 4.2 tick 驱动：降水生成
条件：每 tick
效果：precipitation = 0 或 rain_amount
概率和强度由季节、湿度、前期降水决定
降水影响湿度、土壤湿度、水位、火灾风险
滞后：降水对水位的影响有延迟（见 03-hydrology）
影响范围：按空间单元分别计算（山区降水可能多于镇域）

> **004 补充裁决（2026-11-17，待实现）——日照派生量（方案 A）**：`sunlight_factor = f(当日降水, 季节基准)` 为**纯函数派生量**（量级：晴 1.0 / 雨 0.7 `[调参]`，可按连续无雨天数平滑），作为独立乘数进产量公式（见 [crops.md §4.5](../05-soil-and-fields/crops.md)）。不新增天气状态或 WeatherType 枚举，雨天户外乘数、通行条件、回放均不受影响；数值为地点参数。

### 4.3 累积与趋势
规则：天气趋势计算
条件：每 N tick
效果：weather_trend = 比较近期降水/温度与常态
趋势作为旱涝累积的辅助信号
滞后：无
影响范围：全局

## 5. 事件类型
- `weather_changed`：{variable, old, new, cause}
- `rain_started` / `rain_ended`：{intensity, duration}
- `temperature_dropped` / `temperature_rose`：{old, new, cause}

## 6. 与其他系统的接口
- 写：
  - 03-hydrology 读降水、温度，驱动水位和流速。
  - 05-soil-and-fields 读降水、温度，驱动土壤湿度和作物。
  - 08-hazards 读降水、湿度、风力，驱动火灾和虫害风险。
  - 02-distance-and-time 读天气，修正通行条件。
- 因果链：降水事件可作为父事件，影响水位、土壤、灾害。

## 7. 地点参数占位
- 各季节基准温度、日变化幅度
- 各季节降水概率、降水强度范围
- 湿度基准和变化速率
- 风力基准和变化速率
- 空间单元的天气微调系数（如山区温度 -X）