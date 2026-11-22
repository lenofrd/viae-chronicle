# 生态基础阶段审计：设计树与实现的对齐（E1 第一步，只读）

- **对应任务**：`Ecology-task01` E1（ADR 010 §3.1 架构与文档对齐）
- **审计基线**：`ecology-foundation` @ `73c2078`（阶段二成果 + ADR 010，代码与 `279a33b` 一致）
- **审计日期**：2026-11-22
- **方法**：以 P5–P8 后代码为准（阶段一审计 `docs/design/audits/layered-refactor-phase1/` 的 P5–P8 注记、`tests/test_architecture_boundaries.py` 的 `STATE_OWNERS`、ADR 009 落地注记为权威登记），本轮逐一复核内核/契约/三域代码；设计树侧读全部子系统 `00-overview` 与代表性子文档，并静态检索旧路径与未实现机制的关键词。**本报告不改任何代码与设计文档**；修正口径见 §7，待老板裁决后执行。

## 1. 代码侧现状（复核确认，与既有登记一致）

### 1.1 运行时模块与调度阶段（唯一注册清单在 [world/assembly.py](../../../src/vale/world/assembly.py)）

| 模块 | 注册名 | phase | depends_on | 职责 |
|---|---|---|---|---|
| `domains/environment/climate.py` | climate | 1 NATURAL | — | 季节/天气/温度/降水、水位与灌溉档演化、旱情累积 |
| `domains/environment/resources.py` | ecology | 2 ECOLOGY | climate | 植被类资源池引导/封顶再生（`core/pools.py` 共享机制） |
| `domains/wildlife/wildlife.py` | wildlife | 3 WILDLIFE | climate | 鱼/猎物池引导/再生/捕获结算 |
| `domains/society/agents/module.py` | agents | 4 SOCIETY | climate, ecology | 人物日结算总调度（拆分自 4390 行 `agents.py`，mixin 归口） |
| `domains/society/economy.py` | tenancy_economy | 4 SOCIETY | — | 租约、实物借贷、交易、共享仓储、服务队列 |
| `world/scenarios/xigu/events.py` | xigu_events | 5 IMPACT | agents, ecology | 溪古场景冲击（洪涝/旱/滑坡/野遇/谣言等） |

PHASE_PROJECTION（6）当前无注册模块。profile：`full_modules`（全部六模块）、`base_town_modules`（climate+ecology+agents）、`viz_modules`（同 base_town）；**无 ecology-only profile**（E3 待建）。

### 1.2 状态所有权与依赖

权威登记（不再重复抄录）：

- 写入者登记：`tests/test_architecture_boundaries.py` 的 `STATE_OWNERS`（静态扫描违例即失败，`KNOWN_IMPORT_VIOLATIONS` 为空）；
- 所有权与依赖现状：`audits/layered-refactor-phase1/state-ownership.md` §5/§6、`dependency-map.md` §8；
- 分层裁决与逐批落地：ADR 009 §2、§3 各落地注记。

本轮复核结论：与上述登记一致，无漂移。要点——`core/state.py` 仅组合根；`contracts/`（`queries.py` / `resources.py` / `impacts.py`）只路由，结算在所有者；领域状态模型归各域；Replay 通用引擎在 `core/replay.py`、投影归三域、组装在 `world/replay.py`。

### 1.3 生态相关能力的**实际**边界（E2–E5 规划锚点）

| 主题 | 现状 |
|---|---|
| 植被 | 仅资源池（柴薪/草药/硬木）封顶再生；`world/nature.py` 生成含**静态**植被/栖息地描述（P4 裁决：动态留后续）；无生物量/繁殖/演替/退化 |
| 动物 | 仅鱼/猎物池（`WildlifeState.pools`）；`WildlifeQuery.populations` 返回池目录快照；无个体/种群/行为 |
| 田块生态 | `fields.py`：长势/动态地力/静态地力 + 灾害冲减，经 `EcologicalImpact` 路由（2026-11-21 裁决落地） |
| 水文 | `hydrology.py`：水井类水源库存/再生/抽取结算；河段水位仅 `water_level_ratio` 一个标量 |
| 分解/营养/食物网 | **无任何代码** |
| LOD | **无任何代码**（无 `core/lod*`，无任何多分辨率机制） |
| 守恒记账 | 采集/取水/捕捞走契约配对结算；「无声明外部输入不得凭空生成」尚未有系统性核算边界 |

## 2. 设计树归属错位表

设计树现状四子系统（natural-environment / human-environment / agents / interaction）+ 顶层散文件；实际架构是三域 + 内核 + 契约 + 场景。ADR 009 §4.5 曾裁定「沿用 natural-environment 文档体系、不为层次名称重排目录」；**ADR 010 §2.6（更新）要求设计落在实际域边界下**，故本表是修正依据。

| 设计树 | 应属 | 依据 |
|---|---|---|
| natural-environment/01-spatial-skeleton | 内核空间基础设施（跨域） | 实现在 `src/vale/config/schema/spatial_units.py` + `world/` 生成器 + `contracts/queries.py` SpatialQuery |
| natural-environment/02-climate、03-hydrology、04-terrain、05-soil-and-fields、06-vegetation | Environment | 对应 `domains/environment/` 各模块 |
| natural-environment/**07-fauna** | **Wildlife（错位）** | 对应 `domains/wildlife/`；ADR 010 §2.3 定为对等域 |
| natural-environment/08-hazards | 部分环境 + 部分场景 | 旱累积在 climate；山洪/滑坡/野遇实际由 `world/scenarios/xigu/events.py` 注入（见 §4-5） |
| natural-environment + human-environment 两套 09-dynamics | 内核横切策略（平行建树） | 文档自注未实现；实现散见 climate 限幅 |
| 四套 10-state-and-records | 内核基础设施（平行建树） | 实际集中在 `core/{event_log,snapshots,replay}` + `observability/` |
| agents/ | Society | 对应 `domains/society/agents/` |
| human-environment/（全部） | Society | 对应 society 域 land/governance/social/community/construction/economy 等 |
| interaction/（全部） | Society（域内行为设计） | 无独立域；最近似实现为 `agents/debt.py` 两轮催收 |
| 顶层 buildings-/labor-/tenancy-*.md | Society | 对应 construction、agents 劳动、economy/community |
| observability/ | 内核观察层（位置合理，宜标注归属） | `src/vale/observability/` |

## 3. 能力状态标注清单

简写：**实**=已实现，**部**=部分实现，**规**=仅规划（无代码），**矛**=与实现矛盾。依据为代码对照；未逐字读的文档已注明。

| 子目录 | 判定 | 一句话依据 |
|---|---|---|
| NE/01 空间骨架 | 部 | 节点/连接/可达性有（SpatialQuery）；风险/时间成本表未落 |
| NE/02 气候 | 部 | 季节/降水/限幅/旱累积已实现；极端天气、季节过渡未做 |
| NE/03 水文 | 部 | 水源库存+补水（P3a）；河段/流速/淤积/可渡性未实现 |
| NE/04 地形 | 矛/规 | `terrain.py` 仅静态引导；滑坡风险/山路状态无演化，滑坡由场景注入 |
| NE/05 土壤田地 | 部 | 长势/动态地力/静态地力有；生长阶段/虫害/独立土壤湿度无 |
| NE/06 植被 | 部 | 仅池再生；覆盖度/群落/退化未实现且**未标注** |
| NE/07 动物 | 部+错位 | 仅鱼/猎物池；种群/承载/迁徙/行为全未实现且**未标注** |
| NE/08 灾害 | 部+矛 | 文档称累积触发；实际山洪/滑坡/野遇为场景概率注入，仅旱走累积 |
| NE/09 动力学 | 规 | 文档自注未实现 |
| NE/10 状态记录 | 矛 | 称各子系统独立快照/查询；实际集中 core+contracts+observability |
| AG/01 生理 | 实 | 体力/健康/饥饿/疲劳/孕产落地，004 标注齐全 |
| AG/02 心理 | 规 | 无 stress/fear/valence 等代码 |
| AG/03 认知记忆 | 部 | 头注已自标落地切片与偏差（合规范本） |
| AG/04 需求效用 | 部 | 效用打分在 decision.py；细节未逐字核 |
| AG/05 决策 | 实 | 日内贪心重规划+生存门控有落地记录 |
| AG/06 行动 | 实(大半) | 动作/TU/通用采集已落地；**家畜四动作与实现矛盾**（见 §4-3） |
| AG/09 动力学、AG/10 状态记录 | 规/部 | 未逐字读；快照实际字段少于文档（心理段缺） |
| AG/11 生命历程 | 实(大半) | 家庭/继承/分家有落地表；头部已声明历史基线口径 |
| AG/12 人口婚姻 | 部 | 生育调节/议婚核心已实现并自标；意愿议婚未实现 |
| HE/01 社会空间 | 部 | 建筑/作坊在 land/construction；信息流/社会意义无 |
| HE/02 制度 | 部 | 治理函数存在但生产无调用（见 §6）；水权/禁伐/换工无规则引擎 |
| HE/03 关系 | 部 | 亲缘/债务有；trust/grudge 未实现（05 头注已自标） |
| HE/04 信息、HE/05 教育、HE/06 阶层 | 规 | 无代码（阶层仅 wealth 维度有） |
| HE/07 冲突 | 部 | 仅债务两轮私下催收 |
| HE/08 仪式信仰 | 部 | seasonal_ritual 场景事件；祭祖/婚丧/禁忌认知无 |
| HE/09 动力学 | 规 | 文档自注未实现 |
| HE/10 状态记录 | 部/矛 | 实际投影在 `society/projection/` 包 |
| HE/11 家畜 | 规 | `livestock/raise_livestock/graze/slaughter/use_ox` 全库零匹配（本轮已核） |
| interaction/ 全树 | 规 | 无 session_* 事件与会话机制 |
| buildings-*.md | 部 | §12 有「当前实现边界」清单，与 construction/land 对得上 |
| labor-*.md | 实(大半) | 疲劳宽限/TU 效率/ADR008 修订已落地描述 |
| tenancy-*.md | 部 | 租约/交易/仓储有；社区储备审批链生产无触发 |

## 4. 陈旧与矛盾描述清单（修正对象）

1. **旧代码路径**（`src/vale/modules/*` 已于 P5 删除）：
   - [agents/06-actions.md](../../systems/agents/06-actions.md) §4.2（`vale/modules/hydrology.py`）、§5.1（`agents.py` 单文件语境）；
   - [agents/11-life-course.md](../../systems/agents/11-life-course.md) §18 G10（引用旧 `modules/agents.py` 路径）；
   - [human-environment/03-relationships/05-trust-and-interest.md](../../systems/human-environment/03-relationships/05-trust-and-interest.md) 头注（`vale/modules/social.py`，现 `domains/society/social.py`）；
   - [natural-environment/03-hydrology/00-overview.md](../../systems/natural-environment/03-hydrology/00-overview.md) P3a 注（`vale/modules/hydrology.py` 与**已不存在**的 `vale/contracts/water.py`，现为 `contracts/resources.py`）；
   - [decisions/003](../../decisions/003-config-and-location-separation.md) §系统层举例仍写 `src/vale/modules/`（ADR 属历史记录，建议加落地注记而非改写正文）。
   - `audits/layered-refactor-phase1/` 内旧路径为历史快照，已自注失效，**不需修**。
2. **[00-overview.md](../../00-overview.md) §十四**：文档地图仍按 4 子系统描述，无三域/内核/契约/场景结构，无能力状态标注约定。
3. **家畜动作**：[agents/06-actions.md](../../systems/agents/06-actions.md) §2.1 将 `raise_livestock/graze/use_ox/slaughter` 列入第一版动作清单，全库（src/config/tests）零实现痕迹，且无「规划」标注。
4. **规划写成现状**：NE/06-vegetation、NE/07-fauna 的状态变量表（population/carrying_capacity/cover/degradation 等）未标「未实现」；interaction 全树、HE/04–06/08、NE/04 等通篇无状态标注。
5. **灾害触发机制矛盾**：NE/08-hazards 声称累积触发；实际仅旱灾走气候累积，山洪/滑坡/野遇为 `xigu_events` 概率注入（场景层行为，非环境域机制）。
6. **平行横切树**：两套 09-dynamics、四套 10-state-and-records 声称按子系统落地，实际为内核集中设施——与 ADR 010 §2.6「避免平行/重复设计树」冲突。
7. **残留脚本**：`docs/design/systems/create-hydrology.ps1`——生成 03-hydrology 文档的一次性脚本体，遗留在设计树内，建议删除或移出。

## 5. 缺失主题清单（对照 ADR 010，E2–E5 的文档缺口）

| 主题 | 现状 |
|---|---|
| 植被动态（生物量/繁殖/演替/退化恢复） | 无（06-vegetation 仅资源点池视角） |
| 动物种群/个体（年龄结构/能量/出生死亡迁徙/行为） | 无（07-fauna 仅池变量表） |
| 食物网与物种定义（跨域取食关系、FoodWebQuery） | 无任何文档 |
| 分解者/碎屑/尸体/排泄与分解过程 | 无 |
| 营养循环（养分归还土壤水体、再利用） | 无（05 仅有地力） |
| Simulation LOD（内核多分辨率契约） | 无 |
| 能量/物质守恒核算边界专文 | 无（仅散见工程准则） |

按 ADR 010 §2.6，这些主题的详细规格**在各自次级阶段开工时以短设计文档补齐**（E2：LOD 规范；E3/E4/E5：对应机制设计），不在 E1 预写。

## 6. 已知缺口台账（只登记，不在 E1 修）

| # | 缺口 | 现状与口径 |
|---|---|---|
| 1 | G1 家庭口粮承载力 | 40 年门禁人口存活断言 strict xfail 的唯一原因；G11 田块封顶等一并见 `Layer-task03` §4.2 遗留清单 |
| 2 | CLI 基础 profile 资源池缺口 | `brookvale-town-001` 有采集动作但 `resources` 目录为空，每 tick 记 `agent_error`；三方案（补池目录/改用 xigu 生成/删采集动作）待老板定夺 |
| 3 | `config/shared/` 三个空 YAML | state_constraints、rules/climate、rules/hydrology；暂视为「未启用」 |
| 4 | 治理/建造/社区储备无生产触发 | 函数库存在、仅测试可达（2026-11-20 裁决：保留为正式目标，各自单列任务） |
| 5 | 打猎行为切换 | 模型层关联已修（game↔game_trail），运行时行为切换另立任务（2026-11-21 裁决） |
| 6 | `resource_harvest_refused` 诊断 | 保留拒绝事件，先诊断后调参（2026-11-20 裁决） |
| 7 | PHASE_PROJECTION 空阶段 | 调度阶段已定义、当前无注册模块；生态阶段若引入投影模块需对齐 |

## 7. 修正口径选项（待裁决项 1）

ADR 010 §2.6 约束：优先就地更新与合并；不为整齐做纯装饰性搬移；路径调整必须对应真实职责修正并更新引用。据此给三个方案：

**方案 A — 就地标注，不动结构**
保持四子系统树。逐文档补能力状态头注（实/部/规/矛）、修 §4 陈旧描述、删残留脚本；`00-overview.md` §十四补「设计树 ↔ 实际域对照表」。
- 优点：diff 最小，风险最低。缺点：**不满足** ADR 010 §2.6「三域设计落在实际边界下」（07-fauna 仍挂 natural-environment）；食物网/LOD 等新主题无处安放，只能继续塞错位树。

**方案 B — 轻量归位 + 全面标注（推荐）**
在 A 的全部内容之上，做**三处有真实职责依据的归位**：
1. `systems/natural-environment/07-fauna/` → `systems/wildlife/`（对等域，ADR 010 §2.3）；
2. 人文三树（`agents/`、`human-environment/`、`interaction/`）归入 `systems/society/` 之下（保留三棵子树目录，仅加一层；对应代码单一 `domains/society/`）；
3. 内核视角归位：`01-spatial-skeleton`、两套 `09-dynamics`、四套 `10-state-and-records`、`observability/`——两种子选项：**B1** 原地保留但头注统一标「内核横切/基础设施视角」；**B2** 合并为 `systems/kernel/` 一棵树。
`00-overview.md` §十四重写为「三域 + 内核 + 契约 + 场景」文档地图；新主题（食物网、LOD 等）按 §5 留待各阶段短设计文档挂到对应域下。
- 优点：满足 ADR 010 §2.6；每次移动都有职责依据，非装饰性；`check_docs_config.py` 可校验引用改净。缺点：引用路径更新量中等（一次纯文档提交可完成）。

**方案 C — 重建新树**
按三域重建全新设计树，旧树整体归档。
- 缺点：违反「优先就地更新与合并、不建平行树」，评审与引用成本最高。**不推荐**。

另请一并裁决：
- **B-附 1**：`decisions/003` 等含旧路径的 ADR——正文不改，文末加「落地注记」段指向现行结构（循 ADR 009 先例）；
- **B-附 2**：`create-hydrology.ps1` 删除还是移 `scripts/`（其生成物已交付多年）；
- **B-附 3**：NE/08-hazards 的矛盾按「场景注入为现状、累积触发降为规划」口径标注，还是把灾害从 08 文档中拆出「环境机制 vs 场景注入」两节。

## 8. 验证

- 本报告为纯新增文档；未改任何代码与既有设计文档（`git status` 以证）。
- 修正执行后（E1 第二步）验收口径：`python scripts/check_docs_config.py` exit 0；代码 diff 为零；`python scripts/check_schemas.py` 不受影响（未动 config）。
