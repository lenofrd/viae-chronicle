# 舆论形成

## 1. 目的
定义舆论如何从多人议论中形成、强化、转向、消散。舆论是社区层面的态度和压力，影响制度执行、关系变化、地位升降。

## 2. 核心概念
- **舆论**：社区对某件事、某个人、某条规则的集体态度。
- **形成条件**：多人议论、多次事件累积、公共空间传播。
- **舆论强度**：0–1，支持或反对的力度。
- **舆论方向**：支持/反对/中立/分裂。
- **舆论压力**：对当事人和制度执行的压力。
- **舆论转向**：新事件、新信息、关键人物表态可能改变舆论。
- **舆论消散**：被新话题取代、时间淡化、问题解决。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| topic | string | 舆论话题 |
| direction | enum | 支持/反对/中立/分裂 |
| intensity | float 0–1 | 舆论强度 |
| participants | list | 参与议论的角色 |
| pressure | float 0–1 | 对当事人的压力 |
| related_events | list | 相关事件 |

## 4. 演化规则

### 4.1 舆论形成
```
条件：同一话题被多人多次议论
效果：intensity 累积
      超过阈值后形成舆论
      确定 direction 和 participants
      生成 opinion_formed 事件
滞后：多次议论后
影响范围：社区
```

### 4.2 舆论强化
```
条件：新事件支持现有舆论、关键人物表态
效果：intensity 上升
      participants 增加
      生成 opinion_intensified 事件
滞后：按事件
影响范围：舆论
```

### 4.3 舆论转向
```
条件：新信息推翻原有认知、关键人物改变立场
效果：direction 变化
      intensity 可能重置
      生成 opinion_shifted 事件
滞后：按事件
影响范围：舆论
```

### 4.4 舆论压力
```
条件：舆论形成后
效果：对当事人产生压力
      影响制度执行（支持或反对惩罚）
      影响关系（排挤或支持）
      生成 opinion_pressure 事件
滞后：按舆论强度
影响范围：当事人、制度
```

### 4.5 舆论分裂
```
条件：社区对话题意见分歧
效果：direction = 分裂
      intensity 可能上升（对立加剧）
      生成 opinion_split 事件
滞后：按分歧程度
影响范围：社区
```

### 4.6 舆论消散
```
条件：问题解决、新话题取代、时间淡化
效果：intensity 衰减
      低于阈值后消散
      生成 opinion_dissipated 事件
滞后：长期过程
影响范围：舆论
```

## 5. 事件类型
- `opinion_formed`：{topic, direction, intensity, participants}
- `opinion_intensified`：{topic, old_intensity, new_intensity, cause}
- `opinion_shifted`：{topic, old_direction, new_direction, cause}
- `opinion_pressure`：{topic, target, pressure_type, severity}
- `opinion_split`：{topic, factions, cause}
- `opinion_dissipated`：{topic, cause}

## 6. 与其他系统的接口
- 读：04-information 的谣言和事实；01-social-spaces 的公共空间议论；03-relationships 的传播网络；02-institutions 的违规和惩罚。
- 写：02-institutions 的制度执行压力；03-relationships 的排挤或支持；06-stratification 的地位升降；07-conflicts 的冲突激化或缓和。
- 因果链：偷盗事件 → 谣言传播 → 多人议论 → 舆论形成 → 压力增大 → 祠堂公开惩罚 → 舆论支持 → 村规强化。

## 7. 地点参数占位
- 舆论形成的议论次数阈值
- intensity 的累积和衰减速率
- 关键人物的影响力系数
- 舆论压力的影响系数
- 舆论转向的条件
- 舆论消散的速率