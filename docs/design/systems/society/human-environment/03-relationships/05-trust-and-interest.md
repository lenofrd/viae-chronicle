# 信任与利益

> **落地状态（任务 16 阶段二，2026-11-16）**：本文件为长期设计，trust/grudge 本阶段
> **未实现**。已定载体口径：关系边挂载于观察者侧 `AgentState.acquaintances`
> （任务 16 阶段二落地的认知 dict，key=target_id），未来 trust 字段并入该条目或平行
> dict，不另建全局关系表（裁决 16 §二.1）。衰减接口已留
> `domains/society/social.py::decay_relation(entry, now) -> Optional[float]`（当前返回
> None；路径由 `modules/social.py` 更新，E1 审计 2026-11-22）。债争接入明确不读 trust（07-conflicts/03-debt-disputes L108–118 约束保持）。

## 1. 目的
定义角色之间信任度（`trust`）与利益权重（`interest_weight`）的维护方式、趋势判断与变化约束。信任和利益权重是关系边的核心取值，决定拉扯中的说服力、请求的接受概率与合作意愿。

## 2. 核心概念
- **信任度**：A 对 B 的信任，-1 到 1，负值表示怀疑或敌意。
- **利益权重**：A 认为与 B 交往对自身利益的重要程度，0 到 1。
- **信任趋势**：近期 `trust` 的变化方向（上升/下降/稳定），由近期变化窗口派生的慢变量。
- **利益趋势**：近期 `interest_weight` 的变化方向，由近期变化窗口派生的慢变量。
- **不对称性**：A 对 B 的信任不等于 B 对 A 的信任；利益权重同理。
- **下降快于上升**：背叛导致 `trust` 大幅下降，帮助导致 `trust` 小幅上升。
- **累积效应**：多次小帮助累积成信任；多次小摩擦累积成不信任和恩怨。

## 3. 信任与利益字段（按关系边挂载）
| 字段 | 类型 | 说明 |
|---|---|---|
| trust | float -1–1 | A 对 B 的信任度 |
| interest_weight | float 0–1 | A 认为与 B 交往的利益重要度 |
| trust_trend | enum | 信任趋势：rising / falling / stable，由近期窗口派生 |
| interest_trend | enum | 利益趋势：rising / falling / stable，由近期窗口派生 |
| recent_changes | list | 近期 trust / interest 变化事件，用于计算趋势 |
| last_change_tick | int? | 上次变化 tick |

## 4. 演化规则

### 4.1 信任变化
```
条件：正向事件（帮助、守信、调解成功）/ 负向事件（背叛、欺骗、违约、不公）
效果：正向 → trust 小幅上升（受 max_delta_per_tick 约束）
      负向 → trust 大幅下降
      追加 recent_changes，重算 trust_trend
      生成 trust_changed 事件
滞后：单次事件变化有限，显著变化需累积
影响范围：关系边 A→B
```

### 4.2 利益权重变化
```
条件：合作收益、利益冲突、地位变化、资源分配
效果：合作共赢 → interest_weight 上升
      利益冲突 → interest_weight 下降
      追加 recent_changes，重算 interest_trend
      生成 interest_weight_changed 事件
滞后：渐进
影响范围：关系边 A→B
```

### 4.3 趋势计算
```
条件：recent_changes 窗口更新（每 tick 或事件后）
效果：统计窗口内 trust 净变化 → trust_trend
      统计窗口内 interest_weight 净变化 → interest_trend
      趋势反转且持续 → 生成 trust_trend_changed / interest_trend_changed
滞后：需要窗口内多个数据点
影响范围：关系边
```

### 4.4 不对称更新
```
条件：一方 trust / interest 变化
效果：不自动镜像到反向边；反向边需对应事件才变化
滞后：无
影响范围：单向关系边
```

## 5. 事件类型
- `trust_changed`：{from_agent, to_agent, old, new, cause}
- `interest_weight_changed`：{from_agent, to_agent, old, new, cause}
- `trust_trend_changed`：{from_agent, to_agent, old_trend, new_trend}
- `interest_trend_changed`：{from_agent, to_agent, old_trend, new_trend}

## 6. 与其他系统的接口
- 读：07-conflicts 的冲突与调解结果；02-institutions 的执行公正度；04-information 的传言；01-social-spaces 的互动场景。
- 写：04-information 的传播路径信任度；06-stratification 的地位判断；人物系统的决策与拉扯输入；变化速率受 `09-dynamics/02-relationship-change.md` 约束。
- 因果链：帮助 → trust 小幅上升 → 多次帮助 → trust 显著上升、trust_trend 翻 rising → 未来请求更易被接受；背叛 → trust 大幅下降 → trust_trend 翻 falling → 未来言语效果打折。

## 7. 地点参数占位
- trust 上升 / 下降的速率（下降快于上升）
- interest_weight 变化速率
- trust_trend / interest_trend 的窗口长度与反转阈值
- 各事件对 trust 的影响系数
- `max_delta_per_tick` 上限
