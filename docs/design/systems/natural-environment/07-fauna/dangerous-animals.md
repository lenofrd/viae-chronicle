# 危险动物

## 1. 目的
定义野猪、狼、蛇等危险动物的分布、活动规律、攻击性，以及它们如何因食物短缺或人类干扰而进入浅山和镇域，造成人畜伤害。

## 2. 核心概念
- 危险动物：野猪、狼、蛇，挂载在山林分区，深山和浅山出没。
- 攻击性：0–1，受饥饿、季节、人类干扰、护崽行为影响。
- 食物短缺：猎物减少或植被退化导致危险动物下山觅食。
- 下山事件：危险动物从深山进入浅山或镇域边缘。
- 伤人事件：人物遭遇危险动物时可能受伤，严重时死亡。
- 猎杀：人物组织猎杀危险动物，降低种群和攻击性，但有风险。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| population | float | 种群数量 |
| carrying_capacity | float | 承载上限 |
| regeneration_rate | float | 再生速率 |
| hunting_pressure | float | 捕猎压力 |
| aggression | float 0–1 | 攻击性 |
| food_shortage | float 0–1 | 食物短缺程度 |
| descended | bool | 是否已下山 |

## 4. 演化规则

### 4.1 种群再生
```
条件：每 tick
效果：population += regeneration_rate
                    * density_factor
                    * habitat_quality_factor
      population 不超过 carrying_capacity
滞后：种群增长渐进
影响范围：按山林分区
```

### 4.2 攻击性计算
```
条件：每 tick
效果：aggression = base_aggression
                 + food_shortage * hunger_factor
                 + season_factor（繁殖季/冬季高）
                 + disturbance_factor（人类活动干扰）
      aggression 夹紧到 0–1
滞后：攻击性变化有 1–3 tick 滞后
影响范围：按种群
```

### 4.3 食物短缺信号
```
条件：game.md 提供 food_shortage_signal
效果：food_shortage 上升
      攻击性上升
      下山概率上升
滞后：猎物减少后 3–7 tick 显现
影响范围：同一山层及相邻区域
```

### 4.4 下山判定
```
条件：food_shortage 或 aggression 超过阈值
效果：按概率判定是否下山
      生成 wildlife_descended 事件
      descended = true
      动物从深山进入浅山或镇域边缘
滞后：条件满足后 1–5 tick 内可能下山
影响范围：深山 → 浅山 → 镇域边缘
```

### 4.5 遭遇与伤人
```
条件：人物在危险动物活动区域行动，或动物下山
效果：按 aggression 和遭遇概率判定
      生成 wildlife_incident 事件
      incident_type：遭遇未伤人/伤人/致死/家畜受害
      事件成为人物心理迁移和后续事件的父事件
滞后：无
影响范围：按人物和地点
```

### 4.6 猎杀
```
条件：人物系统写入猎杀事件
效果：population -= amount
      hunting_pressure += amount * pressure_coefficient
      攻击性暂时下降（幸存个体更警惕或更恐惧）
      猎杀本身有风险，可能触发人物受伤事件
滞后：无
影响范围：按种群
```

### 4.7 种群耗尽与恢复
```
条件：population 低于警戒线
效果：生成 population_depleted 事件
      下山事件减少，但幸存个体攻击性可能更高
滞后：恢复需要长时间
影响范围：按栖息地
```

## 5. 事件类型
- `population_changed`：{habitat_id, species, old, new, cause}
- `aggression_changed`：{habitat_id, species, old, new, cause}
- `food_shortage_changed`：{habitat_id, species, old, new, cause}
- `wildlife_descended`：{from_habitat, to_unit, species, cause}
- `wildlife_incident`：{habitat_id, species, incident_type, severity, affected_agents}
- `animal_hunted`：{habitat_id, species, amount, agent_id, cause}
- `population_depleted`：{habitat_id, species, severity}

## 6. 与其他系统的接口
- 读：game.md 的猎物减少信号；06-vegetation 的植被覆盖；02-climate 的季节；人物系统的猎杀和干扰事件。
- 写：人物系统读攻击性和下山状态做决策（防范、猎杀、绕行）；08-hazards 读下山和遭遇事件触发灾害；记录系统把遭遇和猎杀作为人物一生的事件。
- 因果链：捕猎过度 → 猎物减少 → 食物短缺 → 攻击性上升 → 下山 → 遭遇 → 伤人 → 人物组织猎杀 → 种群下降 → 下山减少（但幸存个体更危险）。

## 7. 地点参数占位
- 各山林分区的危险动物初始种群、承载上限、再生速率
- base_aggression、hunger_factor、season_factor、disturbance_factor
- 食物短缺对攻击性的影响系数
- 下山触发阈值和概率
- 遭遇概率、伤人概率、致死概率
- 猎杀的风险和效果
- 种群耗尽警戒线