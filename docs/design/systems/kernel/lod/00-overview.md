# Simulation LOD（多分辨率模拟契约）

> **能力状态**（E1 审计 2026-11-22）：**规划**——本文档为 ECO-01 任务 E2 的短设计文档，**经老板裁决后实现**。依据：ADR 010 §2.2、任务书 E2。

## 1. 定位

Simulation LOD 是**内核级通用能力**（ADR 010 §2.2）：对模拟中的主体（人物、地块、河段、种群……域中立，统一以稳定 ID 引用）按「兴趣」分配**细节档位**，使被关心的对象以精细规则演化、其余对象以粗档规则演化——但**粗档不是冻结**，只是更便宜的演化。内核只负责策略计算与分发，不写任何域状态、不含任何域假设。

解决的未来问题：主传记人物 fine 档逐 tick 演化，远处配景村庄 coarse 档按月聚合演化；预算收紧时自动降档。第一版不解决自适应问题，只立契约。

## 2. 概念模型

| 概念 | 定义 |
|---|---|
| **主体（subject）** | 需要档位决策的对象，由各域注册，形如 `(domain, subject_id)`；内核不解释其语义 |
| **档位（DetailTier）** | `fine` / `normal` / `coarse` 三档枚举（命名待裁决，见 §9-1） |
| **策略（LodPolicy）** | 每 tick 把 `(主体集合, 预算, 世界状态摘要)` 映射为 `主体 → 档位` 的纯函数式对象 |
| **兴趣目标（interest target）** | 档位分配的依据之一：谁（观察者/查询焦点）关心什么；由域或查询层声明，内核聚合 |
| **空间影响（spatial influence）** | 兴趣的空间分量：多个焦点各有影响半径，多焦点并集生效；**不假设单一视角** |
| **预算（BudgetHint）** | 各域每 tick 可承受的「精细档主体量」上限之类的提示；策略据此收敛 |

## 3. 契约（内核 API 草案）

实现位置：`core` 包内新增 `lod.py` 单文件（仅此一处入内核）。

```python
class DetailTier(Enum):
    FINE = "fine"; NORMAL = "normal"; COARSE = "coarse"

@dataclass(frozen=True)
class LodContext:          # 每 tick 供给策略的只读输入
    tick: int
    subjects: tuple[SubjectRef, ...]   # 各域本 tick 注册的主体
    budget: Mapping[str, int]          # domain → 预算提示（可为空）
    seed: int                          # 派生自世界 seed，保证确定性

class LodPolicy(Protocol):
    name: str
    def evaluate(self, ctx: LodContext) -> Mapping[SubjectRef, DetailTier]: ...

class UniformPolicy(LodPolicy): ...      # 全体同档（默认）
class ManualPolicy(LodPolicy): ...       # 配置显式指派 + 默认档

class LodManager:                        # World 持有一个实例
    def register(self, domain: str, subject_id: str) -> SubjectRef: ...
    def evaluate(self, ctx) -> None      # tick 起点计算并缓存当轮档位
    def tier_of(self, subject_id) -> DetailTier
    def on_transition(self, ...)         # 档位变化时发事件（见 §4）
```

**域适配边界**（ADR 010 §2.2 硬约束）：

- 域在自身 `advance` 前注册主体，演化时按 `tier_of(id)` 选择**本域自己定义**的各档行为（如 wildlife：fine=逐个体，coarse=聚合池）；
- 内核**不提供**任何「粗档应该怎么算」的规则——那永远是域的知识；
- 兴趣目标与空间影响的**计算**同样在域/查询层，内核只定义其聚合接口（第一版预留，见 §7）。

## 4. 档位转换：不变量与事件

- 档位变化发 **`lod_tier_changed`** 事件：`{subject, old_tier, new_tier, cause}`；有状态语义（影响后续演化路径），**须补 `replay._on_lod_tier_changed`**，`pytest -k replay` 保持绿。
- **转换不变量（任务书 E2 硬口径）**：fine ↔ coarse 转换不得凭空增减种群、生物量、库存、能量、年龄或空间状态。内核无法检验域语义，故：
  - 内核职责：转换必经事件、事件必带 old/new、同 tick 幂等（无变化不发）；
  - 域职责：转换钩子内做守恒断言/重整（如 fine→coarse 聚合个体为池时计数守恒）；各域接入时（E3+）以专项测试证明。
- 快照投影：当轮档位表进快照（`lod` 节），回放时重建。

## 5. 确定性与调度

- 策略求值只用 `LodContext` 内容：同配置 + 同 seed + 同 LOD 策略 ⇒ 逐 tick 档位表一致 ⇒ 事件流一致（ADR 010 §4-5）。
- 评估时机：每 tick **调度循环起点**（PHASE_NATURAL 之前，逻辑上的 phase 0），保证各域 `advance` 看到的是本轮定案档位。Uniform/Manual 求值 O(1)/O(n) 查表，无性能顾虑。
- 随机性：策略内如需随机（本版不需要）只走 seeded `random.Random(ctx.seed + tick)`。

## 6. 配置草案（机制与内容分离）

世界配置新增可选节（缺省 = 不启用，**既有 profile 行为零变化**）：

```yaml
lod:
  policy: uniform        # uniform | manual   （adaptive 为 deferred，出现即报错）
  default_tier: normal   # uniform 档位 / manual 默认档
  assignments:           # manual 专用：主体类型或显式 ID → 档位
    - subjects: ["wildlife:deer"]
      tier: fine
```

- schema 同步：`config/schema` 增校验；未知 policy 名、非法档位名**启动即报错**。
- 生态阶段不配置 lod 节也能跑（隐含 uniform/normal）。

## 7. E2 最小实现范围与 deferred

**做**：`core/lod.py`（DetailTier、LodContext、UniformPolicy、ManualPolicy、LodManager）、`lod_tier_changed` 事件与渲染、replay 处理器、快照投影、配置 schema 与校验、门禁测试（§8）。

**显式登记 deferred**（出现在文档与代码注释，防误用）：

1. **AdaptivePolicy**（按兴趣/预算自动升降档）——预算接口 `BudgetHint` 本版只透传，不消费；
2. **兴趣目标与空间影响的多焦点聚合计算**——接口占位（`LodContext.interest` 留空字段），无实现；
3. **LOD 档位与调度频率联动**（粗档主体降频结算）——属域行为，待域接入时各自设计。

## 8. 门禁测试（E2 验收口径）

1. **三档可表达**：fixture 域主体可被指派 fine/normal/coarse 且 `tier_of` 正确；
2. **粗档不冻结**：coarse 档 fixture 主体在推进中仍产生事件、状态仍演化（证明契约不隐含「粗=停摆」）；
3. **转换守恒**：fixture 域计数在 fine↔coarse 往返前后不变（不变量的参考实现示例）；
4. **确定性**：同配置 + seed + 策略，两次运行档位表与事件流一致；
5. **内核域中立**：`core/lod.py` 无 `domains/` 导入、无任何域类型引用（静态检查并入架构闸）；
6. **缺省零影响**：无 lod 配置时，full/base_town/viz profile 事件流与基线一致（两年确定性基线测试不动）；
7. **坏配置报错**：未知 policy/非法 tier 启动即报错（专项测试）；
8. **渲染与回放**：`lod_tier_changed` 可读渲染、replay 全绿。

## 9. 待裁决项

| # | 事项 | 建议 |
|---|---|---|
| 1 | 档位命名 | `fine / normal / coarse`（三档枚举、字符串落配置） |
| 2 | 默认档位（无 lod 节时） | uniform + normal：既有 profile 零变化 |
| 3 | 评估时机 | 每 tick 起点全量求值（实现最简、确定性最强） |
| 4 | `lod_tier_changed` 是否入事件流 | 入（回放一致性优先；事件量在 manual/uniform 下极小） |
| 5 | BudgetHint 形状 | `dict[domain, int]` 透传，本版无消费方 |

## 10. 与既有文档的关系

- 归属：[kernel/](../00-overview.md)（E1 归位后内核视角子树）；ADR 010 §2.2 为上位依据；
- 域接入计划：E3（Environment 植被）、E4（Wildlife 种群）各自声明本域各档行为时回写「已落地」；本版不接入任何真实域。


## 10. 与地理数据分辨率的区别

**栅格数据分辨率不是 Simulation LOD。** 30 m、250 m、900 m 表示外部数据源的空间采样/像元尺度；fine、normal、coarse 表示模拟主体采用的计算细节档位。二者不存在默认一一对应关系：30 m 数据不意味着主体必须以 fine 档运行，coarse 档也不意味着把多个源数据像元无声明地重采样成一个值。GridSpace 契约见 [空间骨架 04-grid-space](../spatial-skeleton/04-grid-space.md)，上位决策见 ADR 011。
