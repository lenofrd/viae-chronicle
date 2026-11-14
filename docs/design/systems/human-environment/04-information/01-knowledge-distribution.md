# 知识分布

## 1. 目的
定义每个角色掌握哪些知识、掌握程度如何、如何获得新知识、如何遗忘。知识分布是信息不对称的基础。

## 2. 核心概念
- **知识条目**：一条可被掌握的信息，有唯一 ID、内容、类型、来源、可信度。
- **掌握程度**：角色对某条知识的相信程度（belief_level），0–1。
- **来源记忆**：角色记得这条知识从谁那里听来的、什么时候。
- **知识获取**：亲眼所见、亲耳所闻、他人转述、推理得出。
- **知识遗忘**：长期不提及、不验证，知识淡出记忆。
- **知识验证**：亲眼验证后 belief_level 上升；被证伪后 belief_level 下降。

## 3. 知识条目字段
| 字段 | 类型 | 说明 |
|---|---|---|
| info_id | string | 唯一 ID |
| info_type | enum | 事实/传闻/传说/外来消息 |
| content | string | 信息内容 |
| source_agent | string? | 最初来源，外部消息为 null |
| source_event | string? | 产生这条信息的事件 ID |
| credibility | float 0–1 | 初始可信度 |
| created_tick | int | 产生 tick |
| distortion_level | float 0–1 | 当前变形程度 |

## 4. 角色知识状态
| 字段 | 类型 | 说明 |
|---|---|---|
| agent_id | string | 角色 ID |
| known_items | list | 掌握的知识条目 ID 列表 |
| belief_level | dict | info_id → 相信程度 0–1 |
| source_memory | dict | info_id → {source_agent, learned_tick} |

## 5. 演化规则

### 5.1 知识获取：亲眼所见
```
条件：角色在场目睹事件
效果：生成对应知识条目（若是新信息）
      角色 belief_level = 1.0（亲眼所见）
      source_memory 记录“亲眼所见”
      生成 information_learned 事件
滞后：无
影响范围：在场角色
```

### 5.2 知识获取：他人转述
```
条件：角色从他人处听到信息
效果：角色获得知识条目（或更新已有条目）
      belief_level 受来源 trust 和 credibility 影响
      belief_level = credibility * trust_factor(source)
      source_memory 记录来源和 tick
      生成 information_learned 事件
滞后：无
影响范围：接收角色
```

### 5.3 知识获取：推理得出
```
条件：角色根据已有知识推理出新结论
效果：生成新知识条目（标记为推理来源）
      belief_level 受推理链可信度影响
      生成 information_learned 事件
滞后：推理需要时间
影响范围：推理角色
```

### 5.4 知识验证与证伪
```
条件：角色亲眼验证某条知识
效果：验证 → belief_level = 1.0，生成 information_verified
      证伪 → belief_level 大幅下降，生成 information_falsified
      可能传播验证/证伪结果
滞后：按验证时机
影响范围：验证角色及传播网络
```

### 5.5 知识遗忘
```
条件：长期不提及、不验证、不传播
效果：belief_level 缓慢衰减
      低于遗忘阈值后从 known_items 移除
      生成 information_forgotten 事件
滞后：长期过程
影响范围：角色
```

### 5.6 知识不对称
```
条件：不同角色掌握不同知识
效果：信息不对称影响决策和拉扯
      知道多的人有信息优势
      信息优势影响地位和议价能力
      见 06-stratification
滞后：无
影响范围：角色之间
```

## 6. 事件类型
- `information_created`：{info_id, info_type, content, source_agent, credibility}
- `information_learned`：{agent_id, info_id, source_agent, belief_level}
- `information_verified` / `information_falsified`：{info_id, agent_id, evidence}
- `belief_level_changed`：{agent_id, info_id, old, new, cause}
- `information_forgotten`：{agent_id, info_id, cause}

## 7. 与其他系统的接口
- 读：人物系统的感知事件；01-social-spaces 的在场人物；03-relationships 的 trust。
- 写：02-rumors 的传播；人物系统读 known_items 做决策；06-stratification 的信息优势；05-education 的知识传递。
- 因果链：目睹旱情 → 知识形成 → 传播给邻居 → 邻居 belief_level 上升 → 做出应对决策。

## 8. 地点参数占位
- 初始知识分布
- belief_level 的计算系数（credibility、trust_factor）
- 遗忘阈值和衰减速率
- 推理链的可信度规则