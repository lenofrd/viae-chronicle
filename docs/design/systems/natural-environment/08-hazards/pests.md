# 虫害

## 1. 目的
定义虫害的触发条件、传播、影响范围、后果和恢复。虫害是田地层面的灾害，影响收成，可能传播到邻片。

## 2. 核心概念
- 触发条件：pest_risk 超过爆发阈值，受湿度、连作、季节影响。
- 传播：从一片田向邻片传播，传播速度受距离和风向影响。
- 影响范围：田地片，可能扩散到整个田区。
- 后果：作物长势下降、减产、严重时绝收。
- 可逆性：当季损失不可逆，下一季可恢复；连作会加重虫害。
- 滞后：风险累积到阈值后 1–3 tick 内爆发。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| pest_active | bool | 是否正在爆发 |
| pest_severity | enum | 轻度/中度/重度 |
| pest_duration | int | 已持续 tick |
| affected_fields | list | 受影响的田地 |
| spread_direction | enum | 传播方向（按风向或邻接） |

## 4. 演化规则

### 4.1 触发
```
条件：每 tick 检查
      pest_risk > pest_outbreak_threshold
      且 随机通过（概率随风险和连作上升）
效果：生成 disaster_triggered 事件
      pest_active = true
      pest_severity 由 pest_risk 决定
滞后：风险超阈值后 1–3 tick 内爆发
影响范围：当前田地片
```

### 4.2 传播
```
条件：pest_active = true
效果：每 tick 按传播概率向邻接田地传播
      传播概率受距离、风向、作物类型影响
      邻片 pest_risk 上升
      达到阈值则邻片也爆发
滞后：1–2 tick 后邻片可能爆发
影响范围：邻接田地
```

### 4.3 影响判定
```
条件：田地虫害爆发
效果：growth_health 下降
      pest_damage 按 severity 计算
      预期收成下降
      严重时绝收
滞后：影响在爆发期间持续
影响范围：受影响田地
```

### 4.4 结束
```
条件：pest_duration 超过最大持续时间，或人为干预（捕虫、用药）
效果：pest_active = false
      生成 disaster_ended 事件
      记录减产比例
滞后：结束后 pest_risk 下降但仍需时间消退
影响范围：受影响田地
```

### 4.5 后果记录
```
条件：disaster_ended
效果：汇总 affected_fields、减产比例
      不可逆损失：当季减产/绝收
      可逆损失：下一季可恢复，但连作会加重
影响范围：所有受影响田地
```

## 5. 事件类型
- `disaster_triggered`：{disaster_type: pest, severity, affected_units, cause}
- `pest_spread`：{from_field, to_field, tick}
- `disaster_damage`：{disaster_type: pest, unit_id, damage_type, severity}
- `disaster_ended`：{disaster_type: pest, duration, total_damage}

## 6. 与其他系统的接口
- 读：05-soil-and-fields 的 pest_risk、作物类型、连作状态；02-climate 的湿度和季节。
- 写：05-soil-and-fields 降低 growth_health 和预期收成；人物系统触发捕虫、用药、改种、借粮；记录系统记录虫害事件。
- 因果链：连作 + 高湿 → pest_risk 上升 → 虫害爆发 → 减产 → 人物捕虫/改种 → 下一季 pest_risk 下降。

## 7. 地点参数占位
- pest_outbreak_threshold（虫害爆发阈值）
- 爆发概率曲线（风险、连作、季节）
- 传播概率和传播范围
- 各 severity 的减产比例
- 最大持续时间
- 人为干预的效果（捕虫、用药）