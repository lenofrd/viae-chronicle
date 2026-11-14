# 生计技能

## 1. 目的
定义角色如何学习农事、捕鱼、采药、木工、织布、识字等生计技能。技能学习嵌入在生产里，失败也是教育。

## 2. 核心概念
- **技能类型**：农事、捕鱼、采药、木工、织布、识字、算账、医术、狩猎。
- **学习方式**：跟随父母、拜师学艺、自学摸索、失败教训。
- **技能等级**：0–1，代表熟练程度。
- **学习曲线**：初期快，后期慢；有师傅带比自学快。
- **失败教育**：第一次种地歉收、第一次上山迷路，失败带来深刻教训。
- **技能与地位**：技能影响收成、收入、地位，是向上流动的通道。
- **师徒关系**：拜师是正式的技能学习，师徒关系有义务和拉扯。

## 3. 技能学习字段
| 字段 | 类型 | 说明 |
|---|---|---|
| skill_type | enum | 农事/捕鱼/采药/木工/织布/识字/算账/医术/狩猎 |
| level | float 0–1 | 技能等级 |
| learning_method | enum | 跟随父母/拜师/自学/失败教训 |
| teacher_id | string? | 师傅 ID |
| practice_count | int | 实践次数 |
| failure_count | int | 失败次数 |

## 4. 演化规则

### 4.1 跟随父母学习
```
条件：子女跟随父母劳作
效果：技能缓慢提升
      学习速度受父母技能水平和教导质量影响
      生成 skill_learning_event（method = 跟随父母）
滞后：按实践次数
影响范围：子女
```

### 4.2 拜师学艺
```
条件：拜师，跟随师傅学习
效果：技能提升快于自学
      师徒关系形成，有义务和拉扯
      师傅可能留一手，学习速度受影响
      生成 skill_learning_event（method = 拜师）
滞后：按学习周期
影响范围：徒弟
```

### 4.3 自学摸索
```
条件：无师傅，自己尝试
效果：技能提升慢
      失败概率高
      失败带来经验，可能加速后续学习
      生成 skill_learning_event（method = 自学）
滞后：按实践次数
影响范围：学习者
```

### 4.4 失败教育
```
条件：技能实践失败（歉收、迷路、受伤、做坏活）
效果：失败事件成为经验
      相关技能可能提升（吃一堑长一智）或心理受挫
      生成 experience_learning 事件
滞后：失败后
影响范围：学习者
```

### 4.5 技能等级提升
```
条件：实践次数累积
效果：level 按学习曲线提升
      初期快，后期慢
      受 max_delta_per_tick 约束
      生成 skill_level_changed 事件
滞后：渐进
影响范围：学习者
```

### 4.6 技能与收成/收入
```
条件：技能用于生产
效果：技能等级影响收成、产品质量、收入
      见 05-soil-and-fields 和人物系统
滞后：按生产周期
影响范围：角色
```

## 5. 事件类型
- `skill_learning_event`：{learner_id, teacher_id, skill, method, progress, outcome}
- `skill_level_changed`：{agent_id, skill, old, new, cause}
- `apprenticeship_started` / `apprenticeship_ended`：{master_id, apprentice_id, terms}
- `experience_learning`：{agent_id, event_id, lesson, internalization}

## 6. 与其他系统的接口
- 读：03-kinship 的家庭关系；03-relationships 的师徒关系；05-soil-and-fields 的农事需求；06-vegetation 的采药知识。
- 写：人物系统的技能等级；06-stratification 的向上流动；03-relationships 的师徒关系；05-education/06-generational-transfer 的技能传递。
- 因果链：跟随父亲学犁田 → 技能提升 → 第一次独立种地歉收 → 失败教育 → 以后更谨慎 → 技能进一步提升。

## 7. 地点参数占位
- 技能类型清单
- 学习曲线参数
- 拜师的学习加速系数
- 失败教育的经验值
- 技能对收成/收入的影响系数
- 师徒关系的义务和拉扯规则