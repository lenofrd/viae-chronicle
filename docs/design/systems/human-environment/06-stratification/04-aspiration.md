# 向上与向外意图

## 1. 目的
定义向上意图和向外意图的形成、变化、影响，以及意图如何影响人物决策和人生叙事。意图是“他没去哪、为什么没去、后来怎么面对这个选择”的核心。

## 2. 核心概念
- **向上意图**：想提升地位、学手艺、联姻、争里正、买田、识字。
- **向外意图**：想离开小镇、外出求学、投亲、做工、参军、婚嫁外迁。
- **意图强度**：0–1，随处境、认知、尝试结果变化。
- **意图原因**：贫困、冲突、抱负、好奇、逃婚、逃债、灾害。
- **意图与行动**：意图不一定转化为行动；行动可能受阻、延迟、放弃。
- **意图与心理**：长期未实现的意图可能形成遗憾、不甘、认命。
- **意图与记录**：意图是人生暗线，记录里要能看到“他想过什么、试过什么、为什么没成”。

## 3. 意图状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| upward_aspiration | float 0–1 | 向上意图强度 |
| outward_aspiration | float 0–1 | 向外意图强度 |
| aspiration_reason | string? | 意图原因 |
| aspiration_history | list | 意图变化历史 |
| blocked_attempts | list | 受阻尝试记录 |
| psychological_effect | dict | 长期未实现的心理影响 |

## 4. 演化规则

### 4.1 意图形成
```
条件：处境变化（贫困、冲突、灾害、外来消息、抱负）
效果：upward_aspiration 或 outward_aspiration 上升
      记录 aspiration_reason
      生成 aspiration_changed 事件
滞后：渐进
影响范围：角色
```

### 4.2 意图强化
```
条件：尝试成功、看到希望、他人鼓励
效果：aspiration 上升
      生成 aspiration_changed 事件
滞后：按事件
影响范围：角色
```

### 4.3 意图受挫
```
条件：尝试失败、被阻止、时机错过
效果：aspiration 可能下降（放弃）或维持/上升（不甘）
      受性格、关系、处境影响
      生成 aspiration_changed 事件
滞后：按事件
影响范围：角色
```

### 4.4 意图放弃
```
条件：长期受挫、年龄增长、家庭责任加重
效果：aspiration 下降到阈值以下
      记录放弃原因
      生成 aspiration_abandoned 事件
滞后：长期过程
影响范围：角色
```

### 4.5 意图维持
```
条件：aspiration 未实现但未放弃
效果：意图作为暗线持续存在
      影响心理和决策
      生成 aspiration_maintained 事件
滞后：长期过程
影响范围：角色
```

### 4.6 意图与心理
```
条件：长期未实现
效果：形成遗憾、不甘、认命
      影响心理状态和人生叙事
      生成 aspiration_psychological_effect 事件
滞后：长期过程
影响范围：角色
```

### 4.7 意图与记录
```
条件：查询人生
效果：意图、尝试、未走原因作为人生暗线呈现
      能看到“他想过什么、试过什么、为什么没成”
      生成 life_narrative_line
滞后：查询时
影响范围：记录系统
```

## 5. 事件类型
- `aspiration_changed`：{agent_id, type: upward/outward, old, new, cause}
- `aspiration_abandoned`：{agent_id, type, reason}
- `aspiration_maintained`：{agent_id, type, reason}
- `aspiration_psychological_effect`：{agent_id, effect, severity}
- `life_narrative_line`：{agent_id, aspiration_type, summary}

## 6. 与其他系统的接口
- 读：06-status 的地位变化；06-upward-channels 的尝试结果；06-outward-interfaces 的尝试结果；04-information 的外来消息；03-relationships 的家庭牵绊。
- 写：人物系统的心理状态；记录系统的人生暗线；07-conflicts 的意图冲突（如家庭反对）。
- 因果链：想学手艺 → 家里不让 → 意图受挫 → 偷偷学 → 被发现 → 家庭冲突 → 意图维持或放弃 → 人生暗线。

## 7. 地点参数占位
- 意图形成的触发条件
- 意图强化和受挫的系数
- 放弃的阈值
- 心理影响的映射
- 人生暗线的呈现规则