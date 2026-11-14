# 祭山神

## 1. 目的
定义祭山神仪式的周期、场所、参与者、流程、功能、冲突。祭山神是 Brookvale 与自然环境最直接耦合的仪式，祈求丰收、缓解灾害恐惧、强化山林禁忌。

## 2. 核心概念
- **祭山神周期**：春耕前（祈丰收）、秋收后（谢山神）、灾害后（求平息）。
- **祭山神场所**：山神庙、山口、神树前。
- **参与者**：全村或大部分村民。
- **主持者**：长老/祭司/里正。
- **祭品**：粮食、酒、牲畜（大户出）、香火。
- **功能**：祈求丰收、缓解灾害恐惧、强化山林禁忌、凝聚社区。
- **冲突**：祭品分摊、仪式流程、禁忌解释、谁主持。

## 3. 祭山神仪式字段
| 字段 | 类型 | 说明 |
|---|---|---|
| ritual_id | string | 唯一 ID |
| ritual_type | enum | 春祈/秋谢/灾害后 |
| location | string | 山神庙/山口/神树前 |
| organizer | string | 主持者 |
| participants | list | 参与者 |
| offerings | dict | 祭品和分摊 |
| associated_taboo | string? | 关联的禁忌 |

## 4. 演化规则

### 4.1 仪式预定
```
条件：春耕前、秋收后、灾害后
效果：生成 ritual_scheduled 事件
      确定主持者、祭品分摊
      通知村民
滞后：按周期或灾害
影响范围：全村
```

### 4.2 仪式举行
```
条件：预定 tick 到达
效果：村民聚集山神庙/山口
      长老/祭司主持
      献祭、祈祷、讲述山神传说
      生成 ritual_started / ritual_ended 事件
滞后：无
影响范围：参与者
```

### 4.3 信仰强化
```
条件：仪式参与
效果：信仰强度上升
      禁忌内化上升
      敬畏心理上升
      生成 belief_strength_changed 事件
滞后：按仪式
影响范围：参与者
```

### 4.4 灾害后仪式
```
条件：山洪、滑坡、野兽下山等灾害
效果：举行祭山神仪式
      灾害被解释为“山神发怒”或“惩罚”
      信仰强化，禁忌内化
      生成 ritual_started（ritual_type = 灾害后）
滞后：灾害后
影响范围：全村
```

### 4.5 仪式冲突
```
条件：祭品分摊不均、仪式流程争议、禁忌解释分歧
效果：仪式前后发生争执
      可能影响仪式进行
      生成 ritual_dispute 事件
滞后：按冲突时机
影响范围：村民
```

### 4.6 仪式与山林禁忌
```
条件：仪式强化山林禁忌
效果：禁伐禁猎制度获得合法性
      违反禁忌者受舆论谴责
      生成 taboo_internalization_changed 事件
滞后：长期过程
影响范围：村民、山林
```

## 5. 事件类型
- `ritual_scheduled`：{ritual_id, ritual_type: mountain-god, location, organizer, participants}
- `ritual_started` / `ritual_ended`：{ritual_id, participants}
- `belief_strength_changed`：{agent_id, belief_type: mountain-god, old, new, cause}
- `taboo_internalization_changed`：{agent_id, taboo_id, old, new, cause}
- `ritual_dispute`：{ritual_id, parties, dispute_area, outcome}

## 6. 与其他系统的接口
- 读：06-vegetation 的神树和禁伐区；04-information 的山神传说；08-hazards 的灾害事件；01-social-spaces 的山神庙。
- 写：02-institutions/03-forest-rules 的禁忌支撑；06-vegetation 的保护（禁忌减少砍伐）；05-education 的信仰传递；03-relationships 的社区凝聚；07-conflicts 的仪式冲突。
- 因果链：山洪灾害 → 祭山神仪式 → 信仰强化 → 禁忌内化 → 神树保护 → 植被覆盖上升 → 滑坡风险下降。

## 7. 地点参数占位
- 祭山神周期和触发条件
- 场所（山神庙/山口/神树前）
- 主持者规则
- 祭品分摊规则
- 关联的禁忌
- 灾害后仪式的触发规则
- 仪式冲突的触发条件