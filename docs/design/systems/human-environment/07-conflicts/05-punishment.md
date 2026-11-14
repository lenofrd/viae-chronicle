# 惩罚

## 1. 目的
定义惩罚的类型、执行、后果、心理影响。惩罚是冲突解决的手段，也是社区规训的核心机制。

## 2. 核心概念
- **惩罚类型**：批评、赔礼、赔粮、罚工、公开羞辱、限制权利、驱逐。
- **惩罚执行者**：里正、长老、祠堂议事。
- **惩罚场所**：祠堂（公开）、里正家（私下）。
- **惩罚后果**：财富损失、地位下降、关系恶化、心理影响。
- **惩罚与舆论**：公开惩罚影响舆论，私下惩罚影响关系。
- **惩罚与制度**：惩罚强化制度，过度惩罚可能引发反感，导致制度松动。
- **惩罚与教育**：惩罚是社区规训的一部分，旁观者通过观看惩罚学习规矩。

## 3. 惩罚类型（第一版）
| 惩罚 | 严重度 | 执行场所 | 后果 |
|---|---|---|---|
| 批评 | 轻 | 私下/公开 | 声誉轻微下降 |
| 赔礼 | 轻 | 私下/公开 | 关系缓和或维持 |
| 赔粮 | 中 | 私下/公开 | 财富损失 |
| 罚工 | 中 | 公开 | 时间损失、劳力损失 |
| 公开羞辱 | 重 | 祠堂 | 声誉大幅下降、长期影响 |
| 限制权利 | 重 | 公开 | 限制灌水、换工、集市交易 |
| 驱逐 | 最重 | 公开 | 社区排斥（第一版只记录意图） |

## 4. 惩罚状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| punishment_id | string | 唯一 ID |
| conflict_id | string | 关联冲突 |
| violator_id | string | 被罚者 |
| punishment_type | enum | 批评/赔礼/赔粮/罚工/公开羞辱/限制权利/驱逐 |
| executed_tick | int | 执行 tick |
| location | string | 执行场所 |
| witnesses | list | 旁观者 |
| effects | dict | 后果记录 |

## 5. 演化规则

### 5.1 惩罚裁定
```
条件：冲突裁定有罪
效果：根据违规严重度、制度、舆论裁定惩罚类型
      生成 punishment_decided 事件
滞后：按裁定时机
影响范围：违规者、执行者
```

### 5.2 惩罚执行
```
条件：惩罚裁定
效果：按惩罚类型执行
      公开惩罚在祠堂举行，旁观者围观
      私下惩罚在里正家进行
      生成 punishment_executed 事件
滞后：按惩罚类型
影响范围：违规者、执行者、旁观者
```

### 5.3 惩罚后果
```
条件：惩罚执行后
效果：财富损失、地位下降、关系恶化、心理影响
      公开羞辱可能终身影响地位
      生成 punishment_effect 事件
滞后：长期过程
影响范围：违规者、社区
```

### 5.4 惩罚与舆论
```
条件：公开惩罚
效果：舆论形成，支持或反对惩罚
      舆论影响制度执行
      生成 opinion_formed 事件
滞后：舆论形成需要时间
影响范围：社区
```

### 5.5 惩罚与制度
```
条件：惩罚反复执行
效果：制度强化（惩罚有效）或松动（惩罚过度引发反感）
      生成 enforcement_state_changed 事件
滞后：长期过程
影响范围：制度
```

### 5.6 惩罚与教育
```
条件：公开惩罚
效果：旁观者学习规矩
      违规者可能内化或抗拒
      生成 observer_learning 事件
滞后：按围观时机
影响范围：旁观者、违规者
```

## 6. 事件类型
- `punishment_decided`：{punishment_id, conflict_id, violator_id, punishment_type, reason}
- `punishment_executed`：{punishment_id, violator_id, punishment_type, location, witnesses}
- `punishment_effect`：{punishment_id, effect_type, severity}
- `opinion_formed`：{punishment_id, topic, stance, participants}
- `enforcement_state_changed`：{rule_id, old, new, cause}

## 7. 与其他系统的接口
- 读：07-conflicts 的裁定；02-institutions 的惩罚阶梯；01-social-spaces 的祠堂和里正家；04-information 的舆论。
- 写：03-relationships 的关系变化；02-institutions 的制度强化或松动；05-education 的规训；06-stratification 的地位变化；人物系统的心理影响。
- 因果链：偷盗 → 祠堂公开羞辱 → 旁观者学习 → 被罚者地位下降 → 舆论形成 → 村规强化或松动。

## 8. 地点参数占位
- 惩罚类型清单
- 各惩罚的严重度
- 执行场所
- 后果的影响系数
- 舆论形成的规则
- 制度强化或松动的阈值