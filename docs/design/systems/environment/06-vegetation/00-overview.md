# 植被与采集子系统总览

> **能力状态**（E1 审计 2026-11-22）：**部分实现**——仅植被类资源池再生（`EcologyModule`）；覆盖度、群落、退化恢复未实现（动态植被为生态阶段 E3 主题，文中状态变量表按**规划**读）。 逐项依据见[设计树对齐审计](../../../audits/ecology-foundation/design-tree-alignment.md)。

## 1. 目的
定义山林分区、植被状态、草药与柴薪资源如何随季节、降水、采集压力、人类活动变化，以及资源退化如何反过来影响地形稳定、水土保持、人物生计。

## 2. 核心概念
- 山林分区：按山层和坡面划分的植被单元，挂在空间骨架上。
- 植被覆盖度：0–1，影响水土保持、资源再生、滑坡风险。
- 植被类型：灌木、针叶林、阔叶林、草坡、裸地等。
- 资源点：具体采集位置，挂在山林分区下，有资源类型、存量、再生速度、采集压力。
- 草药：分种类、分位置分布，各有再生速度和采集难度。
- 柴薪：日常采集资源，消耗快、再生中速，过度采集导致近山退化。
- 采集压力：累积采集量超过再生能力时，资源退化和再生速度下降。
- 再生与退化：资源存量按再生速度恢复；采集压力高时再生变慢，甚至触发退化事件。

## 3. 状态变量（按山林分区/资源点挂载）
| 变量 | 类型 | 说明 | 变化速率 |
|---|---|---|---|
| vegetation_cover | float 0–1 | 植被覆盖度 | 慢变量，按季 |
| vegetation_type | enum | 灌木/针叶林/阔叶林/草坡/裸地 | 按退化/恢复变化 |
| resource_stock | float | 资源存量 | 按采集和再生变化 |
| regeneration_rate | float | 当前再生速率 | 受采集压力和植被覆盖影响 |
| gathering_pressure | float | 采集压力累积量 | 按采集事件累积，按恢复速率衰减 |
| degradation_state | enum | 正常/轻度退化/重度退化/裸地 | 按采集压力和植被覆盖迁移 |

## 4. 演化规则分类
- tick 驱动：资源存量按再生速度恢复、采集压力按衰减速率消退、植被覆盖按季缓慢变化。
- 事件驱动：采集事件消耗资源、过度采集触发退化事件、植被退化触发水土流失和滑坡风险上升。
- 累积效应：多人持续采集 → 采集压力累积 → 再生速率下降 → 资源退化 → 采集半径扩大。
- 外部注入：接口写入的植被事件（如人为烧山、外来物种），标注为外部事件。

## 5. 事件类型
- `resource_stock_changed`：{point_id, resource_type, old, new, cause}
- `gathering_pressure_changed`：{point_id, old, new, cause}
- `regeneration_rate_changed`：{point_id, old, new, cause}
- `resource_degraded`：{point_id, old_state, new_state}
- `resource_recovered`：{point_id, old_state, new_state}
- `vegetation_cover_changed`：{zone_id, old, new, cause}
- `vegetation_type_changed`：{zone_id, old, new, cause}（如阔叶林→灌木→裸地）
- `herb_gathered`：{point_id, herb_type, amount, agent_id, cause}
- `firewood_gathered`：{point_id, amount, agent_id, cause}
- `over_gathering_detected`：{point_id, pressure, threshold}

## 6. 与其他系统的接口
- 读：
  - 02-climate：降水、温度、季节系数。
  - 03-hydrology：河边湿地水位。
  - 04-terrain：山层、坡面、坡度、坡向。
  - 08-hazards：火灾和山洪改变植被覆盖度和植被类型。
  - 人物系统：采集事件（草药、柴薪、猎物）。
- 写：
  - 04-terrain：植被覆盖度影响土体稳定度和滑坡风险。
  - 07-fauna：植被退化影响猎物栖息和野兽行为。
  - 08-hazards：植被退化提高滑坡和山洪风险。
  - 人物系统：提供资源存量、采集难度、采集风险，作为决策输入。
- 因果链：持续采集 → 采集压力累积 → 再生速率下降 → 资源退化 → 采集半径扩大 → 人物进更深的山 → 风险和成本上升 → 人物决策（减少采集、换资源、迁徙、协商规则）。

## 7. 地点参数占位
具体地点（如 Brookvale）需要提供：
- 山林分区清单：ID、所属山层/坡面、初始植被类型、初始植被覆盖度
- 资源点清单：ID、所属分区、资源类型、初始存量、再生速度、采集难度、采集风险
- 草药清单：种类、分布位置、再生速度、采集难度、用途
- 柴薪资源点清单：位置、初始存量、再生速度
- 采集压力阈值、退化阈值、恢复阈值
- 再生速度受采集压力和植被覆盖的影响系数
- 植被类型迁移的阈值和条件

## 8. 扩展预留
- 新资源类型（如石料、蜂蜜、蘑菇）：作为资源点扩展。
- 新植被类型（如竹林、果园）：作为植被类型扩展。
- 人工种植（如种树、种药）：作为人物行动事件扩展，恢复资源存量。
- 火灾对植被的影响：由 08-hazards 触发，本子系统读取后果。
- 外来物种入侵：作为外部注入事件，第一版不做。

## 9. 横切机制引用

- 变化速率上限、滞后与累积、空间传播、可逆性规则见 `09-dynamics/`。
- 事件记录、快照结构、查询接口遵循 `10-state-and-records/`。
- 本子系统所有状态变化事件按 `10-state-and-records/event-stream.md` 的统一格式记录。
