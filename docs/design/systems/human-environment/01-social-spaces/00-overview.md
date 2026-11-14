# 社会空间子系统总览

## 1. 目的
定义 Brookvale 小镇的建筑节点和场所的人文属性：功能、社会意义、状态、在场人物、正在发生的事。定义公共空间、私人空间、半公共空间的区分，以及人物在不同场所之间移动时的社会约束。

## 2. 核心概念
- **建筑节点**：有名字、有位置、有功能、有状态的场所，是人物行动的物理依托。
- **场所的社会意义**：每个场所规定“什么行为合适、什么话能说、什么人在场”。
- **公共空间**：祠堂、水井、集市空地、山神庙。信息公开流动，舆论公开形成，规则公开执行。
- **私人空间**：住家、私家田地、私家作坊。信息被保守，关系被私下经营。
- **半公共空间**：磨坊、药铺、私塾。有门槛，信息选择性传播。
- **场所状态**：建筑是否完好、是否开放、当前谁在场、正在发生什么。
- **移动的社会约束**：人物去某场所是否合适、是否需要身份许可、是否会被议论。

## 3. 状态变量（按建筑节点挂载）
| 变量 | 类型 | 说明 | 变化速率 |
|---|---|---|---|
| condition | enum | 完好/受损/废弃 | 事件驱动 |
| openness | enum | 开放/受限/关闭 | 事件驱动 |
| current_occupants | list | 当前在场人物 ID | 每 tick 更新 |
| ongoing_activity | string? | 正在发生的事（如“祭祖”“议事”“磨坊加工”） | 每 tick 更新 |
| social_significance | dict | 本场所的行为规范、禁忌、适合话题 | 固定，由地点参数提供 |
| access_rules | dict | 谁能进、什么时候能进、需要什么条件 | 固定，由地点参数提供 |
| reputation_tag | enum | 场所的社会标签（如“被罚过的地方”“说亲常去的地方”） | 事件驱动，慢变 |

> 公共空间专有状态（information_flow_rate、opinion_formation_rate、behavior_norms、typical_topics、current_discussions 等）见 `02-public-spaces.md`；私人空间专有状态（owner_id、intimacy_levels、information_privacy 等）见 `03-private-spaces.md`，本表只汇总建筑节点级通用变量。

## 4. 演化规则分类
- tick 驱动：current_occupants 每 tick 更新；ongoing_activity 随在场人物和时段变化。
- 事件驱动：建筑状态变化（损坏/修复）、开放状态变化、reputation_tag 变化。
- 累积效应：多次事件在同一场所发生，形成场所的社会标签。
- 外部注入：接口写入的场所事件（如“祠堂被雷击”），标注为外部事件。

## 5. 事件类型
- `building_condition_changed`：{building_id, old, new, cause}
- `building_openness_changed`：{building_id, old, new, cause}
- `occupants_changed`：{building_id, old_list, new_list}
- `activity_started` / `activity_ended`：{building_id, activity, participants}
- `reputation_tag_changed`：{building_id, old, new, cause}
- `space_access_denied`：{agent_id, building_id, reason}

> 空间移动相关事件（movement_intent_formed、movement_completed、movement_failed、arrival）见 `04-movement-between.md`，本表只列场所状态事件。

## 6. 与其他系统的接口
- 读：
  - 自然环境 `01-spatial-skeleton`：空间单元定义（建筑节点挂在空间骨架上）。
  - 02-institutions：制度规定哪些场所执行什么规则。
  - 03-relationships：关系状态影响人物在场所中的行为。
  - 04-information：信息在场所中流动。
  - 08-rituals-beliefs：仪式在特定场所举行。
- 写：
  - 02-institutions：场所是制度执行的物理依托。
  - 03-relationships：场所是关系发生的地点。
  - 04-information：公共空间是信息流动的通道。
  - 08-rituals-beliefs：祠堂、山神庙是仪式的场所。
  - 人物系统：提供场所状态、在场人物、社会意义，作为决策输入。
  - 记录系统：场所事件作为人物一生的场景锚点。
- 因果链：场所状态变化 → 人物行为改变 → 关系和信息变化 → 场所社会标签变化。

## 7. 地点参数占位
具体地点（如 Brookvale）需要提供：
- 建筑节点清单：ID、名称、类型、位置、功能、初始状态
- 每个场所的社会意义：行为规范、禁忌、适合话题
- 每个场所的 access_rules：谁能进、什么时候能进、需要什么条件
- 公共/私人/半公共分类
- 场所之间的连接和移动时间
- reputation_tag 的初始值和变化条件

## 8. 扩展预留
- 新建筑类型（如学堂、客栈、码头）：作为建筑节点扩展。
- 场所扩建/改建：作为事件扩展，改变建筑属性和社会意义。
- 多地点场所网络：城市作为新地点，场所结构扩展。
- 场所的动态生成（如临时集市、临时祭坛）：作为事件驱动的临时场所，第一版不做。

## 9. 横切机制引用

- 变化速率上限、滞后与累积、空间传播、可逆性规则见 `09-dynamics/`。
- 事件记录、快照结构、查询接口遵循 `10-state-and-records/`。
- 本子系统所有状态变化事件按 `10-state-and-records/event-stream.md` 的统一格式记录。