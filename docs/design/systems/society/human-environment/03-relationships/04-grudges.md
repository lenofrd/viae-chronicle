# 恩怨关系

## 1. 目的
定义恩怨关系的形成、累积、爆发、化解。恩怨是负面关系的核心，是冲突和拉扯的深层动力。

## 2. 核心概念
- **恩怨来源**：背叛、欺骗、伤害、羞辱、不公、争夺。
- **恩怨强度**：0–1，随事件累积，随时间可能淡化。
- **恩怨类型**：私怨（个人之间）、家怨（家族之间）、公怨（对不公规则的怨恨）。
- **恩怨记忆**：恩怨带具体事件记忆，人物能说出“他当年怎么对我”。
- **恩怨爆发**：恩怨累积到阈值可能触发冲突。
- **恩怨化解**：道歉、赔偿、调解、时间淡化。

## 3. 恩怨关系字段
| 字段 | 类型 | 说明 |
|---|---|---|
| grudge_source | list | 恩怨来源事件 |
| grudge_intensity | float 0–1 | 恩怨强度 |
| grudge_type | enum | 私怨/家怨/公怨 |
| last_trigger_tick | int? | 上次被触发 tick |
| resolution_attempts | list | 化解尝试记录 |

## 4. 演化规则

### 4.1 恩怨形成
```
条件：背叛、欺骗、伤害、羞辱、不公事件
效果：建立或强化恩怨关系
      grudge_intensity 按事件严重度增加
      grudge_source 记录事件
      生成 grudge_formed / grudge_intensified 事件
滞后：无
影响范围：相关角色
```

### 4.2 恩怨累积
```
条件：多次负面事件
效果：grudge_intensity 累积
      超过阈值可能触发冲突
      受 max_delta_per_tick 约束
滞后：累积过程
影响范围：恩怨关系边
```

### 4.3 恩怨淡化
```
条件：长期无冲突、对方示好、第三方调解
效果：grudge_intensity 缓慢下降
      但不归零，除非明确化解
      生成 grudge_weakened 事件
滞后：长期过程
影响范围：恩怨关系边
```

### 4.4 恩怨爆发
```
条件：grudge_intensity 超过爆发阈值，且有触发事件
效果：触发 07-conflicts
      冲突类型按恩怨类型
      生成 grudge_erupted 事件
滞后：条件满足后 1–3 tick
影响范围：恩怨关系边及社区
```

### 4.5 恩怨化解
```
条件：道歉、赔偿、调解成功
效果：grudge_intensity 大幅下降
      可能消除恩怨
      生成 grudge_resolved 事件
滞后：化解需要时间和诚意
影响范围：恩怨关系边
```

### 4.6 恩怨记忆
```
条件：人物回忆、被问起
效果：人物能说出恩怨来源事件
      记忆影响当前判断
      不因时间淡化而完全遗忘
滞后：无
影响范围：人物认知
```

## 5. 事件类型
- `grudge_formed`：{from_agent, to_agent, source_event, intensity}
- `grudge_intensified`：{from_agent, to_agent, old, new, cause}
- `grudge_weakened`：{from_agent, to_agent, old, new, cause}
- `grudge_erupted`：{from_agent, to_agent, conflict_type, intensity}
- `grudge_resolved`：{from_agent, to_agent, resolution_type}

## 6. 与其他系统的接口
- 读：07-conflicts 的冲突事件；03-debt 的违约；02-institutions 的不公执行；04-information 的传言。
- 写：07-conflicts 的爆发触发；03-trust 的 trust 下降；人物系统的心理状态（怨恨、恐惧）；05-education 的恩怨记忆传递。
- 因果链：被背叛 → 恩怨形成 → 多次摩擦累积 → 恩怨爆发 → 冲突 → 关系破裂或调解 → 恩怨化解或加深。

## 7. 地点参数占位
- 恩怨形成的严重度映射
- 恩怨累积速率
- 恩怨淡化速率
- 爆发阈值
- 化解的条件和效果
- 恩怨记忆的持续时间