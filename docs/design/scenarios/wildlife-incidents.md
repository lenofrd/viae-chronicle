# 野兽下山与伤人

## 1. 目的
定义野兽下山的触发、传播、影响范围、后果和恢复。野兽下山是 07-fauna 的下游事件，影响人物安全和家畜。

## 2. 核心概念
- 触发条件：food_shortage 和 aggression 超过阈值，来自 07-fauna。
- 下山路径：深山 → 浅山 → 镇域边缘。
- 影响范围：山脚、田地、镇域边缘、家畜。
- 后果：家畜受害、人员受伤或死亡、庄稼被毁、人物恐惧和心理迁移。
- 可逆性：家畜死亡不可逆，人员伤亡不可逆，庄稼损失当季不可逆。
- 滞后：条件满足后 1–5 tick 内下山。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| descent_active | bool | 是否已下山 |
| descent_severity | enum | 轻度/中度/重度 |
| descent_duration | int | 已持续 tick |
| affected_units | list | 受影响的空间单元 |
| incidents | list | 遭遇事件记录 |

## 4. 演化规则

### 4.1 触发
```
条件：每 tick 检查
      food_shortage > descent_food_threshold
      或 aggression > descent_aggression_threshold
      且 随机通过
效果：生成 wildlife_descended 事件
      descent_active = true
      descent_severity 由攻击性和食物短缺程度决定
滞后：条件满足后 1–5 tick 内触发
影响范围：深山 → 浅山 → 镇域边缘
```

### 4.2 活动范围
```
条件：descent_active = true
效果：危险动物在浅山和镇域边缘活动
      可能进入田地、家畜圈、镇域边缘
      每 tick 按概率触发遭遇
滞后：无
影响范围：浅山、山脚、田地、镇域边缘
```

### 4.3 遭遇与伤人
```
条件：人物或家畜在活动范围内
效果：按 aggression 和遭遇概率判定
      生成 wildlife_incident 事件
      incident_type：家畜受害/庄稼被毁/人员受伤/人员死亡
      事件成为人物心理迁移和后续事件的父事件
滞后：无
影响范围：按人物、家畜、地点
```

### 4.4 结束
```
条件：食物短缺缓解、动物被猎杀、动物返回深山
效果：descent_active = false
      生成 disaster_ended 事件
      记录损失
滞后：返回深山需要条件满足
影响范围：受影响单元
```

### 4.5 后果记录
```
条件：disaster_ended
效果：汇总 affected_units、incidents、损失
      不可逆损失：家畜死亡、人员伤亡
      可逆损失：庄稼可补种，家畜可补充
影响范围：所有受影响单元
```

## 5. 事件类型
- `disaster_triggered`：{disaster_type: wildlife, severity, affected_units, cause}
- `wildlife_descended`：{from_habitat, to_unit, species, cause}
- `wildlife_incident`：{habitat_id, species, incident_type, severity, affected_agents}
- `disaster_ended`：{disaster_type: wildlife, duration, total_damage}

## 6. 与其他系统的接口
- 读：07-fauna 的食物短缺、攻击性、下山状态；06-vegetation 的植被状态；人物系统的猎杀和防范事件。
- 写：07-fauna 猎杀后种群和攻击性变化；人物系统触发伤亡、恐惧、组织猎杀、加强防范；记录系统记录遭遇事件。
- 因果链：捕猎过度 → 猎物减少 → 食物短缺 → 野兽下山 → 家畜受害/人员伤亡 → 人物组织猎杀 → 种群下降 → 下山减少。

## 7. 地点参数占位
- descent_food_threshold（食物短缺阈值）
- descent_aggression_threshold（攻击性阈值）
- 下山触发概率和滞后范围
- 遭遇概率、伤人概率、致死概率
- 家畜受害概率
- 猎杀效果和风险
- 返回深山的条件