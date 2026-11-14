# 祭祖

## 1. 目的
定义祭祖仪式的周期、场所、参与者、流程、功能、冲突。祭祖是宗族凝聚、继承确认、价值观传递的核心仪式。

## 2. 核心概念
- **祭祖周期**：清明、冬至、祖先忌日、重大事件（婚嫁、分家、中举）。
- **祭祖场所**：祠堂（宗族共同）、祖坟（各房各支）。
- **参与者**：宗族成员，按辈分和性别有不同角色。
- **主持者**：族长/长老/长房。
- **祭品**：粮食、酒、肉、纸钱，按户分摊。
- **功能**：凝聚宗族、确认继承、传递价值观、强化辈分秩序。
- **冲突**：谁主持、谁出钱、继承争议、排场攀比。

## 3. 祭祖仪式字段
| 字段 | 类型 | 说明 |
|---|---|---|
| ritual_id | string | 唯一 ID |
| ritual_type | enum | 清明/冬至/忌日/重大事件 |
| location | string | 祠堂/祖坟 |
| organizer | string | 主持者 |
| participants | list | 参与者及角色 |
| offerings | dict | 祭品和分摊 |
| schedule_tick | int | 预定 tick |

## 4. 演化规则

### 4.1 仪式预定
```
条件：周期到达，或重大事件触发
效果：生成 ritual_scheduled 事件
      确定主持者、参与者、祭品分摊
      生成 ritual_scheduled 事件
滞后：按周期
影响范围：宗族
```

### 4.2 仪式举行
```
条件：预定 tick 到达
效果：宗族成员聚集祠堂/祖坟
      按辈分和性别分工
      举行祭祀流程
      生成 ritual_started / ritual_ended 事件
滞后：无
影响范围：参与者
```

### 4.3 参与与角色
```
条件：宗族成员参与
效果：按辈分和性别分配角色
      长辈主持，晚辈参与，女性有特定角色
      参与者获得信仰强化和宗族认同
      生成 ritual_participation 事件
滞后：按仪式
影响范围：参与者
```

### 4.4 缺席与议论
```
条件：宗族成员缺席
效果：记录缺席原因
      可能被议论（不孝、不敬）
      关系恶化或舆论压力
      生成 ritual_absent 事件
滞后：按仪式
影响范围：缺席者、宗族
```

### 4.5 仪式冲突
```
条件：主持权争议、祭品分摊不均、继承争议
效果：仪式前后发生争执
      可能影响仪式进行
      生成 ritual_dispute 事件
滞后：按冲突时机
影响范围：宗族
```

### 4.6 仪式功能
```
条件：仪式完成
效果：宗族凝聚力上升
      辈分秩序强化
      价值观传递（孝顺、团结）
      生成 community_bond_changed 事件
滞后：长期过程
影响范围：宗族
```

## 5. 事件类型
- `ritual_scheduled`：{ritual_id, ritual_type: ancestor-worship, location, organizer, participants}
- `ritual_started` / `ritual_ended`：{ritual_id, participants, roles}
- `ritual_participation`：{ritual_id, agent_id, role, attitude}
- `ritual_absent`：{ritual_id, agent_id, reason}
- `ritual_dispute`：{ritual_id, parties, dispute_area, outcome}
- `community_bond_changed`：{community_id, old, new, cause}

## 6. 与其他系统的接口
- 读：03-kinship 的宗族关系；01-social-spaces 的祠堂和祖坟；02-institutions 的继承规则；05-education 的家庭教养。
- 写：03-relationships 的宗族纽带；05-education 的价值观传递；06-stratification 的辈分秩序；07-conflicts 的继承和主持权冲突。
- 因果链：长辈去世 → 祭祖仪式 → 继承确认 → 宗族凝聚 → 辈分秩序强化。

## 7. 地点参数占位
- 祭祖周期和日期
- 场所（祠堂/祖坟）
- 主持者规则
- 祭品分摊规则
- 角色分工（按辈分/性别）
- 缺席的舆论惩罚
- 冲突触发条件