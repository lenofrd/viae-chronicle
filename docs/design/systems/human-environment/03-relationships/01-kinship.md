# 亲缘关系

## 1. 目的
定义亲缘关系的类型、权利义务、强度、变化规则。亲缘是小镇关系网络最基础的骨架，决定继承、赡养、婚配、互助的基本格局。

## 2. 核心概念
- **直系亲缘**：父母子女、祖孙。有强赡养和抚养义务。
- **旁系亲缘**：兄弟姐妹、叔伯姑舅、堂表亲。有互助义务，强度随距离递减。
- **姻亲**：通过婚姻形成的关系，如岳家、婆家、连襟。
- **亲缘强度**：随日常互动、共同经历变化，不是一成不变。
- **亲缘义务**：赡养、抚养、婚姻协商支持、丧葬参与。
- **亲缘断裂**：分家、断绝关系、长期不往来。

## 3. 亲缘关系字段
| 字段 | 类型 | 说明 |
|---|---|---|
| kinship_type | enum | 直系/旁系/姻亲 |
| degree | int | 亲缘距离（1=父母子女，2=兄弟姐妹，3=叔伯） |
| obligation_strength | float 0–1 | 义务强度 |
| cohabitation | bool | 是否同住 |
| inheritance_rights | dict | 继承权利（第一版简化） |
| support_duties | list | 赡养/抚养义务 |

## 4. 演化规则

### 4.1 亲缘形成
```
条件：出生、婚姻、收养
效果：建立亲缘关系边
      设置初始 kinship_type、degree、obligation_strength
      生成 relation_formed 事件
滞后：无
影响范围：相关角色
```

### 4.2 亲缘强度变化
```
条件：日常互动、共同经历、冲突
效果：strength 按互动频率和质量变化
      共同经历重大事件（灾害、丧事）→ strength 上升
      长期不往来 → strength 缓慢下降
      受 max_delta_per_tick 约束
滞后：渐进
影响范围：亲缘关系边
```

### 4.3 义务履行
```
条件：亲缘义务被触发（赡养、抚养、婚配支持）
效果：履行则 obligation 平衡，trust 上升
      不履行则 trust 下降，可能触发冲突
      生成 obligation_changed 事件
滞后：按义务类型
影响范围：亲缘关系边
```

### 4.4 分家与断裂
```
条件：分家、断绝关系、严重冲突
效果：cohabitation 变化，obligation_strength 下降
      严重时 relation_ended
      生成 relation_ended 事件
滞后：分家是事件，断裂是过程
影响范围：亲缘关系边
```

### 4.5 继承与婚配
```
条件：长辈去世、子女婚配
效果：按 inheritance_rights 分配财产
      亲缘网络用于识别禁婚亲属、建立姻亲关系并提供家庭支持；不按亲缘关系自动配对，婚姻候选遵循人物系统的双向认知门槛（见 agents/12-population-and-marriage.md）。当前代码明确排除亲子及同父/同母兄弟姐妹；更远亲属的禁婚范围尚未完整实现
      生成 inheritance_event / marriage_event
滞后：按事件
影响范围：亲缘网络
```

## 5. 事件类型
- `relation_formed`：{from_agent, to_agent, relation_type: kinship, kinship_type, degree}
- `relation_ended`：{from_agent, to_agent, reason}
- `obligation_changed`：{from_agent, to_agent, old, new, cause}
- `inheritance_event`：{deceased, heirs, distribution}
- `marriage_event`：{parties, kinship_links_formed}

## 6. 与其他系统的接口
- 读：人物系统的出生、死亡、婚姻事件；02-institutions 的继承和赡养规则。
- 写：05-education 的家庭教养通道；03-debt 的亲缘债务；07-conflicts 的亲缘纠纷；06-stratification 的亲缘地位传递。
- 因果链：长辈去世 → 继承分配 → 亲缘关系变化 → 可能的继承纠纷 → 关系恶化或强化。

## 7. 地点参数占位
- 初始亲缘网络
- 亲缘义务的具体规则（赡养/抚养/婚配支持）
- 亲缘强度变化速率
- 分家和断裂的触发条件
- 继承规则

### 4.3a 家庭照料与互助（ADR 008）

- 直系亲缘的抚养、赡养义务可成为家庭照料决策的重要依据；旁系亲属和姻亲可按亲缘强度、共同生活与既往互动提供互助。
- 亲缘义务影响照料意愿/优先级，不等于无条件自动成功。照料者必须有行动能力、时间和可用资源；冲突、疏远、自身危机可使义务未履行。
- 同户成员对失能者、患病者、老人和幼儿的照料优先考虑，但家庭成员关系与个人意愿仍然有效。
- 履行/未履行重要照料义务可沿用 `obligation_changed`、关系互动和事件日志表达；不另建平行亲缘状态。
- 家庭成员无法代办或全户失能时，转入邻里报告/里正紧急核查流程。公共救济规则见 [ADR 008](../../../decisions/008-household-coordination-nutrition-and-voluntary-reserves.md)。
