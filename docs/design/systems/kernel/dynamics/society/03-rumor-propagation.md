# 谣言传播

## 1. 目的
定义谣言如何沿关系网络传播、变形、衰减。谣言不是全局即时共享的，它沿关系路径传播，有速度、有变形、有可信度衰减。

## 2. 核心概念
- **传播路径**：沿关系边传播，受 trust、strength、互动频率影响。
- **传播速度**：关系越紧密、场所越公共，传播越快。
- **变形**：多轮传播后内容可能夸大、扭曲、添加细节。
- **可信度衰减**：传播越远，可信度越低。
- **公共空间加速**：水井、集市等公共空间传播快。
- **舆论形成**：多人议论同一谣言，形成社区舆论。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| spread_scope | list | 已传播到的角色 |
| spread_velocity | float | 传播速度 |
| distortion_level | float 0–1 | 变形程度 |
| credibility | float 0–1 | 当前可信度 |
| public_attention | float 0–1 | 公共关注度 |

## 4. 演化规则

### 4.1 传播概率
```
条件：角色 A 与他人 B 互动，且 A 知道某谣言
效果：传播概率 = base_rate * trust_factor(A→B) * strength_factor(A→B) *场所_factor
      传播成功则 B 获得谣言
      生成 information_spread 事件
滞后：传播需要人际接触
影响范围：关系边
```

### 4.2 传播速度
```
条件：谣言在传播中
效果：spread_velocity 受以下影响：
      - 关系紧密程度
      - 场所类型（公共空间快）
      - 内容敏感度（越劲爆越快）
      - 传播者活跃度
      生成 spread_velocity_changed 事件
滞后：无
影响范围：谣言
```

### 4.3 变形
```
条件：每轮传播
效果：按变形概率判定
      变形类型：夸大、扭曲、添加细节、改变对象
      distortion_level 上升
      current_content 更新
      credibility 可能上升或下降
      生成 information_distorted 事件
滞后：多轮传播后累积
影响范围：谣言
```

### 4.4 可信度衰减
```
条件：传播距离增加
效果：每跳 credibility *= credibility_decay
      接收者 belief_level = credibility * trust_factor(source)
      生成 belief_level_changed 事件
滞后：无
影响范围：谣言
```

### 4.5 公共空间加速
```
条件：谣言进入公共空间
效果：传播概率和速度上升
      多人同时获知
      生成 information_spread（多人）
滞后：按公共空间聚集
影响范围：公共空间及参与者
```

### 4.6 谣言消散
```
条件：被证伪、被遗忘、被新谣言取代
效果：public_attention 衰减
      spread_velocity 下降
      低于阈值后停止传播
      生成 information_forgotten 事件
滞后：长期过程
影响范围：谣言
```

## 5. 事件类型
- `information_spread`：{info_id, from_agent, to_agent, tick, distortion}
- `information_distorted`：{info_id, old_content, new_content, distortion_level}
- `spread_velocity_changed`：{info_id, old, new, cause}
- `belief_level_changed`：{agent_id, info_id, old, new, cause}
- `information_forgotten`：{info_id, cause}

## 6. 与其他系统的接口
- 读：03-relationships 的 trust 和 strength；01-social-spaces 的场所类型；04-information 的谣言内容。
- 写：04-information 的 spread_scope 和 credibility；03-relationships 的 trust 变化；07-conflicts 的谣言激化；04-public-spaces 的舆论形成。
- 因果链：偷盗事件 → 目击者传谣 → 谣言变形 → 多人议论 → 公共空间加速 → 舆论形成 → 被中伤者地位下降。

## 7. 地点参数占位
- base_rate（基础传播概率）
- trust_factor、strength_factor 的系数
- 场所_factor（公共空间加速系数）
- 变形概率和变形类型
- credibility_decay（可信度衰减率）
- 消散阈值