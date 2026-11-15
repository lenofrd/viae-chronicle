# 生理状态

## 1. 目的
定义人物的生理属性，包括性别带来的生理差异和生育周期，以及这些属性如何随时间和事件变化。

## 2. 核心概念
- **性别（sex）**：male（男）/ female（女）。第一版不涉及复杂的性别认同，只做生理性别及其衍生的社会角色。
- **年龄**：决定体力上限、生育能力、抗病能力。
- **体力（stamina）**：劳作、移动消耗，睡眠和进食恢复。
- **健康（health）**：受疾病、伤害、饥饿、分娩、衰老影响。
- **饥饿（hunger）**：每天累积，进食降低。
- **疲劳（fatigue）**：劳作累积，睡眠降低。
- **怀孕与分娩（仅女性）**：孕期体力受限，分娩有健康和生命风险。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| sex | enum | male / female |
| age | int | 年龄（岁） |
| stamina | float 0–100 | 当前体力 |
| max_stamina | float | 体力上限（受年龄、性别、健康影响） |
| health | float 0–100 | 当前健康 |
| hunger | float 0–100 | 饥饿度（>80 开始掉健康） |
| fatigue | float 0–100 | 疲劳度 |
| pregnancy_stage | enum? | 未怀孕/怀孕早期/怀孕晚期/产后休养 |
| fertility | bool | 当前是否具备生育能力 |

## 4. 演化规则

### 4.1 性别与基础生理
```
条件：角色创建
效果：决定 sex
      第一版不做男女基础体力的大幅差异，但女性在怀孕/产后有显著限制
```

### 4.2 饥饿累积与进食
```
条件：每 tick
效果：hunger += 基础消耗率
      若执行 eat 动作：hunger -= 食物营养值
      若 hunger > 80：health -= 损耗率
```

### 4.3 体力消耗与恢复
```
条件：执行动作或休息
效果：劳作消耗体力，sleep 恢复体力
      体力低于 20 时，决策倾向选择休息
```

### 4.4 怀孕与分娩（仅 female）
```
条件：pregnancy_started 事件触发且处于育龄期
效果：进入 pregnancy_stage = 怀孕早期
      怀孕早期（1–3 个月）：体力消耗略增，无重大限制
      怀孕晚期（7–9 个月）：max_stamina 下降 50%，无法进行重体力劳作（如 farm, gather_firewood 受限）
      分娩时：判定分娩风险
        - 普通成功：health -10，进入产后休养（生成 birth 事件）
        - 难产：health -40，可能触发死亡
      产后休养（1–2 个月）：max_stamina 恢复中，无法进行重体力劳作
```

> **部分已落地（盈余经济阶段二，2026-11-15）**：出生时母亲 `health −= birth.mother_health_cost`（默认 10，
> 即「普通成功 −10」），`agent_born` 追加 `mother_health_before/after`，见 [11-life-course §7.1](file:///f:/viae-chronicle/docs/design/systems/agents/11-life-course.md#L160-L169)。
> **未实现**：`pregnancy_started` / `pregnancy_stage`（孕期分段与体力限制）、难产风险、产后休养——
> 本节**框架完整、只缺数值**（孕期时长、难产概率、产后恢复参数），阶段三前补数值即可实现，不需重新设计
> （缺口登记见 [11-life-course §18 G6](file:///f:/viae-chronicle/docs/design/systems/agents/11-life-course.md#L421)）。

### 4.5 健康与死亡
```
条件：health <= 0 或 age > 寿命阈值（考虑性别差异，女性略高）
效果：人物死亡
      生成 death 事件，触发人文环境的丧葬、继承
```

### 4.5a 失能与死亡生命周期（任务 10 落地）
两阶段状态机（参数外置 `death:` 调参块，代码不写死）：
```
阶段一 失能（incapacitated）：
条件：health <= incapacitation_health_threshold（默认 0）且尚未失能且存活
效果：AgentState.incapacitated = True，记录 incapacitated_tick
      写一次 agent_incapacitated（载荷：tick/agent/原因/health/hunger/stamina/宽限期）
      立即停止感知/决策/执行——后续 tick 不再产生任何 agent_action_taken
      不参与催收（避免对垂死之人重复刷违约）与回血（无法进食恢复）
      饥饿累积与饥饿掉血仍发生（无法进食只会更糟）

阶段二 死亡（alive=False）：
条件：失能满 death_grace_ticks（默认 7，0=立即死亡）仍未恢复
效果：AgentState.alive = False，记录 died_tick
      写一次 agent_died（载荷：tick/agent/原因/失能 tick/死亡 tick/health/遗留债务）
      按 forgive_debt_on_death 核销剩余债务：逐笔写 debt_forgiven（可追溯，不静默消失），
      债务列表清空；核销是坏账处理（债主承担损失），不移动粮食（世界总粮不变，总债减少有事件）

幂等性：两阶段事件各自只写一次（状态机幂等：已失能/已死亡直接短路返回）。
死者保留在 WorldState.agents 中（人生档案），但完全不参与任何处理。
```

### 4.6 健康回血（任务 08）
```
条件：每日结算阶段，hunger < health_recovery_hunger_threshold
                 且 stamina > health_recovery_stamina_threshold
效果：health = min(100, health + health_recovery_per_day)
      仅数值实际变化时生成 health_recovered 事件（含 before/after/reason/hunger/stamina）
滞后：每 tick 结算后
影响范围：单人
```
说明：回血在 `AgentModule._settle` 结算阶段执行，**不覆盖** `_process_one` 中的饥饿扣血（4.2）——二者同日可并存（先扣后回，或条件不满足只扣不回）。健康上限 100 为域常量，非调参；回血速率/两阈值外置为 `health:` 调参块。长期饥饿或体力耗尽时条件不满足，不回血、不写事件。

### 4.7 食物储备与多食物消耗（任务 09，任务 10 扩展）
- `AgentState` 新增 `meat` 字段（≥0），与 `grain` 并列构成食物储备；打猎产出写入 `meat`。
- `eat` 消耗改为按 `physiology.food_fields`（默认 `[grain, meat]`）优先级：吃第一个存量 ≥ `eat_grain_cost` 的字段；都不够时吃尽存量最多的字段（不产生负值）。所有食物字段都 ≤ 0 时 `eat` 判为不可行。
- **任务 10 落地渔业**：`AgentState` 新增 `fish` 字段（≥0），捕鱼产出写入 `fish`；`food_fields` 配置为 `[grain, meat, fish]`，`eat` 核心代码不变——验证了「加食物字段只改配置」的扩展点。
- **任务 11 落地蔬菜**：`AgentState` 新增 `vegetable` 字段（≥0）；田块通过 `spatial.crop_type` 声明作物（`west_field` 为 `vegetable`，其余缺省 `grain`）；`harvest` 按 `crop_type` 从 `agriculture.crop_gain` 取产出并写入同名字段。`food_fields` 调整为 `[grain, vegetable, meat, fish]`，`eat` 核心代码再次零改动。
- **守恒**：粮、菜、肉、鱼各自守恒、不为负、可追溯（`agent_action_taken` 载荷含四者的 before/after，秋收另带 `crop` 字段）。
- 非田地节点（如集市）的 `work_node` 不能 `farm`/`harvest`（决策阶段判不可行），避免「在广场种粮」。

### 4.8 布匹与冬季保暖（任务 11）
- `AgentState` 新增 `cloth` 字段（≥0）：**耐用品**，不参与 `eat` 每日消耗，可进入集市交易。
- 冬季（`Season.WINTER`）每日生理演化后检查：`cloth >= textile.warmth_cloth_threshold` 免惩罚；否则 `health -= textile.cold_health_loss`，并写一条 `cold_exposure`（每人每日至多一条）。
- 织布（`weave`）是 `cloth` 的唯一产出路径（v1 由劳动直接产布，不消耗麻/棉原料，见 06-actions.md §5.2b）。
- **守恒**：`cloth` 不凭空产生/消灭，产出走 `weave_success`（before/after），交易走 `trade_executed`（双方库存快照）。

## 5. 与其他系统的接口
- 读：食物存量、休息场所。
- 写：决策系统（重体力劳作受怀孕和疲劳限制）、人文环境（生育率影响人口结构）。