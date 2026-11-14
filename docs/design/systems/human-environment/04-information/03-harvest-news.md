# 收成传闻

## 1. 目的
定义收成相关信息的产生、传播、可信度变化，以及收成传闻如何影响人物决策（借粮、卖粮、囤粮、改种）。

## 2. 核心概念
- **收成信息**：谁家收成好、谁家收成差、今年整体丰歉。
- **信息来源**：亲眼所见（田里长势）、邻里闲聊、里正统计、粮商报价。
- **信息不对称**：自家知道自家收成，别家只能猜；隐瞒收成是常见行为。
- **传闻影响**：收成传闻影响借粮难度、粮价、婚配、地价、税收。
- **丰歉对比**：丰年传闻让人放松，歉年传闻让人紧张。
- **隐瞒与夸大**：有人隐瞒丰收（怕借粮、怕税收），有人夸大歉收（博同情、求减免）。

## 3. 收成信息字段
| 字段 | 类型 | 说明 |
|---|---|---|
| info_id | string | 唯一 ID |
| subject | string | 关于谁/哪片田的收成 |
| reported_yield | enum | 丰收/平收/歉收/绝收 |
| actual_yield | float | 实际收成（系统内部知道） |
| source_agent | string | 信息来源 |
| credibility | float 0–1 | 可信度 |
| hidden_or_exaggerated | bool | 是否被隐瞒或夸大 |

## 4. 演化规则

### 4.1 收成信息产生
```
条件：收割完成
效果：生成收成知识条目
      知道的人：劳作参与者、目击者、里正（统计）
      不知道的人：其他村民
      生成 information_created 事件
滞后：收割后
影响范围：参与者和目击者
```

### 4.2 收成信息传播
```
条件：邻里闲聊、集市议论、水井边传话
效果：收成信息沿关系网络传播
      传播中可能被隐瞒、夸大、扭曲
      生成 information_spread 事件
滞后：按传播路径
影响范围：社区
```

### 4.3 隐瞒与夸大
```
条件：角色有动机（怕借粮、怕税收、博同情）
效果：传播时修改 reported_yield
      hidden_or_exaggerated = true
      接收者收到的是修改后的版本
      生成 information_distorted 事件
滞后：无
影响范围：传播网络
```

### 4.4 收成信息验证
```
条件：交粮、借粮、卖粮时暴露真实收成
效果：验证 → credibility 上升
      证伪 → 传播者 trust 下降
      生成 information_verified / information_falsified 事件
滞后：按验证时机
影响范围：相关角色
```

### 4.5 收成传闻影响决策
```
条件：角色掌握收成传闻
效果：丰年传闻 → 借粮容易、粮价低、婚配活跃
      歉年传闻 → 借粮难、粮价高、囤粮、推迟婚配
      传闻影响人物决策，见人物系统
滞后：按决策时机
影响范围：社区
```

### 4.6 里正统计
```
条件：秋收后，里正统计各户收成
效果：生成相对准确的收成信息
      可信度高于邻里传闻
      但里正可能被贿赂或施压，篡改统计
      生成 official_harvest_record 事件
滞后：秋收后
影响范围：里正和社区
```

## 5. 事件类型
- `information_created`：{info_id, info_type: 事实, subject, reported_yield, source_agent}
- `information_spread`：{info_id, from_agent, to_agent, tick, distortion}
- `information_distorted`：{info_id, old_yield, new_yield, hidden_or_exaggerated}
- `information_verified` / `information_falsified`：{info_id, agent_id, evidence}
- `official_harvest_record`：{recorder_id, records, credibility}

## 6. 与其他系统的接口
- 读：05-soil-and-fields 的收成事件；01-social-spaces 的集市和水井；03-relationships 的传播路径。
- 写：03-debt 的借贷决策；02-institutions 的税收和减免；06-stratification 的贫富变化；人物系统读收成传闻做决策。
- 因果链：歉收 → 收成传闻传播 → 债权人收紧借贷 → 债务人借不到粮 → 关系恶化 → 冲突或迁徙。

## 7. 地点参数占位
- 收成信息的产生规则
- 传播速度系数
- 隐瞒和夸大的动机和概率
- 里正统计的可信度和篡改概率
- 收成传闻对决策的影响系数