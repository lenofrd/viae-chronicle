# 猎物

## 1. 目的
定义猎物（野兔、鹿、野鸡等）的分布、种群、活动规律、捕猎方式，以及捕猎如何影响种群和危险动物行为。

## 2. 核心概念
- 猎物：挂载在山林分区，是人物肉食和皮毛来源。
- 栖息地偏好：不同猎物偏好不同植被类型和地形。
- 繁殖季节：春季繁殖，种群增长快；秋冬捕猎旺季。
- 捕猎压力：捕猎累积形成压力，降低再生速度。
- 猎物与危险动物：猎物减少会导致危险动物食物短缺，增加下山概率。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| population | float | 种群数量 |
| carrying_capacity | float | 承载上限 |
| regeneration_rate | float | 再生速率 |
| hunting_pressure | float | 捕猎压力 |
| activity_state | enum | 活跃/繁殖/冬眠（部分猎物） |

## 4. 演化规则

### 4.1 猎物种群再生
```
条件：每 tick
效果：population += regeneration_rate
                    * density_factor
                    * habitat_quality_factor(vegetation_cover, vegetation_type)
      population 不超过 carrying_capacity
滞后：种群增长渐进
影响范围：按山林分区
```

### 4.2 捕猎事件
```
条件：人物系统写入 animal_hunted 事件
效果：population -= amount
      hunting_pressure += amount * pressure_coefficient
      若 population < amount，捕猎部分失败
滞后：无
影响范围：按栖息地
```

### 4.3 捕猎压力衰减
```
条件：每 tick
效果：hunting_pressure -= decay_rate
滞后：衰减慢于累积
影响范围：按栖息地
```

### 4.4 栖息地质量影响
```
条件：植被覆盖度或类型变化后
效果：carrying_capacity = base_capacity * habitat_quality_factor
      植被退化 → 承载上限下降 → 种群减少
滞后：按季
影响范围：按山林分区
```

### 4.5 猎物减少对危险动物的影响
```
条件：猎物种群低于阈值
效果：向 dangerous-animals.md 提供 food_shortage_signal
      危险动物攻击性和下山概率上升
滞后：猎物减少后 3–7 tick 显现
影响范围：同一山层及相邻区域
```

### 4.6 种群耗尽与恢复
```
条件：population 低于警戒线
效果：生成 population_depleted 事件
      再生速率下降
      人物感知到“猎物变少”
滞后：恢复需要长时间
影响范围：按栖息地
```

## 5. 事件类型
- `population_changed`：{habitat_id, species, old, new, cause}
- `animal_hunted`：{habitat_id, species, amount, agent_id, cause}
- `hunting_pressure_changed`：{habitat_id, species, old, new, cause}
- `population_depleted`：{habitat_id, species, severity}
- `population_recovered`：{habitat_id, species, severity}
- `habitat_quality_changed`：{habitat_id, old, new, cause}

## 6. 与其他系统的接口
- 读：06-vegetation 的植被覆盖度、植被类型；02-climate 的季节。
- 写：人物系统读种群和捕猎难度做决策；dangerous-animals.md 读猎物减少信号调整攻击性；08-hazards 读捕猎遭遇触发伤害事件。
- 因果链：持续捕猎 → 捕猎压力上升 → 猎物种群下降 → 危险动物食物短缺 → 野兽下山 → 人畜受害。

## 7. 地点参数占位
- 各山林分区的猎物初始种群、承载上限、再生速率
- 各猎物偏好的植被类型和地形
- 季节活动规律（繁殖季、捕猎旺季）
- 捕猎压力系数、衰减速率
- 栖息地质量对承载上限的影响系数
- 猎物减少触发危险动物行为的阈值