# 鱼类与水鸟

## 1. 目的
定义鱼类和水鸟的分布、种群、活动规律、捕猎方式，以及它们如何随水位、流速、季节变化。

## 2. 核心概念
- 鱼类：挂载在河段，受水位、流速、浑浊度影响，是人物食物来源。
- 水鸟：挂载在河边湿地，季节性迁徙，是人物食物来源之一。
- 繁殖季节：春季繁殖，种群增长快；秋冬种群稳定或减少。
- 捕捞压力：捕鱼、捕鸟累积形成压力，降低再生速度。
- 枯水/洪水：枯水期鱼群集中，易捕捞但种群脆弱；洪水期鱼群扩散，难捕捞。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| population | float | 种群数量 |
| carrying_capacity | float | 承载上限 |
| regeneration_rate | float | 再生速率 |
| hunting_pressure | float | 捕捞压力 |
| activity_state | enum | 活跃/繁殖/迁徙/稀少 |

## 4. 演化规则

### 4.1 鱼类种群再生
```
条件：每 tick
效果：population += regeneration_rate
                    * density_factor(population / carrying_capacity)
                    * water_condition_factor(water_level, flow_velocity, turbidity)
      population 不超过 carrying_capacity
滞后：种群增长渐进
影响范围：按河段
```

### 4.2 水鸟种群再生与迁徙
```
条件：每 tick
效果：繁殖季（春）：population += regeneration_rate
      迁徙季（秋/冬）：population -= migration_out
      迁徙季（春）：population += migration_in
      受 water_condition_factor 影响
滞后：迁徙按季节事件触发
影响范围：按湿地
```

### 4.3 捕捞事件
```
条件：人物系统写入 animal_hunted 事件
效果：population -= amount
      hunting_pressure += amount * pressure_coefficient
      若 population < amount，捕捞部分失败
滞后：无
影响范围：按栖息地
```

### 4.4 捕捞压力衰减
```
条件：每 tick
效果：hunting_pressure -= decay_rate
      hunting_pressure 不低于 0
滞后：衰减慢于累积
影响范围：按栖息地
```

### 4.5 水文条件对鱼类的影响
```
条件：水位、流速、浑浊度变化后
效果：枯水期：carrying_capacity 下降，鱼群集中
      洪水期：population 部分被冲走，carrying_capacity 暂时下降
      浑浊度高：捕鱼难度上升
滞后：水文变化后 1–3 tick 生效
影响范围：按河段
```

### 4.6 种群耗尽与恢复
```
条件：population 低于警戒线
效果：生成 population_depleted 事件
      再生速率进一步下降
      人物感知到“鱼变少了”
滞后：恢复需要长时间
影响范围：按栖息地
```

## 5. 事件类型
- `population_changed`：{habitat_id, species, old, new, cause}
- `animal_hunted`：{habitat_id, species, amount, agent_id, cause}
- `hunting_pressure_changed`：{habitat_id, species, old, new, cause}
- `population_depleted`：{habitat_id, species, severity}
- `population_recovered`：{habitat_id, species, severity}
- `migration_started` / `migration_ended`：{species, from, to}
- `fishing_condition_changed`：{segment_id, old, new, cause}

## 6. 与其他系统的接口
- 读：03-hydrology 的水位、流速、浑浊度；02-climate 的季节。
- 写：人物系统读种群和捕捞难度做决策；08-hazards 读洪水对鱼群的影响；记录系统把捕猎事件作为人物一生的事件。
- 因果链：枯水期 → 鱼群集中 → 捕捞容易 → 捕捞压力上升 → 种群下降 → 鱼变少 → 人物转向其他食物来源。

## 7. 地点参数占位
- 各河段的鱼类初始种群、承载上限、再生速率
- 各湿地的水鸟初始种群、承载上限、再生速率
- 季节活动规律（繁殖季、迁徙时间）
- 捕捞压力系数、衰减速率
- 水文条件对承载上限和种群的影响系数
- 种群耗尽警戒线