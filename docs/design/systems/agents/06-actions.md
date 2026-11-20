# 行动类型

## 1. 目的
定义人物能执行的具体动作，并区分“符合社会期望”与“越轨行为”。

## 2. 动作清单（第一版）

### 2.1 生存与生产（普遍适用）
- `eat`：消耗食物，降低饥饿。
- `sleep`：恢复体力。
- `farm`：在田地劳作，提升作物长势。
- `collect_water`：从公共水井取水；当前翠溪不自动视为可饮用水源。
- `gather_firewood`：砍柴，影响植被。
- `hunt` / `fish`：获取肉类，影响动物种群。
- `cook`：消耗柴薪和生食，产出可吃食物。
- `raise_livestock`：喂养照料家畜（消耗饲料，增加家畜健康）。
- `graze`：放牧（消耗体力，若越界可能触发邻里或地界冲突）。
- `use_ox`：使用役畜（如牛）拉犁，大幅提升 `farm` 的劳作效率（消耗家畜体力）。
- `slaughter`：宰杀家畜（获得肉类，同时家畜资产从系统中移除）。

### 2.2 人际交互（普遍适用）
- `talk`：发起对话。
- `trade`：交换物资。
- `borrow_grain`：家庭断粮时，向最近有足额粮食的家庭借粮。
- `borrow_food`：无可借粮时，向最近有富余鱼、肉或蔬菜的家庭借入对应实物，并形成同物资债务。
- `help`：帮助他人。
- `conflict`：攻击、争吵。

### 2.3 移动（普遍适用）
- `move`：从当前节点走到另一节点。

### 2.4 传统性别规范关联动作（可能产生 norm_penalty）
- **男性主导（女性执行会有惩罚）**：深山伐木、重型开垦、祭祖主祭。
- **女性主导（男性执行会有惩罚）**：纺织、精细采集、照顾幼儿。

### 2.5 越轨动作大类（Deviant Actions）
*注：系统只提供动作类型，具体某动作是否违法、严重度多少，由地点配置（location rules）决定。*

- `steal_asset`：窃取资产（可指向食物、财物、家畜）。
- `violate_rule`：违背制度（如截水、越界、盗伐、盗猎）。
- `assault`：人身攻击。
- `sacrilege`：亵渎信仰（破坏神树、冒犯禁忌）。

## 3. 演化规则
```
条件：决策系统选定动作
效果：检查前置条件（体力、怀孕状态、社会硬限制）
      若违背制度硬限制（如女性不能继承），直接失败
      若违背软限制（如女性进深山），执行成功但产生角色冲突压力和舆论风险
      满足条件则执行，修改状态，生成 action_executed 事件。
```

### 3.6 动作的时间与体力成本（004 裁决，2026-11-17，**M5 已落地**）

- 动作属性为 **{TU 时长, 体力速率} 二元组**：重活为纯劳作时长（如 `farm = 4 TU`，25 体力/TU，连续 4 TU 归零）；轻活只占 TU（固定体力消耗 0）。移动另按 TU 计体力消耗。分级表与时长为**地点配置参数**，机制见 [01-physical-state.md §4.3](01-physical-state.md)。
- **「一日约 5 动作」为涌现软目标**（由工作窗 + 体力约束产生），不硬编码、不写断言。
- 位置语义：计距基点为「**当前位置 → 目标**」，日末回家语义保留（C1）。

> **落地记录（M5，2026-11-17）与偏差**：
> - 分级表落为 `agents.yaml: action.tu_cost`（每动作 TU）+ `heavy_actions` + `heavy_stamina_per_tu`（默认 25）；`physiology.rest_stamina_recovery` 与 `action.stamina_cost` 平表已删除。
> - **移动扣 TU**（老板 2026-11-17 裁决）：单次动作占用 = 动作 TU + 往返移动 TU（`_tu_total`），超预算动作决策阶段即不可行；事件 `tu_spent` 为总占用、`round_trip_tu` 为其中移动部分。副作用：镇内往返 13–16 TU 的打猎当前不可达（需过夜机制），贫民区到东/南/西田往返 7–9 TU + 4 TU 农活 > 10 TU，贫民户无法耕作。
> - **rest 就地**：`_target_node("rest")` 返回人物当前位置而非家——力竭者在家外若必须先走回家，会出现「0 体力既不能走也不能歇」的死锁；eat 仍需回家。
> - **可行性闸口径**：移动体力须付得起；重活另需 `stamina > 0`（一次重活≈满格，结算后归零，必须 rest 回满才能再干），轻活不受此限。若要求「满格才可重活」，在贪心打分下会形成「体力 50–99 时重活不可行、轻活又不需要体力」的吸收态，农田长期无人耕作。
> - **闲时收敛**：剩余 TU 不足以执行任何动作、或体力已满仍选到 rest 时，剩余 TU **一次性**折算为一条 `rest`（`idle=true`）事件，不逐 TU 刷屏。
> - **集市计距偏差**：因当前无动作以集市为目标节点，`_settle_market` 仍按 `home_node → market` 计距，仅在执行者当日 `location == market` 时免往返；「顺路赶集」要到出现集市目标动作后才真正生效。

## 4. 可行性门控（任务 08 补充；任务 11 增加生存门控）

### 4.0 生存必要性门控（任务 11）
- 见 `05-decision-making.md §3.2`：有食物且饥饿将跨伤害阈值时强制 `eat`；无食物时不触发，不掩盖「无粮可吃」的死亡。该门控属决策可行性过滤，不参与效用打分，也不写事件。



### 4.0.1 借食物生存门控
- 家庭无任何可食库存、且没有逾期债务时，先尝试向最近可达的足额粮食债主借粮；没有粮食债主时，才向有富余鱼、肉或蔬菜的邻户借食物。
- 借食物由缺粮家庭主动发起，不扫描家庭、不自动划拨；债主保留配置的最低库存，借入物资与债务按同一种物资记账、偿还和催收。

### 4.1 farm 长势封顶
- 当前作物模型为简化标量：`world.state.environment.field_growth` 以节点为键存 0–100 的长势值，agent 取其 `work_node` 对应值作为感知字段 `work_field_growth`。完整作物模型见 `human-environment/01-production/...` 下的作物设计（未来落地），当前以标量近似。
- 当 `work_field_growth >= agriculture.max_field_growth`（长势封顶）时，`farm` 在**决策评分阶段即判为不可行**（返回 `IMPOSSIBLE`），而非仅降分——避免长势已满仍无效劳作、白白消耗体力，且封顶后不再产生 `farm` 事件。
- 所有动作均不可行时，沿用现有兜底（无动作、不崩溃），可通过观察层排查。

> **004 裁决（2026-11-17，待实现）**：长势封顶机制将由**劳动定额**取代——每田每季 TU 定额、家庭成员共享投入、产量按完成度折算、可提前做完（见 [crops.md §4.5](../natural-environment/05-soil-and-fields/crops.md)）。`field_growth` 标量模型废弃；「定额耗尽后 farm 不可行」继承本节「评分阶段判 IMPOSSIBLE」的做法。

### 4.2 生活用水获取
- 当前生活用水唯一来源是公共水井；溪古镇当前每次取水 16 单位（配置值），取水后计入家庭水库存。河流和灌溉渠不自动视为饮用水源。
- 家庭按存活成员数每日消耗生活用水，进食另消耗烹饪用水；水不足时本次进食不可行。当前没有独立脱水健康惩罚。P3a 起水井有有限存量（`EnvironmentState.water_sources`）：每 tick 按水位补水、同 tick 抽取有上限，取水经 `vale/contracts/water.py` 结算；现配置容量按取水量标定，两年基线内不触顶，枯竭只作为边界情况写 `water_withdrawal_refused`。
- 远户按季节可达性提前储水；储水目标是行为目标，不是容量上限。家庭库存仍无限存储。

## 5. 采集类生计与未来接入指南（任务 09）

### 5.1 通用采集机制（不写死动作名）
打猎（`hunt`）是首个「采集类动作」，与 `eat/rest/farm/...` 这类硬编码基础动作不同，采集动作走**配置驱动的通用分支**：
- 候选动作由 `_candidate_actions(tuning)` = 基础动作 + `tuning.gathering.actions` 的键动态生成；
- 目标节点由 `gathering.actions[action].target_node` 指定（`_target_node` 通用解析）；
- 执行走 `AgentModule._execute_gather`：成功率 = `base × season_modifier × bad_weather_mult`，成功则 `setattr(agent, output_field, +amount)`，受伤独立判定（`max(0, health - loss)` 不致死）；
- 事件统一为 `gather_success` / `gather_fail` / `gather_injury`，payload 带 `action`/`output_field`，观察层按 `GATHER_DESC` 映射中文动词与产物。
- `agents.py` 中**不出现** `if action == "hunt"` 式散落分支，新增第二生计无需改核心结算（`_settle` 催收/回血）。

### 5.2 接入新生计（以渔业为例）的步骤
1. **资源节点**：在 `config/worlds/<world>/spatial-units.yaml` 声明或复用一个资源节点（如水域 `river_town`），无需改代码。
2. **状态字段**：在 `src/vale/core/state.py` 的 `AgentState` 加产出字段 `fish: float = Field(default=0, ge=0)`。
3. **配置**：在 `agents.yaml` 的 `tuning.gathering.actions` 下加一项（`target_node` / `output_field: fish` / 成功率 / 产出 / 季节修正 / 风险）；在 `action.fulfill` / `stamina_cost` / `outdoor` 加 `fish`；在 `physiology.food_fields` 追加 `"fish"`（使 `eat` 可消耗）。
4. **观察层**：在 `render.py` 的 `GATHER_DESC` 加一行 `"fish": ("捕鱼", "鱼")`，三种 gather 事件渲染自动复用，无需新增渲染函数。
5. **核心结算**：`_settle`（催收/回血）**不用改**——这正是扩展点验证目标。
6. 写测试：在 `tests/test_hunting_and_sustainability.py` 仿照 `test_execute_gather_works_for_arbitrary_action_name` 加用例，断言新动作产出到指定字段且结算事件照常。

### 5.2a 渔业已按此指南落地（任务 10）
- `AgentState.fish` 字段、`gathering.actions.fish`（target_node=river_town，outdoor）、`food_fields=[grain, meat, fish]`、`GATHER_DESC["fish"]` 全部就位；`_execute_gather` 通用分支处理，核心结算零改动。
- 生计分层涌现：打猎 `survival=0.1`（纯经济远征，只在饱腹+田封顶的农闲窗口出猎）、捕鱼 `survival=0.8`（断粮时压过 rest 的维生手段）；贫民区→河边近路（1.5 TU）使贫民捕鱼可行，与远田阶级壁垒（东片田 3.5 TU）并存。
- 测试：`tests/test_task10_lifecycle_and_fishery.py` 覆盖鱼产出/失败/季节天气修正/eat 消耗鱼/扩展点回归。

### 5.2b 纺织（weave）已落地（任务 11）
- 实现方式与采集动作**不同构**：纺织不挂资源节点与随机采集表，而是仿 `farm` 的「配置驱动固定动作」——`fulfill.weave={economy:1.6}`、`action.stamina_cost.weave=15`、目标节点为自身 `work_node`，核心结算走 `_execute_weave`，不写第二套通用分支。
- 成功率 = `textile.base_success_rate × textile.season_modifier[season]`（冬季 0.8 手僵减产），成功产 `textile.cloth_per_weave` 匹布，分别写 `weave_success` / `weave_fail`。
- **v1 不做原料链**：布由劳动直接产出，不消耗麻/棉；`cloth` 的消费路径是冬季保暖门槛与集市交易，不再是囤积字段。原料链（亚麻/桑田、织机节点）为后续接入点：新增 `loom` 节点并把 `zhou_qiaoniang.work_node` 从 `market` 迁走即可，代码无需改动。
- **性别规范未接入**：`norm_penalty` 通道仍未实现，本任务不做男性织布惩罚（裁决 6.1：不做性别天赋，规范惩罚留待后续）。

### 5.3 集市交易（任务 11，结算阶段而非动作）
- 交易不是候选动作，而是**每日结算阶段**的跨人机制：`market_day_interval/offset` 决定集市日（默认每 10 天），逐人按 `home_node → market_node` 算往返 TU 扣体力；距离超 `market_max_distance_tu` 记 `too_far`，扣完低于 `market_min_stamina` 记 `too_weak`，均不扣体力。
- 撮合：按 `agent_id` 稳定排序后两两（A<B 只撮合一次），对 `trade_values` 中的物品两两组合，判「卖方富余且短缺对方物品、买方反之」；成交量按 `trade_unit_step` 向下取整，受 `max_trade_units` 与双方富余/短缺双向夹逼；交换价值相对误差超 `trade_value_tolerance` 不成交。
- 保护性物资需求：布匹的市场短缺目标不得低于 `textile.warmth_cloth_threshold`。通用 `market.deficit_threshold.cloth` 只表示普通库存短缺；冬季御寒需要 3 匹时，家庭即使已有 1 匹仍应能继续用富余物资换布，直到达到御寒门槛。撮合时动态取两者较大值，不改其他物品的阈值。
- 定价为**固定相对价值**（粮 1 / 菜 1.2 / 肉 2 / 鱼 1.5 / 布 3），无行情波动；v1 只按家到集市计距，不建模到场停留时长（`location` 自 M5 起随动作更新、日末回家）。
  - **004 裁决（2026-11-17，**M5 部分落地**）**：集市往返将改按**实际位置**（当日在场节点）计距，替代 `home_node` 计距。M5 已实现「执行者当日 `location == market_node` → 免往返体力」；但当前**没有**以集市为目标节点的动作，故常规仍按 `home_node → market_node` 计距，「顺路赶集」差异要在出现集市目标动作后成立。`location` 自 M5 起随动作更新、日末回家。
- 事件：每次成交 `trade_executed`（买卖双方 + give/take 数量 + 双方库存快照 + 赶路体力）；每个集市日一条 `market_day_summary`（参与者、分原因跳过计数、成交笔数）。不成交不写事件。
- 守恒：撮合只做物品转移，各物品总量不变、不为负；坏配置（偏移越界、价值≤0、阈值缺失或倒挂、步长≤0）在启动时由 schema 直接报错。

### 5.4 守恒与可追溯
- 每次采集产出写入 `gather_success` 事件（`output_before/after` + `amount`），可重建世界总产出；
- 旧版 `eat` 按 `food_fields` 顺序消耗属于兼容实现记录；新餐食结构以主食+配餐和周营养窗口为目标，见 ADR 008。无论采用哪种规则，实际消耗均须按物资字段守恒、不为负；
- 打猎不凭空消灭角色（受伤 `max(0, ...)`），死亡仍只由 `health<=0` 触发生命周期。

## 6. 家庭照料、协商与公共求助（ADR 008）

以下动作定义目标行为；是否已在运行时代码中可执行，以对应实现和测试为准，不因写入设计文档而视为已经落地。

### 6.1 家庭照料
- `care`：照料同户失能、患病/受伤或需要帮助的成员。可包含喂食、送水和当前模型已支持的基本照护；每次照料必须消耗照料者的 TU，并扣减真实家庭库存。
- `feed_dependent`：向未成年或无法自主进食的家庭成员提供食物。实施时优先复用现有 `_guardian()` 依赖者逻辑，扩展其适用场景，不破坏既有监护行为。
- 照料者必须存活且有行动能力。失能者仍受普通行动门控，不通过运行其普通决策循环完成自救。
- 照料是否发生取决于关系/亲缘义务、同住、紧急程度、照料者能力和可用时间；不得假设所有成员无条件照料。

### 6.2 家庭协商与分工
- 家庭层面可形成轻量任务建议，协调取水、食物生产、照料和对外求助。
- 任务建议不是强制命令；成员按年龄、健康、技能、体力、位置、TU 和个人意愿接受、拒绝或无法完成。
- 家庭计划复用现有 `HouseholdState`、成员列表、田块分配和个人效用决策，不另建家庭/Agent 状态机或时间系统。
- 计划、接受/拒绝、执行和调整应写事件或形成可重建投影，避免无记录地每 tick 改派任务。

### 6.3 公共储备上交与求助
- `donate_to_reserve`：Agent/家庭自愿将明确数量的物资上交公共储备。执行前检查家庭真实库存；成功后家庭库存减少、`community_reserves` 增加，数量守恒。超过安全库存不构成自动上交理由。
- `request_relief`：家庭成员向里正/公共管理者提出物资申请；申请不直接改变库存。
- `process_relief_request`：由有权限的管理者核实并批准、部分批准或拒绝；审批不等于出库。
- `issue_relief`：经批准后实际发放，公共库存减少、家庭库存增加；库存不足时部分满足或排队，不得为负。
- 户主失能时，其他有行动能力的家庭成员可以代办；全家无人可行动时可由邻里报告并启动紧急核查。
- 具体事件名和管理权限以现有治理模块可兼容的事件/决议结构实现；不得绕过 EventLog 与 Replay。
