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

## 8. 实现状态（任务 15 阶段二：只做机制）

> 阶段二只落地「赊账 + 2 轮私下催收」最小切片；调解、公开惩罚、村规、信任/恩怨状态均未实现，且不在本阶段范围。

- **债务来源**：集市赊账（`market.credit`）。仅集市日、仅 `eligible_items`（当前 `[grain]`）、零利息；买方库存 < `min_shortage`、卖方库存 ≥ `min_surplus` 时当期交粮，生成 `debt_formed`（`origin="market_credit"`、`due_tick`）；单户未清偿赊账 ≤ `max_per_household`，已有赊账逾期未清时不新增。
- **触发**：赊账逾期 ≥ `conflict.debt_dispute.trigger_overdue_days`，且债务家庭处于「有粮但不还」窗口 `refusal_threshold < 存粮 ≤ trigger_max_grain`（阶段三语义修正，默认 2 < 存粮 ≤ 5）；断粮（≤ `refusal_threshold`）不进会话，走既有 `debt_defaulted` / `debt_collection_attempt` 强制扣粮；只有 `origin="market_credit"` 的债务参与，借粮路径不变。
- **会话（固定 2 轮，不悬置）**：
  - 第 1 轮债权人提诉求：亲缘 → 延期；有违约前科 → 全额；否则 → 部分（`partial_ratio`）。
  - 第 2 轮债务人回应：有粮足额 → 还款；零粮（≤ `refusal_threshold`）→ 拒绝；有粮不足 → 请求延期（债权人按「亲缘或曾守约」接受，否则坚持）。
  - 判定只读既有事实：家庭库存、逾期天数、事件流中的 `debt_defaulted` / `debt_repaid`、直接亲缘；**不引入 trust/grudge/obligation 新状态**。
- **结果**：还款/部分还款 → `debt_repaid(source="debt_dispute")` + `conflict_resolved`；延期 → `debt_deferred`（更新 `due_tick`，`dispute_started_tick` 清零进入下一周期）+ `conflict_resolved`；拒绝/债权人坚持 → `conflict_broken`，该笔不再重复发起会话，后续仍走既有 `debt_defaulted` / `debt_collection_attempt`。
- **事件**：新增 `conflict_started`、`conflict_negotiation_round`、`conflict_resolved`、`conflict_broken`、`debt_deferred`；复用 `debt_formed`（可选 `origin`）、`debt_repaid`。
- **结算顺序**：催收会话在每日 `_collect_debts` 强制扣粮**之前**执行，让「有粮赖账」窗口先被会话看到；会话还款后设置 `last_collected_tick`，同 tick 不重复扣粮（5 种子 × 3600 实测双重扣粮 0）。
- **验收口径（阶段三第 2 轮）**：5 种子 × 3600，人口 5/5、无 `agent_error`/负值、守恒 gap 全 0、双重扣粮 0；34 次会话、全额 13/延期 11/拒绝 8。原「催收 ≥1 次/种子」门槛降级为「合计 ≥1 次且 ≥2 个种子发生会话，且三种结果各出现 ≥1 次」：seed 1/123 人口后段下滑、债务家庭长期零粮（`debt_defaulted` 27/30 次），按语义正确走强制扣粮，不产生会话；人口问题记入 `11-life-course.md` §18 G1，不挡本切片验收。
- **配置**：`market.credit` 与 `conflict.debt_dispute` 全部标 `[调参]`（`max_rounds` 固定 2 除外）；数值为保守初始值。