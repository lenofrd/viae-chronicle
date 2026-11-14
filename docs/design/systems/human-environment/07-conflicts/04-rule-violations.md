# 违反村规

## 1. 目的
定义违反村规的冲突类型、触发、拉扯、执行、后果。违反村规是社区规训的核心场景，也是公开惩罚和舆论形成的爆发点。

## 2. 核心概念
- **触发**：偷盗、伤人、通奸、不孝、欺诈被发现。
- **拉扯**：受害者/见证人报告，违规者辩解，双方引用村规、人情、见证人。
- **执行**：里正/长老/祠堂议事裁定。
- **公开 vs 私下**：严重违规公开执行，轻微违规私下调解。
- **后果**：惩罚、地位下降、关系恶化、舆论形成、制度强化或松动。
- **旁观者学习**：公开惩罚时旁观者学习规矩。

## 3. 冲突状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| conflict_id | string | 唯一 ID |
| violator | string | 违规者 |
| victim | string? | 受害者（若有） |
| violation_type | enum | 偷盗/伤人/通奸/不孝/欺诈 |
| trigger_event | string | 触发事件 |
| stage | enum | 触发/争执/调解/执行/解决 |
| intensity | float 0–1 | 激烈程度 |
| public | bool | 是否公开执行 |

## 4. 演化规则

### 4.1 触发
```
条件：违规被发现并报告
效果：生成 conflict_started 事件
      conflict_type = rule-violations
      stage = 触发
滞后：发现可能有滞后
影响范围：违规者、受害者、社区
```

### 4.2 拉扯
```
条件：冲突进入争执阶段
效果：多轮交涉
      违规者辩解（否认/求情/反诉）
      受害者/见证人陈述
      双方引用村规、人情、见证人
      生成 conflict_negotiation_round 事件
滞后：每轮按 tick
影响范围：双方、社区
```

### 4.3 裁定
```
条件：里正/长老/祠堂议事介入
效果：根据村规、证据、舆论裁定
      严重违规公开执行，轻微违规私下调解
      生成 conflict_mediated 事件
滞后：按裁定时机
影响范围：违规者、受害者、社区
```

### 4.4 执行与惩罚
```
条件：裁定有罪
效果：按 punishment_ladder 惩罚
      公开羞辱可能终身影响地位
      生成 punishment_executed 事件
滞后：按惩罚类型
影响范围：违规者、执行者、旁观者
```

### 4.5 解决
```
条件：惩罚执行完毕或调解成功
效果：生成 conflict_resolved 事件
      违规者可能改过或更加抵触
      关系变化、地位变化、舆论形成
滞后：长期过程
影响范围：违规者、社区
```

### 4.6 旁观者学习
```
条件：公开惩罚
效果：旁观者内化规矩
      形成“什么能做、什么不能做”的认知
      生成 observer_learning 事件
滞后：按围观时机
影响范围：旁观者
```

## 5. 事件类型
- `conflict_started`：{conflict_id, conflict_type: rule-violations, violator, victim, violation_type, trigger_event}
- `conflict_negotiation_round`：{conflict_id, round, initiator, responder, proposal, response}
- `conflict_mediated`：{conflict_id, mediator_id, outcome, public}
- `punishment_executed`：{conflict_id, violator_id, punishment_type, location, witnesses}
- `conflict_resolved`：{conflict_id, resolution, terms}
- `observer_learning`：{observer_id, conflict_id, lesson, internalization}

## 6. 与其他系统的接口
- 读：02-institutions/04-village-rules 的村规；03-relationships 的当事人关系；04-information 的违规是否被发现和传播；01-social-spaces 的祠堂和里正家。
- 写：03-relationships 的结怨或和解；02-institutions 的制度强化或松动；05-education 的社区规训；06-stratification 的地位变化；人物系统的心理影响。
- 因果链：偷盗 → 被发现 → 报告里正 → 祠堂公开执行 → 舆论形成 → 违规者地位下降 → 关系变化 → 村规强化或松动。

## 7. 地点参数占位
- 违规类型和严重程度
- 公开执行和私下调解的分界
- 拉扯轮数上限
- 裁定者的权限
- 惩罚阶梯
- 旁观者学习的概率