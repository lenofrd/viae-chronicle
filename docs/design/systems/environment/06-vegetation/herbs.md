# 草药资源

## 1. 目的
定义草药的种类、分布位置、再生速度、采集难度和风险，以及采集如何消耗资源、累积采集压力。

## 2. 核心概念
- 草药种类：按药性和生长环境分类，第一版 4–6 种即可。
- 分布位置：具体到资源点，不是“山里随机有”。
- 再生速度：快（周）/中（月）/慢（季）/极慢（年）。
- 采集难度：低（随手可采）/中（需辨认和寻找）/高（需专业知识和装备）。
- 采集风险：无/低（蛇虫）/中（迷路）/高（野兽、滑坡、瘴气）。
- 采集压力：同一资源点反复采集会累积压力，降低再生速度甚至耗尽。

## 3. 草药资源点字段
| 字段 | 类型 | 说明 |
|---|---|---|
| point_id | string | 唯一 ID |
| herb_type | string | 草药种类 |
| parent_zone | string | 所属山林分区 |
| location_desc | string | 具体位置描述（如“浅山阴坡第三片林”） |
| stock | float | 当前存量 |
| max_stock | float | 最大存量 |
| regeneration_rate | float | 再生速度 |
| gathering_difficulty | enum | 低/中/高 |
| gathering_risk | enum | 无/低/中/高 |
| gathering_pressure | float | 采集压力 |

## 4. 草药种类示例（第一版可配置）
| 草药 | 分布 | 再生 | 难度 | 风险 | 用途 |
|---|---|---|---|---|---|
| 车前草 | 田埂地头、近山坡地 | 快 | 低 | 无 | 常见清热 |
| 蒲公英 | 田埂、草坡 | 快 | 低 | 无 | 常见清热 |
| 柴胡 | 浅山阴坡 | 慢 | 中 | 迷路、蛇虫 | 退热 |
| 半夏 | 浅山阴坡、溪边 | 慢 | 中 | 蛇虫 | 化痰 |
| 石斛 | 深山溪谷 | 极慢 | 高 | 野兽、滑坡、瘴气 | 滋补 |
| 灵芝 | 深山老林 | 极慢 | 高 | 野兽、迷路 | 珍贵滋补 |

## 5. 演化规则

### 5.1 资源再生
```
条件：每 tick
效果：stock += regeneration_rate * pressure_factor * season_factor
      pressure_factor 受采集压力影响，压力高时再生慢
      stock 不超过 max_stock
滞后：再生是渐进的，不瞬移
影响范围：按资源点
```

### 5.2 采集事件
```
条件：人物系统写入 herb_gathered 事件
效果：stock -= amount
      gathering_pressure += amount * pressure_coefficient
      若 stock < 0，夹紧到 0，采集部分失败
      生成 herb_gathered 事件，记录 agent_id、amount、point_id
滞后：无
影响范围：按资源点
```

### 5.3 采集压力衰减
```
条件：每 tick
效果：gathering_pressure -= decay_rate
      gathering_pressure 不低于 0
滞后：衰减慢于累积
影响范围：按资源点
```

### 5.4 资源耗尽与恢复
```
条件：stock 低于警戒线
效果：生成 resource_degraded 事件（轻度）
      再生速度进一步下降
      若 stock = 0，标记 point_depleted = true
      停止采集，按极慢速度恢复
滞后：恢复需要长时间
影响范围：按资源点
```

### 5.5 采集遭遇
```
条件：人物采集时，按 gathering_risk 判定
效果：可能触发遭遇事件：蛇虫咬伤、迷路、滑倒、遇到野兽
      事件成为人物心理迁移和后续事件的父事件
滞后：无
影响范围：按人物和资源点
```

## 6. 事件类型
- `herb_gathered`：{point_id, herb_type, amount, agent_id, cause}
- `herb_gathering_failed`：{point_id, agent_id, reason}
- `resource_stock_changed`：{point_id, old, new, cause}
- `gathering_pressure_changed`：{point_id, old, new, cause}
- `resource_degraded`：{point_id, old_state, new_state}
- `resource_recovered`：{point_id, old_state, new_state}
- `gathering_incident`：{point_id, agent_id, incident_type, severity}

## 7. 与其他系统的接口
- 读：forest-zones.md 的分区状态；02-climate 的季节；04-terrain 的坡向和风险。
- 写：人物系统读资源存量和采集难度做决策（去哪采、采多少、是否冒险进深山）；记录系统把采集事件和遭遇作为人物一生的事件；08-hazards 读采集遭遇触发伤害事件。
- 因果链：反复采集 → 采集压力上升 → 再生变慢 → 存量下降 → 采集半径扩大 → 人物进更深的山 → 风险和成本上升。

## 8. 地点参数占位
- 草药资源点清单：point_id、herb_type、parent_zone、location_desc、初始 stock、max_stock
- 各草药的 regeneration_rate、gathering_difficulty、gathering_risk
- pressure_coefficient（采集量转化为采集压力的系数）
- decay_rate（采集压力衰减速率）
- 资源耗尽警戒线
- 采集遭遇事件的触发概率和后果