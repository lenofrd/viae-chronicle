# 火灾

## 1. 目的
定义火灾的触发条件、传播、影响范围、后果和恢复。火灾是低概率高破坏的灾害，对植被和建筑影响大。

## 2. 核心概念
- 触发条件：干燥度 + 植被状态 + 人为用火（第一版可简化为随机 + 干燥度）。
- 传播：沿植被和风向传播，从山林向镇域边缘扩散。
- 影响范围：山林分区、田地、建筑。
- 后果：植被烧毁、动物死亡、房屋损毁、人员伤亡、柴薪和草药资源损失。
- 可逆性：植被可恢复但需要多年，古树被烧不可逆，房屋可重建，人员死亡不可逆。
- 滞后：干燥度累积到阈值后，用火事件触发火灾。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| fire_active | bool | 是否正在燃烧 |
| fire_severity | enum | 轻度/中度/重度 |
| fire_duration | int | 已持续 tick |
| affected_zones | list | 受影响的山林分区 |
| affected_buildings | list | 受影响的建筑 |
| spread_direction | enum | 传播方向（按风向） |

## 4. 演化规则

### 4.1 触发
```
条件：每 tick 检查
      dryness > fire_dryness_threshold
      且 vegetation_cover > fire_fuel_threshold
      且 有人为用火事件或随机通过（低概率）
效果：生成 disaster_triggered 事件
      fire_active = true
      fire_severity 由干燥度和植被状态决定
滞后：干燥度累积到阈值后，用火事件 1–2 tick 内触发
影响范围：起火点所在分区
```

### 4.2 传播
```
条件：fire_active = true
效果：每 tick 按传播概率向邻接分区传播
      传播概率受风向、干燥度、植被类型影响
      针叶林传播快于阔叶林，草坡传播快于裸地
      可能从山林向镇域边缘扩散
滞后：1–2 tick 后邻接分区可能起火
影响范围：邻接分区
```

### 4.3 影响判定
```
条件：分区被火灾覆盖
效果：vegetation_cover 大幅下降
      vegetation_type 退化
      动物种群死亡
      资源点存量归零
      建筑损毁（若火势蔓延到镇域）
      人物按伤亡概率判定
滞后：影响在火灾覆盖时产生
影响范围：被覆盖的单元
```

### 4.4 结束
```
条件：降雨、人为扑救、可燃物耗尽
效果：fire_active = false
      生成 disaster_ended 事件
      记录烧毁面积、损失
滞后：火灾不会立刻熄灭，需要条件满足
影响范围：受影响分区
```

### 4.5 后果记录
```
条件：disaster_ended
效果：汇总 affected_zones、affected_buildings、损失
      不可逆损失：古树烧毁、人员死亡
      可逆损失：植被恢复需要多年，建筑可重建
影响范围：所有受影响单元
```

## 5. 事件类型
- `disaster_triggered`：{disaster_type: fire, severity, affected_units, cause}
- `fire_spread`：{from_zone, to_zone, tick}
- `disaster_damage`：{disaster_type: fire, unit_id, damage_type, severity}
- `disaster_casualty`：{disaster_type: fire, agent_id, severity}
- `disaster_ended`：{disaster_type: fire, duration, total_damage}

## 6. 与其他系统的接口
- 读：02-climate 的干燥度（温度、湿度、降水）；06-vegetation 的植被类型和覆盖度；人物系统的用火事件。
- 写：06-vegetation 降低覆盖度、改变植被类型、清空资源点；07-fauna 减少种群；04-terrain 火灾后土体稳定度下降；05-soil-and-fields 烧毁田地；人物系统触发伤亡、扑救、重建；记录系统记录火灾事件。
- 因果链：长期干燥 → 植被干燥 → 用火/雷击 → 火灾 → 传播 → 植被烧毁/房屋损毁/人员伤亡 → 人物扑救/重建/迁徙 → 植被多年恢复。

## 7. 地点参数占位
- fire_dryness_threshold（干燥度阈值）
- fire_fuel_threshold（可燃物阈值）
- 触发概率（干燥度、植被、人为用火）
- 传播概率和传播速度（风向、植被类型）
- 各 severity 的损失映射
- 伤亡概率
- 扑救效果和条件