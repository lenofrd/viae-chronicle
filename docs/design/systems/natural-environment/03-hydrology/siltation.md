# 河道淤积

## 1. 目的
定义河道淤积如何按季累积、如何降低过水能力、如何通过清淤恢复。淤积是慢变量，是“同流量下水位越来越高”的原因。

## 2. 核心概念
- **淤积度（siltation）**：河道泥沙沉积量，0 到上限。
- **过水能力**：淤积降低河道有效断面，同流量下水位更高。
- **淤积速率**：受流速、上游来沙、植被覆盖影响。
- **清淤**：人类行动，降低淤积度，但有成本和滞后。
- **不可逆与可逆**：清淤可恢复过水能力，但需要劳动和时间；严重淤积可能改变河道形态（不可逆）。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| siltation | float | 淤积度 |
| siltation_trend | enum | 累积中/稳定/减少中 |
| effective_capacity | float | 有效过水能力（派生量） |

## 4. 演化规则
### 4.1 淤积累积
规则：淤积按季累积
条件：每 tick（或每季结算）
效果：siltation += base_silt_rate

- upstream_sediment_factor
- (1 - vegetation_cover_factor)

上游来沙多、植被覆盖低时累积更快
滞后：淤积效果累积到阈值才明显影响水位
影响范围：按河段，下游淤积快于上游


### 4.2 淤积影响过水能力
规则：淤积抬高水位
条件：淤积变化后
效果：effective_capacity = base_capacity * (1 - siltation * silt_impact_factor)
同流量下，淤积越高，water_level 越高
作为 water-level 规则的一个修正项
滞后：无（淤积是慢变量，影响是渐进的）
影响范围：按河段

### 4.3 清淤
规则：清淤降低淤积
条件：人物系统写入 silt_cleared 事件
效果：siltation -= cleared_amount
siltation 不低于 0
过水能力恢复，但恢复有滞后（渠道稳定需要几天）
滞后：清淤后 2–5 tick 过水能力才完全恢复
影响范围：清淤河段

### 4.4 严重淤积的不可逆变化
规则：河道形态改变
条件：siltation 超过不可逆阈值
效果：标记 segment.channel_form_changed = true
即使清淤，base_capacity 也永久降低
滞后：无
影响范围：该河段

## 5. 事件类型
- `siltation_changed`：{segment_id, old, new, cause}
- `effective_capacity_changed`：{segment_id, old, new}
- `silt_cleared`：{segment_id, amount, cause}
- `channel_form_changed`：{segment_id, old, new}（不可逆事件）

## 6. 与其他系统的接口
- 读：water-level.md 的流速（流速低则淤积快）；06-vegetation 的植被覆盖（覆盖低则来沙多）；人物系统的清淤行动。
- 写：water-level.md 读 effective_capacity，修正水位；08-hazards 读淤积度，提高山洪风险。
- 因果链：植被退化 → 来沙增加 → 淤积加快 → 过水能力下降 → 同流量水位更高 → 洪水风险上升 → 清淤行动或灾害。

## 7. 地点参数占位
- base_silt_rate（基础淤积速率）
- silt_impact_factor（淤积对过水能力的影响系数）
- 不可逆阈值
- 清淤的 labor_cost 和恢复滞后
- 上游来沙系数
- 各河段的 base_capacity