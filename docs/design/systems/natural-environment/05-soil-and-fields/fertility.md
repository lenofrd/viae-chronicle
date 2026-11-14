# 地力

## 1. 目的
定义地力如何随连作、施肥、轮耕、休耕变化，以及地力如何影响作物长势和收成。地力是慢变量，变化以季/年计。

## 2. 核心概念
- 地力：0–1 的连续值，代表土壤肥力。
- 消耗源：连作、作物生长吸收。
- 恢复源：施肥、休耕、轮作（种豆类等养地作物）、洪水带来的淤泥（有利有弊）。
- 不可逆退化：长期过度消耗且不恢复，地力可能永久下降（第一版可简化，只做可逆）。
- 滞后：施肥后地力不会立刻提升，要等到下一季才见效；连作惩罚也是累积到阈值才明显。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| fertility | float 0–1 | 当前地力 |
| fertility_trend | enum | 退化中/稳定/恢复中 |
| consecutive_crops | int | 连续种植同种作物的季数 |
| fallow_seasons | int | 休耕季数 |

## 4. 演化规则

### 4.1 地力消耗：连作
```
条件：每季，作物收割后
效果：fertility -= crop_nutrient_cost
      若连续种植同种作物：
        consecutive_crops += 1
        fertility -= consecutive_crops * monoculture_penalty
      受 max_delta_per_season 约束
滞后：连作惩罚在连续 2–3 季后明显
影响范围：按田地片
```

### 4.2 地力恢复：施肥
```
条件：人物系统写入施肥事件
效果：fertility += fertilizer_amount * fertilizer_efficiency
      受 max_delta_per_season 约束
滞后：施肥后下一季才见效，当季不提升
影响范围：被施肥的田地片
```

### 4.3 地力恢复：休耕与轮作
```
条件：每季，田地处于休耕或种植养地作物
效果：fertility += fallow_recovery_rate
      fallow_seasons += 1
      若种植养地作物（如豆类）：
        fertility += legume_recovery_rate
滞后：休耕恢复以季计，完全恢复需要多季
影响范围：按田地片
```

### 4.4 地力趋势
```
条件：每季结算后
效果：fertility_trend = 比较本季与上季地力
      退化中/稳定/恢复中
滞后：无
影响范围：按田地片
```

### 4.5 不可逆退化（预留）
```
条件：fertility 连续多季低于警戒线
效果：标记 field.fertility_degraded = true
      即使休耕，恢复上限也降低
滞后：长期过程
影响范围：按田地片
第一版不实现，预留事件类型和状态位。
```

## 5. 事件类型
- `fertility_changed`：{field_id, old, new, cause}
- `fertility_trend_changed`：{field_id, old, new}
- `fertilizer_applied`：{field_id, amount, cause}
- `fallow_started` / `fallow_ended`：{field_id}
- `fertility_degraded`：{field_id, severity}（预留，第一版不触发）

## 6. 与其他系统的接口
- 读：人物系统的施肥、休耕、轮作事件；crops.md 的作物养分消耗。
- 写：crops.md 读地力判断长势和预期收成；人物系统读地力和趋势做决策（施肥、休耕、换作物、买田）。
- 因果链：连作 → 地力下降 → 收成下降 → 人物施肥或休耕 → 地力恢复（滞后）→ 收成回升。

## 7. 地点参数占位
- 各田地片的初始 fertility
- crop_nutrient_cost（各作物的养分消耗）
- monoculture_penalty（连作惩罚系数）
- fertilizer_amount 和 fertilizer_efficiency（施肥恢复量）
- fallow_recovery_rate（休耕恢复速率）
- legume_recovery_rate（养地作物恢复速率）
- max_delta_per_season（地力变化速率上限）
- 地力警戒线（低于多少算退化风险）