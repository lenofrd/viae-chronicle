# 004 - 日内时间预算与生产底座（时间 × 体力 × 空间耦合）

- **状态**：已采纳 (Accepted)
- **日期**：2026-11-17
- **决策者**：老板（方向与全部参数裁决）、写码员（方案评估与本文起草）

## 1. 背景与上下文 (Context)

生产底座存在四组互相纠缠的简化（任务 28 诊断，2026-11-17）：

1. **1 动作/日**（G10）：每人每天只选一个动作，通勤不占时间。`tu_cost` 配置存在但无代码消费（死配置），与 [05-distances.md](../locations/brookvale-town/01-geography/05-distances.md) 「1 天 = 10 TU、farm 5 TU + 往返 3 TU = 一天」的设计原意不符。
2. **体力无分级**（G11 关联）：所有动作共用一张固定成本表，恢复只有 rest 一条通道；「轻活不耗、重活才耗、闲时快恢复」不存在。
3. **隐式劳动定额**（G11）：「每田每年约 50 次 farm」是 `max_field_growth(100) ÷ field_growth_per_farm(2.0)` 的商，无农时语义；harvest 为全有全无闸（秋季 + 长势阈值）。
4. **水缺位**（G9）：`collect_water` 是空动作；`natural-params.yaml` 的水位/灌溉档配置休眠无读取方；产量公式的 moisture 因子恒 1.0。

老板 2026-11-17 决定进行生产底座改造：机制修正 + 底座迁移，**规划先行、分模块实施、逐模块验收**；本轮只出设计，不写实现。方向与全部参数经三轮直接对话裁决（记录见 `.ai/STATUS.md` 任务 28 第二/三轮）。

## 2. 决策 (Decision)

### 2.1 日内时间预算（替代 1 动作/日）

- **量纲**：1 TU = 1 工作小时；夜间睡眠不占 TU。
- **工作窗随季节**：春 10 / 夏 9（午热） / 秋 10 / 冬 6（TU），外置为配置（`[调参]`），不按节气细分（第一版四档）。
- **动作 = {TU 时长, 体力速率} 二元组**：重活为纯劳作时长（`farm = 4 TU`，无内嵌间歇）。
- **「一日约 5 动作」是涌现软目标**，由时间 + 体力约束自然产生，不硬编码、不写断言。

### 2.2 体力分级与时间耦合

- **重活**：消耗 25 体力/TU（连续纯劳作 4 TU 即归零）。第一版重活 = farm、harvest、hunt。
- **轻活**：固定消耗 0（只占 TU）。第一版轻活 = weave、fish、collect_water、eat、borrow_grain。
- **通勤**：保留按 TU 的移动体力消耗（现量纲 `move_stamina_per_tu`，数值重标定属实现轮 `[调参]`）——远途往返先耗体力，「进山是苦差」的语义保留。
- **恢复**：`rest` 动作保留，1 TU 回满；**闲时**（剩余 TU 不足以执行任何可行动作）同样 1 TU 回满并消耗该 TU。劳逸比 4:1。
- **约束分工**：体力 = 小时级节奏器（防止连续重活）；**日总量约束交给工作窗 TU 与劳动定额**。此结构为有意设计，非疏漏。
- **不动项（G10 保留）**：体力上限 `100 × 分段乘数`、打分紧缺度除数 100 均不改。
- **跨天疲劳接口**：`AgentState.fatigue`（0–100，已存在）保留为接口，语义**以天记**（如连续重活日影响次日上限），本版不实现动力学。
- **废弃**：`rest_stamina_recovery: 40`（rest 动作 +40 的旧语义废止，由 1 TU 回满取代）。

### 2.3 日内决策与迁移策略

- **逐动作贪心重规划**：每完成一个动作，重新感知、重新打分、选择下一个，直到 TU 耗尽或无可行动作；复用现有效用打分器，不做全日规划、不引入序贯求解。
- **一次切换**：不设双模式开关；切换后以 **parity 验收**控制风险——5 种子 × 3600，按季节分层对照旧行为分布（存活、收割量、动作混合比的量级近似，非逐事件相等）。
- **事件量**：暂不聚合、不加日汇总事件，先观察实际量级再议（裁决选 a）。

### 2.4 空间位置语义

- 日内 `agent.location` 真实化：动作间人物位于实际节点；打分计距基点由「家 → 目标」改为「**当前位置 → 目标**」，日末回家（C1 语义）保留。
- 集市结算由按 `home_node` 计距改为按实际位置计距（消除「顺路/专程赶集」不分的失真）。

### 2.5 面积量纲（方案 A）

- `area = 1.0` = **一块标准田**，对应 `base_yield = {grain: 75, vegetable: 55}` 现值；三片田暂不落亩数（50/30/40 亩异质性不表达），面积异质性留给开荒模块（新田可 < 1.0）。

### 2.6 劳动定额（替代长势封顶）

- **按田记、家庭成员共享**：每田每季一个 TU 定额，户内所有成员的 farm 投入共同消耗该定额。
- **标定**：标准田 ≈ 450 TU/季（一季约一半时间做田活：90 天 × 10 TU × 50%），`[调参]`。
- **产量按完成度折算**：
  `产量 = base_yield × area × min(1, 投入 TU ÷ 定额 TU) × fertility × moisture × sunlight × (1 − disaster_damage)`
  废弃「长势 ≥ 阈值才能收割」的全有全无闸与 `field_growth` 标量长势模型（收割仍限秋季农时窗口）。
- **可提前做完**：定额耗尽后 farm 不可选，剩余农时自然流向其他生计。
- **跨季重置**；未完成季的定额投入不结转（颗粒无收风险保留）。

### 2.7 水模型最小切片

- 水位（`water_level_ratio`）与灌溉档（`irrigation_gear`）进世界状态，随气候（降水/干旱）演化——激活 `natural-params.yaml` 已有休眠初值。
- `collect_water` 产出「水」资产（轻活）；产量公式 `moisture` 因子接水位/灌溉档。
- **本版不做**：饮用健康联动、水存储上限、水权冲突（后续独立模块）。

### 2.8 实施顺序（修订）

**M5（日内循环 + 体力分级，吸收原 M1）→ 水模型 → M2（定额）→ M3（产量因子启用演化）→ M4（开荒）**。理由：时间账本是定额与通勤成本的共同量纲，先立地基避免双重返工；水模型不依赖日内循环细节，紧跟其后为 M2/M3 提供 moisture 来源。

### 2.9 补充裁决（2026-11-17 同日）：日照因子与 M3 演化

- **日照选方案 A（派生量）**：`sunlight_factor = f(当日降水, 季节基准)` 纯函数（量级：晴 1.0 / 雨 0.7 `[调参]`，可按连续无雨天数平滑），作为**独立乘数**进产量公式；**不扩 WeatherType、不加新状态/事件**，对雨天户外乘数、通行条件、回放零影响。推导规则见 [weather.md](../systems/natural-environment/02-climate/weather.md)。
- **M3 启用演化**（老板澄清，推翻同日早前「保持中性」的口误）：fertility 启用连作衰减/休耕恢复（规则已设计于 [fertility.md](../systems/natural-environment/05-soil-and-fields/fertility.md)）；moisture 随水模型真实生效；sunlight 同步启用。**边界**：`growth_health` 的虫害项与 `disaster_damage` 因 08-hazards 未建模暂保持中性，灾害模块立项后接入（若需提前另行裁决）。
- 演化速率与各系数为实现轮 `[调参]` 提案，逐项报批，不在设计阶段预设。

## 3. 后果与影响 (Consequences)

### 优势
- 时间 × 空间 × 体力三轴耦合，「环境是主语」兑现链成立：季节 → 工作窗 → 农时定额 → 位置通勤成本 → 日内取舍。
- TU 成为统一账本，后续开荒成本、赶集顺路、农忙农闲全部共享同一量纲。
- 属**补齐而非发明**：恢复 05-distances.md、01-physical-state.md（fatigue）、crops.md §4.5（area）早已写定的设计意图。

### 代价与风险
- 事件量约 ×3–5（冬少夏多）；观察后再决定是否聚合。
- `agent_action_taken` 需加日内序号/TU 区间字段：旧库回放缺字段按默认处理（replay 保持绿为硬红线）。
- 既有 `[调参]` 值（move_stamina_per_tu、fulfill 权重等）需在新量纲下重标定一轮；G1「5 种子存活」旧基线作废，新验收口径**另行裁决**。
- `field_growth` 状态被定额状态取代：旧世界实例（`data/`）不迁移，重开新世界。

### 设计文档回写清单（已于设计阶段完成，2026-11-17）
- [x] [05-distances.md](../locations/brookvale-town/01-geography/05-distances.md)：「1 天 = 10 TU」改为「工作窗随季节」（本镇数值春 10/夏 9/秋 10/冬 6）；farm 劳作 5 TU 例子改纯劳作 4 TU。**（locations 级：数值归此）**
- [x] [02-distance-and-time.md](../systems/natural-environment/01-spatial-skeleton/02-distance-and-time.md)：TU 量纲 1 TU = 1 工作小时、工作窗机制（数值由地点配置提供）。**（系统级：机制归此）**
- [x] [06-actions.md](../systems/agents/06-actions.md)：新增 §3.6 动作 {TU 时长, 体力速率}；§4.1 长势封顶→定额注记；§5.3 集市实际位置计距注记。
- [x] [05-decision-making.md](../systems/agents/05-decision-making.md)：§3.1 日内贪心重规划注记。
- [x] [01-physical-state.md](../systems/agents/01-physical-state.md)：§4.3 体力分级模型、fatigue「以天记」接口、与孕期限制（§4.4）的衔接、`rest_stamina_recovery` 废弃。
- [x] [crops.md](../systems/natural-environment/05-soil-and-fields/crops.md) §4.5：定额与完成度公式（数值标为地点参数）。
- [x] [03-hydrology/00-overview.md](../systems/natural-environment/03-hydrology/00-overview.md)：最小切片激活说明（单点简化水文先行，完整河段模型后置）。
- [x] 附带：[01-event-viewer-cli.md](../systems/observability/01-event-viewer-cli.md)（事件 schema 变更预告）、[11-life-course.md §18](../systems/agents/11-life-course.md)（G8/G9/G10 挂 004 裁决状态）、[01-initial-state.md](../locations/brookvale-town/05-setup/01-initial-state.md)（水文初值激活注记，locations 级）。

## 4. 验收口径（设计阶段先立，实现轮执行）

1. **parity**：M5 切换后 5 种子 × 3600，按季节分层对照旧行为分布（存活数、收割量、动作混合比的量级近似）。
2. **涌现检查**：日均动作事件数落在 4–6 区间；冬季显著少于春秋。
3. **红线**：replay 全绿；新事件可渲染；无 `agent_error`；守恒断言（粮/水/货币不凭空增减）不破。

## 落地注记（E1 审计归位，2026-11-22）

本文引用的 `../systems/natural-environment/*` 现位于 `systems/environment/`（环境域）或 `systems/kernel/`（空间骨架等横切层）；`../systems/agents/*` 现位于 `systems/society/agents/`。设计树按 ADR 010 §2.6 与裁决 5（B2）归位，正文不改，链接按新路径解读。
