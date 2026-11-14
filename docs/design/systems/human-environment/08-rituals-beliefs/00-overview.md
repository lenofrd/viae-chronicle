# 仪式与信仰子系统总览

## 1. 目的
定义 Brookvale 的仪式与信仰：祭祖、祭山神、节庆、婚丧嫁娶、禁忌认知。仪式塑造世界观、支撑制度合法性、提供心理安慰、凝聚社区，也是冲突的潜在来源（仪式分歧、禁忌冒犯）。

## 2. 核心概念
- **仪式**：按固定周期或特定场合举行的集体活动，有场所、参与者、角色分工、流程。
- **信仰**：对山神、祖先、禁忌的相信程度，影响行为和心理。
- **禁忌认知**：角色对“什么不能碰”的认知和内化程度。
- **仪式功能**：教育（传递信仰和规矩）、凝聚（强化社区纽带）、安慰（缓解恐惧和焦虑）、合法化（支撑制度和权威）。
- **仪式分歧**：谁主持、谁出钱、流程怎么走、谁能参加，都可能引发分歧。
- **仪式与自然环境**：山神仪式与山林、河流、灾害绑定；祭祖与土地、继承绑定。
- **仪式与心理**：仪式提供心理安慰，灾害后仪式缓解恐惧。

## 3. 仪式类型与功能
| 仪式 | 周期 | 场所 | 主要功能 | 潜在冲突 |
|---|---|---|---|---|
| 祭祖 | 清明/冬至/忌日 | 祠堂/祖坟 | 凝聚宗族、确认继承、传递价值观 | 谁主持、谁出钱、继承争议 |
| 祭山神 | 春耕前/秋收后/灾害后 | 山神庙/山口 | 祈求丰收、缓解灾害恐惧、强化禁忌 | 祭品分摊、仪式流程、禁忌解释 |
| 节庆 | 春节/端午/中秋 | 祠堂/集市/各家 | 凝聚社区、信息交换、婚配机会 | 谁家办、谁参加、排场攀比 |
| 婚丧嫁娶 | 按事件 | 各家/祠堂 | 确认关系、传递规矩、社区参与 | 彩礼、排场、谁坐主位 |
| 禁忌实践 | 日常/特定日子 | 各处 | 约束行为、传递世界观 | 禁忌解释分歧、违反后的惩罚 |

## 4. 状态变量（按角色和仪式挂载）
| 变量 | 类型 | 说明 | 变化速率 |
|---|---|---|---|
| belief_strength | float 0–1 | 对山神/祖先/禁忌的相信程度 | 慢变 |
| taboo_internalization | dict | 对各禁忌的内化程度 | 慢变 |
| ritual_participation_history | list | 仪式参与记录 | 只追加 |
| ritual_role | enum? | 在仪式中的角色（主持/参与/旁观/缺席） | 事件驱动 |
| ritual_attitude | enum | 虔诚/应付/怀疑/反感 | 慢变 |
| community_bond | float 0–1 | 通过仪式强化的社区纽带 | 渐进 |

> ritual_attitude 为角色级慢变量（对仪式的整体态度），在 ritual_participation 事件中以 attitude 字段记录当次取值，不是仪式实例的固定字段。

## 5. 演化规则分类
- tick 驱动：信仰随年龄和经历缓慢变化；社区纽带随仪式频率变化。
- 事件驱动：仪式举行、参与、缺席、分歧、禁忌违反。
- 累积效应：多次仪式参与 → 信仰强化、纽带强化；多次缺席 → 纽带弱化、被议论。
- 外部注入：接口写入的仪式事件（如“外来祭司主持仪式”），标注为外部事件。

## 6. 事件类型
- `ritual_scheduled`：{ritual_id, ritual_type, tick, location, organizer}
- `ritual_started` / `ritual_ended`：{ritual_id, participants, roles}
- `ritual_participation`：{ritual_id, agent_id, role, attitude}
- `ritual_absent`：{ritual_id, agent_id, reason}
- `ritual_dispute`：{ritual_id, parties, dispute_area, outcome}
- `belief_strength_changed`：{agent_id, belief_type, old, new, cause}
- `taboo_internalization_changed`：{agent_id, taboo_id, old, new, cause}
- `community_bond_changed`：{community_id, old, new, cause}

> 禁忌认知子文件另声明专有事件：taboo_cognition_formed、taboo_violated、psychological_effect、taboo_support_institution（见 `05-taboo-cognition.md`），本表只列通用仪式事件。

## 7. 与其他系统的接口
- 读：
  - 01-social-spaces：祠堂、山神庙、集市是仪式场所。
  - 02-institutions：仪式支撑制度合法性；禁忌是制度的一部分。
  - 03-relationships：仪式强化或改变关系。
  - 04-information：传说和故事是仪式的叙事基础。
  - 05-education：仪式是信仰教育的一部分。
  - 自然环境：`08-hazards` 灾害后仪式、`02-climate` 季节仪式。
- 写：
  - 02-institutions：仪式支撑禁忌和制度。
  - 05-education：仪式传递信仰和规矩。
  - 03-relationships：共同仪式强化关系；仪式分歧恶化关系。
  - 07-conflicts：仪式分歧和禁忌冒犯触发冲突。
  - 人物系统：提供信仰、禁忌认知、心理安慰，作为决策和情绪输入。
- 因果链：山洪灾害 → 祭山神仪式 → 信仰强化 → 禁忌内化 → 神树保护 → 灾害减少（或传说继续）。

## 8. 地点参数占位
具体地点（如 Brookvale）需要提供：
- 仪式清单和周期
- 各仪式的场所、参与者、角色分工、流程
- 祭品和费用分摊规则
- 信仰和禁忌的初始分布
- 仪式分歧的触发条件和解决方式
- 灾害后仪式的触发规则

## 9. 扩展预留
- 新仪式（如求雨、驱邪、建房仪式）：作为新文件扩展。
- 外来信仰（如外来宗教）：作为外部注入事件，第一版不做。
- 信仰冲突（两种信仰竞争）：作为扩展，第一版只做单一信仰体系。
- 仪式与政治的耦合（仪式主持权与权力）：作为 06-stratification 的扩展。

## 10. 横切机制引用

- 变化速率上限、滞后与累积、空间传播、可逆性规则见 `09-dynamics/`。
- 事件记录、快照结构、查询接口遵循 `10-state-and-records/`。
- 本子系统所有状态变化事件按 `10-state-and-records/event-stream.md` 的统一格式记录。