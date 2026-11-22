# 信息经验教育

## 1. 目的
定义角色如何从环境事件、他人讲述、邻里闲聊中获得经验和知识。环境事件本身就是教材：洪水冲过哪块田、哪条山路会滑坡、谁家借粮不还。

## 2. 核心概念
- **经验来源**：亲眼目睹、亲身经历、他人讲述、邻里闲聊。
- **经验类型**：自然风险（洪水、滑坡、野兽）、社会风险（借粮不还、背叛）、生计知识（哪块田肥、哪条路近）。
- **经验学习**：经验改变角色的认知和行为倾向。
- **失败教训**：亲身经历的失败比听来的教训更深刻。
- **代际经验**：老人讲述的经验是晚辈的重要知识来源。
- **经验与决策**：经验影响角色对风险的判断和决策。

## 3. 经验学习字段
| 字段 | 类型 | 说明 |
|---|---|---|
| experience_id | string | 唯一 ID |
| agent_id | string | 学习者 |
| source | enum | 亲眼目睹/亲身经历/他人讲述/邻里闲聊 |
| experience_type | enum | 自然风险/社会风险/生计知识 |
| lesson | string | 学到的教训或知识 |
| internalization | float 0–1 | 内化程度 |
| behavior_effect | dict | 对行为倾向的影响 |

## 4. 演化规则

### 4.1 亲眼目睹
```
条件：角色在场目睹事件
效果：获得经验知识
      internalization 较高（亲眼所见）
      生成 experience_learning 事件（source = 亲眼目睹）
滞后：无
影响范围：在场角色
```

### 4.2 亲身经历
```
条件：角色亲身经历事件（失败、受伤、损失）
效果：获得深刻经验
      internalization 最高（亲身经历）
      可能改变行为倾向（更谨慎或更冒险）
      生成 experience_learning 事件（source = 亲身经历）
滞后：事件后
影响范围：经历者
```

### 4.3 他人讲述
```
条件：长辈、邻里讲述经验
效果：获得经验知识
      internalization 受讲述者 trust 和讲述生动程度影响
      生成 experience_learning 事件（source = 他人讲述）
滞后：按讲述时机
影响范围：听者
```

### 4.4 邻里闲聊
```
条件：邻里闲聊中提及经验
效果：获得零散经验知识
      internalization 较低（闲聊信息可信度低）
      生成 experience_learning 事件（source = 邻里闲聊）
滞后：按闲聊时机
影响范围：参与者
```

### 4.5 经验影响决策
```
条件：角色面临类似情境
效果：经验影响风险判断和决策
      有洪水经验的人 → 洪水前更早撤离
      有借粮不还经验的人 → 借粮更谨慎
      生成 experience_applied 事件
滞后：按决策时机
影响范围：角色
```

### 4.6 经验传递
```
条件：长辈向晚辈讲述经验
效果：晚辈获得经验知识
      代际传递经验
      生成 experience_learning 事件（source = 他人讲述）
滞后：按讲述时机
影响范围：晚辈
```

## 5. 事件类型
- `experience_learning`：{agent_id, source, experience_type, lesson, internalization, behavior_effect}
- `experience_applied`：{agent_id, experience_id, situation, decision}

## 6. 与其他系统的接口
- 读：自然环境事件（洪水、滑坡、野兽）；04-information 的信息；03-relationships 的信任。
- 写：人物系统的风险判断和行为倾向；05-education/06-generational-transfer 的代际经验传递；04-information 的经验传播。
- 因果链：洪水冲田 → 亲眼目睹 → 获得洪水经验 → 以后洪水前更早撤离 → 减少损失。

## 7. 地点参数占位
- 经验类型清单
- 各来源的内化系数
- 经验对行为的影响规则
- 经验传递的条件