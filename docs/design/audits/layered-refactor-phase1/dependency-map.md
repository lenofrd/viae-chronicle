# 模块依赖图与跨域访问清单（dependency-map）

- **对应任务**：TASK-01 第 3 项
- **基线**：`c9f29a5`
- **证据**：`.check/audit_imports.py` 输出（AST 静态导入边）+ `state-ownership.md` 的读写清单 + 逐条调用链复核。

## 1. 先区分四类依赖

| 类型 | 现状 | 是否架构问题 |
|---|---|---|
| A. 模块直接 import 模块 | 见 §2 | 部分有问题（见环与基础设施倒置） |
| B. 模块读其他领域状态 | 普遍存在，绝大多数是合理的"查询" | 读本身可接受，但当前无只读接口 |
| C. 模块写其他领域状态 | 采集扣资源池、灾害改长势/地力、事件模块改健康 | **全部是问题** |
| D. 通过事件/公开函数通信 | `environment` 的函数库被 agents 调用；`xigu_events` 读 `agent_action_taken` payload | 半问题：函数库调用实为同进程直调，不是契约 |

## 2. 模块级导入图

```text
入口: cli / main / scripts.run_xigu / viz.sim_worker
        |
        v
   core.world <-- core.state
        |
        v
  Scheduler (core.scheduler)

  climate  ->  core.calendar, core.state, config.schema
  ecology  ->  (无内部导入，只读 world.config/state)
  agents   ->  core.calendar, core.household, core.state,
               modules.social, modules.environment,
               (延迟) modules.land, modules.construction
  tenancy_economy -> core.state
  xigu_events     -> (无内部导入)

  construction -> core.state, modules.agents (age_years)
  governance   -> core.calendar, core.state, modules.agents (age_years)
  land         -> core.state
  social       -> core.state
  environment  -> core.household, core.state

  core.replay  -> core.state, modules.social  ← 基础设施依赖领域
```

### 关键观察

1. **agents ↔ construction 逻辑环**：`construction` 在模块顶层 import `agents.age_years`，`agents` 在 `construct` 动作里延迟 import `advance_construction`。导入期不成环（靠延迟导入规避），但两个模块互认对方，边界已破。
2. **governance → agents**：治理模块为了复用 `age_years` 反向依赖人类主模块。年龄计算属基础设施派生函数，被放在 217KB 的 agents 里。
3. **replay → modules.social**：回放层（基础设施）依赖人类领域函数做亲缘默认值。任何人类领域的重构都会波及回放。
4. **environment 是函数库不是模块**：没有 `name`/`step`，被 agents 在日结算末尾调用两次；同时它读写家庭、建筑、议事结果，实际是"人文社区服务"域，与 ADR 的 Environment（自然环境）同名不同义。
5. **land/construction/governance 在运行时无独立调度**：land 只在 agents 初始化时被调用一次（[agents.py:546](file:///F:/viae-chronicle/src/vale/modules/agents.py#L546)），继承结算在死亡路径调用（[L2819](file:///F:/viae-chronicle/src/vale/modules/agents.py#L2819)、[L2908](file:///F:/viae-chronicle/src/vale/modules/agents.py#L2908)），construction 只在 `construct` 动作里推进；governance 无生产调用点。

## 3. 跨域直接访问清单（写）

| 写入方 | 被写状态 | 目标所有者 | 证据 |
|---|---|---|---|
| `AgentModule._execute_gather` | `ecological_resources[*].current_stock`、`harvested_this_tick` | Environment / Wildlife | [agents.py:1891-L1911](file:///F:/viae-chronicle/src/vale/modules/agents.py#L1891-L1911) |
| `AgentModule._execute_gather` -> 家庭库存 | `households[*].<output_field>` | Human Economy | 同上 L1913-L1914 |
| `XiguEventsModule._apply_flood_damage` | `field_growth` | Environment | [xigu_events.py:57-L68](file:///F:/viae-chronicle/src/vale/modules/xigu_events.py#L57-L68) |
| `XiguEventsModule._apply_drought_damage` | `field_growth` | Environment | [L70-L86](file:///F:/viae-chronicle/src/vale/modules/xigu_events.py#L70-L86) |
| `XiguEventsModule._apply_landslide` | `field_fertility` | Environment（土壤） | [L88-L110](file:///F:/viae-chronicle/src/vale/modules/xigu_events.py#L88-L110) |
| `XiguEventsModule._apply_wildlife_encounter` | `agents[*].health`、`last_injury_tick` | Human Society | [L112-L142](file:///F:/viae-chronicle/src/vale/modules/xigu_events.py#L112-L142) |
| `land.relocate_household` | `households[*].home_node` | Human Economy | [land.py:306-L330](file:///F:/viae-chronicle/src/vale/modules/land.py#L306-L330) |
| `construction` | `households[*].coin/hardwood`、`land_parcels[*]` | Human Economy / Land | [construction.py:50-L63](file:///F:/viae-chronicle/src/vale/modules/construction.py#L50-L63) |
| `environment.contribute/approve` | `households`、`community_reserves`、`service_queues` | Human Community | [environment.py:102-L233](file:///F:/viae-chronicle/src/vale/modules/environment.py#L102-L233) |

## 4. 跨域读取（只读，但无接口约束）

- `agents` 读 `climate`（天气、季节）、`water_level_ratio`（用 `getattr`）、`field_growth`、`ecological_resources`、`buildings`/`land_parcels`（via environment 效率函数）。
- `ecology` 读 `climate.season`。
- `environment` 读 `agents`、`households`、`buildings`、`land_parcels`、`council_decisions`、`headman_id`。
- `construction` 读 `agents`、`land_parcels`、`council_decisions`、`climate`。
- `tenancy_economy` 读 `households`、`land_parcels`、`council_decisions`、`climate`。
- `xigu_events` 读 `climate`、`field_growth`、`field_fertility`、`ecological_resources`，并通过事件表读 `agent_action_taken`。

**结论**：读侧几乎无收敛。即便不做领域拆分，也值得先为气候、水位、资源池、地块建立只读查询函数，把散落的字段访问收口。

## 5. 循环与倒置

| 编号 | 形态 | 影响 | 处理方向 |
|---|---|---|---|
| D1 | agents ↔ construction | 边界互穿，任一方改动波及另一方 | 把 `age_years` 等派生函数移到 core，施工改为由主循环调用的独立阶段 |
| D2 | governance → agents | 治理依赖人类主模块 | 同上，抽取公共派生函数 |
| D3 | replay → modules.social | 基础设施依赖领域 | 亲缘默认值改为事件可推导，或把规则下沉到 core |
| D4 | environment（社区服务）被 agents 调用且反向读人文状态 | 同名混淆 + 双向耦合 | 更名并并入人文域，明确调用点 |
| D5 | xigu_events 通过事件 payload 读取本 tick 行为 | 隐式协议，payload 字段即接口 | 若保留，需把 payload 字段当作契约并测试 |

## 6. 应改为契约调用的地方（优先级从高到低）

1. **采集**：`harvest/fish/hunt/gather_*` → `ResourceService.request(...)` → 由资源所有者校验额度、扣减、发事件、返回结算结果；调用方只读返回结果。
2. **灾害影响**：洪涝/旱灾/滑坡 → `EcologicalImpact.submit(...)` → 环境结算 `field_growth` / `field_fertility`。
3. **野生动物袭击**：`WildlifeQuery` 查当日风险 + `EcologicalImpact` 提交伤害；不得直接写 `agent.health`。
4. **取水**：`collect_water` 目前凭空产水，应走 `EnvironmentQuery` 读水源可用量，再由水文所有者结算抽取。
5. **天气/水位/土壤**：统一 `EnvironmentQuery.get_snapshot(node_id, tick)`，替代 `getattr(world.state, ...)` 与直接字段读。
6. **施工与土地**：`construction`/`land` 不再读 `agents`，改为接受参数（年龄由调用方算好传入）。

## 7. 待确认

- `state.terrain_cells` 在运行时是否有消费者（静态检索无读取点）。
- `public_treasury` 是否有生产写入路径（仅见 tenancy_economy 结算函数，调用者待查）。
- `land.initialize_land` 在首个 tick 创建住宅与公共仓房（[L123-L164](file:///F:/viae-chronicle/src/vale/modules/land.py#L123-L164)）；`construction` 只负责后续改造。建筑状态的"创建者"与"改造者"不是同一个模块，迁移时需明确归口。

## 8. P5/P6 完成后的依赖现状（2026-11-21）

§2 的导入图是 P0 审计基线 `c9f29a5` 的快照，`modules.*` 路径与行号已失效。P5 之后的实际依赖以代码为准，摘要：

```text
入口: cli / main / scripts.run_xigu / viz.sim_worker
  world.assembly -> 三个领域模块 + core.world/scheduler（唯一模块清单与组装入口）
  world.replay -> core.replay.engine、domains.{environment,wildlife,society}.projection
  core.replay -> core.state、core.pools（通用引擎；无 domains 导入）
  domains.{environment,wildlife,society}.projection -> 本领域 state、core.*、本领域模块
  core.state -> domains.*.state（组合根：WorldState 由三个领域容器组成，架构闸唯一豁免）
  core.pools / core.snapshots -> 无内部依赖（跨领域共享值对象）
  各领域模块 -> core.world（PHASE_*）、本领域模块、contracts.*
  domains.society.agents.module -> agents.{lifecycle,labor,decision,actions,household,
        market,mortality,marriage,reproduction,debt}、agents.{perception,production,
        spatial,demographics,constants}、domains.society.social、domains.society.community
  各 mixin -> core.*、contracts.*、domains.society.{households,community,social}、同包子模块
  domains.society.{construction,governance} -> domains.society.agents.demographics (age_years)
  domains.environment.{climate,hydrology,fields,resources,terrain} -> core.*、contracts.*、core.pools
  domains.wildlife.wildlife -> core.*、contracts.*、core.pools
  world.scenarios.xigu.events -> core.*（场景独有，不进领域）
```

§6 的 6 条改造项在 P3b/P3c/P5 已全部落地（采集、灾害、野遇、取水走契约；天气/水位/土壤走 `EnvironmentQuery`；`construction`/`land` 不再读 `agents` 主模块，只依赖 `agents.demographics.age_years` 派生函数）。`agents` 协调器不再被其他人类子系统反向依赖，架构闸以此设红线。

P6（2026-11-21）：D3 已消除——老板裁决「core 只留通用重放引擎，领域投影由各领域提供，world 组装注册」，据此 `core/replay.py` 无 domain 导入、`domains/{environment,wildlife,society}/` 各自承接投影（人文投影在 P8 拆为 `projection/` 包）、`world/replay.py` 只注册；`core/household.py` 迁 `domains/society/households.py`；`core/state.py` 只留组合根，且是唯一被豁免的 core→domain 导入。当前 `KNOWN_IMPORT_VIOLATIONS` 为空。

P7（2026-11-21）：新增 `world/assembly.py` 作为唯一组装入口（`full_modules` / `base_town_modules` / `viz_modules`），三个运行入口不再各自 `world.register`；调度按 `phase` + `depends_on` 拓扑，结构性错误直接 `ValueError`；无新增跨域依赖。
