# 谣言传播

## 1. 目的
定义谣言的形成、传播、变形、可信度变化、消散。谣言是信息环境中最活跃的部分，是拉扯和冲突的催化剂。

## 2. 核心概念
- **谣言**：未经证实的信息，可能是真、可能是假、可能半真半假。
- **传播路径**：沿关系边传播，受信任度、互动频率、场所影响。
- **传播速度**：关系越紧密、场所越公共，传播越快。
- **变形**：多轮传播后内容可能夸大、扭曲、添油加醋。
- **可信度衰减**：传播越远，可信度越低，但变形可能让内容更“劲爆”而重新获得关注。
- **舆论形成**：多人议论同一谣言，形成社区舆论。
- **谣言消散**：被证伪、被遗忘、被新谣言取代。

## 3. 谣言状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| rumor_id | string | 唯一 ID |
| original_content | string | 原始内容 |
| current_content | string | 当前传播版本 |
| distortion_level | float 0–1 | 变形程度 |
| credibility | float 0–1 | 当前可信度 |
| spread_scope | list | 已传播到的角色 |
| spread_velocity | float | 传播速度 |
| public_attention | float 0–1 | 公共关注度 |
| truth_value | bool? | 真实值（系统内部知道，角色不知道） |

## 4. 演化规则

### 4.1 谣言形成
```
条件：角色对某事件不确定，或出于恶意/无意编造
效果：生成谣言条目
      设置 original_content、credibility、truth_value
      生成 information_created 事件（info_type = 传闻）
滞后：无
影响范围：编造者
```

### 4.2 谣言传播
```
条件：角色与他人互动，且提及谣言
效果：按关系 trust 和互动频率判定传播概率
      接收者 belief_level = credibility * trust_factor
      传播者加入 spread_scope
      生成 information_spread 事件
滞后：传播需要人际接触
影响范围：关系网络
```

### 4.3 传播速度
```
条件：谣言在传播中
效果：spread_velocity 受以下影响：
      - 关系紧密程度（strength）
      - 场所类型（公共空间传播快）
      - 内容敏感度（越劲爆传播越快）
      - 传播者活跃度
      生成 spread_velocity_changed 事件
滞后：无
影响范围：谣言传播网络
```

### 4.4 谣言变形
```
条件：每轮传播
效果：按变形概率判定是否变形
      变形类型：夸大、扭曲、添加细节、改变对象
      distortion_level 上升
      current_content 更新
      credibility 可能上升（更劲爆）或下降（更离谱）
      生成 information_distorted 事件
滞后：多轮传播后累积
影响范围：谣言
```

### 4.5 舆论形成
```
条件：谣言被多人议论，public_attention 超过阈值
效果：形成社区舆论
      舆论影响关系、地位、冲突
      生成 opinion_formed 事件
滞后：多次议论后
影响范围：社区
```

### 4.6 谣言验证与消散
```
条件：被证实、被证伪、被遗忘、被新谣言取代
效果：证实 → credibility 上升，传播加速，生成 information_verified
      证伪 → credibility 大幅下降，传播减速，生成 information_falsified
      遗忘 → public_attention 衰减到阈值以下
      取代 → 新谣言 public_attention 超过旧谣言
      生成 information_forgotten 事件
滞后：按验证或遗忘过程
影响范围：谣言及传播网络
```

### 4.7 谣言与冲突
```
条件：谣言涉及冲突相关方
效果：可能激化冲突
      被谣言中伤者 trust 下降，可能触发 07-conflicts
      生成 rumor_triggered_conflict 事件
滞后：按传播和舆论形成
影响范围：相关角色
```

## 5. 事件类型
- `information_created`：{info_id, info_type: 传闻, content, source_agent, credibility}
- `information_spread`：{info_id, from_agent, to_agent, tick, distortion}
- `information_distorted`：{info_id, old_content, new_content, distortion_level}
- `spread_velocity_changed`：{info_id, old, new, cause}
- `opinion_formed`：{info_id, topic, stance, participants}
- `information_verified` / `information_falsified`：{info_id, agent_id, evidence}
- `information_forgotten`：{info_id, cause}
- `rumor_triggered_conflict`：{info_id, parties, conflict_type}

## 6. 与其他系统的接口
- 读：03-relationships 的 trust 和 strength；01-social-spaces 的场所类型；02-institutions 的违规事件（谣言素材）。
- 写：03-relationships 的 trust 和关系变化；07-conflicts 的冲突触发；06-stratification 的地位变化（舆论影响地位）；04-public-spaces 的舆论形成。
- 因果链：偷盗事件 → 目击者传谣 → 谣言变形 → 多人议论 → 舆论形成 → 被中伤者地位下降 → 冲突。

## 7. 地点参数占位
- 谣言形成概率
- 传播概率（按关系类型、场所类型）
- 变形概率和变形类型
- credibility 变化规则
- 舆论形成阈值
- 谣言消散和遗忘速率
- 谣言触发冲突的阈值