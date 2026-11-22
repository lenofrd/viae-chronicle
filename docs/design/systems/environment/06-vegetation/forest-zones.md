# 山林分区

## 1. 目的
定义山林分区作为植被单元的结构、植被类型、覆盖度，以及分区如何随采集压力和自然过程退化或恢复。

## 2. 核心概念
- 山林分区：按山层和坡面划分的植被单元，一个山层可包含多个坡面，一个坡面可包含多个分区。
- 植被类型：灌木、针叶林、阔叶林、草坡、裸地。
- 植被覆盖度：0–1，代表地表植被密集程度。
- 退化序列：阔叶林 → 灌木 → 草坡 → 裸地（不可逆或难逆）。
- 恢复序列：裸地 → 草坡 → 灌木 → 阔叶林（需要长时间和条件）。
- 分区是资源点的父单元，资源点挂在分区下。

## 3. 分区字段
| 字段 | 类型 | 说明 |
|---|---|---|
| zone_id | string | 唯一 ID |
| name | string | 显示名 |
| parent_layer | string | 所属山层 ID |
| parent_slope | string | 所属坡面 ID |
| vegetation_type | enum | 灌木/针叶林/阔叶林/草坡/裸地 |
| vegetation_cover | float 0–1 | 植被覆盖度 |
| resource_points | list | 挂载的资源点 ID |
| state | dict | 采集压力、退化状态等 |

## 4. 演化规则

### 4.1 植被覆盖度自然变化
```
条件：每季
效果：vegetation_cover 向平衡覆盖度缓慢趋近
      平衡覆盖度由植被类型、降水、温度决定
      受 max_delta_per_season 约束
滞后：按季，不瞬移
影响范围：按分区
```

### 4.2 采集压力影响覆盖度
```
条件：每季，分区内采集压力超过阈值
效果：vegetation_cover -= pressure_impact
      采集压力越高，覆盖度下降越快
滞后：覆盖度下降滞后于采集压力累积
影响范围：按分区
```

### 4.3 植被类型迁移：退化
```
条件：vegetation_cover 低于当前类型的下限阈值
效果：vegetation_type 退化一级
      阔叶林 → 灌木 → 草坡 → 裸地
      生成 vegetation_type_changed 事件
滞后：覆盖度持续低于阈值若干季才迁移
影响范围：按分区
不可逆性：裸地恢复到阔叶林需要极长时间，视为准不可逆
```

### 4.4 植被类型迁移：恢复
```
条件：vegetation_cover 高于当前类型的上限阈值，且采集压力低
效果：vegetation_type 恢复一级
      裸地 → 草坡 → 灌木 → 阔叶林
      生成 vegetation_type_changed 事件
滞后：恢复慢于退化，需要多季甚至多年
影响范围：按分区
```

### 4.5 植被覆盖度对下游的影响
```
条件：覆盖度变化后
效果：向 04-terrain 提供 soil_stability_factor
      向 08-hazards 提供 landslide_risk_factor 和 flood_risk_factor
      向 05-soil-and-fields 提供 water_retention_factor
滞后：无（系数即时生效，但下游变量有自身速率上限）
影响范围：按分区及下方单元
```

## 5. 事件类型
- `vegetation_cover_changed`：{zone_id, old, new, cause}
- `vegetation_type_changed`：{zone_id, old, new, cause}
- `zone_degraded`：{zone_id, severity}
- `zone_recovered`：{zone_id, severity}

## 6. 与其他系统的接口
- 读：02-climate 的降水、温度、季节；04-terrain 的坡向坡度；本子系统资源点的采集压力。
- 写：04-terrain 读覆盖度调整土体稳定度和滑坡风险；08-hazards 读覆盖度调整山洪和滑坡风险；05-soil-and-fields 读覆盖度调整水土保持；07-fauna 读植被类型决定栖息地。
- 因果链：持续采集 → 采集压力累积 → 覆盖度下降 → 植被类型退化 → 土体稳定度下降 → 滑坡风险上升 → 灾害事件。

## 7. 地点参数占位
- 分区清单：ID、名称、所属山层/坡面、初始植被类型、初始覆盖度
- 各植被类型的平衡覆盖度范围
- max_delta_per_season（覆盖度变化速率上限）
- 采集压力对覆盖度的影响系数
- 植被类型退化和恢复的阈值
- 覆盖度对土体稳定度、滑坡风险、山洪风险、水土保持的影响系数