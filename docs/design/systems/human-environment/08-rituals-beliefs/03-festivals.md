# 节庆

## 1. 目的
定义节庆的周期、场所、参与者、活动、功能、冲突。节庆是社区凝聚、信息交换、婚配机会、情绪释放的核心场景。

## 2. 核心概念
- **节庆周期**：春节、端午、中秋、地方性节庆。
- **节庆场所**：祠堂、集市空地、各家。
- **参与者**：全村或大部分村民。
- **活动**：祭祀、宴席、娱乐、走亲访友、集市交易。
- **功能**：凝聚社区、信息交换、婚配机会、情绪释放、经济交换。
- **冲突**：谁家办、排场攀比、谁被邀请、谁被冷落。

## 3. 节庆字段
| 字段 | 类型 | 说明 |
|---|---|---|
| festival_id | string | 唯一 ID |
| festival_type | enum | 春节/端午/中秋/地方性 |
| location | string | 祠堂/集市/各家 |
| organizer | string | 组织者 |
| participants | list | 参与者 |
| activities | list | 活动清单 |
| schedule_tick | int | 预定 tick |

## 4. 演化规则

### 4.1 节庆预定
```
条件：周期到达
效果：生成 festival_scheduled 事件
      确定组织者、活动、场所
      通知村民
滞后：按周期
影响范围：全村
```

### 4.2 节庆举行
```
条件：预定 tick 到达
效果：村民参与节庆活动
      祭祀、宴席、娱乐、走亲访友、集市交易
      生成 festival_started / festival_ended 事件
滞后：无
影响范围：参与者
```

### 4.3 社区凝聚
```
条件：节庆参与
效果：社区纽带上升
      关系强化
      情绪释放
      生成 community_bond_changed 事件
滞后：按节庆
影响范围：参与者
```

### 4.4 信息交换
```
条件：节庆聚集
效果：信息在节庆中快速传播
      收成传闻、婚配消息、外来消息
      生成 information_spread 事件
滞后：按节庆
影响范围：参与者
```

### 4.5 婚配机会
```
条件：节庆聚集
效果：未婚男女有更多接触机会
      家长观察、媒人牵线
      生成 courtship_opportunity 事件
滞后：按节庆
影响范围：未婚男女及家庭
```

### 4.6 节庆冲突
```
条件：排场攀比、谁被邀请、谁被冷落、活动争议
效果：节庆前后发生争执
      关系恶化或舆论形成
      生成 festival_dispute 事件
滞后：按冲突时机
影响范围：村民
```

## 5. 事件类型
- `festival_scheduled`：{festival_id, festival_type, location, organizer, activities}
- `festival_started` / `festival_ended`：{festival_id, participants}
- `community_bond_changed`：{community_id, old, new, cause}
- `information_spread`：{festival_id, info_id, participants}
- `courtship_opportunity`：{festival_id, participants, outcome}
- `festival_dispute`：{festival_id, parties, dispute_area, outcome}

## 6. 与其他系统的接口
- 读：01-social-spaces 的祠堂和集市；04-information 的信息；03-relationships 的婚配关系；05-education 的价值观传递。
- 写：03-relationships 的关系强化和婚配；04-information 的信息传播；06-stratification 的婚配流动；07-conflicts 的节庆冲突。
- 因果链：春节 → 走亲访友 → 信息交换 → 婚配机会 → 关系形成 → 社区凝聚。

## 7. 地点参数占位
- 节庆清单和周期
- 场所和组织者
- 活动清单
- 信息传播速度
- 婚配机会的规则
- 节庆冲突的触发条件