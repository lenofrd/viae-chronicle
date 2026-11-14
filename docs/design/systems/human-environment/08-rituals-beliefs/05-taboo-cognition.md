# 禁忌认知

## 1. 目的
定义角色对禁忌的认知、内化、遵守、违反、心理影响。禁忌认知是“什么不能碰”的内化程度，影响行为和心理。

## 2. 核心概念
- **禁忌对象**：神树、山神庙、祖坟、特定日子、特定行为。
- **禁忌认知**：角色知道哪些禁忌、相信程度、内化程度。
- **禁忌内化**：从“知道”到“相信”到“自觉遵守”。
- **违反禁忌**：行为上违反，或心里不信。
- **心理影响**：违反禁忌后恐惧、内疚、焦虑；遵守禁忌获得安心。
- **禁忌与舆论**：违反禁忌受舆论谴责，严重时社区排斥。
- **禁忌与制度**：禁忌支撑禁伐禁猎、祭祀制度。

## 3. 禁忌认知字段
| 字段 | 类型 | 说明 |
|---|---|---|
| taboo_id | string | 禁忌 ID |
| taboo_object | string | 禁忌对象（神树/山神庙/祖坟/日子/行为） |
| agent_id | string | 角色 |
| knowledge_level | enum | 不知道/知道/相信/内化 |
| internalization | float 0–1 | 内化程度 |
| violation_history | list | 违反记录 |
| psychological_effect | dict | 心理影响记录 |

## 4. 演化规则

### 4.1 禁忌认知形成
```
条件：家庭教养、仪式参与、长辈讲述、传说传播
效果：角色从“不知道”到“知道”
      知道禁忌的存在和内容
      生成 taboo_cognition_formed 事件
滞后：按教育过程
影响范围：角色
```

### 4.2 禁忌相信
```
条件：反复听闻、仪式强化、灾害解释
效果：从“知道”到“相信”
      belief_strength 上升
      生成 belief_strength_changed 事件
滞后：长期过程
影响范围：角色
```

### 4.3 禁忌内化
```
条件：长期遵守、仪式参与、心理强化
效果：从“相信”到“内化”
      internalization 上升
      自觉遵守禁忌
      生成 taboo_internalization_changed 事件
滞后：长期过程
影响范围：角色
```

### 4.4 违反禁忌
```
条件：角色违反禁忌（行为或心里不信）
效果：记录违反
      心理影响（恐惧、内疚、焦虑）
      可能被舆论谴责
      生成 taboo_violated 事件
滞后：按违反时机
影响范围：角色、社区
```

### 4.5 心理影响
```
条件：违反禁忌后
效果：恐惧、内疚、焦虑
      可能寻求仪式净化
      可能改变信仰（更信或不信）
      生成 psychological_effect 事件
滞后：长期过程
影响范围：角色
```

### 4.6 禁忌与舆论
```
条件：违反禁忌被传播
效果：舆论谴责
      社区排斥
      生成 opinion_formed 事件
滞后：舆论形成需要时间
影响范围：角色、社区
```

### 4.7 禁忌与制度
```
条件：禁忌内化程度高
效果：禁伐禁猎、祭祀制度获得合法性
      违反禁忌者受惩罚
      生成 taboo_support_institution 事件
滞后：长期过程
影响范围：制度
```

## 5. 事件类型
- `taboo_cognition_formed`：{agent_id, taboo_id, knowledge_level}
- `belief_strength_changed`：{agent_id, taboo_id, old, new, cause}
- `taboo_internalization_changed`：{agent_id, taboo_id, old, new, cause}
- `taboo_violated`：{agent_id, taboo_id, violation_type, witnesses}
- `psychological_effect`：{agent_id, taboo_id, effect, severity}
- `opinion_formed`：{taboo_id, topic, stance, participants}
- `taboo_support_institution`：{taboo_id, institution_id, support_level}

## 6. 与其他系统的接口
- 读：05-education 的家庭教养和仪式教育；04-information 的传说和故事；08-rituals-beliefs 的仪式参与；02-institutions/06-taboos 的禁忌规则。
- 写：人物系统的 world_view 和心理状态；02-institutions 的禁忌支撑；07-conflicts 的禁忌冲突；06-vegetation 的神树保护。
- 因果链：长辈讲述神树禁忌 → 孩子知道 → 仪式强化 → 相信 → 内化 → 自觉不砍神树。

## 7. 地点参数占位
- 禁忌清单和禁忌对象
- 认知形成的教育路径
- 相信和内化的速率
- 违反禁忌的心理影响系数
- 舆论谴责的规则
- 禁忌支撑制度的规则