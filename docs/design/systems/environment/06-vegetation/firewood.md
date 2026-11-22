# 柴薪资源

## 1. 目的
定义柴薪作为日常必需资源的分布、采集、消耗和退化。柴薪是“近山资源有限”的最直接体现：近处砍完，就得走更远。

## 2. 核心概念
- 柴薪资源点：分布在近山、浅山，深山也有但风险高。
- 柴薪存量：按资源点记录。
- 再生速度：中速（月），低于日常消耗速度时就会退化。
- 采集半径：近山柴薪耗尽后，人物必须去更远的浅山砍柴，时间成本上升。
- 采集压力：近山采集压力最高，因为日常可达。
- 柴薪消耗：人物日常做饭、取暖消耗柴薪，按户或按人计算。

## 3. 柴薪资源点字段
| 字段 | 类型 | 说明 |
|---|---|---|
| point_id | string | 唯一 ID |
| parent_zone | string | 所属山林分区 |
| location_desc | string | 位置描述（如“近山东坡”） |
| stock | float | 当前存量 |
| max_stock | float | 最大存量 |
| regeneration_rate | float | 再生速度 |
| gathering_difficulty | enum | 低/中/高 |
| gathering_risk | enum | 无/低/中/高 |
| gathering_pressure | float | 采集压力 |
| travel_time_from_town | string | 从镇域出发的单程时间 |

## 4. 演化规则

### 4.1 柴薪再生
```
条件：每 tick
效果：stock += regeneration_rate * pressure_factor
      stock 不超过 max_stock
滞后：再生是渐进的
影响范围：按资源点
```

### 4.2 柴薪采集
```
条件：人物系统写入 firewood_gathered 事件
效果：stock -= amount
      gathering_pressure += amount * pressure_coefficient
      若 stock < 0，夹紧到 0，采集部分失败
滞后：无
影响范围：按资源点
```

### 4.3 采集压力衰减
```
条件：每 tick
效果：gathering_pressure -= decay_rate
      gathering_pressure 不低于 0
滞后：衰减慢于累积
影响范围：按资源点
```

### 4.4 近山退化与采集半径扩大
```
条件：近山柴薪点 stock 低于警戒线
效果：生成 resource_degraded 事件
      人物系统感知到“近山柴薪变少”
      人物决策倾向转向浅山砍柴
      浅山采集压力上升
滞后：退化在持续采集若干季后显现
影响范围：近山资源点及人物决策
```

### 4.5 柴薪消耗
```
条件：每 tick，人物系统结算日常消耗
效果：人物柴薪存量 -= daily_consumption
      柴薪存量不足时，人物需要去采集或向他人借/买
滞后：无
影响范围：按人物/户
```

## 5. 事件类型
- `firewood_gathered`：{point_id, amount, agent_id, cause}
- `firewood_stock_changed`：{point_id, old, new, cause}
- `firewood_pressure_changed`：{point_id, old, new, cause}
- `firewood_degraded`：{point_id, severity}
- `firewood_gathering_radius_expanded`：{old_zone, new_zone, cause}
- `firewood_shortage`：{agent_id, severity}（人物柴薪存量不足）

## 6. 与其他系统的接口
- 读：forest-zones.md 的分区状态；02-climate 的季节（冬季消耗高）。
- 写：人物系统读柴薪存量和采集半径做决策（去哪砍、砍多少、是否买柴）；04-terrain 读近山退化状态调整土体稳定度；08-hazards 读柴薪退化触发滑坡和山洪风险。
- 因果链：日常砍柴 → 近山采集压力上升 → 近山柴薪退化 → 采集半径扩大到浅山 → 时间成本上升 → 人物决策（减少用柴、买柴、协商轮砍规则）。

## 7. 地点参数占位
- 柴薪资源点清单：point_id、parent_zone、location_desc、初始 stock、max_stock
- regeneration_rate（柴薪再生速度）
- pressure_coefficient、decay_rate
- 柴薪耗尽警戒线
- travel_time_from_town（各柴薪点的单程时间）
- daily_consumption（人均/户均日消耗）
- 冬季消耗系数