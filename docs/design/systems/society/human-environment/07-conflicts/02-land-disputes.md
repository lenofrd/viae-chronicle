# 地界冲突

## 1. 目的
定义地界冲突的触发、拉扯、调解、后果。地界冲突源于越界、界石移动、灾害后地界模糊。

## 2. 核心概念
- **触发**：犁过界、多占一垄、移动界石、灾害后地界模糊。
- **拉扯**：双方引用地契、见证人、祖传约定。
- **调解**：里正、地契见证人、邻地双方。
- **后果**：恢复原界、赔粮、关系恶化、制度强化或松动。
- **灾害后高发**：山洪冲毁田埂后地界模糊，冲突概率上升。

## 3. 冲突状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| conflict_id | string | 唯一 ID |
| party_a | string | 一方 |
| party_b | string | 另一方 |
| field_a | string | 一方田地 |
| field_b | string | 另一方田地 |
| trigger_event | string | 触发事件 |
| stage | enum | 触发/争执/调解/解决/破裂 |
| intensity | float 0–1 | 激烈程度 |

## 4. 演化规则

### 4.1 触发
```
条件：越界被发现，或灾害后地界模糊
效果：生成 conflict_started 事件
      conflict_type = land-disputes
      stage = 触发
滞后：发现可能有滞后
影响范围：相邻田地双方
```

### 4.2 拉扯
```
条件：冲突进入争执阶段
效果：多轮交涉
      一方主张地界，另一方反驳
      引用地契、见证人、祖传约定
      可能同意恢复原界、拒绝、提反诉
      生成 conflict_negotiation_round 事件
滞后：每轮按 tick
影响范围：双方
```

### 4.3 调解
```
条件：双方僵持
效果：里正/地契见证人介入
      验证地契、询问见证人、现场勘察
      提出方案
      生成 conflict_mediated 事件
滞后：按调解时机
影响范围：双方、调解者
```

### 4.4 解决
```
条件：双方达成协议或调解成功
效果：恢复原界、重新划界、赔粮、道歉
      生成 conflict_resolved 事件
滞后：按协议执行
影响范围：双方、制度
```

### 4.5 破裂
```
条件：调解失败、一方拒绝
效果：关系恶化、长期对抗
      可能反复冲突
      生成 conflict_broken 事件
滞后：按冲突演化
影响范围：双方、社区
```

### 4.6 灾害后地界模糊
```
条件：山洪冲毁田埂、滑坡掩埋界石
效果：地界标志消失
      disputed_boundaries 增加
      触发地界冲突
滞后：灾害后立即
影响范围：受灾田地
```

## 5. 事件类型
- `conflict_started`：{conflict_id, conflict_type: land-disputes, party_a, party_b, trigger_event}
- `conflict_negotiation_round`：{conflict_id, round, initiator, responder, proposal, response}
- `conflict_mediated`：{conflict_id, mediator_id, outcome}
- `conflict_resolved`：{conflict_id, resolution, terms}
- `conflict_broken`：{conflict_id, reason}

## 6. 与其他系统的接口
- 读：02-institutions/02-land-boundaries 的地界规则；03-relationships 的相邻关系；08-hazards 的灾害后果。
- 写：03-relationships 的结怨或和解；02-institutions 的制度强化或松动；06-stratification 的地位变化。
- 因果链：山洪冲毁田埂 → 地界模糊 → 双方各执一词 → 争执 → 里正调解 → 重新划界或维持原界 → 关系变化。

## 7. 地点参数占位
- 触发阈值
- 拉扯轮数上限
- 调解者权限和成功率
- 灾害后地界模糊的概率
- 后果的影响系数