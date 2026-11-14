# 旱

## 1. 目的
定义旱灾的触发条件、影响范围、后果和恢复。旱是慢灾害，影响面广，持续时间长。

## 2. 核心概念
- 触发条件：降水持续不足累积 + 水位下降 + 土壤湿度下降。
- 影响范围：田地、河段、取水点、人畜饮水、植被。
- 后果：作物减产或绝收、水井干涸、取水点失效、柴薪和草药采集受影响、人畜饮水困难。
- 滞后：旱情累积若干天才成灾，成灾后影响持续。
- 可逆性：降雨恢复后可逆，但作物当季损失不可逆，地力恢复需要时间。
- 空间差异：靠河田和远河田受影响程度不同，上游和下游不同。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| drought_active | bool | 是否正在发生 |
| drought_severity | enum | 轻度/中度/重度 |
| drought_duration | int | 已持续 tick |
| affected_fields | list | 受影响的田地 |
| affected_water_sources | list | 受影响的取水点/水井 |
| crop_loss | dict | 各田地的减产比例 |

## 4. 演化规则

### 4.1 触发
```
条件：每 tick 检查
      drought_accumulation > drought_threshold
      且 soil_moisture 持续低于干旱阈值
      且 water_level 低于旱情水位阈值
效果：生成 disaster_triggered 事件
      drought_active = true
      drought_severity 由累积量和持续时间决定
滞后：条件满足后 3–7 tick 内触发
影响范围：按空间单元分别判定
```

### 4.2 影响判定
```
条件：drought_active = true
效果：田地：soil_moisture 下降，growth_health 下降，预期收成下降
      取水点：水位低于阈值，intake_status = 受限或失效
      水井：水位下降，可能干涸
      植被：柴薪和草药再生速度下降
      人物：饮水困难，劳作效率下降
滞后：影响随旱情持续加重
影响范围：按空间单元，靠河田受影响小于远河田
```

### 4.3 严重程度升级
```
条件：旱情持续
效果：duration 增加，severity 按持续时间和累积量升级
      轻度 → 中度 → 重度
      重度时作物可能绝收，水井干涸
滞后：按持续时间
影响范围：受影响单元
```

### 4.4 结束
```
条件：降水恢复，drought_accumulation 降到阈值以下
效果：drought_active = false
      生成 disaster_ended 事件
      记录作物损失、水井状态、地力损失
滞后：降雨恢复后旱情不会立刻解除，需要若干 tick 消退
影响范围：受影响单元
```

### 4.5 后果记录
```
条件：disaster_ended
效果：汇总 affected_fields、affected_water_sources、crop_loss
      不可逆损失：当季作物减产/绝收
      可逆损失：地力恢复需要时间，水井可重新蓄水
影响范围：所有受影响单元
```

## 5. 事件类型
- `disaster_triggered`：{disaster_type: drought, severity, affected_units, cause}
- `drought_intensified`：{old_severity, new_severity}
- `disaster_damage`：{disaster_type: drought, unit_id, damage_type, severity}
- `disaster_ended`：{disaster_type: drought, duration, total_damage}

## 6. 与其他系统的接口
- 读：02-climate 的降水累积；03-hydrology 的水位；05-soil-and-fields 的土壤湿度。
- 写：03-hydrology 降低水位；05-soil-and-fields 降低土壤湿度和地力、减产；06-vegetation 降低再生速度；人物系统触发饮水困难、争水、借粮、心理迁移；记录系统记录旱灾事件。
- 因果链：持续无雨 → 水位下降 → 取水点失效 → 田地缺水 → 作物减产 → 人物争水/借粮/迁徙 → 关系变化。

## 7. 地点参数占位
- drought_threshold（旱情累积阈值）
- 旱情水位阈值、土壤湿度干旱阈值
- 触发滞后范围（tick）
- 严重程度分级标准（按持续时间和累积量）
- 各单元受影响系数（靠河田 vs 远河田）
- 作物减产映射
- 消退速率