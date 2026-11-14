# 村规

## 1. 目的
定义村规的一般规则、执行、违反、冲突和变迁。村规是 Brookvale 最基础的制度框架，涵盖偷盗、伤人、通奸、不孝等日常行为规范。

## 2. 核心概念
- **村规内容**：禁止偷盗、禁止伤人、禁止通奸、要求孝顺、要求互助。
- **执行者**：里正、长老、祠堂议事。
- **执行场所**：祠堂（公开惩罚）、里正家（私下调解）。
- **公开性**：严重违规公开执行，轻微违规私下调解。
- **惩罚阶梯**：批评、赔礼、赔粮、罚工、公开羞辱、驱逐。
- **村规与舆论**：村规执行依赖舆论支持，舆论反对时执行困难。

## 3. 规则内容（地点参数可配）
| 字段 | 说明 |
|---|---|
| prohibited_acts | 禁止行为清单（偷盗/伤人/通奸/不孝/欺诈） |
| enforcement_authority | 执行者（里正/长老/祠堂议事） |
| public_vs_private | 公开执行和私下调解的分界 |
| punishment_ladder | 惩罚阶梯 |
| appeal_mechanism | 申诉机制（向长老申诉/祠堂复议） |

## 4. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| rule_content | dict | 村规内容 |
| enforcement_state | enum | 严格执行/宽松执行/名存实亡 |
| challenge_count | int | 被挑战次数 |
| looseness | float 0–1 | 松动程度 |
| recent_violations | list | 近期违规记录 |
| public_opinion | dict | 舆论对村规的态度 |

## 5. 演化规则

### 5.1 违规判定
```
条件：人物行为触犯 prohibited_acts
效果：生成 rule_violated 事件
      violation_type = 偷盗/伤人/通奸/不孝/欺诈
      severity 按行为严重程度
      若被受害者或见证人报告，触发冲突
滞后：发现可能有滞后
影响范围：违规者、受害者、社区
```

### 5.2 公开执行与私下调解
```
条件：rule_violated 事件被确认
效果：严重违规 → 祠堂公开执行，生成 rule_enforced 事件
      轻微违规 → 里正家私下调解，生成 mediation_completed 事件
      公开执行影响舆论，私下调解影响关系
滞后：调解和惩罚需要时间
影响范围：违规者、受害者、社区
```

### 5.3 执行与惩罚
```
条件：违规被确认且执行者裁定
效果：按 punishment_ladder 惩罚
      公开羞辱可能终身影响地位
      驱逐是最重惩罚（第一版可只记录意图，不执行离开）
      生成 rule_enforced 事件
滞后：按惩罚类型
影响范围：违规者、执行者、见证人
```

### 5.4 制度挑战
```
条件：违规者不服、或多人认为村规不公
效果：生成 rule_challenged 事件
      挑战可能成功（修改规则）或失败（维持原规）
      挑战成功则 looseness 上升
滞后：反复挑战后才可能修改
影响范围：制度及社区
```

### 5.5 舆论与执行
```
条件：public_opinion 对村规的态度变化
效果：舆论支持 → 执行容易
      舆论反对 → 执行困难，enforcement_state 趋松
      生成 enforcement_state_changed 事件
滞后：舆论变化慢于事件
影响范围：制度及社区
```

### 5.6 制度修改
```
条件：looseness 超过阈值，且多人支持修改
效果：生成 rule_modified 事件
      村规内容可能改变（增删禁止行为、调整惩罚）
      改变后 looseness 重置
滞后：长期过程
影响范围：制度及社区
```

## 6. 事件类型
- `rule_violated`：{rule_id: village-rules, violator_id, violation_type, severity, witnesses}
- `rule_enforced`：{rule_id: village-rules, violator_id, enforcer_id, punishment, location, public}
- `mediation_completed`：{rule_id: village-rules, parties, mediator, outcome}
- `rule_challenged`：{rule_id: village-rules, challenger_id, reason, outcome}
- `rule_modified`：{rule_id: village-rules, old_content, new_content, cause}
- `enforcement_state_changed`：{rule_id: village-rules, old, new, cause}
- `public_opinion_changed`：{rule_id: village-rules, old, new, cause}

## 7. 与其他系统的接口
- 读：01-social-spaces 的祠堂和里正家；03-relationships 的当事人关系；04-information 的违规是否被发现和传播；02-public-spaces 的舆论。
- 写：07-conflicts 的村规冲突；03-relationships 的结怨或和解；05-education 的社区规训；06-stratification 的地位变化（公开羞辱影响地位）；人物系统读规则约束做决策。
- 因果链：偷盗发生 → 被发现 → 报告里正 → 祠堂公开执行 → 舆论形成 → 违规者地位下降 → 关系变化 → 村规强化或松动。

## 8. 地点参数占位
- prohibited_acts 清单
- enforcement_authority
- public_vs_private 分界
- punishment_ladder（批评/赔礼/赔粮/罚工/公开羞辱/驱逐）
- appeal_mechanism
- 初始 looseness 和 enforcement_state
- 舆论对执行的影响系数
- 制度修改的阈值