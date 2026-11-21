# 生命历程与代际：家庭经济模型（任务 12 实现记录）

> **文档定位**：本文件保留任务 12 家庭模型迁移的实现记录、数据结构、事件载荷、Replay 兼容和历史测试结论。它不是婚姻与人口承载规则的最新规范。
> **历史基线**：任务 12 于 2026-11-15 完成家庭状态迁移、家庭经济流转、婚配合并、继承和分家等阶段；本文件中的“已落地”均指当时记录的代码状态，不能自动视为 ADR 007 后的目标行为。
> **当前设计规范**：人口不设全镇人数上限或家庭成员硬上限；婚姻认知门槛、从夫居、彩礼、陪嫁和家庭资产边界以 [人口承载与婚姻形成](12-population-and-marriage.md) 与 [ADR 007](../../decisions/007-population-and-marriage.md) 为准。
> **实现状态注意**：本文件保留的旧婚姻结算、家庭容量与资产合并逻辑，是需要按新决策调整的旧实现行为；不得将其作为新增代码的设计依据。

## 0. 落地进度

| 项 | 状态 |
|---|---|
| Household 状态层（资产/债务/住所/默认 work_node/head/guardian 预留） | 已落地 |
| `AgentState` 迁移（去资产/债务/住所，保留 `work_node: Optional` 个人偏好） | 已落地 |
| 四个访问器 `household_of / household_members / living_households / work_node_of` | 已落地 |
| 开局单人家庭（`hh_{id}`，资产=配置） | 已落地 |
| 出生：加入母亲家庭、不转移资产、不再产生 `birth_asset_transfer` | 已落地 |
| 消费/生产/借粮/还债/催收/集市/保暖改家庭库存 | 已落地 |
| 旧事件流只读重放 + `legacy_events.json` fixture + 4 条回放一致性测试 | 已落地 |
| 婚配合并、从夫居、容量、分家、户主接任、家庭继承/归公、债权家庭消亡 | 已落地（第 2–3 步；其中婚配合并与容量为 ADR 007 前的旧规则） |
| 每户每日一次集市、同户禁自交易 | 已落地（第 2 步） |
| 新生儿随迁（分家在生育后结算） | 已落地（第 3 步） |

## 1. 模型总览

- **经济单位 = `Household`（家庭）**。资产、债务、住所归家庭；`AgentState` 只保留个人生理、年龄、关系、家庭引用与**个人劳作点偏好**。
- **单人家庭 = 现有个人账户语义**：孤儿、独居者、未成家成年人各自一个家庭，资产/债务/住所一对一映射；这是保持 225 条既有测试语义的基石。
- 多人家庭：夫妻与子女共享资产/债务/住所；劳动仍可按个人 `work_node` 偏好分配到不同田块。
- 事件先行不变：家庭合并、分家、住所迁移、户主变更、消亡、继承都先写事件，状态是投影。
- 守恒不变：合并/分家/继承/借贷/交易只做转移；消费与归公是唯一允许的减少，且必须逐笔有事件。

## 2. `HouseholdState` 完整 Schema（P1）

```python
class DebtRecord(BaseModel):
    debtor_household_id: str            # Q8：运行时字段家庭化
    creditor_household_id: str          # 原 creditor_id 语义改为家庭 id
    amount: float = Field(..., ge=0)
    originated_tick: int = Field(..., ge=0)
    due_tick: int = Field(..., ge=0)
    last_collected_tick: Optional[int] = Field(None, ge=0)
    overdue: bool = False


class HouseholdState(BaseModel):
    household_id: str
    member_ids: list[str] = []          # 有序：户主在前
    head_id: Optional[str] = None
    guardian_id: Optional[str] = None   # Q7：预留，默认 None，本任务不实现外部监护

    # -- 共同资产（原 AgentState 字段整体迁移，语义不变）--
    grain: float = Field(0.0, ge=0)
    meat: float = Field(0.0, ge=0)
    fish: float = Field(0.0, ge=0)
    vegetable: float = Field(0.0, ge=0)
    cloth: float = Field(0.0, ge=0)

    debts: list[DebtRecord] = []        # 债务记录挂在债务家庭；字段内 debtor 必须等于 household_id
    home_node: str                       # 家庭住所（唯一真相源）
    work_node: str                       # 家庭默认主田/主工作节点
    work_nodes: list[str] = []           # 阶段二 C：家庭可分配田块（默认田优先，其余按家→田距离+节点 id）
    formed_tick: int = Field(..., ge=0)

    @computed_field
    def debt(self) -> float: ...         # sum(d.amount)，只读
```

`WorldState` 新增 `households: dict[str, HouseholdState]`。

**访问入口（唯一，禁止散落字段直读）**

```python
household_of(world, agent) -> HouseholdState
household_members(world, household) -> list[AgentState]
living_households(world) -> list[HouseholdState]
work_node_of(world, agent) -> str        # 个人偏好（有效且可达）→ household.work_nodes → household.work_node
inventory_of(world, agent) -> dict[str, float]   # 家庭资产快照（按 market.trade_values 键）
```

`household_of` 在家庭缺失时抛错（不静默兜底）；启动/重放阶段负责保证无孤儿。

## 3. `AgentState` 字段迁移表（P1/Q2）

| 字段 | 处置 | 说明 |
|---|---|---|
| `grain` / `meat` / `fish` / `vegetable` / `cloth` | **移走** → `HouseholdState` | 个人不再持有资产 |
| `debts` / `debt`(computed) | **移走** → `HouseholdState` | 债务归家庭 |
| `home_node` | **移走** → `HouseholdState` | 住所按家庭 |
| `work_node` | **保留为 `Optional[str]`，默认 `None`** | 个人劳作点偏好；`None` = 取家庭 `work_node`（Q2） |
| `location` | **保留** | 个人位置；v1 仅叙事，赶集按家庭住所计距 |
| `health` / `hunger` / `stamina` / `fatigue` | **保留** | 生理状态属个人 |
| `birth_tick` / `life_stage` / `spouse_id` / `married_tick` / `mother_id` / `father_id` / `children_ids` / `last_birth_tick` / `death_cause` / `last_injury_tick` | **保留** | 阶段二已落地 |
| `alive` / `incapacitated` / `incapacitated_tick` / `died_tick` / `last_action` / `recent_actions` | **保留** | 生命状态机不变 |
| — | **新增** `household_id: str` | 必填、不为 None |

**禁止资产/债务镜像**，也不做 property 代理。`AgentConfig.assets/home_node/work_node` 仅作开局输入（`work_node` 写入家庭默认值，个人偏好初始为 `None`）。

**生产事件**记录 `agent_id + household_id + 实际 work_node`（`work_node_of` 的结果），便于追溯“谁在哪块田干活、产出进哪个家庭”。

## 4. 单人家庭如何保持现有测试语义

1. 开局每个 `cfg.agents` 项生成 `hh_{id}` 单人家庭：`member_ids=[id]`、`head_id=id`，资产/住所原样搬入；`Household.work_node = cfg.work_node`，`AgentState.work_node=None`。
2. 单人家庭的操作与旧个人模型一一对应：`agent.grain` → `household_of(world, agent).grain`，数值、事件顺序、守恒断言不变。
3. 测试 helper 收敛：

```python
def hh(world, agent): return world.state.human.households[agent.household_id]
def inv(world, agent): return inventory_of(world, agent)
```

4. 事件键名**不重命名**（`grain_before/after`、`debt_after` 等），只新增 `household_id`；渲染器与既有断言无需改键名。
5. 单人家庭在借粮/还债/集市/继承中，家庭 id 与个人 id 一一对应，语义与旧个人模型等价。

## 5. 初始化

1. 为每个配置人物建单人家庭（资产来自 `AgentConfig.assets`，住所/默认工作节点来自配置）。
2. 建 `AgentState` 并写 `household_id`，个人 `work_node=None`。
3. 校验：`home_node`/`work_node` 必须存在于 `spatial.nodes`；`home_node` 非法时回退 `household.default_home_node` 并写 `household_moved(reason="default_home")`；`work_node` 非法时回退家庭 `home_node`。
4. 校验 `marriage.residence` 只能是 `patrilocal`（Q1），非法值启动即报错；其他枚举只预留、不实现。
5. 不写“开局家庭创建”事件（种子状态）。

## 6. 婚配与家庭合并（旧实现快照；目标规则见 12-population-and-marriage.md）

> 本节记录 ADR 007 前代码的实际行为，供迁移和旧事件 Replay 对照。容量限制、自动配对、女方原家庭成年成员限制、婚后资产/债务整体合并均已被新决策取代，不得作为新增代码的设计依据。

### 6.1 旧资格条件（D5/D15/D6）

- 双方存活、未失能；
- 年龄、健康和家庭存粮达到配置门槛；未婚或配偶已死且允许再婚；
- 异性（配置）；
- 非亲子/同父/同母（D15）；
- 两家 `home_node` 距离不超过 `marriage.max_distance_tu`；
- 女方原家庭除女方本人外不得有其他在世成年成员（当前代码的额外限制）；
- **容量**：`target.member_ids + incoming <= household.house_max_members`；超限静默跳过（Q6）。
- 旧实现没有认知关系门槛，陌生人也可能进入自动配对候选。

### 6.2 旧合并规则（Q1：从夫居 `patrilocal`）

1. 女方本人及其在世未成年子女随母迁入男方家庭；
2. 女方原家庭全部资产逐项并入男方家庭，债务列表拼接并改写债务家庭 ID；
3. 家庭住所和默认 `work_node` 取男方；女方个人劳作点偏好按旧代码规则重置；
4. 旧资格要求女方原家庭没有其他成年成员，因此迁移后来源家庭通常被清空；
5. 旧事件为 `agent_married` + `household_merged(reason="marriage")`。新婚姻不得继续用家庭合并事件表达。

### 6.3 旧 `agent_married` 载荷

```text
{tick, agent_id, agent_name, spouse_id, spouse_name, distance_tu,
 household_id, source_household_id,
 participants:[{id,name}, ...]}
```

### 6.4 旧 `household_merged` 载荷

```text
{tick, target_household_id, source_household_id, head_id,
 members_before, members_after,
 target_assets_before, target_assets_after, source_assets_before,
 debts_before, debts_after,
 home_node, work_node, reason:"marriage", participants:[{id,name}, ...]}
```

## 7. 出生与抚养

### 7.1 出生（A4 取消）

- 新生儿 `household_id = 母亲 household_id`；家庭资产**不变**；
- **阶段二 C 修订**：劳作点解析改为「个人偏好（有效且可达）→ 家庭 `work_nodes`（按可劳作成员序确定性对位分配，未成年/高龄不占劳作位）→ 家庭默认」；
  新生儿不继承个人偏好，取家庭分配，事件记 `work_node_source="household_allocation"`（无田/非田默认点时仍为 `"household"`）。
- `home_node` 取家庭；
- `agent_born` 追加 `household_id`；**不再产生 `birth_asset_transfer`**；
- **阶段二 §3.0 生育代价**：出生时母亲 `health −= birth.mother_health_cost`（默认 10，来自 01-physical-state §4.4 普通分娩），
  事件追加 `mother_health_before/after`。难产（−40 + 死亡风险）、孕期体力限制、产后休养**未实现**（见 §18 G6）。
- 旧事件库兼容：`birth_asset_transfer` 渲染器保留，仅用于旧库展示。

### 7.2 消费（D9 改写）

- `eat` 消耗家庭库存，按 `physiology.food_fields` 优先级扣减；事件记录 `household_id` + `household_inv_before/after`；
- 未成年人直接消费家庭库存，**不做资产转账**；`fed_by` 保留为叙事字段（照料者姓名），无经济语义；
- 生存门控：家庭任一可食库存 > 0 即可 `eat`；家庭无粮才不可行。

## 8. 住所与迁移（旧容量规则）

- `Household.home_node` 为唯一住所真相源；个人 `location` 不参与经济计距。
- 旧实现使用 `household.house_max_members` 限制婚姻迁入，并在生育时使用同一容量值跳过出生；这两项都是 ADR 007 明确取消的硬上限，不再是目标规则。
- 新规则不因家庭人数达到固定值而拒绝婚姻迁入或出生；住房拥挤只有在存在真实的建筑容量/居住质量模型时才作为生活条件反馈。
- `household.default_home_node`：不得为 None；非法/缺失时回退并写 `household_moved(reason="default_home")`。
- 赶集按 `Household.home_node` 计距。
- 住所变化写 `household_moved`：

```text
{tick, household_id, from_node, to_node, reason:"marriage"|"split"|"default_home"}
```

## 9. 分家与户主

### 9.1 户主接任（确定性）

户主死亡/离开时，按序取第一个存活成年成员（age ≥ `marriage.min_age`）：

1. 配偶（`spouse_id` 且同家庭）；
2. 最长成年子女（`birth_tick` 最小）；
3. 最长成年成员；
4. 全为未成年：取最长成员，`head_is_minor=true`（Q7）。

事件：

```text
{tick, household_id, old_head_id, old_head_name, new_head_id, new_head_name,
 reason:"death", head_is_minor: bool}
```

### 9.2 分家（Q4 采用）

触发：家庭人数 ≥ `split.min_members`（默认 4），且存在一对**已婚成年夫妻**、其中丈夫不是户主 → 该夫妻（及其未成年子女）分出。不限定必须是户主子女（兄弟同住/入赘同样适用）。**每户每 tick 最多一次**，确定性。

- 新家庭资产 = 原资产 × `split.asset_ratio`（逐项 `round(before × ratio, 2)`），`source_after = round(before − new, 2)`，余额留原户（P3：最后取差额，避免浮点误差）；
- 债务按同比例拆分：`new = round(amount × ratio, 2)`，`source_after = round(amount − new, 2)`；
- 新住所从 `split.home_node_candidates` 按新家庭 id 稳定轮转；候选为空或均无容量 → 沿用原 `home_node`（同节点分户）；
- 新户主 = 分出的丈夫；原户主不变（被分出者不是户主）；
- 事件 `household_split`：

```text
{tick, source_household_id, new_household_id, members,
 assets_before, source_assets_after, new_assets,
 debts_before, source_debts_after, new_debts,
 home_node, head_id, reason:"married_couple_out"}
```

## 10. 继承、归公与最后成员死亡

### 10.1 家庭未消亡

- 资产、债务不动；写 `agent_died`（追加 `household_id`）+ `household_head_changed`（若死者是户主）；**不写继承事件**（Q9）。

### 10.2 家庭最后成员死亡

- 先写 `agent_died`，再按 D10 在**家庭外**找继承人：配偶 > 子女最长者 > 父母；
- 有继承人：资产逐项转移至继承人家庭，写 `inheritance_executed`（含 `deceased_household_id` / `heir_household_id`）；债务 `debt_ratio` 转移，余额 `debt_written_off(reason="inheritance_remainder")`；
- 无继承人：逐物品写 `inheritance_escheated`，债务全额核销（`debt_written_off(reason="no_heir")`）；
- 最后写 `household_dissolved`：

```text
{tick, household_id, last_member_id, assets, debts, reason:"all_dead"}
```

- 守恒：`继承人家庭增量 + 归公量 = 死者家庭原资产`；`债务转移 + 核销 = 原债务`。

### 10.3 债权家庭消亡（Q5）

- 债权家庭最后成员死亡时，其**应收债权**（记录在各债务家庭 `debts` 中、`creditor_household_id` 指向它）优先由债权家庭的继承人承接：改写为继承人家庭 id，写 `debt_transferred`；
- `debt_transferred`（债权侧）追加 `debtor_household_id`（被承接债务的债务方），与 `debt_written_off` 对齐，保证逐笔核对可定位（任务 14 G7）；旧库缺该键时回放按债务侧逻辑处理，不报错；
- 债权家庭无继承人：逐笔核销，写 **`debt_written_off`**，`reason="creditor_household_dissolved"`；
- 不记坏账挂账、不向不存在家庭转账。

## 11. 经济流转（家庭口径）

### 11.1 借粮

- 债权人 = `living_households()` 中存粮 ≥ 借出量、且非自身家庭，按存粮降序（并列按 household_id）；
- 转账：债权家庭 −amount → 债务家庭 +amount；`DebtRecord` 写入债务家庭，`debtor_household_id` = 债务家庭；
- 事件 `debt_formed` 追加 `debtor_household_id` / `creditor_household_id`；保留旧键 `creditor_id`（= 债权家庭户主 agent id）与姓名叙事（Q8）。

### 11.2 还债/催收

- 债务家庭库存 → 债权家庭库存；不得扣成负；
- 事件 `debt_repaid` / `debt_collected` / `debt_defaulted` 追加双方 `household_id`，保留旧键兼容；
- 债权家庭消亡：按 §10.3。

### 11.3 集市（Q3）

- **每户每日最多一次**家庭集市行程；执行者：
  1. 户主，若存活、未失能、成年（age ≥ `marriage.min_age`）且体力足够；
  2. 否则取最长成年可行动成员；
  3. 无成年可行动成员 → 整户不去，计入 `skipped.dead_or_incap`。
- 体力成本记在执行者个人 `stamina`；
- 撮合以家庭库存为单位，**禁止同户自交易**；
- 事件：`trade_executed` 追加 `seller_household_id` / `buyer_household_id`、`seller_agent_id` / `buyer_agent_id`；
- `market_day_summary.participants` 每项：

```text
{household_id, participant_agent_id, participant_name, travel_stamina_cost, member_count}
```

- `skipped` 键保持 `dead_or_incap / too_far / too_weak`（D16）。

### 11.4 生产与保暖

- `farm` / `harvest` / `gather` / `weave` 产出进家庭库存；田块取 `work_node_of(world, agent)`（阶段二 C：个人偏好（有效且可达）→ 家庭 `work_nodes` 按可劳作成员序对位分配 → 家庭默认）；
- 冬季保暖判定用家庭 `cloth`；
- `agent_action_taken` 追加 `household_id`、`household_inv_before/after`、`work_node`；个人 `health/hunger/stamina` 字段不变。

## 12. A2 扩展：过滤无成员家庭

```python
living_agents(world)       # 动作层：谁今天能决策/劳作/吃饭
living_households(world)   # 经济层：家庭仍有存活成员即参与
```

- 债权人、交易对手、债务对象、继承转账、婚配容量统一走 `living_households()`；
- 死者家庭若仍有成员继续参与经济；家庭无成员才由 `household_dissolved` 移出；
- 禁止散落 `if agent.alive` 的经济过滤。

## 13. 事件清单与兼容（Q8/P1）

**新增**：`household_merged`、`household_split`、`household_moved`、`household_head_changed`、`household_dissolved`、`debt_written_off`。

**追加 `household_id` 的既有事件**：`agent_action_taken`、`agent_born`、`agent_died`、`agent_married`、`debt_formed`、`debt_repaid`、`debt_collected`、`debt_defaulted`、`debt_forgiven`、`debt_transferred`、`trade_executed`、`market_day_summary`、`inheritance_executed`、`inheritance_escheated`、`cold_exposure`、`gather_success`、`gather_fail`、`gather_injury`、`weave_success`、`weave_fail`。

**停用**：`birth_asset_transfer`（仅旧库渲染兼容）。

**旧键兼容**：旧事件流中的 `creditor_id` / `debtor_id` 保留不动；新事件同时写 `creditor_id`（= 债权家庭户主 agent id）与 `creditor_household_id`。

**观察层**：新增 6 类家庭事件中文渲染；`debt_written_off` 渲染“核销”；旧字段缺失时降级但不崩。

**查询层（Q10/D14）**：`EventFilter` 新增 `household`，匹配 `payload.household_id` 或 `participants[].household_id`；CLI 新增 `events timeline --household <id>` 过滤参数（不新建子命令）；`events list` 默认行为不变。

## 14. 旧库/旧事件重放策略（P2，关键补丁）

**原则**：事件是真相，迁移**不得改写旧事件**；家庭是只读投影上的包装，旧库照常可查、可重放。

### 14.1 重放入口（迁移阶段新增）

`src/vale/world/replay.py`（P6 起由 `src/vale/core/replay.py` 迁入）：

```python
def rebuild_state(events: list[dict], config) -> WorldState
```

- 只读：不写事件库、不改事件载荷；
- 按事件 `id` 升序（= tick + 写入序）回放；
- 未知事件类型计入 `ignored_events` 计数，不中断。

### 14.2 旧事件 → 家庭投影规则

| 旧事件 | 重放规则 |
|---|---|
| 任意事件首次出现某 `agent_id`（或 `agent_name` 可反查） | 动态创建 `hh_{agent_id}` 单人家庭（幂等），`member_ids=[id]`、`head_id=id` |
| `agent_action_taken`（旧） | 资产 `*_after` 写入 `hh_{agent_id}`；`home_node` 取配置（旧事件未编码住所变更） |
| `debt_formed` / `debt_repaid` / `debt_collected` / `debt_defaulted` / `debt_forgiven`（旧） | `creditor_id` / `debtor_id` 为 agent id → 映射 `hh_{agent_id}`；债务记录按事件顺序重建 |
| `trade_executed`（旧） | `seller_id`/`buyer_id` → 各自 `hh_{agent_id}`；库存 `*_after` 写入对应家庭 |
| `gather_*` / `weave_*` / `cold_exposure`（旧） | 产出/扣减映射到 `hh_{agent_id}` |
| `agent_born`（旧） | 新生儿建 `hh_{child_id}` 单人家庭；旧 `birth_asset_transfer` 按旧语义落到父母/子女各自家庭 |
| `birth_asset_transfer`（旧） | 仅重放为旧语义（个人资产转移），不再新产生；渲染器保留 |
| 新事件（含 `household_id`） | 直接按 `household_id` 重放；缺失时按 14.2 首行动态建单人家庭 |

### 14.3 重放后不变量

1. 每个 `agent.household_id` 非空且指向存在的家庭；
2. 每个家庭 `head_id ∈ member_ids`，`member_ids` 无重复、无不存在成员；
3. 无孤儿家庭（成员全部不存在）与孤儿成员；
4. 旧库重放后的逐 agent 资产/债务/住所与旧实现快照一致，仅多一层家庭包装；
5. 事件条数、id、载荷与旧库完全一致（`query` 不丢事件）。

### 14.4 验收测试（迁移阶段）

- `test_legacy_replay_creates_single_households`：旧事件流 → 每个 agent 一个单人家庭，无孤儿；
- `test_legacy_replay_assets_match_old_snapshots`：逐 agent 资产等于最后 `*_after`，债务总额等于最后 `debt_after`；
- `test_legacy_replay_debt_ids_mapped`：旧 `creditor_id` 正确映射 `hh_{id}`；
- `test_legacy_replay_does_not_rewrite_events`：重放前后事件库逐字节/逐行一致；
- 旧库 fixture：`tests/fixtures/legacy_events.json`（从当前个人模型版本导出的最小事件流，含借粮/还债/出生/继承）。

## 15. 守恒与浮点（P3）

| 操作 | 不变量 |
|---|---|
| 初始化 | Σ家庭各物品 = Σ配置 `assets`；住所/工作节点有效 |
| 合并 | 逐项 `target_after = target_before + source_before`（2 位小数）；债务笔数/总额相等 |
| 分家 | `new = round(before × ratio, 2)`；`source_after = round(before − new, 2)`；`source_after + new = before` 精确成立 |
| 出生 | 家庭资产不变 |
| 消费 | 家庭库存减少 = 实际进食成本；世界总量仅因此减少 |
| 生产 | 家庭库存增加 = 产出；世界总量仅因此增加 |
| 交易 | 各物品跨家庭总量不变；无同户自交易 |
| 借/还/催收 | 两户合计不变；库存/债务非负 |
| 最后成员死亡 | `继承 + 归公 = 原资产`；`债务转移 + 核销 = 原债务`；归公逐笔事件 |
| 债权家庭消亡 | 债务转移至继承人家庭或核销，资产不动，事件可追溯 |

**浮点规则**：所有家庭库存写入统一 `round(x, 2)`；比例拆分先算新份额、原户取差额；断言用 `pytest.approx(abs=1e-9)` 或“逐项 2 位小数相等”。

## 16. 迁移步骤（裁决确认后执行）

1. Schema：`HouseholdState`、`DebtRecord` 家庭化、`AgentState.work_node: Optional`、`household_id`、`WorldState.households`；`HouseholdTuning`（`house_max_members`、`default_home_node`、`marriage.residence`、`split.*`）与 `agents.yaml` 配置。
2. 初始化建家庭 + 访问器（`household_of/work_node_of/household_members/living_households`）。
3. 经济读写全部切家庭；借粮/还债/催收家庭化；集市按户执行；生产按 `work_node_of`。
4. 婚配合并、户主接任、分家、最后成员死亡与继承；出生/消费改写。
5. `replay.py` 旧库重放 + fixture + 四条回放测试。
6. 观察层新事件渲染；`EventFilter.household` 与 `timeline --household`。
7. 测试按 §17 顺序适配；全量回归 + 2 种子 × 1800 tick 冒烟；**不调参、不提交、不 push**。

## 17. 测试适配顺序（P5）

**每步结束跑全量回归；不得用改测试掩盖语义变化。**

| 步骤 | 内容 | 预计 |
|---|---|---|
| 1 | `hh()` / `inv()` 机械替换，断言数值不变 | ~60 条，6 个文件 |
| 2 | A4 两条删除（改为“出生前后家庭资产不变”）；D8/D9/D13 共 4 条改写 | 6 条 |
| 3 | 集市/借粮/债务改家庭口径（`household_id` + 户主 agent，`skipped` 键不变） | ~12 条 |
| 4 | 新增家庭专项 12–16 条 + 旧库回放 4 条 | 16–20 条新增 |

**最终验收**：`225 passed + 新增专项` 全绿；新增至少覆盖合并/分家/接任/消亡/容量/同户不自交易/家庭时间线/重放一致性。

## 附录 A 裁决结果（Q1–Q10）

| # | 裁决 | 设计落点 |
|---|---|---|
| Q1 | 默认从夫居，`marriage.residence: patrilocal`，非法值报错 | §5.4、§6.2 |
| Q2 | 保留 `AgentState.work_node: Optional` 个人偏好，家庭 `work_node` 为默认 | §2、§3、§6.2、§11.4 |
| Q3 | 每户每日一次家庭集市行程，户主优先，禁同户自交易 | §11.3 |
| Q4 | 人数 ≥4 且有“丈夫非户主”的已婚成年夫妻可分家，每户每 tick 最多一次 | §9.2 |
| Q5 | 债权家庭消亡：继承人承接，否则 `debt_written_off` 核销 | §10.3 |
| Q6 | 婚配容量不足静默跳过，不写事件 | §6.1 |
| Q7 | 全户未成年取最长成员，`guardian_id` 预留 | §2、§9.1 |
| Q8 | `DebtRecord` 家庭化字段；事件保留旧键兼容；旧 id 映射 | §2、§13、§14 |
| Q9 | 不新增遗属家庭审计事件 | §10.1 |
| Q10 | 新增 `events timeline --household <id>` 过滤参数 | §13 |

## 18. 历史已知缺口（任务 12/阶段三记录，约 2026-11-15）

> 本表是当时的技术债快照，不是当前 CI 状态。后续 PR #12 长程模拟与 ADR 006/007 已更新相关问题的诊断口径；不要把表中的 seed 结果、测试状态或解除条件当作当前结论。

| # | 缺口 | 现象/证据 | 影响 | 解除条件 |
|---|---|---|---|---|
| G1 | 家庭口粮承载力不足 | 2 种子 × 600 tick：4 成年 + 2 未成年时每 50 tick 进食 73–77 次，`gather_success` 仅 4–17 次，食物 135 → 0；关闭合并（少 1–2 张嘴）则可稳定在 140–207。**任务 15 收尾验收（5 种子 × 3600）**：seed 1 从 10 人跌到 2、seed 123 从 10 人跌到 4，后段库存耗尽；两 seed 债务家庭长期零粮（`debt_defaulted` 27/30 次），与债务机制无关 | 人口在 400–600 tick 内归零；长程可持续性不达标；接近崩溃的种子无「有粮赖账」窗口 | 阶段三调参（采集产出/生育间隔/未成年人 `food_share`/采集体力）或补“口粮承载力”设计；第 3 轮提产冲 5/5 |
| G2 | ~~无劳动分配机制~~ **阶段二 C 已落地确定性田块分配**（`work_nodes` 按可劳作成员序对位，解决 east_field 零投入）；搭便车治理诊断结论不变（不明显，主因是承载力） | 与对照相比，成年成员人均 `fish+hunt` 无系统性下降；家庭食物下降与人口数（6 vs 4）同步 | 田块分配已实现；搭便车治理不实现 | 阶段三调参后若仍出现明确搭便车数据，再补设计 |
| G3 | ~~长程可持续性测试降级为技术债~~ **已恢复（阶段三第 2 轮）** | 12 条 `_tech_debt` 断言全部恢复原名与 `assert survivors/alive`；1080 tick × 5 种子、1800 tick × 5 种子、1080 tick × 2 种子全部通过 | — | 已完成；3600 tick 仍 4/5（seed 42 第 2461 tick 库存耗尽灭绝），属 G1 承载力缺口 |
| G4 | ~~分家未实现~~ **已在第 3 步落地** | `split.min_members` / `asset_ratio` / `home_node_candidates` 与 `household_split` 事件已实现，含守恒与住所轮转 | — | 已完成 |
| G5 | 外部监护/其他居所制未实现 | 全户未成年仅取最长成员为户主（Q7），不做亲属间监护转移 | 孤儿户可能由未成年户主支撑 | 后续家庭扩展 |
| G6 | 生育代价缺数值（阶段二 §3.0 登记） | **设计有框架**（[01-physical-state.md §4.4](01-physical-state.md)：孕期分段、晚期 `max_stamina −50%`、普通分娩 health −10、难产 −40 可能死亡、产后休养 1–2 月），**缺**难产概率 / 孕期时长 / 产后休养数值 | 当前仅落地「普通分娩 health −10」 | 阶段三前补数值即可实现，**不需重新设计** |
| G7 | **债务链路在盈余经济下休眠** | 2 种子 × 2600 tick 无 `debt_formed`；借粮要求家庭存粮 <2 且有存粮 ≥5 的债主，盈余改善后两者不同时出现；受控 A–F 六场景 6/6 守恒（债权侧转移已补 `debtor_household_id`） | 非缺陷，是盈余经济的副作用：无人断粮是正面效果，但债务/催收/纠纷系统在正常年景无素材 | **已缓解（最小切片）**：阶段二以集市赊账（`market.credit`）恢复债务素材，阶段三以「有粮赖账」2 轮私下催收恢复冲突素材；5 种子 × 3600 实测 34 次会话、全额 13/延期 11/拒绝 8。完整冲突系统（调解/村规/公开惩罚/信任恩怨）仍后置 |
| G8 | **位置跟踪缺失（任务 16 阶段二登记）** | `agent.location` 仅每日结束时置回 `home_node`（agents.py 日终结算），白天劳作/集市位置不落状态；无地点→在场 agent 反向索引 | 「进入/离开地点」感知触发无法实现；同地点判定不可靠，任务 16 社会认知层以「交互即升级 KNOWN」规避（裁决 16 §3.2/§3.3） | 未来做感知/在场系统前先补位置跟踪，独立立项。**004 已裁决（2026-11-17，待实现）**：日内位置真实化（当前位置→目标计距、集市按实际位置计距），见 [decisions/004](../../decisions/004-intraday-time-and-production-base.md) §2.4；感知/在场系统仍后置 |
| G9 | ~~饮水系统未建模、`collect_water` 为空动作（任务 23 历史登记）~~ **已由任务 30 最小切片解决** | 当前 Household 已有 water 库存；`collect_water` 通过水井服务产水，每餐消耗用水，before/after 进入行动事件 | 人体脱水健康后果、水质与旱灾/水权冲突仍未完整建模 | 已落地的家庭水库存、取水和佐餐用水以当前代码为准；剩余水文扩展另行设计，不再沿用本行旧的“未建模”结论 |
| G10 | **「1 动作/日」架构假设（任务 24 登记）** | 每人每日只做一次决策、只执行一个动作（[agents.py L544-580](file:///f:/viae-chronicle/src/vale/modules/agents.py#L544-L580) `_process_one`；移动按「一天一次往返」计 [L773-780](file:///f:/viae-chronicle/src/vale/modules/agents.py#L773-L780)）；体力节奏调整只能改恢复量/门槛，无法表达「早干、午歇、下午再干」。裁决 24 §2.3：体力上限（代码常数 `100×分段乘数`、打分体力紧缺度除数硬编码 100）一并归入本项 | 单日动作粒度粗，体力曲线只能靠跨日恢复近似；休息与劳作互斥，无法表达半日劳动；体力上限无法作为单一配置杠杆调整 | **004 已裁决（2026-11-17，待实现）**：日内多动作（工作窗 TU 预算 + 体力分级 + 贪心重规划）落地，见 [decisions/004](../../decisions/004-intraday-time-and-production-base.md)；**上限与除数两处硬编码维持不动**（004 §2.2 不动项） |

> G1–G3 为第 2 步收尾的显式技术债，代码中所有降级测试以 `_tech_debt` 后缀标记，解除条件写在测试 docstring 与本表。

### 18.1 阶段三输入清单（定稿）

阶段三直接引用本节，不重读历史裁决。

| 输入 | 位置 | 规模 | 当前口径 |
|---|---|---|---|
| 长程打猎/采集可持续 | `tests/test_hunting_and_sustainability.py` 5 条 `_tech_debt` | 5 | 种子 0/1/7/42/123；无 `agent_error`、无负值、记录每 200 tick 人口曲线 |
| 长程多样化食物 | `tests/test_task10_lifecycle_and_fishery.py` 5 条 `_tech_debt` | 5 | 同上（种子 0/1/7/42/123） |
| 第二阶段长程 | `tests/test_task11_movement_market_textile.py` 2 条 `_tech_debt` | 2 | 同上（种子 0/7） |
| G1 家庭口粮承载力不足 | §18 | — | 人口 400–600 tick 归零 |
| G2 无劳动分配 | §18 | — | 暂不实现，待明确搭便车数据 |
| G3 长程测试降级 | §18 | 12 条 | 阶段三恢复原断言 |
| G4 分家 | §18 | 已完成 | 无需输入 |
| G5 外部监护/其他居所制 | §18 | — | 后续家庭扩展 |

逐条测试名、种子与人口曲线见 `.ai/REPORTS/STATUS-task-12-2026-11-15.md` §3.1。

### 18.2 阶段三前置条件（只列不执行）

1. 12 条 `_tech_debt` 恢复原断言并通过后，删除后缀与 docstring 技术债说明。
2. G1 调参白名单：采集产出 / 生育间隔 / 未成年人 `food_share` / 采集体力；一轮只动一个杠杆。
3. G2 需先给出“明确搭便车数据”再决定是否实现劳动分配；无数据不实现。
4. 分家长程触发依赖人口回升（出现第二对“丈夫非户主”夫妻）；此前以专项测试覆盖，不以冒烟 0 次判失效。
5. 旧库 4 条回放保持绿；守恒、非负断言不得放松。

