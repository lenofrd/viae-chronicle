# 向外接口

## 1. 目的
定义角色离开小镇的通道、门槛、意图、尝试，以及第一版只记录不执行的处理方式。向外接口是“终生在小镇”故事的暗线：他没走，但想过走。

## 2. 核心概念
- **向外接口**：外出求学、投亲靠友、做工经商、参军、婚嫁外迁、逃荒。
- **门槛**：路费、关系、勇气、家庭责任、信息。
- **意图**：想走的原因（贫困、冲突、好奇、抱负、逃婚、逃债）。
- **尝试**：打听消息、攒路费、托人介绍、走到山口又回来。
- **第一版不执行离开**：只记录意图和镇内结果，角色最终留在镇内。
- **未走的原因**：家庭牵绊、路费不够、信息不足、害怕、错过时机、被劝阻。

## 3. 向外接口清单（第一版）
| 接口 | 门槛 | 典型意图 | 未走原因 |
|---|---|---|---|
| 外出求学 | 学费、路费、关系、识字基础 | 抱负、向上 | 学费不够、家里不让 |
| 投亲靠友 | 亲戚关系、路费、信息 | 贫困、冲突 | 亲戚不靠谱、路费不够 |
| 做工经商 | 门路、路费、技能 | 贫困、抱负 | 没门路、怕被骗 |
| 参军 | 征召、身体、路费 | 逃债、抱负、被迫 | 家里需要、害怕 |
| 婚嫁外迁 | 媒人、彩礼、关系 | 逃婚、向上、家庭安排 | 舍不得家、对方不靠谱 |
| 逃荒 | 灾害、路费、体力 | 生存 | 走不动、舍不得家、路上更危险 |

## 4. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| outward_aspiration | float 0–1 | 向外意图强度 |
| aspiration_reason | string? | 意图原因 |
| outward_attempts | list | 尝试记录 |
| blocked_reasons | list | 未走原因 |
| information_about_outside | list | 掌握的外界信息 |

## 5. 演化规则

### 5.1 意图形成
```
条件：贫困、冲突、灾害、外来消息、抱负
效果：outward_aspiration 上升
      记录 aspiration_reason
      生成 aspiration_changed 事件
滞后：渐进
影响范围：角色
```

### 5.2 信息收集
```
条件：角色有向外意图
效果：打听外界消息（货郎、亲戚、逃难者）
      获得 information_about_outside
      生成 outward_info_gathered 事件
滞后：按信息获取
影响范围：角色
```

### 5.3 尝试与受阻
```
条件：角色尝试向外（攒路费、托人、走到山口）
效果：检查门槛
      不满足则受阻，记录 blocked_reasons
      满足则可能走到山口又回来（第一版不执行离开）
      生成 outward_attempt 事件
滞后：按尝试
影响范围：角色
```

### 5.4 未走的原因
```
条件：尝试后未离开
效果：记录未走原因（家庭牵绊、路费不够、害怕、被劝阻）
      aspiration 可能下降（放弃）或维持（等待时机）
      生成 aspiration_abandoned 或 aspiration_maintained 事件
滞后：按事件
影响范围：角色
```

### 5.5 意图与心理
```
条件：向外意图长期未实现
效果：可能形成遗憾、不甘、认命
      影响心理状态和人生叙事
      生成 aspiration_psychological_effect 事件
滞后：长期过程
影响范围：角色
```

### 5.6 第一版约束
```
条件：所有向外尝试
效果：不执行实际离开
      角色最终留在镇内
      记录意图、尝试、未走原因
      作为人生暗线
滞后：无
影响范围：角色
```

## 6. 事件类型
- `aspiration_changed`：{agent_id, type: outward, old, new, cause}
- `outward_info_gathered`：{agent_id, info_id, source}
- `outward_attempt`：{agent_id, channel, outcome, blocked_reason}
- `aspiration_abandoned`：{agent_id, reason}
- `aspiration_maintained`：{agent_id, reason}
- `aspiration_psychological_effect`：{agent_id, effect, severity}

## 7. 与其他系统的接口
- 读：04-information 的外来消息；02-institutions 的约束；03-relationships 的家庭牵绊；自然环境 08-hazards 的灾害（逃荒动机）。
- 写：人物系统的心理状态（遗憾、不甘、认命）；06-aspiration 的意图变化；记录系统的人生暗线。
- 因果链：灾害 → 贫困 → 向外意图 → 打听消息 → 攒路费 → 家里老人病倒 → 未走 → 遗憾终身。

## 8. 地点参数占位
- 向外接口清单和门槛
- 意图形成的触发条件
- 信息收集的渠道
- 尝试的成功/受阻概率
- 未走原因的映射
- 心理影响的规则