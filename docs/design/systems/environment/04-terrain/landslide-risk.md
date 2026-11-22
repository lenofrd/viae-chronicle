# 滑坡风险

## 1. 目的
定义滑坡风险如何随降雨、植被、坡度累积，如何触发滑坡，滑坡对山路、田地、人物的影响。

## 2. 核心概念
- 滑坡风险：0–1 的连续值，不是二值开关。
- 触发条件：前期降雨累积 + 短时暴雨 + 坡度陡 + 植被覆盖低。
- 滞后：降雨停止后风险不会立刻下降，土体饱和需要时间消退。
- 后果：山路中断、田地冲毁、房屋损毁、人物伤亡。
- 可逆性：山路可修复，但需要时间和人力；坡面形态改变不可逆。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| landslide_risk | float 0–1 | 当前滑坡风险 |
| soil_saturation | float 0–1 | 土体饱和度 |
| trail_state | enum | 山路畅通/受损/中断 |

## 4. 演化规则

### 4.1 风险累积
```
条件：每 tick，降水超过阈值
效果：soil_saturation 上升
      soil_stability 由 06 的 vegetation_cover 和本子系统的 soil_saturation 派生，不单独维护。
      landslide_risk = f(soil_saturation, 坡度, 植被覆盖度)
      坡度越陡、植被越少，风险上升越快
滞后：无
影响范围：按坡面
```

### 4.2 风险消退
```
条件：降水停止后
效果：soil_saturation 按恢复速率下降
      landslide_risk 随之下降
滞后：消退慢于累积，体现土体饱和的滞后
影响范围：按坡面
```

### 4.3 滑坡触发
```
条件：landslide_risk 超过触发阈值
效果：按概率判定是否发生滑坡
      生成 landslide_occurred 事件
      severity 由风险和坡度决定
滞后：风险超过阈值后 1–3 tick 内可能触发
影响范围：本坡面及下方单元
```

### 4.4 滑坡后果
```
条件：landslide_occurred 事件
效果：山路中断（trail_state = 中断）
      田地可能被冲毁，房屋可能损毁，人物可能伤亡
      山路修复需要人力事件，修复时间由 severity 决定
滞后：修复需时间
影响范围：本坡面、下方单元、连接的山路
```

### 4.5 不可逆变化
```
条件：severity 超过不可逆阈值
效果：坡面 gradient 从陡坡变为崖壁
      不可逆
影响范围：本坡面
```

## 5. 事件类型
- `landslide_risk_changed`：{slope_id, old, new, cause}
- `soil_saturation_changed`：{slope_id, old, new, cause}
- `landslide_occurred`：{slope_id, severity, affected_units, casualties}
- `trail_state_changed`：{trail_id, old, new, cause}
- `trail_repaired`：{trail_id, cause, labor_cost}

## 6. 与其他系统的接口
- 读：02-climate 的降水、暴雨；06-vegetation 的植被覆盖；slopes.md 的坡度和坡向。
- 写：02-distance-and-time 读 trail_state，修正通行；08-hazards 读 landslide_risk，触发滑坡事件；05-soil-and-fields 读滑坡后果，田地冲毁；人物系统读滑坡事件，触发伤亡和心理变化。
- 因果链：暴雨 → 土体饱和 → 滑坡风险上升 → 滑坡发生 → 山路中断/田地冲毁 → 人物通行受阻/受伤 → 心理变化 → 修复行动或迁徙。

## 7. 地点参数占位
- 各滑坡风险点的基础风险
- 降水对 soil_saturation 的影响系数
- soil_saturation 的恢复速率
- 坡度、植被覆盖对 landslide_risk 的修正系数
- 滑坡触发阈值和触发概率
- 滑坡 severity 的分级和后果映射
- 山路修复的人力成本和时间
- 不可逆变化的 severity 阈值