# 资源流转审计（resource-flow）

- **对应任务**：TASK-01 第 4 项
- **基线**：`c9f29a5`
- **范围**：水、植物（木材/柴薪/草药）、鱼、动物（猎物）、食物（谷物/蔬菜/肉/鱼）、土地（地块/田块）、矿物。
- **口径**：每种资源给出"来源 → 载体 → 消耗/去向"，再标守恒性、可追溯性、可重放性与观察层覆盖。

## 1. 总览

| 资源 | 来源 | 存储载体 | 主要去向 | 守恒 | 事件可追溯 | 重放 |
|---|---|---|---|---|---|---|
| 生活用水 | `collect_water` 凭空产出 | `HouseholdState.water` | 每餐/每日饮水扣减 | **不成立**（源头无库存） | 仅 `agent_action_taken` | 靠该事件 |
| 谷物/蔬菜 | `harvest` 按长势结算 | `HouseholdState.grain/vegetable` | 进食、集市、还债、救济 | 部分（产出为源，消耗有记录） | `harvest_*`、`agent_action_taken` | 有 |
| 肉 | `hunt` 从浅山池扣减 | `HouseholdState.meat` | 进食、集市 | 池→家庭账面成立，但**扣错池** | `resource_harvested`、`gather_success` | 有 |
| 鱼 | `fish` 从河段池扣减 | `HouseholdState.fish` | 进食、集市 | 成立 | 同上 | 有 |
| 柴薪 | `gather_firewood` 从林地池扣减 | `HouseholdState.firewood` | **无消耗**，仅集市可交易 | 池→家庭成立 | 同上 | 有 |
| 草药 | `gather_herbs` 从林地池扣减 | `HouseholdState.herbs` | **无消耗**，仅集市可交易 | 池→家庭成立 | 同上 | 有 |
| 硬木 | `gather_hardwood` 从浅山/林地池扣减 | `HouseholdState.hardwood` | 建造、扩建、修缮配方 | 池→家庭成立；但建造在生产路径不可触发 | 同上 | 有 |
| 布 | `weave` 由劳动直接产出，无原料 | `HouseholdState.cloth` | 集市 | 源头未建模（麻/棉未接） | `weave_success` | 有 |
| 铜钱 | 集市出售货物 | `HouseholdState.coin` | 购买、建造、地租 | 集市配对转移；建造扣款 | `market_*`、`building_*` | 有 |
| 土地 | 生成器分配，继承时转移 | `LandParcelState` + `SpatialNode(parcel_refs)` | 租赁、用途变更 | 地块所有权配对转移 | `land_*` | 有 |
| 矿物 | 不存在 | - | - | - | - | - |

## 2. 逐项说明

### 2.1 水

- 产水：`collect_water` 每次加 `tuning.water.collect_amount`，代码注释明确"无上限"（[agents.py:1772-L1774](file:///F:/viae-chronicle/src/vale/modules/agents.py#L1772-L1774)）。
- 耗水：每餐 `water_per_meal`、日末饮水量（[agents.py:1609-L1612](file:///F:/viae-chronicle/src/vale/modules/agents.py#L1609-L1612)）。
- 自然侧只有 `water_level_ratio`，且只用于灌溉效率与产量修正（[agents.py:325](file:///F:/viae-chronicle/src/vale/modules/agents.py#L325)），不构成可抽取水源库存。
- 结论：水是"劳动换水"的抽象，不属于任何自然水体。迁入水文子系统时，必须先定义水源节点库存与抽取额度，否则守恒测试无从写起。

### 2.2 植物类（木材/柴薪/草药）

- 采集走统一的 `_execute_gather`（[agents.py:1877-L1944](file:///F:/viae-chronicle/src/vale/modules/agents.py#L1877-L1944)），三者共用"生态资源池"结构：森林节点提供柴薪、草药、硬木，浅山提供草药与硬木。
- 池结构只有 `current_stock / max_stock / regeneration_per_tick / extraction_limit_per_tick / seasonal_weights`，**没有生物量、生长阶段、退化度**。ADR §2.2 要求的植被生态属性在当前代码中完全缺失。
- 柴薪与草药没有任何消耗路径，只进不出；硬木只在建造配方里消耗，而建造工程在生产路径没有创建入口（见 §4）。
- 生成器还额外生成 `game_trail` 资源池，但没有任何动作指向它：猎物产出实际从 `low_mountain` 的"草药与硬木"池扣除（[agents.yaml:152-L154](file:///F:/viae-chronicle/config/worlds/brookvale-town-001/agents.yaml#L152-L154)）。这是一处明确的语义错配。

### 2.3 鱼与猎物

- 鱼：`fish` 动作目标 `river_town`，池类型在生成时被改写为 `fish`，扣减与产出配对记录，链路成立。
- 猎物：配置目标 `low_mountain`，与"兽径"池 `game_trail` 无关；`game_trail` 每 tick 再生、永不被采集。
- 两者都以"资源池"表达种群，没有个体、年龄结构、繁殖与捕食关系，ADR 的 Wildlife 目标状态尚未存在。

### 2.4 食物与农业

- `farm` 只累积 `field_growth`（上限 `max_field_growth`），并记录季内劳动；`harvest` 将长势清零，按田块面积、地力、灌溉档、作物基准产量结算 `grain` 或 `vegetable`（[agents.py:1616-L1662](file:///F:/viae-chronicle/src/vale/modules/agents.py#L1616-L1662)）。
- 没有种子消耗、没有土壤养分扣减、没有秸秆/绿肥回路。产量是净增的外部输入，`field_fertility` 除灾害外不会变化。
- `field_fertility` 与 `TerrainCellState.soil_fertility` 是两份独立数据：前者参与产量，后者生成后基本无人使用。
- 进食从家庭食物库存扣减，存量不足时清零且不产生负数（[agents.py:1594-L1605](file:///F:/viae-chronicle/src/vale/modules/agents.py#L1594-L1605)）；这是目前记账最严谨的一处。

### 2.5 布

`weave` 由劳动直接产布，代码注释明说"原料链为后续接入点"（[agents.py:1973-L1976](file:///F:/viae-chronicle/src/vale/modules/agents.py#L1973-L1976)）。所以布是第二类"无原料产出"，与谷物同性质。

### 2.6 土地

- 生成器按田块节点分配 `parcel_refs` 与每户可达田块顺序；`land.initialize_land` 在首个 tick 把 `terrain_cells` 与 `land_parcels` 写入状态（[land.py:46-L117](file:///F:/viae-chronicle/src/vale/modules/land.py#L46-L117)）。
- 继承在死亡结算中转移权属（agents 调用 land），租约由 `tenancy_economy` 结算。
- 土地没有市场交易，用途变更（旱田/水浇田）由生成器决定，运行期不可变更（待确认是否有隐藏入口）。

### 2.7 矿物

仓库内没有矿物、矿石、采石场相关状态或动作。ADR 的所有权表把矿物归环境，但目标状态尚不存在。

## 3. 额外发现：库存藏在 `attributes` 里

`tenancy_economy` 把公共仓库的存粮与储户余额写进 `building.attributes["stored_inventory"]`、`["depositor_balances"]`（[tenancy_economy.py:217-L252](file:///F:/viae-chronicle/src/vale/modules/tenancy_economy.py#L217-L252)）。这意味着"家庭库存"之外还有一份不受 `HouseholdState` 约束的食物库存，且只能通过 attributes 读写。所有权清单应把它单列，否则漏账。

## 4. 生产路径与测试路径不一致

下列能力只在测试里被调用，在生产循环中没有触发者：

| 能力 | 入口函数 | 运行时调用者 |
|---|---|---|
| 发起建造 | `construction.request_building` | 无（仅测试） |
| 推进建造 | `construction.advance_construction` | `construct` 动作，但需先有工程对象 |
| 议事决策 | `governance.propose_council_decision` 等 | 无（仅测试） |
| 社区储备与救济 | `environment.contribute/request/approve/settle` | 无（仅测试） |
| 借贷到期催收 | `tenancy_economy` 的 step | 有（run_xigu 注册） |

后果：硬木、铜钱的"消耗端"在长程模拟里基本不发生，资源单调累积；用长程数据做平衡判断时，必须知道这条事实。

## 5. 守恒与可追溯性结论

1. **能写出守恒断言的**：集市交易、借贷转移、采集池扣减与家庭入库、进食扣减。这些都有成对字段或 before/after。
2. **写不出守恒的**：取水（无源）、农业产量（无养分与种子输入）、织布（无原料）、采集池再生（凭空增长，只有事件没有约束）。
3. **重复来源**：`ResourcePool` 与 `SpatialNode.attributes` 同一份数据两份表示（生成器显式复制，见 `current-state.md` §5）；`field_fertility` 与 `terrain_cells.soil_fertility` 两份肥力。
4. **迁移要求**：先统一资源模型（池/种群/地块/建筑库存各归其主），再谈契约。否则 `ResourceService` 会把上述四类不同性质的"资源"强行塞进一个门面。
