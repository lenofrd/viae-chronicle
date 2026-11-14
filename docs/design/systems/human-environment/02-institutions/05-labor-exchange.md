# 互助换工

## 1. 目的
定义互助换工制度的规则、执行、违反、冲突和变迁。农忙缺劳力、修渠出工、建房帮工都依赖换工，换工是人情和债务的来源。

## 2. 核心概念
- **换工**：今天我帮你插秧，明天你帮我收割，以工换工。
- **人情账**：换工不平衡时形成人情债，欠人情的人需要找机会还。
- **换工圈**：经常互相换工的人形成稳定关系。
- **修渠出工**：公共水利工程按户出工，不出工需以粮代工。
- **执行者**：里正协调公共工程，私人换工靠约定和人情。
- **违反**：答应换工不来、出工偷懒、长期欠人情不还。

## 3. 规则内容（地点参数可配）
| 字段 | 说明 |
|---|---|
| exchange_norms | 换工规范（等价交换/人情优先） |
| public_work_rules | 公共工程出工规则 |
| substitution_rules | 以粮代工规则 |
| enforcement_authority | 公共工程由里正协调，私人换工靠约定 |
| violation_types | 违反类型（爽约/偷懒/欠人情不还） |

## 4. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| rule_content | dict | 换工规则 |
| enforcement_state | enum | 严格执行/宽松执行/名存实亡 |
| challenge_count | int | 被挑战次数 |
| looseness | float 0–1 | 松动程度 |
| exchange_ledger | dict | 人物之间的换工账（谁欠谁多少工） |
| public_work_status | dict | 公共工程出工状态 |

## 5. 演化规则

### 5.1 换工记录
```
条件：人物之间发生换工
效果：exchange_ledger 更新
      记录谁帮谁、多少工、什么时候
      生成 labor_exchanged 事件
滞后：无
影响范围：参与换工的人物
```

### 5.2 人情账平衡
```
条件：换工不平衡
效果：欠人情的人被标记
      欠人情时间越长，压力越大
      还人情时关系改善
滞后：长期过程
影响范围：参与换工的人物
```

### 5.3 违反判定：爽约/偷懒
```
条件：答应换工不来，或出工偷懒
效果：生成 rule_violated 事件
      violation_type = 爽约/偷懒
      severity 按影响程度
      若被对方发现，触发冲突
滞后：发现可能有滞后
影响范围：双方关系
```

### 5.4 公共工程出工
```
条件：里正组织修渠、修路、建房
效果：按户分配出工任务
      出工记录，不出工需以粮代工
      生成 public_work_assigned / public_work_completed 事件
滞后：按工程进度
影响范围：全体村民
```

### 5.5 执行与惩罚
```
条件：违反被确认
效果：私人换工靠关系惩罚（减少未来换工、舆论压力）
      公共工程由里正按规则处理（补工/罚粮/公开批评）
      生成 rule_enforced 事件
滞后：按惩罚类型
影响范围：违反者、对方、社区
```

### 5.6 制度挑战与修改
```
条件：村民认为换工规则不公、公共工程负担过重
效果：生成 rule_challenged 事件
      挑战可能成功（调整出工规则）或失败
      修改后 looseness 重置
滞后：反复挑战后才可能修改
影响范围：制度及全体村民
```

## 6. 事件类型
- `labor_exchanged`：{from_agent, to_agent, amount, activity, tick}
- `debt_formed` / `debt_repaid`：{debtor_id, creditor_id, amount, cause}
- `rule_violated`：{rule_id: labor-exchange, violator_id, violation_type, severity, witnesses}
- `rule_enforced`：{rule_id: labor-exchange, violator_id, enforcer_id, punishment}
- `public_work_assigned` / `public_work_completed`：{work_id, assigned_agents, progress}
- `rule_challenged`：{rule_id: labor-exchange, challenger_id, reason, outcome}
- `rule_modified`：{rule_id: labor-exchange, old_content, new_content, cause}

## 7. 与其他系统的接口
- 读：03-relationships 的换工关系；04-information 的爽约是否被知道；05-soil-and-fields 的农忙季节；08-hazards 的灾害后修复需求。
- 写：03-relationships 的人情债和关系变化；07-conflicts 的换工纠纷；05-education 的互助规训；人物系统读换工账做决策。
- 因果链：农忙缺劳力 → 换工 → 欠人情 → 还人情 → 关系深化；爽约 → 关系恶化 → 未来换工减少 → 生产困难。

## 8. 地点参数占位
- exchange_norms
- public_work_rules
- substitution_rules
- enforcement_authority
- violation_types 和 severity 分级
- 初始 looseness 和 enforcement_state
- 人情账的压力系数
- 公共工程的出工分配规则