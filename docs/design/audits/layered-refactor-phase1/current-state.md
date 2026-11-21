# 当前系统实况（current-state）

- **对应任务**：Architecture Audit - TASK-01，阶段一第 1 项
- **审计基线**：`refactor/layered-architecture` @ `c9f29a5`
- **审计日期**：2026-11-20
- **方法**：从入口脚本追踪真实调用链，再以静态检索辅助核对状态读写；不依据目录名或函数名推断职责。凡是未追到调用点的，标注"待确认"。

---

## 1. 先更正一个目录直觉

`src/vale/modules/` 下确实存在 `fauna/`、`hydrology/`、`terrain/`、`vegetation/`、`soil_and_fields/`、`hazards/` 六个空目录，`src/vale/api/main.py`、`tests/test_full_tick.py`、`tests/test_world_isolation.py` 以及 `config/worlds/brookvale-town-001/human-params.yaml`、`links.yaml` 均为 0 字节。它们是脚手架留下的占位，**没有运行时代码**。当前真正的环境实现只有 `climate.py` 与 `ecology.py` 两个模块，加上世界生成里的地形与资源池数据。

---

## 2. 核心对象与持有关系

| 对象 | 位置 | 职责 | 创建者 / 持有者 |
|---|---|---|---|
| `World` | [world.py](file:///F:/viae-chronicle/src/vale/core/world.py#L22-L40) | 持有事件日志、当前 tick、模块列表、配置聚合对象、`WorldState` | 入口脚本创建 |
| `WorldState` | [state.py](file:///F:/viae-chronicle/src/vale/core/state.py#L358-L392) | 单一扁平状态容器：气候、地形单元、地块、建筑、工程、租约、借贷、服务队列、公库、社区储备、选举、议事、申诉、水位、人物、家庭、田块长势/地力/劳力、生态资源 | `World.__init__` 直接 `WorldState()` |
| `EventLog` | [event_log.py](file:///F:/viae-chronicle/src/vale/core/event_log.py#L14-L59) | SQLite 只追加事件表（id/tick/event_type/payload/created_at） | 入口脚本创建，注入 `World` |
| `LoadedConfig` | [config_loader.py](file:///F:/viae-chronicle/src/vale/core/config_loader.py#L21-L49) | `world` / `natural_params` / `spatial` / `agents` / `terrain` 五块 | `load_config()` 或 `run_xigu` 手动拼装 |
| Scheduler | [scheduler.py](file:///F:/viae-chronicle/src/vale/core/scheduler.py#L16-L70) | 按 `depends_on` 拓扑排序调用模块 `step()`，异常隔离 | 无状态函数 |
| Replay | [replay.py](file:///F:/viae-chronicle/src/vale/core/replay.py) | 从事件重建 `WorldState` | 观察层/测试使用 |

要点：**状态不是由领域对象持有的**。所有领域共享同一个 `WorldState` 实例，`World` 只是把引用传下去。模块之间没有读写闸门，写入合法性靠自觉。

---

## 3. 三个真实入口（职责不同）

| 入口 | 配置 | 注册模块 | 用途 |
|---|---|---|---|
| [scripts/run_xigu.py](file:///F:/viae-chronicle/scripts/run_xigu.py#L28-L56) | Brookvale 基础配置 + 西谷生成结果 | climate, ecology, agents, tenancy_economy, xigu_events | 长程模拟与验收 |
| [src/vale/cli.py](file:///F:/viae-chronicle/src/vale/cli.py#L96-L112) | Brookvale 原配置 | climate, ecology, agents | 短跑与事件观察 |
| [viz/sim_worker.py](file:///F:/viae-chronicle/viz/sim_worker.py#L121-L132) | Brookvale 原配置 | climate, agents | 观察器实时推进 |

同一套代码在三个入口注册的模块集合不同，`tenancy_economy` 与 `xigu_events` 只在 `run_xigu` 中存在；观察器连 `ecology` 都没有。`src/vale/main.py` 是 10 tick 气候演示，`src/vale/api/main.py` 为空文件。

`land.py`、`construction.py`、`governance.py`、`social.py` **不是** Scheduler 模块（无 `name` / `depends_on` / `step`），它们是被 `AgentModule` 与测试直接调用的函数库。所以"模块清单"不能只看 `modules/` 目录。

---

## 4. 配置加载与传递

`load_config(world_id)` 顺序读取 `config/worlds/<id>/` 下四个 YAML，分别用 Pydantic Schema 校验（[schema/agents.py](file:///F:/viae-chronicle/config/schema/agents.py)、`natural_params.py`、`spatial_units.py`、`world_config.py`），聚合成 `LoadedConfig`。没有任何 Schema 版本号或迁移机制。

西谷路径在此基础上替换三块：

```text
load_config(brookvale-town-001)
  → generate_xigu_town(seed, base_spatial)   # 地形/节点/道路/距离矩阵/资源池/田块分配
  → build_xigu_agents_config(generated, ...) # 40 人 / 30 户初始人物与家庭
  → LoadedConfig(world, natural_params, generated.spatial, generated_agents, generated.terrain)
```

配置在运行时被模块当作只读参数使用，但 `WorldState` 的初值并非全部来自配置：`AgentModule._ensure_agents` 在第一个 tick 懒初始化人物与家庭，`land.initialize_land` 懒初始化地块与地形单元，`ClimateModule` 在首个 tick 初始化水位。**初始状态的创建分散在三个模块里，且依赖调用顺序**。

---

## 5. 世界生成流程（真实顺序）

[generate_xigu_town](file:///F:/viae-chronicle/src/vale/worldgen/xigu.py#L441-L470)：

1. `_make_terrain`：按坐标解析地形类型、高程、坡度、洪涝风险、土壤肥力。
2. `_make_nodes`：地标 + 河流/渠/井 + 资源节点（河段、林地、浅山、兽径）+ 水浇田与旱田 + 三个街区宅院；末尾把 `ResourcePool` 的字段**复制进 `SpatialNode.attributes`**（`resource_stock`、`resource_max_stock`、`resource_regeneration_per_tick`、`resource_extraction_limit_per_tick`、`resource_seasonal_weights`、`restricted`）。
3. `_make_roads` + `_distance_matrix`：最小成本道路与全点距离矩阵，回填 `travel_cost_from_well_tu`。
4. 按距离为每户宅院排好可达田块顺序（`household_work_nodes`）。
5. [build_xigu_agents_config](file:///F:/viae-chronicle/src/vale/worldgen/xigu.py#L473-L550)：在 Brookvale 原有四名居民基础上补齐 40 人，分配宅院、田块、初始资产。
6. 生成过程**不创建 `WorldState`**，也不写事件。自然地理生成与聚落/人口生成在同一文件的相邻函数里，只靠调用顺序区分。

`validate_xigu_town` 只做生成结果的结构性校验，不进入运行时。

---

## 6. Tick 执行流程

[run_tick](file:///F:/viae-chronicle/src/vale/core/scheduler.py#L52-L70)：

```text
topo_sort(world.modules)  →  module.step(world)  →  异常则写 module_error
world.current_tick += 1
```

拓扑排序只认模块 `depends_on` 声明的名字；检测到环时打印警告并**退回注册顺序继续跑**。当前声明：agents 依赖 climate、ecology；ecology 依赖 climate；xigu_events 依赖 agents、ecology；tenancy_economy 无依赖。

`AgentModule.step` 事实上是一个"日结算总调度器"（[agents.py](file:///F:/viae-chronicle/src/vale/modules/agents.py#L386-L422)），顺序为：

1. 懒初始化人物/家庭（仅首个 tick）。
2. 社会认知默认亲缘（`social.apply_kin_defaults`）。
3. 劳作点对账。
4. 家庭当日分工规划。
5. 逐人 `_process_one`：`_perceive → _decide → _score → _execute`（含 farm/harvest/hunt/fish/gather/weave/construct/collect_water/court/try_for_child/借贷/交易）。
6. 同地点日常接触 → 认知升级、记忆写入。
7. `_settle`：死亡与继承、债务催收、集市、婚配（含结亲结算）、生育、回血。
8. 全员归位回家。
9. 疲劳结算。
10. **调用环境模块函数**：`settle_building_maintenance`、`update_building_needs`（来自 `modules/environment.py`）。
11. 低频遗忘清理。

也就是说，人类模块在同一个 `step` 内完成了人口、家庭、经济、土地继承（懒 import `land`）、施工推进（懒 import `construction`）、社会认知与部分环境结算。`tenancy_economy` 与 `xigu_events` 只是这个主循环之后的补充钩子。

---

## 7. 事件记录现状

- 静态检索到 **115 种事件类型**（`event_log.append` 字面量统计，见 `.check/audit_event_types.py`）。
- 事件表只有 `payload` JSON，没有事件 schema、版本、因果父 ID、生产者模块字段。
- 大多数状态变化会写事件，但**不是全部**：`collect_water` 直接 `household.water +=`，只记录在随后 `agent_action_taken` 的 before/after 字段里；`xigu_events` 修改 `agent.health` 有事件；`ecology` 初始化与再生有事件。
- 存在"以事件流当消息总线"的用法：`xigu_events._apply_wildlife_encounter` 查询本 tick 的 `agent_action_taken` payload 判断谁去了兽径，再决定是否袭击。
- Replay 为状态语义事件提供 `_on_<event>` 处理器，但同一事件类型存在重复定义（如 `_on_agent_fatigue_settled`、`_on_field_labor_progressed`），后者覆盖前者；无测试断言两者一致。

---

## 8. 观察层与回放

`observability/render.py` 按事件类型渲染中文叙述，缺字段降级不崩；`replay.py` 从事件重建 `WorldState` 并在末尾再次调用 `social.apply_kin_defaults`（因此 replay 依赖人文领域模块）。viz 进程直接读 SQLite 事件库。

---

## 9. 与 ADR 009 的直接差距（详见同目录其他交付物）

1. 没有一个领域持有自己的状态；`WorldState` 是唯一容器，写权限无约束。
2. 自然与人文的边界在 `AgentModule` 内部被抹平：采集直接扣 `ecological_resources`，施工/维护/需求更新由 agents 循环触发。
3. 世界生成不分自然/聚落两段，资源池模型与运行时不统一。
4. 调度顺序是"注册表 + 声明依赖"，没有 ADR §2.7 的阶段语义，同 tick 因果关系依赖模块内部代码顺序。
5. 环境只有气候与资源再生，没有水文、土壤水分、植被生物量、动物种群，ADR 的大部分目标状态尚不存在。
