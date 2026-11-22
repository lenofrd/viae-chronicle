# 水文子系统总览

> **能力状态**（E1 审计 2026-11-22）：**部分实现**——水井类水源库存/补水/抽取结算已实现；河段流速、淤积、可渡性未实现。 逐项依据见[设计树对齐审计](../../../audits/ecology-foundation/design-tree-alignment.md)。

## 1. 目的
定义河段的水位、流速、可渡性、取水与灌溉条件、河道淤积如何随气候和人类活动变化，以及水文如何驱动土壤湿度、山洪、通行条件。

> **004 裁决（2026-11-17，M5 + 任务30）——生活用水最小切片**：`water_level_ratio` 与 `irrigation_gear` 随降水演化，驱动灌溉和产量 `moisture`；它们**不是地下水位**，当前不控制水井出水。溪古镇唯一饮用水来源是公共水井，翠溪/灌溉渠不自动视为可饮用水。`collect_water` 每次从水井取 12 单位并计入家庭库存，往返移动时间计入工作窗；取水后人物回到家，不能在井边连续零通勤取水。家庭每日按存活成员数消耗生活用水（1×人数），每次进食另耗 0.5（烹饪/佐餐），水不足则该次无法进食。远户在春/秋可达时按季节可达性自行储备，以应对夏/冬工作窗缩短；家庭库存无容量上限。水井当前没有有限地下水库存或枯竭模拟。饮用水健康惩罚、水质处理、水存储上限、水权冲突**不在本切片**；完整河段与地下水模型为后续版本目标，实现顺序见 [decisions/004](../../../decisions/004-intraday-time-and-production-base.md) §2.7–2.8。
>
> **P3a 已落地（2026-11-20，架构审计阶段二）——水源库存**：水井取得有限存量，状态挂在 `EnvironmentState.water_sources`（`capacity` / `current_stock` / `regeneration_per_tick` / `extraction_limit_per_tick`），由 `domains/environment/hydrology.py` 统一「读-校验-写」结算（P3a 期间结算在现已删除的 `contracts/water.py` 切片，P3c 按契约所有权裁决移交环境域所有者，人类模块经 `contracts.resources.ResourceService.withdraw_water` 路由；路径指称由 `modules/hydrology.py` 更新，E1 审计 2026-11-22），人类模块不得直接改库存。每 tick 按 `regeneration_per_tick × water_level_ratio` 补水（到容量即止），同 tick 全部取水合计不超过 `extraction_limit_per_tick`；存量或额度不足时写 `water_withdrawal_refused`，实际给付量可小于请求量。容量与额度按现量标定（[调参][临时值]，见 `config/worlds/brookvale-town-001/natural-params.yaml` 的 `water_supply.well`），两年基线内不触顶、取水行为与 P3a 前逐 tick 等价。地下水、河段取水点与水质仍不在本切片。

## 2. 核心概念
- **河段**：河流按上下游划分的空间单元，第一版为上游段、镇前段、下游段。
- **水位**：河段当前水面高度，相对基准的偏离量。
- **流速**：水流速度，影响渡河风险、磨坊动力、泥沙搬运。
- **可渡性**：分“可涉水、需渡船、不可渡”三档，随水位变化。
- **取水点**：河段上可引水灌溉或取生活用水的位置。
- **灌溉条件**：依赖水位和取水点状态，分“充足、偏少、缺水、断水”四档。
- **河道淤积**：慢变量，降低过水能力，抬高同流量下的水位。
- **上下游传播**：上游水位变化沿河段向下游传播，有时滞和衰减。

## 3. 状态变量（按河段挂载）
| 变量 | 类型 | 说明 | 变化速率上限 |
|---|---|---|---|
| water_level | float | 水位相对基准的偏离 | 每 tick 不超过 X |
| flow_velocity | float | 流速 | 每 tick 不超过 Y |
| turbidity | float | 浑浊度/泥沙含量 | 受降水影响，有上限 |
| crossing_state | enum | 可涉水/需渡船/不可渡 | 随水位跳档，但有滞后 |
| intake_status | dict | 各取水点状态（正常/受限/失效） | 随水位变化 |
| irrigation_state | enum | 充足/偏少/缺水/断水 | 随水位和取水点 |
| siltation | float | 淤积度 | 慢变量，按季累积 |

## 4. 演化规则分类
- **tick 驱动**：水位向平衡水位缓慢回归、淤积按季累积、流速随水位调整。
- **事件驱动**：暴雨触发水位快速上升、山洪触发、清淤事件降低淤积。
- **累积效应**：上游截水累积导致下游水位偏低；淤积累积降低过水能力。
- **外部注入**：接口写入的水文事件，标注为外部事件。

## 5. 事件类型
- `water_level_changed`：{segment_id, old, new, cause}
- `flow_velocity_changed`：{segment_id, old, new, cause}
- `crossing_state_changed`：{segment_id, old, new, cause}
- `intake_status_changed`：{segment_id, intake_id, old, new, cause}
- `irrigation_state_changed`：{segment_id, old, new, cause}
- `siltation_changed`：{segment_id, old, new, cause}
- `upstream_withdrawal`：{segment_id, amount, cause}（人类截水事件，由人物系统写入）
- `silt_cleared`：{segment_id, amount, cause}（清淤事件，由人物系统写入）

P3a 水源库存事件（已实现）：`water_source_initialized`、`water_source_regenerated`、`water_withdrawn`（含 `requester_id`、`stock_before/stock_after`）、`water_withdrawal_refused`（含 `requested/granted/reason`）。

## 6. 与其他系统的接口
- **读**：
  - 02-climate：降水、温度、季节系数、极端天气（暴雨）。
  - 04-terrain：坡度（影响流速和淤积）。
  - 08-hazards：山洪事件改变水位、冲毁取水点。
  - 人物系统：截水、清淤、修渠等行动事件。
- **写**：
  - 05-soil-and-fields：提供灌溉条件、土壤湿度修正。
  - 06-vegetation：河边湿地资源受水位影响。
  - 07-fauna：鱼群随水位和流速变化。
  - 08-hazards：提供水位、流速、淤积状态，由 08 计算山洪风险。
  - 02-distance-and-time：提供渡河通行条件和风险。
- **因果链**：暴雨 → 水位上升 → 可渡性变化 → 山洪风险 → 山洪事件 → 田地冲毁/人物伤亡。上游截水 → 下游水位下降 → 下游灌溉缺水 → 下游人物行动。

## 7. 地点参数占位
具体地点（如 Brookvale）需要提供：
- 河段清单：ID、上下游顺序、基准水位、河宽等级、取水点清单、渡口清单
- 水位变化速率上限、流速变化速率上限
- 可渡性阈值（可涉水/需渡船/不可渡三档的水位分界）
- 取水点失效阈值、灌溉条件四档的水位分界
- 淤积速率、淤积对过水能力的影响系数
- 上下游传播时滞和衰减系数
- 山洪触发的水位和降水累积阈值

## 8. 扩展预留
- 新河段：在 river-segments.md 里扩展，上下游关系通过配置声明。
- 新取水点/渡口：作为河段子对象扩展，规则不变。
- 多河流/支流：作为新河段类型，连接关系扩展。
- 地下水/井水：作为新水源类型，第一版不做，预留接口。
- 水质：作为新状态变量扩展，第一版只做浑浊度。

## 9. 横切机制引用

- 变化速率上限、滞后与累积、空间传播、可逆性规则见 `09-dynamics/`。
- 事件记录、快照结构、查询接口遵循 `10-state-and-records/`。
- 本子系统所有状态变化事件按 `10-state-and-records/event-stream.md` 的统一格式记录。
