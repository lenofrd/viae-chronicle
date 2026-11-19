# 人物系统总览

## 1. 目的
定义模拟中“人”的构成：生理状态（含性别与生育）、心理状态、认知记忆、需求动机、决策机制、行动类型。人物系统是自然环境、人文环境和交互系统之间的枢纽。

## 2. 核心原则
- **自主性**：人物按内部逻辑和感知到的环境自主行动。
- **有限理性**：人物只能感知局部环境，基于主观认知和情绪做决策，允许误判。
- **性别与社会角色**：性别不仅是生理标签，还决定了劳动分工、继承权、社会期望。角色在成长中内化这些期望，并可能在个人意愿与社会期望之间产生冲突。
- **事件驱动**：所有人物状态的变化、行动的产生，都必须挂载因果事件。

## 3. 模块划分与依赖
```text
感知 (从自然/人文环境读取)
  ↓
认知与记忆 (更新主观认知，含性别规范)
  ↓
心理与生理 (情绪、压力、需求、怀孕/衰老)
  ↓
决策 (需求评估 -> 社会规范校验 -> 行动选择)
  ↓
行动 (写入行动事件，修改环境)
```

- **01-physical-state.md**：年龄、性别、体力、健康、饥饿、生育周期。
- **02-psychological-state.md**：情绪、压力、动机优先级、性别角色内化压力。
- **03-cognition-and-memory.md**：知道什么、记得谁、性别期望认知。
- **04-needs-and-utility.md**：需求层次与效用计算（含社会规范惩罚）。
- **05-decision-making.md**：如何选择目标，如何选择行动。
- **06-actions.md**：人物能执行的具体动作清单（区分社会期望与越轨行为）。
- **09-dynamics.md**：习惯化、衰老、性别观念的代际演变。
- **10-state-and-records.md**：人物快照与人生事件流。
- **11-life-course.md**：家庭经济模型、出生、年龄分段、继承、分家与死因；保留任务 12 历史实现记录。
- **12-population-and-marriage.md**：人口资源承载、认知参与婚姻、从夫居、彩礼、陪嫁与家庭财产边界（ADR 007）。
- **家庭协作与生存保障**：家庭照料、协商分工、营养饮食、自愿公共储备与救济申请（ADR 008；实现复用 HouseholdState、AgentState、亲缘关系、治理与事件系统）。

## 4. 状态变量总表（按角色挂载）
| 模块 | 典型变量 | 变化速率 |
|---|---|---|
| 生理 | sex, age, stamina, health, hunger, pregnancy_stage | 快（天）与慢（年） |
| 心理 | stress, fear, valence, role_conflict_pressure | 渐进，按事件 |
| 认知 | knowledge_set, beliefs, gender_norms | 事件驱动 |
| 需求 | current_needs (字典), utility_scores | 每 tick 评估 |

## 5. 事件类型总表
| 事件 | 产生模块 | 说明 |
|---|---|---|
| `action_executed` | 05 / 06 | 人物执行动作，带 agent_id、动作与因果指向，更新环境并被记录系统捕获 |
| `death` | 01 | 人物死亡，触发丧葬、继承 |
| `pregnancy_started` / `birth` | 01 | 生育周期事件（仅 female），伴随体力限制与分娩风险 |
| `cognitive_dissonance` | 03 | 新信息与内化性别规范冲突，推高角色冲突压力 |
| `role_conflict_surged` | 02 | 角色冲突压力超阈值，可能放弃行动或叛逆执行 |
| `firewood_gathered` / `herb_gathered` | 06 → 06-vegetation | 采集动作写入自然环境资源点，影响存量与采集压力 |
| `raise_livestock` / `graze` / `use_ox` / `slaughter` | 06 → 11-livestock | 家畜动作写入人文环境家畜资产，繁衍/损耗走 `wealth_changed` |

## 6. 与其他系统的接口
- **读**：自然环境状态、人文环境制度、社会规范、关系网络。
- **写**：自然环境（劳作、采集）、人文环境（交互、冲突）、记录系统。
- **扩展预留**：决策模块预留 LLM 旁路；性别观念随外部冲击（如外来文化）演变的接口。

## 7. 第一版范围
- 生理：性别、饥饿、体力、健康、年龄、基础怀孕机制。
- 心理：压力、恐惧、角色冲突压力。
- 认知：知道的事、对周围人的态度、内化的性别规范。
- 需求：生存、安全、经济、社交。
- 决策：效用打分制，叠加社会规范成本。

## 8. 横切机制引用
- 变化速率与滞后见 [09-dynamics.md](file:///f:/viae-chronicle/docs/design/systems/agents/09-dynamics.md)。
- 状态记录与快照遵循 [10-state-and-records.md](file:///f:/viae-chronicle/docs/design/systems/agents/10-state-and-records.md)。
- 家庭经济单位、出生、继承、分家与死因的历史实现见 [11-life-course.md](11-life-course.md)；当前人口承载与婚姻规范见 [12-population-and-marriage.md](12-population-and-marriage.md)。
- 家庭协作、饮食营养、公共储备和救济见 [ADR 008](../../decisions/008-household-coordination-nutrition-and-voluntary-reserves.md)。
