# 灾害子系统总览（环境机制视角）

> **能力状态**（E1 审计 2026-11-22，裁决 5-③ 拆分后口径）：本文件只描述**环境侧灾害机制与累积状态**。当前实现仅旱情累积（`domains/environment/climate.py`）；山洪/滑坡/野兽遭遇的现行形态是**场景层概率注入**（见 [scenarios/hazard-injection.md](../../../scenarios/hazard-injection.md)），不得视为已实现的环境机制；火灾、虫害为规划。依据见[设计树对齐审计 §3](../../../audits/ecology-foundation/design-tree-alignment.md)。

## 1. 目的
统一定义山洪、旱、虫害、火灾等灾害的**环境机制**：触发条件（累积状态超阈值）、演化过程、影响范围和后果。灾害是环境各子系统累积状态超过阈值后的爆发事件，不是随机凭空发生。

## 2. 核心概念
- 灾害类型：山洪、旱、虫害、火灾（野兽下山属 Wildlife 域行为与场景注入，见 [wildlife/](../../wildlife/00-overview.md) 与 [scenarios/wildlife-incidents.md](../../../scenarios/wildlife-incidents.md)）。
- 触发条件：依赖上游子系统的累积状态（旱涝累积、滑坡风险、虫害风险、植被干燥度），不是纯随机。
- 滞后：触发条件满足后，灾害在若干 tick 内爆发，不是立即。
- 影响范围：按空间单元和传播路径计算，不是全局一刀切。
- 后果：改变其他子系统状态，生成人物可感知的事件，成为人物心理迁移和决策的父事件。
- 可逆/不可逆：部分后果可恢复（修渠、补种），部分不可逆（冲毁的田、致死）。

## 3. 灾害类型与上游触发源（规划目标）
| 灾害 | 触发源子系统 | 关键累积量 | 触发滞后 | 现状 |
|---|---|---|---|---|
| 旱 | 02-climate + 03-hydrology | 降水不足累积 + 水位 | 3–7 tick | **已实现**（climate 旱情标量累积；损害施加为场景注入） |
| 山洪 | 02-climate + 03-hydrology | 降水累积 + 水位 + 淤积 | 1–3 tick | 环境机制**规划**；现为[场景注入](../../../scenarios/hazard-injection.md) |
| 虫害 | 05-soil-and-fields | pest_risk | 1–3 tick | **规划** |
| 火灾 | 02-climate + 06-vegetation | 干燥度 + 植被状态 | 1–2 tick | **规划** |
| 滑坡 | 04-terrain | 滑坡风险累积 | 1–3 tick | 环境机制**规划**（terrain 现仅静态引导）；现为[场景注入](../../../scenarios/hazard-injection.md) |

## 4. 状态变量（按灾害类型和空间单元挂载）
| 变量 | 类型 | 说明 |
|---|---|---|
| active_disasters | list | 当前活跃的灾害事件 |
| disaster_severity | enum | 轻度/中度/重度 |
| disaster_duration | int | 已持续 tick |
| affected_units | list | 受影响的空间单元 |
| damage_record | dict | 各灾害子文件用各自字段记录损失（flood: affected_segments/fields/buildings/casualties；drought: crop_loss/affected_water_sources；pest: 减产比例；fire: 烧毁面积），不强制统一 |

各灾害状态变量的变化速率受 [kernel/dynamics/](../../kernel/dynamics/00-overview.md) 约束，`max_delta` 见地点参数。

## 5. 演化规则分类
- 事件驱动：上游累积量超阈值触发灾害。
- 累积效应：灾害后果改变其他子系统状态（田毁、路断、人伤）。
- 传播：灾害沿空间路径扩散（山洪沿河段、火灾沿植被、虫害沿田地）。
- 外部注入：接口写入的灾害事件，标注为外部事件（现行山洪/滑坡/野遇即此形态，见场景层）。

## 6. 事件类型（规划）
- `disaster_triggered`：{disaster_type, severity, affected_units, cause}
- `disaster_ended`：{disaster_type, duration, total_damage}
- `disaster_damage`：{disaster_type, unit_id, damage_type, severity}
- `disaster_casualty`：{disaster_type, agent_id, severity}

## 7. 与其他系统的接口
- 读：
  - 02-climate：旱涝累积、极端天气。
  - 03-hydrology：水位、流速、山洪风险、淤积。
  - 04-terrain：滑坡风险、山路状态。
  - 05-soil-and-fields：虫害风险、田地状态。
  - 06-vegetation：植被干燥度、退化状态。
- 写：
  - 03-hydrology：山洪改变水位、冲毁取水点。
  - 04-terrain：滑坡和山洪改变山路状态。
  - 05-soil-and-fields：山洪冲毁田地、旱降低地力、虫害降低收成。
  - 06-vegetation：火灾和山洪改变植被覆盖度。
  - 人物系统（Society 域）：灾害事件作为人物决策和心理迁移的父事件。
- 因果链：旱涝累积 → 灾害触发 → 后果广播 → 人物感知和决策 → 修复或迁徙 → 环境状态改变。

## 8. 地点参数占位
具体地点（如 Brookvale）需要提供：
- 各灾害的触发阈值（累积量、风险值）
- 触发滞后范围（tick）
- 严重程度分级标准
- 传播路径和传播速度
- 各灾害对各子系统的影响系数
- 灾害持续时间和结束条件
- 灾害伤亡概率

## 9. 扩展预留
- 新灾害类型（地震、瘟疫、外来入侵）：作为新文件扩展。
- 灾害链（山洪→滑坡→疫病）：作为组合事件扩展，第一版不做。
- 气候变化对灾害频率的影响：作为外部注入或慢变量扩展。
- 灾害预警：作为人物系统的认知扩展，第一版不做。

## 10. 横切机制引用

- 变化速率上限、滞后与累积、空间传播、可逆性规则见 [kernel/dynamics/](../../kernel/dynamics/00-overview.md)。
- 事件记录、快照结构、查询接口遵循 [kernel/state-and-records/](../../kernel/state-and-records/00-overview.md)。
- 本子系统所有状态变化事件按其统一格式记录。
