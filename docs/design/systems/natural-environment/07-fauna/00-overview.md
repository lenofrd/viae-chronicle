# 动物与生态子系统总览

## 1. 目的
定义鱼类、水鸟、猎物、危险动物的分布、数量、活动规律，以及动物如何随季节、水文、植被、人类捕猎变化，如何影响人物生计和安全。

## 2. 核心概念
- 动物类群：鱼、水鸟、猎物（野兔、鹿、野鸡等）、危险动物（野猪、狼、蛇）。
- 栖息地：动物挂载在空间单元上，鱼挂河段，水鸟挂河边湿地，猎物和危险动物挂山林分区。
- 种群数量：按栖息地记录，有承载上限和再生速度。
- 活动规律：季节性活动（迁徙、冬眠、繁殖）、昼夜活动（第一版不做昼夜，只做季节）。
- 捕猎压力：人类捕猎累积形成压力，降低种群再生速度，甚至导致局部灭绝。
- 野兽下山：深山食物短缺或人类活动干扰时，危险动物进入浅山和镇域边缘。
- 生态平衡：捕猎过度导致猎物减少，危险动物食物短缺，可能更频繁下山。

## 3. 状态变量（按栖息地挂载）
| 变量 | 类型 | 说明 | 变化速率 |
|---|---|---|---|
| population | float | 种群数量 | 按再生和捕猎变化 |
| carrying_capacity | float | 环境承载上限 | 受栖息地质量影响 |
| regeneration_rate | float | 当前再生速率 | 受种群密度和栖息地影响 |
| hunting_pressure | float | 捕猎压力累积量 | 按捕猎事件累积，按衰减速率消退 |
| activity_state | enum | 活跃/迁徙/冬眠/繁殖 | 按季节切换 |
| aggression | float 0–1 | 危险动物的攻击性 | 受饥饿、干扰、季节影响 |

各状态变量的 `max_delta_per_tick` 见地点参数。

## 4. 演化规则分类
- tick 驱动：种群按再生速率增长、捕猎压力按衰减速率消退、活动状态按季节切换。
- 事件驱动：捕猎事件减少种群、野兽下山事件、动物伤人事件、迁徙事件。
- 累积效应：持续捕猎 → 捕猎压力累积 → 再生速率下降 → 种群减少 → 猎物稀缺 → 危险动物下山。
- 外部注入：接口写入的动物事件（如外来物种、疫病），标注为外部事件。

## 5. 事件类型
- `population_changed`：{habitat_id, species, old, new, cause}
- `hunting_pressure_changed`：{habitat_id, species, old, new, cause}
- `animal_hunted`：{habitat_id, species, amount, agent_id, cause}
- `population_depleted`：{habitat_id, species, severity}
- `population_recovered`：{habitat_id, species, severity}
- `activity_state_changed`：{habitat_id, species, old, new}
- `wildlife_incident`：{habitat_id, species, incident_type, severity, affected_agents}
- `wildlife_descended`：{from_habitat, to_unit, species, cause}
- `migration_started` / `migration_ended`：{species, from, to}

## 6. 与其他系统的接口
- 读：
  - 02-climate：季节、温度、降水。
  - 03-hydrology：水位、流速、浑浊度。
  - 06-vegetation：植被类型、覆盖度、资源存量。
  - 08-hazards：山洪/火灾事件改变栖息地、减少种群。
  - 人物系统：捕猎事件。
- 写：
  - 人物系统：提供猎物存量、捕猎难度、危险动物风险，作为决策输入。
  - 08-hazards：提供野兽下山和动物伤人事件。
  - 06-vegetation：捕猎压力影响植被（如食草动物减少影响植被生长，第一版可简化不做）。
  - 记录系统：捕猎和遭遇作为人物一生的事件。
- 因果链：持续捕猎 → 捕猎压力上升 → 猎物种群下降 → 危险动物食物短缺 → 野兽下山 → 人畜受害 → 人物组织猎杀或加强防范。

## 7. 地点参数占位
具体地点（如 Brookvale）需要提供：
- 栖息地清单：ID、类型（河段/湿地/山林分区）、挂载的动物类群
- 各动物类群的初始种群、承载上限、再生速率
- 季节活动规律（迁徙时间、冬眠时间、繁殖季节）
- 捕猎压力系数、衰减速率
- 野兽下山的触发条件（食物短缺阈值、干扰阈值）
- 动物伤人事件的触发概率和后果
- 捕猎遭遇的触发概率

## 8. 扩展预留
- 新动物类群（如家畜、蜜蜂、害虫）：作为新类群扩展。
- 疫病：作为外部注入事件，影响种群。
- 食物链：第一版不做完整食物链，只做“捕猎压力 → 种群 → 野兽下山”一条链。
- 驯化/养殖：作为人物系统扩展，动物子系统只提供基础种群数据。

## 9. 横切机制引用

- 变化速率上限、滞后与累积、空间传播、可逆性规则见 `09-dynamics/`。
- 事件记录、快照结构、查询接口遵循 `10-state-and-records/`。
- 本子系统所有状态变化事件按 `10-state-and-records/event-stream.md` 的统一格式记录。