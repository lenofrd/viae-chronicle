# 状态所有权清单（state-ownership）

- **对应任务**：TASK-01 第 2 项
- **基线**：`c9f29a5`
- **证据口径**：静态检索脚本 `.check/audit_state_access.py`（按字段匹配 `.state.<field>` 的读写形态）+ 逐条人工复核调用链。
- **已知盲区**：通过局部别名写字段（如 `pool = world.state.ecological_resources[...]` 后 `pool["current_stock"] = ...`）与 `getattr(world.state, "...")` 动态访问不会被脚本命中，下文已人工补记；其余无法确认的条目明确标"待确认"。

所有状态都存放在 [WorldState](file:///F:/viae-chronicle/src/vale/core/state.py#L358-L392) 的同一实例上。下表"当前所有者"指事实上的写入者，不代表代码有保护。

## 1. 自然侧状态

| 状态 | 存放 | 当前写入者 | 当前读者 | 写入机制 | 目标所有者 | 判定 |
|---|---|---|---|---|---|---|
| 气候快照 | `state.climate` | `ClimateModule`（[climate.py](file:///F:/viae-chronicle/src/vale/modules/climate.py#L93-L177)） | agents / construction / ecology / environment / xigu_events / cli / replay | 每 tick 重算后整体赋值，写 `weather_changed` 等事件 | Environment | 边界干净，唯一写者 |
| 水位比例、灌溉档 | `state.water_level_ratio`、`irrigation_gear` | `ClimateModule`（[L236-L264](file:///F:/viae-chronicle/src/vale/modules/climate.py#L236-L264)） | `AgentModule` 用 `getattr` 读取参与产量计算（[agents.py:325](file:///F:/viae-chronicle/src/vale/modules/agents.py#L325)） | 按降水/蒸发演化，变化写事件 | Environment（水文） | 写者单一；读侧用动态访问，静态检查查不到 |
| 生态资源池 | `state.ecological_resources`（裸 dict，无 Schema） | `EcologyModule` 初始化与再生（[ecology.py](file:///F:/viae-chronicle/src/vale/modules/ecology.py#L15-L47)）；**`AgentModule._execute_gather` 直接扣减**（[agents.py:1891-L1911](file:///F:/viae-chronicle/src/vale/modules/agents.py#L1891-L1911)） | agents / xigu_events / replay / render | 池子以局部别名取出后原地改字典；采集另写 `resource_harvested` | Environment（植物与无机资源）、Wildlife（鱼与猎物） | **主要违例**：人类模块直接写环境状态；且鱼、猎物、柴薪、草药共用同一种池结构 |
| 田块长势 | `state.field_growth`（`node_id -> float`） | `AgentModule`（farm/harvest）；`XiguEventsModule` 洪涝/旱灾扣减 | agents / render / replay | 直接改 dict + 写 `field_labor_progressed`、`field_flood_damage` 等 | Environment（作物生长），收成结算归 Human | **跨域写**：灾害模块直接改长势 |
| 田块地力 | `state.field_fertility` | `AgentModule` 初始化为 1.0；`XiguEventsModule` 滑坡扣减 | agents | 直接改 dict | Environment（土壤） | **跨域写**；且与 `TerrainCellState.soil_fertility` 形成两份肥力 |
| 田块季内劳力 | `state.field_season_labor` | `AgentModule` | agents | 直接改 dict | Human（劳动记录） | 属人类生产记录，暂可接受 |
| 地形单元 | `state.terrain_cells` | `land.initialize_land`（[land.py:46-L117](file:///F:/viae-chronicle/src/vale/modules/land.py#L46-L117)） | 待确认（未见运行期读取） | 首次 tick 从生成结果复制，写 `land_parcel_created` | Environment | 初始化后不再演化，是静态副本 |
| 动物个体/种群 | 不存在 | - | - | - | Wildlife | ADR 目标状态尚未实现 |

补充事实：`hunt` 配置的目标节点是 `low_mountain`（[agents.yaml:152-153](file:///F:/viae-chronicle/config/worlds/brookvale-town-001/agents.yaml#L152-L153)），而生成器为猎物单列了 `game_trail` 资源池（[xigu.py:169-L178](file:///F:/viae-chronicle/src/vale/worldgen/xigu.py#L169-L178)）。结果是打猎扣的是"草药与硬木"池，`game_trail` 池只再生、从不被采集。这说明"资源池"与"物种/资源类型"没有语义绑定。

## 2. 人文侧状态

| 状态 | 存放 | 当前写入者 | 当前读者 | 写入机制 | 目标所有者 | 判定 |
|---|---|---|---|---|---|---|
| 人物状态 | `state.agents` | `AgentModule`（[agents.py:386-L422](file:///F:/viae-chronicle/src/vale/modules/agents.py#L386-L422)）；`XiguEventsModule` 直接改 `agent.health`（[xigu_events.py:132-L142](file:///F:/viae-chronicle/src/vale/modules/xigu_events.py#L132-L142)） | construction / governance / land / environment / social / xigu_events / replay | 直接改 Pydantic 对象字段 + 写事件 | Human Society | **跨域写**：事件模块改人物健康 |
| 家庭状态与库存 | `state.households` | `AgentModule`；`land.relocate_household` 改 `home_node`；`construction` 扣 `coin`/`hardwood`；`environment` 改社区储备相关家庭资产 | 多个模块 | 直接改对象字段 + 写配对事件 | Human Economy | 多写者，无统一结算入口 |
| 地块与权属 | `state.land_parcels` | `land`（初始化、转移、用途变更、继承）；replay | agents / construction / environment / tenancy_economy | 改 Pydantic 对象 + `land_*` 事件 | Human（土地制度） | 写者集中在 land，但 land 被 agents 懒调用 |
| 建筑 | `state.buildings` | `land.initialize_land`（住宅与公共仓房初始化，[L123-L164](file:///F:/viae-chronicle/src/vale/modules/land.py#L123-L164)）；`construction`（扩建、拆除、修缮）；replay | agents / environment / tenancy_economy | 改对象 + `building_*` 事件 | Human（建设） | 初始化与改造分属两个模块 |
| 建造工程 | `state.construction_projects` | `construction`；replay | agents | 对象字段 + `construction_*` 事件 | Human（建设） | 运行时无触发路径（见 §4） |
| 租约 | `state.land_leases` | `tenancy_economy` | construction / land / replay | 字典写入 + `land_lease_*` 事件 | Human Economy | 干净 |
| 实物借贷 | `state.resource_loans` | `tenancy_economy` | replay | 字典写入 + `resource_loan_*` 事件 | Human Economy | 干净 |
| 公库 | `state.public_treasury` | `tenancy_economy`；replay | 待确认 | 字典写入 | Human（治理） | 运行时无写入路径（待确认） |
| 社区储备 | `state.community_reserves` | 生产路径无写入；仅 replay | `environment` | - | Human（公共资源） | **死代码**：`contribute/request/approve/settle` 仅测试调用 |
| 服务队列 | `state.service_queues` | `environment`（申请、审批）；`tenancy_economy`（处理）；replay | - | 字典写入 + `service_*` 事件 | Human（公共服务） | 写者两家，边界重叠 |
| 建筑需求 | `state.building_needs` | `environment.update_building_needs`；`construction`（解决）；replay | - | 字典写入 + `building_need_*` 事件 | Human（建设需求） | 两家写 |
| 代表/选举/议事/申诉 | `state.representatives`、`elections`、`headman_id`、`acting_headman_id`、`council_decisions`、`appeals` | `governance`；replay | environment（读取里正）、construction / land / tenancy（读议事结果） | 字典写入 + `election_*`、`council_*`、`appeal_*` 事件 | Human（治理） | **运行时无调用者**（仅测试） |
| 社会认知/记忆/印象 | 内嵌于 `AgentState`（`acquaintances`、`recent_interactions`、`impressions`） | `social`（由 agents 调用）；replay | agents | 直接改人物对象 + `acquaintance_changed` 等 | Human（社会关系） | 人、户、关系三类状态混在同一对象中 |

## 3. 只更新内存、不产生独立事件的变化（抽样）

- `collect_water`：`household.water += collect_amount`（[agents.py:1772-L1774](file:///F:/viae-chronicle/src/vale/modules/agents.py#L1772-L1774)），无独立事件，只体现在 `agent_action_taken` 的 before/after 字段。
- 日末归位：`agent.location = home_node_of(...)`（[L413-L414](file:///F:/viae-chronicle/src/vale/modules/agents.py#L413-L414)），无事件。
- `_ensure_agents` 建立初始人物/家庭时，只写 `household_registered` 等少量事件，人物个体初始状态靠事件重建。
- `field_fertility` 初始化在 `_ensure_agents` 旁直接写 dict，未见事件。

这些不必然是缺陷（可由后续事件推导），但**迁移时若状态容器拆分，必须确认 replay 能重建它们**。

## 4. 结论

1. 唯一真正满足"单一写入者"的大状态是气候与水位；其余都至少有两个写入口。
2. 最重要的两处越界：人类采集直接改 `ecological_resources`；灾害事件模块直接改田块长势/地力与人物健康。
3. 治理、社区储备、建造工程在运行时没有触发路径，只有测试在调用。迁移计划不能假设它们是"活"的子系统。
4. 状态按"数据形状"聚在一起（人物 + 社会认知 + 记忆），而不是按领域所有权；拆分容器时需按字段迁移，不能整对象搬迁。

## 5. P5 完成后的写入者现状（2026-11-21）

本文以上各表是 P0 审计基线 `c9f29a5` 的快照（行号与 `modules.*` 路径已随分层迁移失效）。P5 完成后，**写入者的权威登记**是 `tests/test_architecture_boundaries.py` 的 `STATE_OWNERS`（静态扫描会失败）与 [ADR 009 §3 落地注记](../../decisions/009-layered-domain-architecture.md)；P5-a/b/c/d 的归口结论摘要：

- 环境侧：`climate` 归 `domains.environment.climate`；`water_sources` 归 `domains.environment.hydrology`；`field_growth`/`fertility_factor`/`soil_quality` 归 `domains.environment.fields`；`terrain_cells` 归 `domains.environment.terrain`；`ecological_resources` 归 `domains.environment.resources`；`pools`（fish/game）归 `domains.wildlife.wildlife`。
- 本文 §1 的两处越界已消除：采集改由 `ResourceService` 路由、结算在资源所有者；灾害改由 `EcologicalImpact` 路由、田块生态结算在环境域；野遇伤害由 `domains.society.agents.demographics.apply_wildlife_attack` 结算（人文域所有者）。
- 人文侧：`agents`/`households` 的写入者是最小必要子集——`agents.demographics`（开局播种）、`agents.lifecycle`（健康/体力/存活）、`agents.marriage`、`agents.reproduction`、`agents.actions`、`agents.module`（日末归位），以及 `domains.society.land`/`social`/`construction` 的既有职责；`field_season_labor` 归 `agents.actions`（农事劳动簿记）。
- `modules.*` 包已不存在；`xigu_events` 迁 `world.scenarios.xigu.events`。

## 6. P6 完成后的状态模型归属（2026-11-21）

- 状态模型本身也按领域落位：`domains/environment/state.py`、`domains/wildlife/state.py`、`domains/society/state.py`。
- `core/state.py` 只剩 `WorldState` 组合根；跨领域共享值对象在 `core/snapshots.py`（气候快照）与 `core/pools.py`（资源池形状）。
- 投影（Replay）按 2026-11-21 裁决拆分：`core/replay.py` 只留通用引擎（事件读取/顺序/派发/finalize/validate），领域投影在 `domains/{environment,wildlife,society}/projection.py`（人文投影在 P8 拆为 `projection/` 包：`people`/`households`/`economy`/`land_governance`，`__init__` 为统一入口），`world/replay.py` 只注册组装并暴露 `rebuild_state`。基础设施不再反向依赖领域业务（D3 已消除）。
