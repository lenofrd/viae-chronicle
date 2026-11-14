# 信息子系统总览

## 1. 目的
定义 Brookvale 的信息环境：谁知道什么、信息如何沿关系网络传播、谣言如何变形、收成传闻如何影响决策、山神传说如何塑造认知、外来消息如何进入。信息不对称是人物决策和拉扯的重要输入。

## 2. 核心概念
- **知识条目**：一条可被角色掌握的信息，有内容、来源、可信度、传播范围。
- **知识分布**：每个角色掌握哪些知识条目，掌握程度如何。
- **传播路径**：信息沿关系边传播，受信任度、互动频率、场所影响。
- **传播变形**：信息在多轮传播中可能失真、夸大、扭曲。
- **可信度**：角色对某条信息的相信程度，受来源、关系、既有认知影响。
- **信息类型**：事实（收成、水位）、传闻（谣言、猜测）、传说（山神、祖辈故事）、外来消息。
- **信息不对称**：不同角色知道的事不一样，这是拉扯和冲突的重要来源。

## 3. 状态变量（按角色和知识条目挂载）
| 变量 | 类型 | 说明 | 变化速率 |
|---|---|---|---|
| known_items | list | 角色掌握的知识条目 ID | 事件驱动 |
| belief_level | dict | 对每条知识的相信程度 0–1 | 渐进 |
| source_memory | dict | 每条知识的来源和获取 tick | 只追加 |
| information_type | enum | 事实/传闻/传说/外来消息 | 固定 |
| content | string | 信息内容 | 传播中可变 |
| credibility | float 0–1 | 信息本身的初始可信度 | 固定 |
| spread_scope | list | 已传播到的角色 | 事件驱动 |
| distortion_level | float 0–1 | 传播中的变形程度 | 累积 |

> 本表混合挂载维度：known_items、belief_level、source_memory 为角色级；information_type、content、credibility、spread_scope、distortion_level 为知识条目级。谣言传播速度（spread_velocity）见 `02-rumors.md`。

## 4. 演化规则分类
- tick 驱动：belief_level 随时间衰减（久未验证的信息可信度下降）；长期无传播的信息淡出记忆。
- 事件驱动：信息产生、传播、变形、验证、证伪。
- 累积效应：多人多次传播 → 信息扩散 → 变形累积 → 舆论形成。
- 外部注入：接口写入的信息事件（如“外来消息”），标注为外部事件。

## 5. 事件类型
- `information_created`：{info_id, info_type, content, source_agent, credibility}
- `information_learned`：{agent_id, info_id, source_agent, belief_level}
- `information_spread`：{info_id, from_agent, to_agent, tick, distortion}
- `information_distorted`：{info_id, old_content, new_content, distortion_level}
- `information_verified` / `information_falsified`：{info_id, agent_id, evidence}
- `belief_level_changed`：{agent_id, info_id, old, new, cause}
- `information_forgotten`：{agent_id, info_id, cause}

> 谣言传播相关事件（spread_velocity_changed 等）见 `02-rumors.md`，本表只列通用信息事件。

## 6. 与其他系统的接口
- 读：
  - 03-relationships：关系路径决定传播范围和速度；trust 影响信息采信度。
  - 01-social-spaces：公共空间是信息流动的通道；私人空间信息被保守。
  - 02-institutions：制度执行产生信息（谁被罚、谁违规）。
  - 自然环境：`03-hydrology` 水位、`05-soil-and-fields` 地力、`08-hazards` 灾害产生事实信息。
- 写：
  - 03-relationships：信息传播改变信任和关系。
  - 07-conflicts：谣言和传闻可以激化冲突。
  - 05-education：信息经验是教育的一部分。
  - 06-stratification：信息优势影响地位。
  - 人物系统：提供角色掌握的信息，作为决策输入。
  - 交互系统（interaction）：提供双方掌握的信息差，作为拉扯的输入。
- 因果链：收成差 → 事实信息传播 → 借粮传闻 → 债权人收紧借贷 → 债务人关系恶化 → 冲突。

## 7. 地点参数占位
具体地点（如 Brookvale）需要提供：
- 初始知识分布：哪些角色知道哪些事
- 信息类型和初始可信度
- 传播速度系数（按关系类型、场所类型）
- 变形概率和变形类型
- 可信度衰减速率
- 传说和外来消息的初始内容

## 8. 扩展预留
- 新信息类型（如书信、告示、密语）：作为 enum 扩展。
- 群体信息（家族共有知识、全村共识）：作为扩展，第一版只做个体知识。
- 信息网络分析（谁掌握最多信息、信息瓶颈）：作为查询扩展。
- 跨镇信息传播：作为多地点扩展，第一版外来消息只做低频注入。

## 9. 横切机制引用

- 变化速率上限、滞后与累积、空间传播、可逆性规则见 `09-dynamics/`。
- 事件记录、快照结构、查询接口遵循 `10-state-and-records/`。
- 本子系统所有状态变化事件按 `10-state-and-records/event-stream.md` 的统一格式记录。