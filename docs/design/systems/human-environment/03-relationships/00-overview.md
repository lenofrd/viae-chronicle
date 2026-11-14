# 关系子系统总览

## 1. 目的
定义角色之间的关系网络：亲缘、邻里、债务、恩怨、信任和利益权重。关系是人物交互的先验，决定同一句话、同一个请求在不同关系下产生不同效果。

## 2. 核心概念
- **关系边**：两个角色之间的关系，有方向（A→B 和 B→A 可以不同）、类型、强度、历史。
- **关系类型**：亲缘、邻里、债务、恩怨、师徒、雇佣、婚约。
- **信任度**：A 对 B 的信任程度，-1 到 1，负值表示怀疑或敌意。
- **利益权重**：A 认为与 B 的交往对自己利益的重要程度，0 到 1。
- **关系强度**：关系的紧密程度，0 到 1，影响互动频率和信息传播。
- **关系历史**：形成关系的关键事件序列，是关系变化的因果依据。
- **不对称性**：A 对 B 的信任不等于 B 对 A 的信任；A 欠 B 的人情不等于 B 欠 A 的。

## 3. 状态变量（按关系边挂载）
| 变量 | 类型 | 说明 | 变化速率 |
|---|---|---|---|
| relation_type | enum | 亲缘/邻里/债务/恩怨/师徒/雇佣/婚约 | 事件驱动 |
| trust | float -1–1 | A 对 B 的信任 | 渐进，单次事件变化有限 |
| interest_weight | float 0–1 | A 认为与 B 交往的利益重要度 | 渐进 |
| strength | float 0–1 | 关系紧密程度 | 渐进 |
| obligation | float | 人情债/义务（正= A 欠 B，负= B 欠 A） | 事件驱动 |
| history | list | 关键事件序列 | 只追加 |
| last_interaction_tick | int? | 上次互动 tick | 事件驱动 |

> `trust_trend`、`interest_trend` 由 `05-trust-and-interest.md` 维护，本表只汇总关系边通用变量。

## 4. 演化规则分类
- tick 驱动：长期无互动，strength 缓慢衰减；obligation 随时间压力上升（欠人情越久越不安）。
- 事件驱动：帮助、背叛、借还、冲突、婚嫁、分家等事件改变 trust、obligation、relation_type。
- 累积效应：多次小帮助累积成信任；多次小摩擦累积成恩怨。
- 外部注入：接口写入的关系事件（如“外来者与某人有旧交”），标注为外部事件。

## 5. 事件类型
- `relation_formed`：{from_agent, to_agent, relation_type, cause}
- `relation_ended`：{from_agent, to_agent, relation_type, cause}
- `trust_changed`：{from_agent, to_agent, old, new, cause}
- `interest_weight_changed`：{from_agent, to_agent, old, new, cause}
- `strength_changed`：{from_agent, to_agent, old, new, cause}
- `obligation_changed`：{from_agent, to_agent, old, new, cause}
- `interaction_occurred`：{from_agent, to_agent, interaction_type, outcome, scene}

## 6. 与其他系统的接口
- 读：
  - 01-social-spaces：互动发生在特定场所，场所的社会意义影响关系变化。
  - 02-institutions：制度执行影响关系（惩罚、包庇、调解）。
  - 04-information：信息传播依赖关系路径。
  - 05-education：家庭和师徒关系是教育通道。
  - 07-conflicts：冲突改变关系。
  - 06-stratification：地位差异影响关系中的权力不对等。
  - 08-rituals-beliefs：共同仪式强化关系，仪式分歧恶化关系。
  - 人物系统：人物行动产生关系事件。
- 写：
  - 04-information：关系路径决定信息传播范围和速度。
  - 05-education：亲缘和师徒关系是教育的主要通道。
  - 07-conflicts：关系恶化触发冲突；冲突结果改变关系。
  - 06-stratification：关系网络影响地位和流动机会。
  - 人物系统：提供信任、利益权重、义务，作为决策和拉扯的输入。
  - 交互系统（interaction）：提供 trust、interest_weight、obligation，作为交涉的先验和门槛。
- 被写：交互系统（interaction）的会话结果产生 trust_changed / obligation_changed 事件写入本系统（达成、破裂、违约、补偿）。
- 因果链：帮助事件 → trust 上升 → 未来拉扯中更容易被说服；背叛事件 → trust 下降 → 未来拉扯中言语效果打折。

## 7. 地点参数占位
具体地点（如 Brookvale）需要提供：
- 角色清单和初始关系网络（谁和谁什么关系、初始 trust/interest/strength/obligation）
- 各关系类型的初始参数
- trust、interest、strength 的变化速率上限
- obligation 的压力系数
- 关系形成和结束的条件

## 8. 扩展预留
- 新关系类型（如商业合伙、政治同盟）：作为 enum 扩展。
- 群体关系（家族对家族、群体对群体）：作为关系边扩展，第一版只做个体对个体。
- 关系网络分析（中心度、派系）：作为查询扩展，第一版不做。
- 跨世界关系迁移：作为扩展，第一版不做。

## 9. 横切机制引用

- 变化速率上限、滞后与累积、空间传播、可逆性规则见 `09-dynamics/`。
- 事件记录、快照结构、查询接口遵循 `10-state-and-records/`。
- 本子系统所有状态变化事件按 `10-state-and-records/event-stream.md` 的统一格式记录。