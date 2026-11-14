# 生理状态

## 1. 目的
定义人物的生理属性，包括性别带来的生理差异和生育周期，以及这些属性如何随时间和事件变化。

## 2. 核心概念
- **性别（sex）**：male（男）/ female（女）。第一版不涉及复杂的性别认同，只做生理性别及其衍生的社会角色。
- **年龄**：决定体力上限、生育能力、抗病能力。
- **体力（stamina）**：劳作、移动消耗，睡眠和进食恢复。
- **健康（health）**：受疾病、伤害、饥饿、分娩、衰老影响。
- **饥饿（hunger）**：每天累积，进食降低。
- **疲劳（fatigue）**：劳作累积，睡眠降低。
- **怀孕与分娩（仅女性）**：孕期体力受限，分娩有健康和生命风险。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| sex | enum | male / female |
| age | int | 年龄（岁） |
| stamina | float 0–100 | 当前体力 |
| max_stamina | float | 体力上限（受年龄、性别、健康影响） |
| health | float 0–100 | 当前健康 |
| hunger | float 0–100 | 饥饿度（>80 开始掉健康） |
| fatigue | float 0–100 | 疲劳度 |
| pregnancy_stage | enum? | 未怀孕/怀孕早期/怀孕晚期/产后休养 |
| fertility | bool | 当前是否具备生育能力 |

## 4. 演化规则

### 4.1 性别与基础生理
```
条件：角色创建
效果：决定 sex
      第一版不做男女基础体力的大幅差异，但女性在怀孕/产后有显著限制
```

### 4.2 饥饿累积与进食
```
条件：每 tick
效果：hunger += 基础消耗率
      若执行 eat 动作：hunger -= 食物营养值
      若 hunger > 80：health -= 损耗率
```

### 4.3 体力消耗与恢复
```
条件：执行动作或休息
效果：劳作消耗体力，sleep 恢复体力
      体力低于 20 时，决策倾向选择休息
```

### 4.4 怀孕与分娩（仅 female）
```
条件：pregnancy_started 事件触发且处于育龄期
效果：进入 pregnancy_stage = 怀孕早期
      怀孕早期（1–3 个月）：体力消耗略增，无重大限制
      怀孕晚期（7–9 个月）：max_stamina 下降 50%，无法进行重体力劳作（如 farm, gather_firewood 受限）
      分娩时：判定分娩风险
        - 普通成功：health -10，进入产后休养（生成 birth 事件）
        - 难产：health -40，可能触发死亡
      产后休养（1–2 个月）：max_stamina 恢复中，无法进行重体力劳作
```

### 4.5 健康与死亡
```
条件：health <= 0 或 age > 寿命阈值（考虑性别差异，女性略高）
效果：人物死亡
      生成 death 事件，触发人文环境的丧葬、继承
```

### 4.6 健康回血（任务 08）
```
条件：每日结算阶段，hunger < health_recovery_hunger_threshold
                 且 stamina > health_recovery_stamina_threshold
效果：health = min(100, health + health_recovery_per_day)
      仅数值实际变化时生成 health_recovered 事件（含 before/after/reason/hunger/stamina）
滞后：每 tick 结算后
影响范围：单人
```
说明：回血在 `AgentModule._settle` 结算阶段执行，**不覆盖** `_process_one` 中的饥饿扣血（4.2）——二者同日可并存（先扣后回，或条件不满足只扣不回）。健康上限 100 为域常量，非调参；回血速率/两阈值外置为 `health:` 调参块。长期饥饿或体力耗尽时条件不满足，不回血、不写事件。

## 5. 与其他系统的接口
- 读：食物存量、休息场所。
- 写：决策系统（重体力劳作受怀孕和疲劳限制）、人文环境（生育率影响人口结构）。