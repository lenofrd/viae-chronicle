# 水权纠纷

## 1. 目的
定义水权纠纷的触发、拉扯、调解、后果。水权纠纷是 Brookvale 最核心的冲突类型，因为旱季水少，上游和下游利益天然对立。

## 2. 核心概念
- **触发**：上游截水、轮灌争执、下游缺水、水渠被堵。
- **拉扯**：双方多轮交涉，引用轮灌规则、地契、祖传约定、人情。
- **调解**：里正、长老、见证人介入。
- **后果**：关系恶化、惩罚、制度强化或松动、心理影响。
- **旱季高发**：水位下降时冲突概率上升。
- **空间差异**：上游有地理优势，下游依赖规则约束上游。

## 3. 冲突状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| conflict_id | string | 唯一 ID |
| upstream_party | string | 上游方 |
| downstream_party | string | 下游方 |
| trigger_event | string | 触发事件 |
| stage | enum | 触发/争执/调解/解决/破裂 |
| intensity | float 0–1 | 激烈程度 |
| negotiation_rounds | list | 拉扯记录 |
| resolution | enum? | 解决方式 |

## 4. 演化规则

### 4.1 触发
```
条件：上游截水被发现，或下游缺水严重
效果：生成 conflict_started 事件
      conflict_type = water-disputes
      stage = 触发
      生成争执事件
滞后：发现可能有滞后
影响范围：上下游双方
```

### 4.2 拉扯
```
条件：冲突进入争执阶段
效果：多轮交涉，每轮：
      - 发起方提出要求（恢复供水/赔偿/道歉）
      - 接收方根据 trust、利益、关系历史回应
      - 可能同意、拒绝、拖延、提条件、反诉
      轮数受 intensity 和重要性影响
      生成 conflict_negotiation_round 事件
滞后：每轮按 tick
影响范围：双方
```

### 4.3 调解
```
条件：双方僵持，或一方请求调解
效果：里正/长老介入
      调解者根据制度、关系、舆论提出方案
      双方接受或拒绝
      生成 conflict_mediated 事件
滞后：按调解时机
影响范围：双方、调解者、社区
```

### 4.4 解决
```
条件：双方达成协议或调解成功
效果：恢复供水、赔偿、道歉、调整轮灌
      生成 conflict_resolved 事件
      关系可能缓和或维持紧张
滞后：按协议执行
影响范围：双方、制度
```

### 4.5 破裂
```
条件：调解失败、一方拒绝、冲突升级
效果：关系恶化、可能暴力或长期对抗
      制度被挑战
      生成 conflict_broken 事件
滞后：按冲突演化
影响范围：双方、社区
```

### 4.6 后果
```
条件：冲突解决或破裂
效果：关系变化（结怨/和解）
      制度强化或松动
      心理影响（愤怒、委屈、恐惧）
      地位和声誉变化
      记录冲突后果
滞后：长期过程
影响范围：双方、社区
```

## 5. 事件类型
- `conflict_started`：{conflict_id, conflict_type: water-disputes, upstream_party, downstream_party, trigger_event}
- `conflict_negotiation_round`：{conflict_id, round, initiator, responder, proposal, response}
- `conflict_mediated`：{conflict_id, mediator_id, outcome}
- `conflict_resolved`：{conflict_id, resolution, terms}
- `conflict_broken`：{conflict_id, reason}

## 6. 与其他系统的接口
- 读：03-hydrology 的水位和灌溉条件；02-institutions/01-water-rights 的轮灌规则；03-relationships 的上下游关系；08-hazards 的旱情。
- 写：03-relationships 的结怨或和解；02-institutions 的制度强化或松动；05-education 的水权规训；06-stratification 的地位变化。
- 因果链：旱季水位下降 → 轮灌紧张 → 上游截水 → 下游发现 → 争执 → 调解 → 惩罚或包庇 → 关系变化 → 制度松动或强化。

## 7. 地点参数占位
- 触发阈值（水位、缺水程度）
- 拉扯轮数上限
- 调解者权限和成功率
- 解决方式的映射
- 后果的影响系数