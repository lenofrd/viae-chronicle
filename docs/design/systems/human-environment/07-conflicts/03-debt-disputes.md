# 债务纠纷

## 1. 目的
定义债务纠纷的触发、拉扯、调解、后果。债务纠纷源于逾期不还、赖账、讨债方式不当。

## 2. 核心概念
- **触发**：逾期不还、赖账、讨债方式不当、利息争议。
- **拉扯**：债权人讨债，债务人推脱，双方引用借据、人情、见证人。
- **调解**：里正、长老、共同亲友。
- **后果**：还款、延期、豁免、关系恶化、公开执行。
- **收成差时高发**：歉收导致还款能力下降，纠纷概率上升。

## 3. 冲突状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| conflict_id | string | 唯一 ID |
| creditor | string | 债权人 |
| debtor | string | 债务人 |
| debt_id | string | 债务关系 ID |
| trigger_event | string | 触发事件 |
| stage | enum | 触发/争执/调解/解决/破裂 |
| intensity | float 0–1 | 激烈程度 |

## 4. 演化规则

### 4.1 触发
```
条件：债务逾期，或债权人讨债，或债务人赖账
效果：生成 conflict_started 事件
      conflict_type = debt-disputes
      stage = 触发
滞后：按 due_tick
影响范围：债权人和债务人
```

### 4.2 拉扯
```
条件：冲突进入争执阶段
效果：多轮交涉
      债权人要求还款，债务人推脱或请求延期
      双方引用借据、人情、见证人
      可能同意延期、部分还款、拒绝、反诉
      生成 conflict_negotiation_round 事件
滞后：每轮按 tick
影响范围：双方
```

### 4.3 调解
```
条件：双方僵持
效果：里正/长老/共同亲友介入
      提出方案（延期/分期/部分豁免）
      双方接受或拒绝
      生成 conflict_mediated 事件
滞后：按调解时机
影响范围：双方、调解者
```

### 4.4 解决
```
条件：双方达成协议或调解成功
效果：还款、延期、豁免、以工抵债
      生成 conflict_resolved 事件
      关系可能缓和或维持紧张
滞后：按协议执行
影响范围：双方、制度
```

### 4.5 破裂
```
条件：调解失败、一方拒绝
效果：关系恶化、公开讨债、社区排挤
      可能触发村规执行
      生成 conflict_broken 事件
滞后：按冲突演化
影响范围：双方、社区
```

### 4.6 收成差时高发
```
条件：歉收、灾害
效果：还款能力下降
      纠纷概率上升
      生成 conflict_started（trigger_event = 收成差）
滞后：歉收后
影响范围：债权人和债务人
```

## 5. 事件类型
- `conflict_started`：{conflict_id, conflict_type: debt-disputes, creditor, debtor, debt_id, trigger_event}
- `conflict_negotiation_round`：{conflict_id, round, initiator, responder, proposal, response}
- `conflict_mediated`：{conflict_id, mediator_id, outcome}
- `conflict_resolved`：{conflict_id, resolution, terms}
- `conflict_broken`：{conflict_id, reason}

## 6. 与其他系统的接口
- 读：03-relationships/03-debt 的债务状态；02-institutions/04-village-rules 的村规；05-soil-and-fields 的收成。
- 写：03-relationships 的 trust 和恩怨；02-institutions 的制度执行；06-stratification 的地位变化。
- 因果链：歉收 → 还款能力下降 → 逾期 → 债权人讨债 → 争执 → 调解 → 延期或破裂 → 关系恶化。

## 7. 地点参数占位
- 触发阈值（逾期天数、金额）
- 拉扯轮数上限
- 调解者权限和成功率
- 解决方式的映射
- 收成差时纠纷概率上升系数