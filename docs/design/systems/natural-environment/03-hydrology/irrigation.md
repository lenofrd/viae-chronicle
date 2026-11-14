# 取水与灌溉

## 1. 目的
定义取水点如何从河段引水，灌溉条件如何随水位和取水点状态变化，以及人类取水/截水如何影响下游。

## 2. 核心概念
- **取水点**：河段上可引水的位置，挂在河段下。
- **取水能力**：取水点的最大引水量，受水位限制。
- **灌溉条件**：依赖水位和取水点状态，分“充足、偏少、缺水、断水”四档。
- **截水**：上游人物或群体主动减少下游来水的行动，作为事件写入。
- **水渠**：连接取水点和田地的通道，第一版可简化为“取水点直接服务某片田”。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| intake_status | dict | 各取水点状态：正常/受限/失效 |
| irrigation_state | enum | 充足/偏少/缺水/断水 |
| withdrawal_amount | float | 当前取水量 |
| upstream_withdrawal | float | 上游截水量（影响下游） |

## 4. 演化规则
### 4.1 取水点状态
规则：取水点随水位变化
条件：水位变化后
效果：若 water_level >= intake_normal_threshold：
intake_status = 正常
若 intake_low_threshold <= water_level < intake_normal_threshold：
intake_status = 受限（取水量打折）
若 water_level < intake_low_threshold：
intake_status = 失效
滞后：无
影响范围：按取水点

### 4.2 灌溉条件
规则：灌溉条件判定
条件：取水点状态变化后
效果：根据取水点状态和当前取水量，映射到四档：
充足 / 偏少 / 缺水 / 断水
生成 irrigation_state_changed 事件
滞后：灌溉条件变化对作物的影响有 1–3 tick 滞后（见 05-soil-and-fields）
影响范围：按田地片（每片田依赖特定取水点）

### 4.3 人类截水
规则：上游截水影响下游
条件：人物系统写入 upstream_withdrawal 事件
效果：上游河段 water_level 下降
withdrawal_amount 增加
下游 equilibrium_level 下降（通过传播规则）
滞后：下游水位下降有 propagation_delay
影响范围：截水河段及其下游

### 4.4 取水与下游来水
规则：镇域取水影响下游
条件：每 tick
效果：镇前段取水减少下游来水
取水量受取水点状态和人口需求影响
滞后：无
影响范围：下游河段

## 5. 事件类型
- `intake_status_changed`：{segment_id, intake_id, old, new, cause}
- `irrigation_state_changed`：{segment_id, field_id, old, new, cause}
- `upstream_withdrawal`：{segment_id, amount, cause}
- `withdrawal_changed`：{segment_id, old, new, cause}

## 6. 与其他系统的接口
- 读：water-level.md 的水位；人物系统的截水、修渠行动。
- 写：05-soil-and-fields 读灌溉条件，调整土壤湿度和作物；人物系统读灌溉条件做决策（争水、修渠、改种）。
- 因果链：旱季水位下降 → 取水点受限 → 上游截水 → 下游断水 → 下游人物行动（争水、找水、改种、迁徙）。

## 7. 地点参数占位
- 各取水点的位置、最大取水量、服务田地片
- intake_normal_threshold、intake_low_threshold
- 灌溉条件四档的判定规则
- 镇域人口取水需求系数
- 截水对下游水位的影响系数
- 修渠事件对取水点状态的恢复量