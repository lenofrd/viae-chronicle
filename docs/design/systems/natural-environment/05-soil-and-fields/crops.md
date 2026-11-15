# 作物与病虫害

## 1. 目的
定义作物从播种到收割的生长周期、长势如何受湿度地力影响、病虫害如何累积和爆发、收成如何计算。

## 2. 核心概念
- 作物类型：稻、麦、麻、菜等，各有生长周期、适宜季节、需水量、养分消耗。
- 生长阶段：播种 → 发芽 → 生长 → 抽穗/开花 → 成熟 → 收割 → 休耕。
- 长势健康度：0–1，受土壤湿度、地力、病虫害、极端天气影响。
- 病虫害风险：随季节、湿度、连作累积，超过阈值触发虫害爆发。
- 预期收成：地力 × 湿度适宜度 × 健康度 × 面积 × 灾害修正。
- 实际收成：收割时结算，受收割时机和灾害影响。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| crop_type | enum? | 当前作物，无则为 null |
| growth_stage | enum | 播种/发芽/生长/抽穗/成熟/收割/休耕 |
| growth_progress | float 0–1 | 当前阶段进度 |
| growth_health | float 0–1 | 长势健康度 |
| pest_risk | float 0–1 | 病虫害风险 |
| pest_outbreak_active | bool | 是否正在虫害爆发 |
| expected_yield | float | 预期收成 |

## 4. 演化规则

### 4.1 生长阶段推进
```
条件：每 tick，田地有作物
效果：growth_progress += 1 / stage_duration(crop_type, stage)
      进度满 1 进入下一阶段
      生成 growth_stage_changed 事件
滞后：按作物周期，不跳阶段
影响范围：按田地片
```

### 4.2 长势健康度
```
条件：每 tick
效果：health_delta = 0
      若 soil_moisture < drought_threshold：
        health_delta -= drought_penalty
      若 soil_moisture > waterlog_threshold：
        health_delta -= waterlog_penalty
      若 fertility < low_fertility_threshold：
        health_delta -= fertility_penalty
      若 pest_outbreak_active：
        health_delta -= pest_damage
      若遭遇霜冻/酷热：
        health_delta -= extreme_weather_damage
      growth_health += health_delta，夹紧到 0–1
滞后：健康度下降有 1–3 tick 滞后
影响范围：按田地片
```

### 4.3 病虫害风险累积
```
条件：每 tick
效果：pest_risk += base_pest_rate
                    * humidity_factor
                    * monoculture_factor
                    * season_factor
      湿度高、连作、夏季时风险上升快
      受 max_delta_per_tick 约束
滞后：风险累积到阈值才可能爆发
影响范围：按田地片
```

### 4.4 虫害爆发
```
条件：pest_risk 超过爆发阈值
效果：按概率判定是否爆发
      生成 pest_outbreak 事件
      pest_outbreak_active = true
      持续若干 tick 后结束
滞后：风险超阈值后 1–3 tick 内可能爆发
影响范围：本田地片，可能向邻片传播
```

### 4.5 预期收成
```
条件：生长阶段进入成熟
效果：expected_yield = base_yield(crop_type)
                     * area
                     * fertility_factor
                     * moisture_factor
                     * growth_health
                     * (1 - disaster_damage)
滞后：无
影响范围：按田地片
```

> **已落地（盈余经济阶段二，2026-11-15）**：`harvest` 改按本式结算，实现见 `vale.modules.agents.expected_yield`。
> - `base_yield`：配置键 `agriculture.base_yield`（原 `crop_gain` 更名，数值 75/55 不变）。
> - `area`：`spatial-units.yaml` 节点 `area`，默认 1.0。
> - `fertility_factor`：`WorldState.field_fertility`，阶段二恒 1.0；连作衰减/休耕恢复**未启用**（阶段三）。
> - `moisture_factor` / `growth_health` / `disaster_damage`：阶段二取中性占位 1/1/0，未接气候与病虫害。
> - 偏差：§4.6 的 `harvest_timing_factor` 未实现（阶段二保持实际收成 = expected_yield）；`growth_stage` 仍由长势阈值与季节近似。

### 4.6 收割
```
条件：人物系统写入收割事件，且 growth_stage = 成熟
效果：实际收成 = expected_yield * harvest_timing_factor
      生成 harvested 事件
      记录 yield_amount、quality
      crop_type = null，growth_stage = 休耕
      consecutive_crops 更新（见 fertility.md）
滞后：无
影响范围：按田地片
```

### 4.7 灾害对作物的影响
```
条件：山洪、滑坡、霜冻、酷热等事件
效果：growth_health 下降
      严重时整片田绝收（field_damaged 事件）
      不可逆损失：当季无法恢复
滞后：按灾害类型
影响范围：受影响的田地片
```

## 5. 事件类型
- `crop_planted`：{field_id, crop_type, cause}
- `growth_stage_changed`：{field_id, old, new}
- `growth_health_changed`：{field_id, old, new, cause}
- `pest_risk_changed`：{field_id, old, new, cause}
- `pest_outbreak`：{field_id, severity, affected_area}
- `pest_outbreak_ended`：{field_id}
- `harvested`：{field_id, crop_type, yield_amount, quality, cause}
- `field_damaged`：{field_id, damage_type, severity, cause}

## 6. 与其他系统的接口
- 读：soil-moisture.md 的土壤湿度；fertility.md 的地力；02-climate 的季节、温度、降水、极端天气；08-hazards 的灾害事件。
- 写：人物系统读 expected_yield 和 growth_stage 做决策（收割、改种、借粮、卖粮）；08-hazards 读 pest_risk 触发虫害；记录系统把 harvested 事件作为人物一生的关键节点。
- 因果链：连作 → 地力下降 + 病虫害风险上升 → 长势变差 → 虫害爆发 → 收成下降 → 人物决策（施肥、休耕、借粮、卖地）。

## 7. 地点参数占位
- 作物清单：类型、生长周期、各阶段时长、适宜季节、需水量、养分消耗、base_yield
- drought_threshold、waterlog_threshold（湿度适宜区间）
- drought_penalty、waterlog_penalty、fertility_penalty、pest_damage（健康度惩罚系数）
- extreme_weather_damage（霜冻/酷热的健康度损失）
- base_pest_rate、humidity_factor、monoculture_factor、season_factor
- pest_outbreak_threshold、爆发概率、爆发持续 tick
- harvest_timing_factor（收割时机对收成的影响）
- disaster_damage 映射（各灾害对收成的削减）