# 向上通道

## 1. 目的
定义角色从低地位向高地位流动的路径、门槛、成功率、失败后果。向上通道是 aspiration 的主要指向，也是拉扯和冲突的来源。

## 2. 核心概念
- **向上通道**：学手艺、联姻、争里正、买田、识字、认干亲。
- **门槛**：进入通道需要满足的条件（学费、劳力、关系、技能、彩礼）。
- **成功率**：受技能、关系、财富、声誉、时机影响。
- **失败后果**：浪费钱财、耽误时间、关系恶化、aspiration 受挫。
- **通道竞争**：有限的通道位置（如里正只有一个），竞争产生冲突。
- **通道与制度**：制度定义谁有资格走通道。

## 3. 向上通道清单（第一版）
| 通道 | 门槛 | 成功条件 | 失败后果 |
|---|---|---|---|
| 学手艺 | 拜师礼、家里同意、劳力机会成本 | 师傅愿意教、学徒努力、学成 | 浪费学费、耽误农时、师徒关系破裂 |
| 联姻 | 彩礼、门当户对、媒人 | 双方家庭同意、当事人接受 | 彩礼损失、名声受损、关系恶化 |
| 争里正 | 声望、关系、长老支持 | 被推举、有威望 | 得罪人、关系恶化 |
| 买田 | 积蓄、卖家愿意卖 | 价格合适、地契清晰 | 积蓄耗尽、买到差田 |
| 识字 | 学费、私塾名额 | 学有所成、能写会算 | 学费浪费、耽误劳作 |
| 认干亲 | 关系、礼物 | 对方接受、形成庇护 | 被拒绝、丢面子 |

## 4. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| available_channels | list | 当前可尝试的通道 |
| channel_attempts | dict | 各通道尝试记录 |
| channel_success_rate | dict | 各通道成功率 |
| blocked_reasons | list | 被阻止的原因 |

## 5. 演化规则

### 5.1 通道识别
```
条件：角色有 aspiration
效果：根据 aspiration、门槛、关系，识别可行通道
      生成 channel_identified 事件
滞后：无
影响范围：角色
```

### 5.2 门槛检查
```
条件：角色尝试某通道
效果：检查门槛（学费、劳力、关系、技能、彩礼）
      不满足则 blocked，记录 blocked_reasons
      生成 upward_attempt（outcome = blocked）
滞后：无
影响范围：角色
```

### 5.3 尝试与成功率
```
条件：门槛满足，角色尝试
效果：按 channel_success_rate 判定
      成功率受技能、关系、财富、声誉、时机影响
      成功 → status 或 role 变化
      失败 → 记录失败后果
      生成 upward_attempt 事件
滞后：按通道类型
影响范围：角色
```

### 5.4 失败后果
```
条件：尝试失败
效果：财富损失、时间浪费、关系恶化、aspiration 受挫
      可能放弃或再次尝试
      生成 upward_attempt（outcome = failed）
滞后：按通道
影响范围：角色
```

### 5.5 通道竞争
```
条件：多人竞争同一通道位置
效果：按 reputation、关系、wealth 排序
      失败者可能记恨成功者
      生成 channel_competition 事件
滞后：按竞争时机
影响范围：竞争者
```

### 5.6 通道与制度
```
条件：制度变化
效果：通道门槛和资格可能变化
      如村规修改允许/禁止某类人走某通道
      生成 channel_rule_changed 事件
滞后：按制度变化
影响范围：角色
```

## 6. 事件类型
- `channel_identified`：{agent_id, channel, feasibility}
- `upward_attempt`：{agent_id, channel, outcome, cause}
- `channel_competition`：{channel, competitors, winner, losers}
- `channel_rule_changed`：{channel, old_rule, new_rule, cause}

## 7. 与其他系统的接口
- 读：05-education 的技能；03-relationships 的关系；02-institutions 的资格规则；06-status 的当前地位。
- 写：06-status 的地位变化；03-relationships 的关系变化（竞争、记恨）；07-conflicts 的通道冲突；人物系统的 aspiration 和 blocked_attempts。
- 因果链：想学手艺 → 家里缺劳力不让 → blocked → aspiration 受挫 → 偷偷学 → 被发现 → 家庭冲突。

## 8. 地点参数占位
- 向上通道清单和门槛
- 各通道的成功率
- 失败后果的映射
- 通道竞争的规则
- 制度对通道的影响