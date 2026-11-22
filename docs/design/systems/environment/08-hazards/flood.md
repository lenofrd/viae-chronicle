# 山洪

> **能力状态**（E1 审计 2026-11-22）：**规划**——环境侧累积触发机制未实现；现行山洪为场景概率注入（scenarios/hazard-injection.md）。 依据见[设计树对齐审计](../../../audits/ecology-foundation/design-tree-alignment.md)。

## 1. 目的
定义山洪的触发条件、传播路径、影响范围、后果和恢复。山洪是 Brookvale 设定里破坏力最强的自然灾害。

## 2. 核心概念
- 触发条件：前期降雨累积 + 短时暴雨 + 河道淤积 + 上游水位超阈值。
- 传播：从上游河段向下游传播，沿河道和低洼地扩散，有时滞。
- 影响范围：河段、河边田地、镇域低洼处、山路。
- 后果：田埂冲毁、作物绝收、房屋损毁、道路中断、人畜伤亡、取水点损毁。
- 可逆性：田埂可修，作物当季不可恢复，房屋可重建，人员死亡不可逆。
- 滞后：暴雨停止后洪水不会立刻退去，需要若干 tick 消退。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| flood_active | bool | 是否正在发生 |
| flood_severity | enum | 轻度/中度/重度 |
| flood_peak_level | float | 峰值水位 |
| flood_duration | int | 已持续 tick |
| affected_segments | list | 受影响的河段 |
| affected_fields | list | 受影响的田地 |
| affected_buildings | list | 受影响的建筑 |
| casualties | list | 伤亡记录 |

## 4. 演化规则

### 4.1 触发
```
flood_risk 由 03 的 water_level、flow_velocity、siltation 与 02 的 flood_accumulation 合成计算。
条件：每 tick 检查
      flood_accumulation > flood_threshold
      且 water_level > flood_level_threshold
      且 随机通过（概率随累积量和淤积上升）
效果：生成 disaster_triggered 事件
      flood_active = true
      flood_severity 由累积量和峰值水位决定
滞后：条件满足后 1–3 tick 内触发
影响范围：超阈值的河段及其下游
```

### 4.2 传播
```
条件：flood_active = true
效果：洪水从上游河段向下游传播
      传播速度受流速和河道形态影响
      每 tick 检查下游河段是否达到影响阈值
      达到则加入 affected_segments
滞后：上游→下游 propagation_delay
影响范围：沿河段向下游，以及河边低洼田地
```

### 4.3 影响判定
```
条件：空间单元被洪水覆盖
效果：田地：生成 disaster_damage 事件，作物绝收，田埂冲毁
      建筑：低洼处建筑损毁，生成 disaster_damage
      山路：沿河山路中断
      取水点：部分取水点损毁，intake_status = 失效
      人物：按伤亡概率判定，生成 disaster_casualty
滞后：影响在洪水覆盖时立即产生
影响范围：被覆盖的单元
```

### 4.4 消退
```
条件：暴雨停止且 flood_accumulation 下降
效果：water_level 按消退速率下降
      flood_active 在 water_level 低于阈值后设为 false
      生成 disaster_ended 事件
滞后：消退慢于上涨，需要若干 tick
影响范围：受影响河段
```

### 4.5 后果记录
```
条件：disaster_ended
效果：汇总 affected_segments、affected_fields、affected_buildings、casualties
      生成 total_damage 记录
      不可逆损失标记（作物绝收、人员死亡、田埂彻底冲毁）
      可逆损失带恢复条件（田埂修复、房屋重建、取水点修复）
影响范围：所有受影响单元
```

## 5. 事件类型
- `disaster_triggered`：{disaster_type: flood, severity, affected_units, cause}
- `flood_spread`：{from_segment, to_segment, tick}
- `disaster_damage`：{disaster_type: flood, unit_id, damage_type, severity}
- `disaster_casualty`：{disaster_type: flood, agent_id, severity}
- `disaster_ended`：{disaster_type: flood, duration, total_damage}

## 6. 与其他系统的接口
- 读：02-climate 的降水累积和暴雨；03-hydrology 的水位、流速、淤积、山洪风险；04-terrain 的坡度（影响汇流速度）。
- 写：03-hydrology 改变水位和取水点状态；05-soil-and-fields 冲毁田地和作物；04-terrain 中断山路；06-vegetation 冲毁河边植被；人物系统触发伤亡、心理迁移、修复行动；记录系统记录灾害事件。
- 因果链：暴雨 → 水位上涨 → 山洪触发 → 沿河传播 → 田地冲毁/房屋损毁/人员伤亡 → 人物修复或迁徙 → 环境状态改变。

## 7. 地点参数占位
- flood_threshold（涝情累积阈值）
- flood_level_threshold（水位阈值）
- 触发概率曲线（累积量、淤积、坡度）
- 传播速度和传播衰减
- 各单元的伤亡概率和损失程度
- 消退速率
- 修复所需人力和时间
