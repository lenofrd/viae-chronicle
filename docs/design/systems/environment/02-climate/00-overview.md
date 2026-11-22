# 气候子系统总览

> **能力状态**（E1 审计 2026-11-22）：**部分实现**——季节/天气/降水/限幅/旱涝累积已实现（`domains/environment/climate.py`）；极端天气与季节过渡未实现。 逐项依据见[设计树对齐审计](../../../audits/ecology-foundation/design-tree-alignment.md)。

## 1. 目的
定义季节和天气如何推进，以及气候状态如何驱动水文、土壤与田地、地形、灾害。
气候是慢变量和快变量的混合体：季节是慢变量，天气是快变量，旱涝是累积量，极端天气是事件。

## 2. 核心概念
- **季节**：春/夏/秋/冬，按 tick 推进，有固定跨度和渐变过渡。
- **天气**：温度、降水、湿度、风力，按日推进，有趋势和波动。
- **旱涝累积**：降水偏离常态的累积量，超过阈值才触发旱灾/洪涝。
- **极端天气**：暴雨、连阴雨、霜冻、酷热，作为事件触发，但依赖前期累积状态。
- **气候状态**：当前季节 + 当前天气 + 累积量 + 近期趋势。

## 3. 状态变量（按空间单元挂载）
| 变量 | 类型 | 说明 | 变化速率 |
|---|---|---|---|
| season | enum | 当前季节 | 按季节长度切换 |
| season_progress | float 0–1 | 当前季节进度 | 每 tick 递增 |
| transition_state | enum | 是否处于季节过渡期 | 按过渡长度切换 |
| temperature | float | 温度 | 有日变化和趋势，不跳变 |
| precipitation | float | 当日降水量 | 按日生成，有趋势 |
| humidity | float | 湿度 | 受降水和温度影响 |
| wind | float | 风力 | 慢变，有波动 |
| drought_accumulation | float | 旱情累积量 | 按日累积，可恢复 |
| flood_accumulation | float | 涝情累积量 | 按日累积，可消退 |
| weather_trend | enum | 近期趋势（转好/转差/稳定） | 由 weather.md 维护 |

各状态变量的 `max_delta_per_tick` 见地点参数。

## 4. 演化规则分类
- **tick 驱动**：季节推进、温度日变化、湿度缓慢变化。
- **事件驱动**：极端天气触发、旱涝成灾触发。
- **累积效应**：旱涝累积量随降水偏离累积，恢复慢。
- **外部注入**：接口写入的天气/气候事件，标注为外部事件。

## 5. 事件类型
- `season_changed`：{old_season, new_season, tick}
- `season_transition_started` / `season_transition_ended`
- `weather_changed`：{variable, old, new, cause}
- `drought_accumulation_changed` / `flood_accumulation_changed`
- `drought_triggered` / `flood_triggered`
- `extreme_weather_started` / `extreme_weather_ended`

## 6. 与其他系统的接口
- **读**：无（气候是上游驱动源）。
- **写**：
  - 向 03-hydrology 提供降水、温度、季节系数，驱动水位和流速。
  - 向 05-soil-and-fields 提供降水、温度、季节信息，驱动土壤湿度和作物生长。
  - 向 04-terrain 提供暴雨信息，驱动滑坡风险。
  - 向 08-hazards 提供旱涝累积量和极端天气状态，触发灾害。
  - 记录系统：季节变化、旱涝成灾、极端天气作为人物一生的环境背景事件。
- **因果链**：季节变化和极端天气通常作为父事件，影响后续环境事件和人物事件。

## 7. 地点参数占位
具体地点（如 Brookvale）需要提供：
- 每季长度（tick）、季节过渡期长度（tick）
- 各季节基准温度、降水概率、湿度范围
- 雨季/旱季对应的季节
- 旱涝累积的成灾阈值、恢复速率
- 极端天气的触发概率和前期条件

## 8. 扩展预留
- 新季节类型：在 seasons.md 里扩展枚举，现有规则通过配置引用。
- 新天气变量：在 weather.md 里新增字段，状态和事件 payload 扩展。
- 多地点气候差异：通过地点参数配置，机制不变。
- 气候变化（长期趋势）：作为外部注入或慢变量扩展，第一版不做。

## 9. 横切机制引用

- 变化速率上限、滞后与累积、空间传播、可逆性规则见 `09-dynamics/`。
- 事件记录、快照结构、查询接口遵循 `10-state-and-records/`。
- 本子系统所有状态变化事件按 `10-state-and-records/event-stream.md` 的统一格式记录。
