# 外来消息

## 1. 目的
定义外来消息（货郎、逃难者、官方告示、远方亲戚）如何进入小镇、传播、影响人物认知和决策。第一版外来消息低频，但存在。

## 2. 核心概念
- **外来消息**：来自镇外的信息，通过货郎、逃难者、官方差役、远方亲戚带入。
- **消息类型**：外面世界的事（战争、饥荒、新政）、商品信息（盐铁价格）、亲戚消息、官方告示。
- **可信度**：外来消息可信度不确定，有人信、有人疑。
- **传播**：外来消息先在集市、水井传播，再扩散到全村。
- **影响**：外来消息影响人物对外部世界的认知、对未来的判断、是否考虑向外。
- **第一版低频**：外来消息不是日常，几个月一次，但每次可能引发讨论。

## 3. 外来消息字段
| 字段 | 类型 | 说明 |
|---|---|---|
| news_id | string | 唯一 ID |
| news_type | enum | 外面世界/商品/亲戚/官方 |
| content | string | 消息内容 |
| source | string | 货郎/逃难者/差役/亲戚 |
| arrival_tick | int | 进入小镇 tick |
| credibility | float 0–1 | 可信度 |
| spread_scope | list | 已传播到的角色 |

## 4. 演化规则

### 4.1 消息进入
```
条件：货郎到访、逃难者路过、差役来镇、亲戚来信
效果：生成外来消息条目
      消息首先被少数人获知（集市上的人、里正、亲戚）
      生成 information_created 事件（info_type = 外来消息）
滞后：无
影响范围：首批获知者
```

### 4.2 消息传播
```
条件：首批获知者在公共空间提及
效果：消息沿关系网络传播
      传播速度受消息敏感度和可信度影响
      生成 information_spread 事件
滞后：按传播路径
影响范围：社区
```

### 4.3 可信度判断
```
条件：角色接收外来消息
效果：belief_level 受来源 trust、消息内容与既有认知的一致性影响
      与既有认知冲突的消息可信度低
      来自信任来源的消息可信度高
      生成 belief_level_changed 事件
滞后：无
影响范围：接收角色
```

### 4.4 消息影响决策
```
条件：角色掌握外来消息
效果：影响对外部世界的认知
      可能激发“向外”意图（见 06-stratification）
      影响商品交易、婚配、迁徙意向
      生成 news_influenced_decision 事件
滞后：按决策时机
影响范围：角色
```

### 4.5 消息淡出
```
条件：长期无新消息、无验证
效果：public_attention 衰减
      角色逐渐遗忘
      生成 information_forgotten 事件
滞后：长期过程
影响范围：社区
```

### 4.6 第一版频率控制
```
条件：外来消息注入
效果：第一版低频，每季最多 1–2 条
      消息内容由地点参数预设或外部注入
      不开放实时外部世界模拟
滞后：按频率
影响范围：社区
```

## 5. 事件类型
- `information_created`：{news_id, news_type, content, source, credibility}
- `information_spread`：{news_id, from_agent, to_agent, tick}
- `belief_level_changed`：{agent_id, news_id, old, new, cause}
- `news_influenced_decision`：{agent_id, news_id, decision}
- `information_forgotten`：{news_id, cause}

## 6. 与其他系统的接口
- 读：01-social-spaces 的集市和水井；03-relationships 的信任；06-stratification 的向外意图。
- 写：06-stratification 的向外意图激发；人物系统读外来消息做决策；04-rumors 的消息可能演变为谣言。
- 因果链：货郎带来盐价上涨消息 → 集市议论 → 村民囤盐 → 盐价进一步上涨 → 贫户买不起盐 → 关系紧张。

## 7. 地点参数占位
- 外来消息的初始清单和预设内容
- 消息进入频率（第一版每季 1–2 条）
- 消息来源类型和可信度
- 传播速度系数
- 可信度判断的规则
- 消息影响决策的系数