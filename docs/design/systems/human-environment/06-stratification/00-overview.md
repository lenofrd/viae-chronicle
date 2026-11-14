# 阶层与流动子系统总览

## 1. 目的
定义 Brookvale 的地位、角色、向上流动通道、向外的接口、向上/向外意图。第一版聚焦终生留在小镇的人：他们知道通道存在，可能尝试过、犹豫过、放弃过，但一生在镇内完成。

## 2. 核心概念
- **地位**：角色在社区中的相对位置（贫户、自耕农、富户、工匠、里正、长老）。
- **角色**：角色承担的社会身份（农夫、织户、木匠、郎中、货郎、学徒）。
- **向上通道**：从低地位向高地位流动的路径（学手艺、联姻、争里正、买田、识字）。
- **向外接口**：离开小镇的通道（外出求学、投亲、做工、参军、婚嫁外迁）。
- **向上/向外意图**：角色想不想往上走、想不想离开，以及为什么。
- **意图与行动**：第一版只记录意图和镇内结果（尝试拜师、尝试说亲、想走但没走），不执行实际离开。
- **地位与关系**：地位影响关系中的权力不对等；关系影响流动机会。

## 3. 状态变量（按角色挂载）
| 变量 | 类型 | 说明 | 变化速率 |
|---|---|---|---|
| status | enum | 贫户/自耕农/富户/工匠/里正/长老 | 事件驱动，慢变 |
| roles | list | 承担的社会角色 | 事件驱动 |
| wealth | float | 财产水平（粮、田、钱） | 按事件 |
| reputation | float | 社区声誉 | 渐进 |
| upward_aspiration | float 0–1 | 向上意图强度 | 慢变 |
| outward_aspiration | float 0–1 | 向外意图强度 | 慢变 |
| aspiration_reason | string? | 意图的原因 | 事件驱动 |
| blocked_attempts | list | 尝试失败记录 | 只追加 |

## 4. 演化规则分类
- tick 驱动：wealth 随收成和支出变化；reputation 随日常行为缓慢变化；aspiration 随处境和认知缓慢变化。
- 事件驱动：技能提升、婚配、继承、争里正、尝试拜师、想走但没走。
- 累积效应：多次尝试失败 → aspiration 变化（放弃或更强）；多次成功 → 地位上升。
- 外部注入：接口写入的流动事件（如“外来招工”），标注为外部事件。

## 5. 事件类型
- `status_changed`：{agent_id, old, new, cause}
- `role_gained` / `role_lost`：{agent_id, role, cause}
- `wealth_changed`：{agent_id, old, new, cause}
- `reputation_changed`：{agent_id, old, new, cause}
- `aspiration_changed`：{agent_id, type, old, new, cause}
- `upward_attempt`：{agent_id, channel, outcome, cause}
- `outward_attempt`：{agent_id, channel, outcome, cause}
- `aspiration_abandoned`：{agent_id, type, reason}

> 各子文件另声明专有事件：channel_identified、channel_competition、channel_rule_changed（`02-upward-channels.md`）；outward_info_gathered、aspiration_maintained（`03-outward-interfaces.md` / `04-aspiration.md`），本表只列通用地位与意图事件。

## 6. 与其他系统的接口
- 读：
  - 05-education：技能和价值观影响流动机会。
  - 03-relationships：关系网络影响流动机会。
  - 02-institutions：制度定义地位和流动规则。
  - 04-information：外来消息影响向外意图。
  - 自然环境：`05-soil-and-fields` 收成、`08-hazards` 灾害影响财富和地位。
  - 07-conflicts：冲突结果影响地位和声誉。
- 写：
  - 03-relationships：地位影响关系中的权力不对等。
  - 07-conflicts：阶层差异和流动受阻触发冲突。
  - 人物系统：提供 aspiration 和 blocked_attempts，影响决策和心理。
  - 记录系统：流动意图和尝试作为人生暗线。
- 因果链：想学手艺 → 家里缺劳力不让 → 偷偷学 → 被发现 → 家庭冲突 → 意图受挫 → 可能放弃或更强。

## 7. 地点参数占位
具体地点（如 Brookvale）需要提供：
- 地位层级和定义
- 角色清单和获取条件
- 向上通道清单和门槛
- 向外接口清单和门槛
- 初始角色的 status、wealth、reputation
- aspiration 的初始值和影响因素
- 尝试成功/失败的概率

## 8. 扩展预留
- 新地位层级（如士绅、官员）：作为 enum 扩展。
- 新向上通道（如科举、经商）：作为通道扩展。
- 实际离开（执行向外）：第一版只记录意图，预留执行接口。
- 跨镇流动：作为多地点扩展，第一版不做。

## 9. 横切机制引用

- 变化速率上限、滞后与累积、空间传播、可逆性规则见 `09-dynamics/`。
- 事件记录、快照结构、查询接口遵循 `10-state-and-records/`。
- 本子系统所有状态变化事件按 `10-state-and-records/event-stream.md` 的统一格式记录。