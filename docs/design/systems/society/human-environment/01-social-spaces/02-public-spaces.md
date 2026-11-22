# 公共空间

## 1. 目的
定义公共空间的特点、功能、信息流动规则、舆论形成机制，以及公共空间如何影响人物行为。

## 2. 核心概念
- **公共空间**：祠堂、水井、集市空地、山神庙。所有人可进入（或大部分时间可进入）。
- **信息公开**：在公共空间发生的事，在场的人都能感知，信息传播快。
- **舆论形成**：多人议论、多次事件累积，形成社区舆论。
- **规则公开执行**：惩罚、议事、仪式在公共空间举行，具有公开性和示范性。
- **行为约束**：公共空间对行为有更强的规范要求，失态会被围观和议论。

## 3. 公共空间字段
| 字段 | 类型 | 说明 |
|---|---|---|
| space_id | string | 唯一 ID |
| space_type | enum | 祠堂/水井/集市/山神庙 |
| openness | enum | 开放/受限/关闭 |
| information_flow_rate | float | 信息传播速度 |
| opinion_formation_rate | float | 舆论形成速度 |
| behavior_norms | list | 行为规范（如“不得大声喧哗”“祭祖时不得穿鞋”） |
| typical_topics | list | 适合讨论的话题 |
| taboo_topics | list | 禁忌话题 |
| current_occupants | list | 当前在场人物 |
| current_discussions | list | 当前正在议论的话题 |

## 4. 公共空间类型示例
| 空间 | 信息流动 | 舆论形成 | 行为规范 | 典型话题 |
|---|---|---|---|---|
| 祠堂 | 中（仪式和议事时） | 高（公开惩罚和议事） | 严格 | 宗族事务、惩罚、婚丧 |
| 水井 | 高（日常高频） | 中（闲聊传谣） | 宽松 | 家常、收成、婚嫁、传闻 |
| 集市空地 | 高（定期聚集） | 中（买卖闲聊） | 中等 | 买卖、收成、外来消息 |
| 山神庙 | 低（节庆时高） | 低 | 严格 | 祭祀、禁忌、求签 |

## 5. 演化规则

### 5.1 信息传播
```
条件：公共空间有事件发生或有话题被讨论
效果：信息传播给在场人物
      传播速度受 information_flow_rate 影响
      在场人物多，传播范围广
滞后：信息传播需要人际接触，不瞬移
影响范围：公共空间及在场人物
```

### 5.2 舆论形成
```
条件：同一话题被多人多次讨论
效果：opinion_formation_rate 累积
      超过阈值后形成社区舆论
      舆论影响人物判断和关系
滞后：多次议论后形成
影响范围：公共空间及社区
```

### 5.3 公开执行
```
条件：制度执行、惩罚、仪式在公共空间举行
效果：在场人物都感知到
      行为规范和后果被公开示范
      参与者心理状态变化（畏惧、认同、反感）
滞后：无
影响范围：公共空间及在场人物
```

### 5.4 行为约束
```
条件：人物在公共空间行动
效果：行为受 behavior_norms 约束
      违反规范可能触发围观、议论、惩罚
      生成行为约束事件
滞后：无
影响范围：人物和公共空间
```

### 5.5 话题流动
```
条件：每 tick，公共空间有在场人物
效果：current_discussions 更新
      话题来自人物当前关心的事、近期事件、传闻
      生成 discussion_started / discussion_ended 事件
滞后：无
影响范围：公共空间及在场人物
```

## 6. 事件类型
- `information_spread`：{space_id, topic, from_agent, to_agents, cause}
- `opinion_formed`：{space_id, topic, stance, participants}
- `public_execution`：{space_id, event_type, participants, cause}
- `behavior_norm_violated`：{space_id, agent_id, violation, witnesses}
- `discussion_started` / `discussion_ended`：{space_id, topic, participants}

## 7. 与其他系统的接口
- 读：01-buildings 的建筑状态和在场人物；02-institutions 的公开执行制度；04-information 的信息内容；08-rituals-beliefs 的仪式安排。
- 写：04-information 读信息传播和舆论形成；03-relationships 读公开执行和舆论对关系的影响；人物系统读行为规范和在场人物做决策。
- 因果链：公开惩罚 → 信息传播 → 舆论形成 → 关系变化 → 人物行为调整。

## 8. 地点参数占位
- 公共空间清单：ID、类型、openness、information_flow_rate、opinion_formation_rate
- behavior_norms、typical_topics、taboo_topics
- 舆论形成的阈值和累积速率
- 行为违规的围观和惩罚映射