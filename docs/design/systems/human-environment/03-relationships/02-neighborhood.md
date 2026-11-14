# 邻里关系

## 1. 目的
定义邻里关系的类型、互动规则、强度变化。邻里是日常互动最频繁的关系，换工、借物、传谣、纠纷都发生在邻里之间。

## 2. 核心概念
- **邻里**：住在附近、田地相邻、日常见面的人。
- **日常互动**：借农具、换工、串门、闲聊、帮忙。
- **邻里强度**：随互动频率和质量变化。
- **邻里义务**：红白喜事帮忙、灾害互助、看家护院。
- **邻里纠纷**：地界、水权、家畜破坏庄稼、孩童打架。
- **邻里舆论**：邻里是舆论形成的基本单位。

## 3. 邻里关系字段
| 字段 | 类型 | 说明 |
|---|---|---|
| proximity | enum | 紧邻/同片/同镇 |
| interaction_frequency | float | 互动频率 |
| mutual_help_history | list | 互助历史 |
| dispute_history | list | 纠纷历史 |

## 4. 演化规则

### 4.1 邻里形成
```
条件：迁入、分家、建房
效果：建立邻里关系边
      设置初始 proximity
      生成 relation_formed 事件
滞后：无
影响范围：相关角色
```

### 4.2 日常互动
```
条件：借物、换工、串门、闲聊
效果：strength 按互动质量变化
      正向互动 → trust 上升，strength 上升
      负向互动 → trust 下降
      生成 interaction_occurred 事件
滞后：渐进
影响范围：邻里关系边
```

### 4.3 邻里义务
```
条件：红白喜事、灾害、急难
效果：履行义务 → trust 和 strength 上升
      不履行 → trust 下降，舆论压力
      生成 obligation_changed 事件
滞后：按事件
影响范围：邻里关系边
```

### 4.4 邻里纠纷
```
条件：地界、水权、家畜、孩童冲突
效果：触发 07-conflicts
      纠纷结果改变 trust 和 strength
      生成 dispute_event
滞后：按纠纷处理
影响范围：邻里关系边
```

### 4.5 邻里舆论
```
条件：邻里间多次议论同一话题
效果：形成邻里层面的舆论
      舆论影响 trust 和关系
      见 04-information/rumors.md
滞后：多次议论后
影响范围：邻里网络
```

## 5. 事件类型
- `relation_formed`：{from_agent, to_agent, relation_type: neighborhood, proximity}
- `interaction_occurred`：{from_agent, to_agent, interaction_type, outcome}
- `obligation_changed`：{from_agent, to_agent, old, new, cause}
- `dispute_event`：{parties, dispute_type, outcome}

## 6. 与其他系统的接口
- 读：01-social-spaces 的场所互动；02-institutions 的邻里义务规则；04-information 的舆论。
- 写：03-debt 的邻里借还；07-conflicts 的邻里纠纷；04-information 的舆论传播；05-education 的邻里规训。
- 因果链：借农具 → trust 上升 → 未来换工更容易；家畜破坏庄稼 → 纠纷 → trust 下降 → 邻里关系恶化。

## 7. 地点参数占位
- 初始邻里网络
- proximity 分级和影响
- 邻里义务的具体规则
- 互动频率和 strength 变化速率
- 邻里纠纷的触发条件