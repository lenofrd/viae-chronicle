# 土壤湿度

## 1. 目的
定义土壤湿度如何随降水、灌溉、蒸发、作物耗水变化，以及湿度如何影响作物长势和病虫害风险。

## 2. 核心概念
- 土壤湿度：0–1 的连续值，不是二值开关。
- 补给源：降水、灌溉。
- 消耗源：蒸发（温度相关）、作物耗水（生长期相关）、下渗。
- 平衡湿度：当前气候和灌溉条件下趋向的目标值。
- 变化速率上限：每 tick 变化量有上限，禁止瞬移。
- 干旱/过湿：湿度过低或过高都会影响作物，但第一版主要做干旱影响。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| soil_moisture | float 0–1 | 当前土壤湿度 |
| moisture_trend | enum | 变干/稳定/变湿 |
| last_irrigation_tick | int? | 上次灌溉 tick |

## 4. 演化规则

### 4.1 湿度补给：降水
```
条件：每 tick，02-climate 降水 > 0
效果：soil_moisture += precipitation * infiltration_rate
      受 max_delta_per_tick 约束
滞后：降水后 1 tick 内生效
影响范围：按田地片，坡地入渗率低于平地
```

### 4.2 湿度补给：灌溉
```
条件：人物系统写入灌溉事件
效果：soil_moisture += irrigation_amount * irrigation_efficiency
      灌溉效率受灌溉条件影响（充足/偏少/缺水/断水）
      受 max_delta_per_tick 约束
滞后：灌溉后 1 tick 内生效
影响范围：被灌溉的田地片
```

### 4.3 湿度消耗：蒸发与作物耗水
```
条件：每 tick
效果：evaporation = f(temperature, wind, crop_cover)
      crop_water_use = f(crop_type, growth_stage)
      soil_moisture -= evaporation + crop_water_use
      soil_moisture 不低于 0
滞后：无
影响范围：按田地片，阳坡蒸发高于阴坡
```

### 4.4 湿度趋势
```
条件：每 N tick
效果：moisture_trend = 比较近期湿度变化
      作为人物决策的辅助信号（如“田在变干”）
滞后：无
影响范围：按田地片
```

## 5. 事件类型
- `soil_moisture_changed`：{field_id, old, new, cause, rate_limited}
- `moisture_trend_changed`：{field_id, old, new}
- `irrigation_applied`：{field_id, amount, source, cause}

## 6. 与其他系统的接口
- 读：02-climate 的降水、温度、风力；03-hydrology 的灌溉条件；crops.md 的作物耗水系数。
- 写：crops.md 读土壤湿度判断长势和病虫害风险；人物系统读湿度趋势做灌溉决策。
- 因果链：降水 → 湿度上升 → 作物长势改善；持续无雨 → 湿度下降 → 作物受旱 → 人物灌溉或争水。

## 7. 地点参数占位
- 各田地片的初始 soil_moisture
- infiltration_rate（降水入渗率）
- irrigation_efficiency（灌溉效率，按灌溉条件分档）
- evaporation 系数（温度、风力、坡向相关）
- crop_water_use 系数（按作物类型和生长期）
- max_delta_per_tick（湿度变化速率上限）
- 干旱阈值（湿度低于多少算受旱）