# 债务关系

## 1. 目的
定义债务关系的形成、履行、违约、变化。债务是人情和经济的双重纽带，欠债和讨债是拉扯的重要场景。

## 2. 核心概念
- **债务类型**：粮食借贷、工具借用、劳力换工、银钱借贷（第一版以粮食和劳力为主）。
- **债权人/债务人**：谁欠谁。
- **债务额度**：欠多少（粮、工、钱）。
- **利息/人情**：是否要还更多，还是只还本金。
- **还款期限**：约定何时还，或“什么时候有什么时候还”。
- **违约**：逾期不还、赖账、以次充好。
- **债务与关系**：债务影响 trust 和 obligation；违约可能触发冲突。

## 3. 债务关系字段
| 字段 | 类型 | 说明 |
|---|---|---|
| debt_type | enum | 粮食/工具/劳力/银钱 |
| amount | float | 债务额度 |
| interest_rate | float | 利息或人情系数 |
| due_tick | int? | 约定还款 tick，null 表示无固定期限 |
| status | enum | 未还/部分还/已还/违约 |
| creditor_id | string | 债权人 |
| debtor_id | string | 债务人 |

## 4. 演化规则

### 4.1 债务形成
```
条件：借粮、借工具、换工不平衡
效果：建立债务关系边
      设置 debt_type、amount、due_tick
      生成 debt_formed 事件
滞后：无
影响范围：债权人和债务人
```

### 4.2 债务履行
```
条件：债务人归还
效果：amount 减少，status 更新
      还清则 status = 已还，obligation 平衡
      trust 可能上升
      生成 debt_repaid 事件
滞后：按还款行为
影响范围：债务关系边
```

### 4.3 债务违约
```
条件：逾期未还，或明确赖账
效果：status = 违约
      trust 下降
      obligation 压力上升
      可能触发 07-conflicts 的债务纠纷
      生成 debt_defaulted 事件
滞后：按 due_tick
影响范围：债务关系边
```

### 4.4 债务与关系
```
条件：债务存续期间
效果：债权人 trust 受债务状态影响
      债务人 obligation 压力随时间上升
      长期欠债 → 关系恶化
      按时还债 → 关系强化
滞后：渐进
影响范围：债务关系边
```

### 4.5 债务转移与豁免
```
条件：债务转移给他人、债权人豁免
效果：更新 creditor_id 或 amount
      生成 debt_transferred / debt_forgiven 事件
滞后：按事件
影响范围：相关角色
```

## 5. 事件类型
- `debt_formed`：{creditor_id, debtor_id, debt_type, amount, due_tick}
- `debt_repaid`：{creditor_id, debtor_id, amount, remaining}
- `debt_defaulted`：{creditor_id, debtor_id, amount, overdue_ticks}
- `debt_transferred`：{old_creditor, new_creditor, debtor, amount}
- `debt_forgiven`：{creditor_id, debtor_id, amount, cause}

## 6. 与其他系统的接口
- 读：03-kinship 和 03-neighborhood 的初始关系；02-institutions 的借贷规则；05-soil-and-fields 的收成（决定还款能力）。
- 写：07-conflicts 的债务纠纷；03-trust 的 trust 变化；05-education 的债务观念；人物系统读债务状态做决策。
- 因果链：收成差 → 借粮 → 欠债 → 逾期 → 讨债 → 纠纷 → 关系恶化；按时还债 → trust 上升 → 未来更容易借到。

## 7. 地点参数占位
- 债务类型和初始利息/人情系数
- 还款期限规则
- 违约的 trust 惩罚
- obligation 压力系数
- 债务纠纷的触发条件

## 8. 实现状态（任务 08）

> 本节记录任务 08 已落地的粮食债务闭环；利息/人情、债务转移与豁免、trust/obligation 联动、07-conflicts 债务纠纷触发等为未来完整模型，当前未实现。

### 8.1 数据结构（已实现）
- `DebtRecord`（见 `src/vale/core/state.py`）：`creditor_id`、`amount`（≥0）、`originated_tick`、`due_tick`、`last_collected_tick`（可空）、`overdue`。
- `AgentState.debts: list[DebtRecord]` 为唯一事实源；`AgentState.debt` 改为 `@computed_field` 派生值（= 各记录 `amount` 求和），**只读不可赋值**，消除双写不一致。任何对 `agent.debt = X` 的赋值会抛 `AttributeError`，须操作 `.debts` 列表。

### 8.2 演化规则（已实现）
- **债务形成**（`borrow_grain` 动作）：在他人中按存粮降序选存粮 ≥ 借出量的债主（纯函数 `select_creditor`，感知与执行共用保证一致）；扣债主粮、加借粮者粮（世界总粮守恒），append `DebtRecord`，`due_tick = 当前 tick + debt.due_days`。无债主 → 动作不可行。
- **每日结算**（`AgentModule._settle`，在全部 agent 动作循环之后统一执行，避免迭代中改状态）：
  - 到期催收：`tick >= due_tick` 且（首次 或 `tick - last_collected_tick >= collection_interval_days`）时触发；有粮足额 → 扣粮还债主、记录减少/清零；部分 → 扣尽存粮、剩余标 `overdue`；零粮 → 标 `overdue`。
  - 逾期者 `borrow_grain` 在评分阶段判为不可行，直至逾期债务清零。
- **秋收还款**（`_repay_debts`，秋收动作内调用）：按 `(due_tick, originated_tick)` 升序，单笔还 `min(rec.amount, 预算, 存粮)`，预算上限复用已批准的 `agriculture.harvest_debt_repayment`；清偿记录移出列表。
- 逐人 try/except，失败写 `agent_error`（`phase="daily_settlement"`），不拖垮主循环。
- **守恒与非负**：粮只在角色间转移，不凭空产粮/直接消债；断言粮与债不为负。

### 8.3 事件载荷（已实现，观察层可读）
| event_type | 触发 | 关键字段 |
|---|---|---|
| `debt_formed` | 借粮成功 | creditor/debtor 的 id+name, debt_type, amount, due_tick, originated_tick, 双方 grain_before/after, debt_before/after |
| `debt_collected` | 到期催收（足额或部分） | creditor/debtor 的 id+name, amount_paid, remaining, overdue, 双方 grain_after |
| `debt_defaulted` | 到期零粮 | creditor/debtor 的 id+name, amount, overdue_ticks |
| `debt_repaid` | 秋收还款 | creditor/debtor 的 id+name, amount, remaining, source, 双方 grain_after |

> 1 tick = 1 天（`time.tu_per_tick=10`），`due_days` / `collection_interval_days` 直接映射为 tick 差。

## 9. 任务 09 平衡调参：due_days 90 → 180

- **问题**：任务 08 取 `due_days=90`，借粮集中在春季（tick 8–99），到期日落在夏季（tick 98–189），而秋收在秋季（tick 181+）才发生——债务在秋收前集中到期→催收→违约，与农业产出周期错位，加剧夏季断粮灭绝。
- **调整**：`debt.due_days` 由 90 调为 180（[调参]，`agents.yaml`），使借粮到期跨越秋收，借款人有机会在秋收后还款，降低秋收前集中违约。
- **理由**：纯参数调整，不改规则；仍外置可追溯，等裁决确认。其余债务规则（催收/违约/秋收还款/守恒）不变。