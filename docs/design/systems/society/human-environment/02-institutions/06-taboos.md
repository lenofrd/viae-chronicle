# 祭祀禁忌

## 1. 目的
定义祭祀禁忌制度的规则、执行、违反、冲突和变迁。禁忌不是法律，但违反禁忌会引发心理恐惧、舆论压力和仪式性惩罚。

## 2. 核心概念
- **禁忌对象**：神树、山神庙、祖坟、特定日子、特定行为。
- **禁忌认知**：谁知道禁忌、谁相信禁忌、谁不在乎。
- **违反后果**：心理恐惧、舆论谴责、仪式性净化、社区排斥。
- **执行者**：长老、祭司、舆论。
- **禁忌与心理**：禁忌影响人物心理状态，违反者可能长期恐惧。
- **禁忌与自然环境**：神树、禁伐区、禁猎期往往有禁忌支撑。

## 3. 规则内容（地点参数可配）
| 字段 | 说明 |
|---|---|
| taboo_objects | 禁忌对象清单 |
| taboo_behaviors | 禁忌行为清单 |
| enforcement_authority | 执行者（长老/祭司/舆论） |
| punishment_ladder | 惩罚阶梯（舆论谴责/仪式净化/社区排斥） |
| belief_strength | 禁忌在社区中的信仰强度 |

## 4. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| rule_content | dict | 禁忌内容 |
| enforcement_state | enum | 严格执行/宽松执行/名存实亡 |
| challenge_count | int | 被挑战次数 |
| looseness | float 0–1 | 松动程度 |
| belief_strength | float 0–1 | 信仰强度 |
| recent_violations | list | 近期违反记录 |

## 5. 演化规则

### 5.1 违反判定
```
条件：人物触犯 taboo_behaviors
效果：生成 rule_violated 事件
      violation_type = 冒犯禁忌
      severity 按禁忌敏感度
      违反者心理状态变化（恐惧、内疚）
      若被见证或传播，触发舆论和冲突
滞后：发现可能有滞后
影响范围：违反者、见证人、社区
```

### 5.2 心理影响
```
条件：人物违反禁忌或被卷入禁忌事件
效果：心理状态变化（恐惧、焦虑、内疚）
      可能触发仪式性净化需求
      生成 taboo_psychological_impact 事件
滞后：心理影响持续
影响范围：违反者和相关人员
```

### 5.3 舆论与执行
```
条件：违反被传播
效果：舆论谴责
      长老或祭司执行仪式性惩罚
      严重时社区排斥
      生成 rule_enforced 事件
滞后：舆论形成需要时间
影响范围：违反者、社区
```

### 5.4 信仰强度变化
```
条件：反复违反无人受罚、或重大事件（如山神“显灵”）
效果：belief_strength 变化
      信仰强 → 禁忌执行严
      信仰弱 → 禁忌松动
      生成 belief_strength_changed 事件
滞后：长期过程
影响范围：禁忌制度和社区
```

### 5.5 制度挑战与修改
```
条件：村民质疑禁忌合理性、或外来观念冲击
效果：生成 rule_challenged 事件
      挑战可能成功（禁忌松动）或失败（禁忌强化）
      修改后 looseness 重置
滞后：反复挑战后才可能修改
影响范围：禁忌制度和社区
```

### 5.6 禁忌与自然环境耦合
```
条件：06-vegetation 的神树被砍、禁伐区被侵犯
效果：触发禁忌违反
      舆论谴责
      可能触发仪式性惩罚
滞后：按事件
影响范围：违反者、社区、自然环境
```

## 6. 事件类型
- `rule_violated`：{rule_id: taboos, violator_id, violation_type: 冒犯禁忌, severity, witnesses}
- `taboo_psychological_impact`：{agent_id, taboo_id, effect, severity}
- `rule_enforced`：{rule_id: taboos, violator_id, enforcer_id, punishment, public}
- `belief_strength_changed`：{rule_id: taboos, old, new, cause}
- `rule_challenged`：{rule_id: taboos, challenger_id, reason, outcome}
- `rule_modified`：{rule_id: taboos, old_content, new_content, cause}

## 7. 与其他系统的接口
- 读：08-rituals-beliefs 的仪式和信仰；06-vegetation 的神树和禁伐区；04-information 的禁忌传播；人物系统的心理状态。
- 写：人物系统的心理状态（恐惧、内疚）；03-relationships 的舆论和排斥；05-education 的禁忌传递；07-conflicts 的禁忌冲突；06-vegetation 的禁伐禁猎支撑。
- 因果链：神树被砍 → 触犯禁忌 → 违反者恐惧 → 舆论谴责 → 长老执行仪式惩罚 → 社区排斥 → 信仰强化或松动。

## 8. 地点参数占位
- taboo_objects、taboo_behaviors 清单
- enforcement_authority
- punishment_ladder（舆论谴责/仪式净化/社区排斥）
- 初始 belief_strength 和 enforcement_state
- 违反的心理影响系数
- 信仰强度变化的条件
- 禁忌与自然环境对象的映射