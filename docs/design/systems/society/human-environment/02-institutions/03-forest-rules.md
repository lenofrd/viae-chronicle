# 禁伐禁猎

## 1. 目的
定义禁伐禁猎制度的规则、执行、违反、冲突和变迁。山林是公共资源，过度砍伐和捕猎导致资源退化，制度用来约束个人行为。

## 2. 核心概念
- **禁伐区**：神树、水源林、陡坡林，禁止砍伐。
- **禁猎期**：繁殖季节禁止捕猎。
- **限额**：日常砍柴和捕猎的数量限制。
- **护林人**：负责巡查和报告违规的人（第一版可由里正兼任）。
- **监督**：村民互相监督，发现违规可报告。
- **惩罚**：罚粮、罚工、公开批评、没收工具。

## 3. 规则内容（地点参数可配）
| 字段 | 说明 |
|---|---|
| protected_zones | 禁伐区清单 |
| hunting_seasons | 禁猎期 |
| daily_limits | 日常砍柴/捕猎限额 |
| enforcement_authority | 执行者/护林人 |
| punishment_ladder | 惩罚阶梯 |
| monitoring_mechanism | 监督方式（村民报告/巡查） |

## 4. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| rule_content | dict | 禁伐禁猎规则 |
| enforcement_state | enum | 严格执行/宽松执行/名存实亡 |
| challenge_count | int | 被挑战次数 |
| looseness | float 0–1 | 松动程度 |
| violations_this_season | list | 本季违反记录 |
| protected_zone_state | dict | 禁伐区状态（是否被破坏） |

## 5. 演化规则

### 5.1 违规判定：盗伐/盗猎
```
条件：人物在禁伐区砍伐，或在禁猎期捕猎，或超过限额
效果：生成 rule_violated 事件
      violation_type = 盗伐/盗猎/超限
      severity 按数量和区域敏感度
      若被护林人或村民发现，触发冲突
滞后：发现可能有滞后
影响范围：违规者和公共资源
```

### 5.2 监督与发现
```
条件：违规发生后
效果：按 monitoring_mechanism 判定是否被发现
      村民报告概率受关系和信息传播影响
      发现则触发 rule_enforced
滞后：发现需要时间
影响范围：违规者和社区
```

### 5.3 执行与惩罚
```
条件：rule_violated 事件被确认
效果：执行者按 punishment_ladder 惩罚
      没收工具、罚粮、罚工、公开批评
      生成 rule_enforced 事件
      违规者关系恶化，举报者可能被记恨
滞后：调解和惩罚需要时间
影响范围：违规者、执行者、举报者
```

### 5.4 制度挑战
```
条件：村民认为限额太严、禁伐区影响生计
效果：生成 rule_challenged 事件
      挑战可能成功（放宽限额、缩小禁伐区）或失败
滞后：反复挑战后才可能修改
影响范围：制度及依赖山林的村民
```

### 5.5 资源退化触发制度强化
```
条件：06-vegetation 的近山资源退化达到阈值
效果：enforcement_state 趋严
      限额收紧，惩罚加重
      生成 enforcement_state_changed 事件
滞后：资源退化后
影响范围：制度及所有依赖山林的村民
```

## 6. 事件类型
- `rule_violated`：{rule_id: forest-rules, violator_id, violation_type, severity, witnesses}
- `rule_enforced`：{rule_id: forest-rules, violator_id, enforcer_id, punishment, location}
- `rule_challenged`：{rule_id: forest-rules, challenger_id, reason, outcome}
- `rule_modified`：{rule_id: forest-rules, old_content, new_content, cause}
- `enforcement_state_changed`：{rule_id: forest-rules, old, new, cause}
- `protected_zone_damaged`：{zone_id, severity, cause}

## 7. 与其他系统的接口
- 读：06-vegetation 的资源退化状态；07-fauna 的猎物种群；04-information 的违规是否被发现；03-relationships 的监督和包庇。
- 写：07-conflicts 的盗伐盗猎冲突；03-relationships 的举报与记恨；06-vegetation 的采集压力；05-education 的禁伐禁猎规训；人物系统读规则约束做决策。
- 因果链：近山柴薪退化 → 村民转向浅山 → 禁伐区被侵犯 → 护林人发现 → 惩罚 → 关系恶化 → 制度松动或强化。

## 8. 地点参数占位
- protected_zones 清单
- hunting_seasons
- daily_limits
- enforcement_authority / 护林人
- punishment_ladder（没收工具/罚粮/罚工/公开批评）
- monitoring_mechanism 和监督概率
- 初始 looseness 和 enforcement_state
- 资源退化触发制度强化的阈值