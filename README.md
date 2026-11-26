# Vale Chronicle

修仙界边缘凡人小镇 Brookvale 的文字人生模拟器。

世界按逻辑时间 Tick 自演化，NPC 自主生活、拉扯、成长；任何角色从出生到死亡的全部经历——流水账、关键转折、传记——都可随时查阅。

**这不是种田游戏，也不是挂机 RPG。** 核心产物是「可持续产出、因果可追溯的个体人生档案」。

## 设计哲学

**环境是主语，人是谓语。** 气候、灾害、制度逼迫人做选择，选择累积又改变环境；命运必须因果可循。

- 纯规则驱动，不接 LLM 实时推理；LLM 只做事后叙事渲染。
- 确定性、可重放、低算力，可快进跑几百年。
- 事件是真相，状态是投影；所有状态改变写入 SQLite 事件流。
- 机制与配置分离；业务数值在 YAML，schema 用 Pydantic。

## 仓库结构

```text
src/vale/              模拟核心
  core/                基础设施：事件库、WorldState 组合根、调度器、日历、资源池账本、
                       跨领域只读快照（snapshots）；领域状态模型在各领域内
  contracts/           跨领域契约（只读查询 queries；写入契约 resources / impacts 只路由，
                       结算在领域所有者模块）
  config/schema/       配置模型与校验（Pydantic；世界 YAML 数据仍在仓库根 config/）
  domains/             领域层（ADR 009）
    environment/       环境域：state 状态模型、climate 气候、hydrology 水文库存、
                       terrain 地形栅格、fields 田块生态、resources 植被类资源池、
                       projection 环境事件投影
    wildlife/          动物域：state 状态模型、wildlife 鱼/猎物存量池（个体与种群留待后续）、
                       projection 动物事件投影
    society/           人文社会域：state 状态模型、households 家庭访问器、
                       land 土地、community 社区设施、social 社会互动、
                       governance 治理、construction 建造、economy 租佃经济、
                       projection/ 人文事件投影（people 人物、households 家庭、
                       economy 经济、land_governance 土地治理，__init__ 为统一入口）；
                       agents/ 人物子系统（module 协调日结算，lifecycle 生命周期、
                       labor 劳动、decision 决策、actions 动作、household 家庭日常、
                       market 集市、mortality 死亡继承、marriage 婚配、
                       reproduction 分家生育、debt 债务催收、perception 感知、
                       production 生产口径、spatial 距离索引、demographics 人口基础）
  world/               世界协调：assembly 统一组装入口（模块清单/profile 唯一来源）、
                       replay 注册三领域投影并暴露 rebuild_state、xigu 世界生成组合门面
                       与 nature/settlement 分段
  world/scenarios/xigu/ 溪古镇场景独有逻辑（xigu_events 季节性灾害/村落事件），不进通用领域
  observability/       只读观察层（事件查询、文本渲染、导出、CLI viewer）
  cli.py               命令行入口（events list / timeline / run 等）
  main.py              独立气候演示入口（只注册气候模块，非正式模拟入口）
  api/                 HTTP/查询接口占位（routes），当前非主要入口

config/                世界配置数据（纯 YAML，不含 Python 包）
  shared/              跨世界共享参数
  worlds/              具体世界实例（brookvale-town-001）

docs/                  设计与协作文档（核心资产，深度远超当前代码）
  design/              设计图纸：agents / human-environment / interaction / observability 等
  collab/              面向人类协作者的进度文件（PROGRESS.md）

tests/                 pytest 测试与事件流 fixture（旧库回放样本）
viz/                   Tkinter 本地可视化（只读事件库，不写状态）
scripts/               世界生成与运行（run_xigu）、External Seed 静态校验（check_seed）、文档与 schema 一致性检查
data/                  运行时世界实例与 SQLite 事件库（不入 Git）
.ai/                   本地 AI 工作区：STATUS、任务裁决、验收报告（不入 Git）
.check/                本地诊断/长程验收脚本与输出（不入 Git）
.trae/                 本地 Agent 规则（不入 Git）
```

`docs/design/` 已有 130+ 份设计。**代码按图纸逐步落地，新增机制前先查 `docs/` 是否已有设计。**

## 快速开始

```bash
python -m pytest -q
python scripts/run_xigu.py 360        # 按种子生成西谷镇并跑 360 天（默认 seed 20261118）
```

模拟运行、事件查询与字段字典见 `docs/design/systems/observability/01-event-viewer-cli.md`。

## 当前进展（2026-11-26）

- 已合入 `main`：环境基座 → 人物生存 → 时间现实化 → 观察层 → 经济闭环 → 打猎 → 死亡/失能/渔业 → 移动校准/赶集/纺织/蔬菜 → 家庭经济模型（任务 12）→ 盈余经济补丁（任务 13）→ 债务转移窄修（任务 14）→ 社会冲突最小切片（任务 15）→ Tkinter 可视化（PR #2）→ 社会认知与关系层（任务 16，PR #7）。
- 任务 15：集市赊账 +「有粮赖账」2 轮私下催收；5 种子 × 3600 验收通过（三种结果、守恒与无负值）。
- 任务 16：两级认知（unknown → met → known）+ 短期交互记忆（容量环形缓冲）+ TTL 遗忘 + 债争结果写回双方记忆；`acquaintance_changed` 事件与 `events timeline <姓名>` 的参与人匹配可用。
- 任务 17（观察层接线）：债争开口写只读成因（`social_adjustment` / `proposal_basis`）与双方姓名（`initiator_name` / `responder_name`），文案可读出「为何开这个口」；人物时间线识别债争/认知事件的成对字段；viz 识别人名并把认知变化归入关系关注点；修复 `household_merged` 渲染降级。
- 任务 18 P1（印象沉淀层）：新增 `impression_formed` / `impression_changed` 事件与配置 `agents.tuning.social.impression_window`（默认 5，临时值待复核）；从债争记忆窗口合成「观察者对目标的印象」标签（`defaulting` 屡次违约 / `reliable` 向来守约 / `unknown` 尚且说不准），存储 counts 为最近一次 label 变化时的快照。
- 本 PR（任务 23 c1，少年劳动力）：年龄分段拆出「少年」8–12 岁（`allowed_actions: [farm, harvest, weave]`，体力上限 0.60×、恢复 0.80×、健康上限 0.70×），旧「幼年」收窄为 0–8 岁；少年可下田/秋收/织布，但不开放 fish/hunt/borrow/collect_water。分段与白名单为**临时初值**，待阶段三复核。
- 本 PR（任务 24，体力节奏第一层）：`rest_stamina_recovery` 试调 40→60 后按裁决回退 40。实测成人 rest 占比 37.6%→31.8%，但「体力型被迫休息占 rest」28.2%/27.2%，未达 ≤22%；缺口的约 47% 来自田块长势封顶（farm 每年 50 次/田），且布料 +65%。结论：体力节奏第一层**边际有限、机制保留**；体力上限并入 G10，田块封顶登记 G11 候选（不实施），回血门槛登记为独立生存余量杠杆。
- 本 PR（任务 25 P2，印象接决策）：新增配置 `agents.tuning.social.impression_in_decision`（**默认 false**）。打开后「观察者对债务方的印象为 `defaulting`」可把债争诉求从 partial 升为 full（前科优先、既有记忆调节段不变）；关闭时不读印象、零行为变化。开关打开→关闭可回到基线。
- 本 PR（任务 29，M5 日内时间预算与体力分级）：`_process_one` 改为**日内 TU 循环**——季节工作窗（春 10 / 夏 9 / 秋 10 / 冬 6 TU，配置 `natural_params.climate_evolution.seasons.*.work_window_tu`）下逐动作贪心重规划；**单次动作占用 = 动作 TU + 往返移动 TU**，超预算动作在决策阶段即不可行。新增 `agents.tuning.action.tu_cost` / `heavy_actions` / `heavy_stamina_per_tu`（重活 25 体力/TU，轻活 0），删除 `action.stamina_cost` 平表与 `physiology.rest_stamina_recovery`；`rest` 为 1 TU 回满且**就地**歇息，剩余 TU 一次性转闲时休整（`idle=true`）；`location` 日内真实化（动作停在目标节点、日末回家），计距基点由家改为当前位置。`agent_action_taken` 新增 `slot` / `tu_spent` / `tu_remaining` / `move_stamina` / `labor_stamina` / `idle`，废弃 `stamina_cost`；观察层渲染「当日第 N 件」，旧库缺字段降级（`pytest -k replay` 保持绿）。**重标定临时值（待长期方案复核）**：`utility.stamina_score_divisor` 100→500、hunt/fish `injury_risk` 0.07/0.02→0.035/0.01。验收：5 种子 × 3600 存活 8–10、`agent_error` 0（饿死 0–6）；成人首年 2.6–2.7 动作/日，冬季/夏季动作比 0.78–0.94。**已登记副作用**：镇内往返 13–16 TU 的打猎当前不可达（需过夜/营地机制）；贫民区到东/南/西田往返 7–9 TU + 4 TU 农活 > 工作窗，贫民户无法耕作。
- 本 PR（任务 30，水模型最小切片）：激活 `hydrology_initial`（水位 0.60 / 灌溉档 low）到 `WorldState.water_level_ratio` / `irrigation_gear`，由 `ClimateModule` 确定性演化——有效降水按 `recharge_per_mm × mm × (1 − 水位)` 补水、无雨日按 `dry_loss_per_day` 下降，夹紧 0–1，跨档写 `irrigation_gear_changed`，每天变化写 `water_level_changed`。新增 `HouseholdState.water`：`collect_water` 每次产水 5；每日结算按存活成员数扣水（1/人，写 `water_consumed`），**每次进食另耗 0.5（烹饪/佐餐，水不足则该次无法进食，生存门控会先去打水）**；存水低于目标 5 时打水紧迫度线性上升（权重 2.0），成年劳力因此主动维持水缸。水随继承/分家按比例转移、无继承人时归公，不参与集市交易。产量公式 `moisture` 接灌溉档（充足 1.0 / 偏少 0.85 / 缺水 0.7 / 断水 0.5），`harvest_detail` 带 `moisture`。观察层渲染三类新事件与打水产出，replay 支持新事件、旧库无水文事件时取配置初值。验收：5 种子 × 3600 存活 8–10、`agent_error` 0、水守恒 `产出−日耗−归公−存量=0`。
- 本 PR（西谷镇世界生成 + 婚育动作化）：新增 `src/vale/world/xigu.py` 与 `scripts/run_xigu.py`，按种子生成 30 户、40 名居民的西谷镇（开局家庭口粮 50–70 石，**临时值**）。婚配与生育从系统定时结算下沉为 agent 动作：新增 `court`（结亲）与 `try_for_child`（求子），未婚者感知最近合格候选、双方当日互选才成婚（日末 `_settle_courtship` 结算），育龄女方在生育闸门内自主决定求子；新增 `courtship_offer` 事件。断粮户坏账核销：`debt_forgiven`（含 `cause`）+ `debt.write_off_unpayable` 开关，解除逾期对借粮/借食/赊账的永久锁死。2 年基线（seed 20261118，720 tick）：婚姻 20、新生儿 18、生育户 13、死亡 41。
- 本 PR（任务 P4，世界生成分段与领域归口）：`worldgen` 拆为自然段（`nature.py`：地形栅格、资源池目录、静态植被/栖息地描述）与聚落段（`settlement.py`：布点、路网、距离矩阵），`xigu.py` 保留为组合门面；资源池参数正式化为 `ResourcePoolSpec`（经 `LoadedConfig.resources` 进运行时，节点 attributes 不再携带 `resource_*` 副本），运行时投影为 `ResourcePoolState`；鱼/猎物池归动物域新增 `domains/wildlife/wildlife.py` 引导与结算（暂为池形式，个体/种群留待后续阶段）；植被仅结构迁移，动态生物量/退化未启用；`terrain_cells` 归口环境域；采集配置新增 `agents.tuning.gathering.*.harvests_resource_type` 声明产出类型（当前仅模型关联，运行时行为不变）。同种子 worldgen 逐字段等价、两年仿真快照 byte-identical（seed 20261118）；40 年门禁首跑 `agent_error` 0、无负值，人口仍受既有承载力问题约束（见已知问题 ⑩）。
- 本阶段（Ecology Foundation · P0，数据契约与世界身份冻结）：接入外部地理数据包 Xigu Environment Seed v2（manifest v3）。`config/worlds/brookvale-town-001/world.yaml` 新增可选 `environment_seed` 节冻结契约（seed_id、10 个必需资产 SHA-256、自定义 WGS84 Albers 网格 668×666 @30 m、圆形模拟范围与核心流域口径、来源与升级策略）；静态校验机制在 `src/vale/world/seed_contract.py`（数据集成边界、失败关闭、不依赖 GDAL），CLI 入口 `scripts/check_seed.py`；本地缓存定位 B+C（`VALE_SEED_CACHE` 环境变量，缺省 `data/seed-cache`，**解析规则待老板条件裁决**）。真实资产哈希冻结前已对本机实际文件复算核验（10/10 一致）。尚无 Loader/导入能力（P1/P2）。
- 本 PR（任务 P5–P8，分层架构收口）：领域层按 Environment / Wildlife / Human Society 拆包；`core/` 只留通用基础设施（含 Replay 引擎），`contracts/` 只路由请求，`world/assembly.py` 为唯一组装入口；调度按显式阶段 + `depends_on` 拓扑且默认严格（孤立夹具须显式声明例外）；可视化补 `EcologyModule`；`society/projection.py` 拆为人物/家庭/经济/土地治理四个投影（统一入口不变）；`scripts/check_schemas.py`、`check_docs_config.py` 实现真实检查，与 `tests/test_p8_architecture_gates.py` 十二条门禁共同验收；`main.py` 明确为独立气候演示入口。两年基线（seed 20261118，720 tick）逐字段 identical。
- 已知问题（未解决）：① G1 家庭口粮承载力——长程仍有个别饿死（任务 29/30 后 5 种子 × 3600：饿死 5–7、存活 8–10），口粮承载力未做专项调平；② 弥留窗口（plan A 回滚后未修）；③ 田块封顶使成人约 47% 的休息与体力无关（G11，待老板定夺）；④ 体力上限、打分体力紧缺度除数仍为代码硬编码（G10，需单独立项；「1 动作/日」已由任务 29 的日内 TU 循环解除）；⑤ 部分还款自然流结构性低频（机制仅由单测覆盖）；⑥ 印象 P2 已接线但当前 8 种子 × 3600 中**零可观测差异**（defaulting 会话均已因前科走 full），且规则只升不降，不能减轻诉求；⑦ 少年分段与白名单为临时值；⑧ 水已用于烹饪/日耗，但未建模口渴健康惩罚与水存储上限；少年白名单不开放打水，纯儿童户缺水时无法炊事；⑨ 打猎因往返 TU 超工作窗不可达、贫民户无法耕作（任务 29 移动扣 TU 的副作用，需过夜/营地或距离调平）；⑩ 西谷镇长程承载力不足——单产 `base_yield=155`（**临时值**）下人口仍从峰值 53 回落到 t720 的 17，秋收产出只够约 52 人吃半年，第 2 年春荒崩塌后劳力不足以恢复；40 年门禁已恢复为 `test_forty_year_xigu_run_keeps_population_alive`（seed 20261118，断言终局人口 > 0），当前因 G1 以 **strict xfail** 登记，解 G1 后移除标记。
- 下一阶段方向：阶段五收口（P2 验收与统一 PR）；G1 承载力提产与弥留窗口修复的取舍；G11 田块封顶；货币系统评估、派生系统前置（教育/地位）。
- 协作者请看 [`docs/collab/PROGRESS.md`](docs/collab/PROGRESS.md)；最新内部状态以维护者提供的 STATUS 为准。

## 协作方式

本仓库面向多人协作，`main` 受保护，**所有改动走 Pull Request**。

- **有疑问、发现数据异常、想提需求**：在 GitHub 仓库开 **Issue**，写清涉及的分支/commit、事件样本、复现步骤。
- **想改代码或文档**：从 `main` 开分支 → 提 PR → 在网页上回复 Review 评论；不要直接 push `main`。
- **合并**：至少 1 人审核通过后由维护者合并；PR 作者不能自审。
- **讨论入口**：Issue / PR 评论 / Review；不另建本地问答文件。
- 不依赖未合入分支或未稳定事件；`conflict_*` / `debt_deferred` 等事件自任务 15 合入起可用；`acquaintance_changed` 自任务 16 起可用；`conflict_negotiation_round` 的 `social_adjustment` / `proposal_basis`（round=1）与 `initiator_name` / `responder_name`（round=1/2）自任务 17 起可用（只读元数据，旧库事件缺字段时渲染自动回退）；`impression_formed` / `impression_changed` 自任务 18 P1 起可用（依赖 PR #8 合入链）。

## 可视化 / 展示层

目标是一个**图形交互界面（GUI）**，用来观察世界运行、翻阅人生档案，而不是命令行输出。

### 当前实现状态（2026-11-19）

`viz/app.py` 提供本地 Tkinter 应用：只读打开 SQLite 事件库或内嵌启动模拟子进程实时观察。运行控制支持多档速度与「全速」（界面显示实测 tick/s）；事件流面板增量刷新并默认渲染尾部窗口（条数可调），支持「回到最新」与固定历史时保留滚动位置；筛选、分组展开状态与底部窗格布局在刷新后保持。时间线可按「逐事件 / 按天 / 按活动区间聚合」三种粒度显示（活动区间将同主体的连续同类活动合并为一段，如捕鱼、织布）；角色档案含「生平阶段」与「一生大事记」（传记：出生、婚配、生育、死亡、迁徙、继承、债务违约等关键转折按时间序成条）视图，角色与家庭档案计算在后台线程执行。大库载入后后台构建人物事件索引，角色档案按人秒级开出（索引就绪前状态栏会提示稍慢）。

### 界面形态

- 桌面窗口应用或本地 Web UI 均可，优先能离线打开样本数据。
- 主窗口至少包含：**事件流面板**、**筛选/显示控制**、**关注点面板**、**运行控制栏**。
- 不依赖运行中的模拟也能浏览已保存的事件库。

### 功能要求

1. **事件流面板**：按 tick 顺序显示事件，支持滚动、选中、查看事件详情（字段、参与者、家庭、地点）。
2. **显示调节按钮**：按事件类型/角色/家庭/地点/时间范围筛选；时间粒度切换（逐 tick / 按天 / 按事件簇）；暂停时单步、跳转指定 tick。
3. **关注点**：标记/收藏角色、家庭或事件；高亮出生、婚配、生育、死亡、继承、债务违约、迁徙等关键转折。
4. **世界运行控制**：运行 / 暂停 / 单步 / 速度；运行控制通过模拟子进程或 CLI 控制接口实现，不直接写事件库。
5. **角色与家庭视图**：角色档案（生卒、家庭、事件时间线）、家庭视图（按 `household_id` 聚合）。

### 数据来源

- 事件真相源：SQLite `events` 表（只读连接）。
- 稳定接口：`events list` / `events timeline <姓名>` 的 JSON 输出。
- 字段字典：`docs/design/systems/observability/01-event-viewer-cli.md`。
- 样本数据：`tests/fixtures/legacy_events.json`、`legacy_events_expected.json`。

### 边界要求

1. **事件库只读**：不写 SQLite、不建表、不改写事件；运行控制不得绕开模拟核心直接写状态。
2. **不依赖内部 state schema**：不 import `src/vale/core/state.py`，只按事件 schema 编程。
3. **只动 `viz/`**：不修改 `src/`、`config/`、`tests/`；不改 `events list` 默认行为。
4. **不接 LLM 实时推理**；叙事渲染可后置。
5. 分支开发、PR 审核合入，不直接推 `main`。

## 文档

- `docs/design/00-overview.md`：设计总索引。
- `docs/design/decisions/`：架构决策记录。
- `docs/design/systems/observability/`：事件查看器与字段字典。
- `docs/design/systems/society/agents/11-life-course.md`：生命历程与家庭模型。
- `docs/design/systems/society/agents/12-population-and-marriage.md`：婚配与生育模型。
- `docs/design/decisions/007-population-and-marriage.md`、`008-household-coordination-nutrition-and-voluntary-reserves.md`：婚育与家庭协作决策。
- `docs/design/locations/brookvale-town/`：溪谷镇剧本。
- `docs/design/locations/xigu-town-worldgen.md`：西谷镇世界生成。
- `docs/collab/PROGRESS.md`：面向协作者的已合入事实与 WIP 边界。

## 红线

1. 不接 LLM 实时推理。
2. 事件溯源：状态是投影，事件是真相；不改写旧事件。
3. 机制与配置分离，不硬编码业务数值。
4. 观察层只读：不写库、不建表；运行控制只控制模拟进程，不直接写状态。
5. 守恒与可追溯：资源与债务不得凭空产生或消失。
6. 不擅自修改已批准参数；改动单列「原值→新值→理由→影响」。
