# 婚丧嫁娶

## 1. 目的
定义婚丧嫁娶仪式的类型、流程、参与者、功能、冲突。婚丧嫁娶是人生关键节点的仪式，确认关系、传递规矩、社区参与、地位展示。

## 2. 核心概念
- **婚礼**：提亲、定亲、彩礼、迎亲、婚宴。
- **丧礼**：报丧、守灵、出殡、下葬、祭奠。
- **满月/成年礼**：出生、满月、成年。
- **参与者**：家庭、宗族、邻里、媒人。
- **功能**：确认关系、传递规矩、社区参与、地位展示、经济交换。
- **冲突**：彩礼、排场、谁坐主位、仪式流程。

## 3. 婚丧嫁娶字段
| 字段 | 类型 | 说明 |
|---|---|---|
| ritual_id | string | 唯一 ID |
| ritual_type | enum | 婚礼/丧礼/满月/成年礼 |
| principal | string | 主角（新人/逝者/孩子） |
| family | list | 家庭参与者 |
| organizer | string | 组织者 |
| participants | list | 参与者 |
| schedule_tick | int | 预定 tick |

## 4. 演化规则

### 4.1 仪式预定
```
条件：人生节点事件（婚约、死亡、出生、成年）
效果：生成 ritual_scheduled 事件
      确定主角、家庭、组织者、参与者
      准备彩礼/祭品/宴席
滞后：按仪式类型
影响范围：家庭、宗族
```

### 4.2 婚礼流程
```
条件：婚约达成
效果：提亲 → 定亲 → 彩礼 → 迎亲 → 婚宴
      每一步有交涉和拉扯
      生成 ritual_started / ritual_ended 事件
滞后：按婚礼周期
影响范围：双方家庭、宗族
```

### 4.3 丧礼流程
```
条件：角色死亡
效果：报丧 → 守灵 → 出殡 → 下葬 → 祭奠
      宗族和邻里参与
      生成 ritual_started / ritual_ended 事件
滞后：按丧礼周期
影响范围：家庭、宗族、邻里
```

### 4.4 仪式功能
```
条件：仪式完成
效果：关系确认（婚姻、继承）
      社区参与和凝聚
      地位展示（排场）
      经济交换（彩礼、礼金）
      生成 community_bond_changed 事件
滞后：按仪式
影响范围：参与者
```

### 4.5 仪式冲突
```
条件：彩礼争议、排场攀比、谁坐主位、流程分歧
效果：仪式前后发生争执
      关系恶化或舆论形成
      生成 ritual_dispute 事件
滞后：按冲突时机
影响范围：家庭、宗族
```

### 4.6 仪式与地位
```
条件：排场大小
效果：排场大 → 地位展示，声誉上升
      排场小 → 可能被议论
      生成 status_effect 事件
滞后：按仪式
影响范围：家庭
```

## 5. 事件类型
- `ritual_scheduled`：{ritual_id, ritual_type, principal, family, organizer}
- `ritual_started` / `ritual_ended`：{ritual_id, participants}
- `wedding_negotiation`：{ritual_id, round, parties, proposal, response}
- `community_bond_changed`：{community_id, old, new, cause}
- `ritual_dispute`：{ritual_id, parties, dispute_area, outcome}
- `status_effect`：{family_id, effect, severity}

## 6. 与其他系统的接口
- 读：03-kinship 的亲属关系；02-institutions 的继承和婚配规则；03-relationships 的婚配关系；01-social-spaces 的祠堂。
- 写：03-relationships 的婚姻和亲属关系；06-stratification 的地位展示；07-conflicts 的彩礼和排场冲突；04-information 的婚配消息传播。
- 因果链：婚约达成 → 提亲 → 彩礼交涉 → 婚礼 → 关系确认 → 社区凝聚。

## 7. 地点参数占位
- 婚丧嫁娶的类型和流程
- 彩礼和礼金的规则
- 参与者规则
- 排场和地位展示的映射
- 仪式冲突的触发条件