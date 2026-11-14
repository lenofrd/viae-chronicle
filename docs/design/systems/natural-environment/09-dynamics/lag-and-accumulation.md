# 滞后与累积

## 1. 目的
定义条件满足后效果延迟若干 tick 才显现（滞后），以及变量按 tick 累积、超过阈值才触发下一阶段（累积）的通用机制。

## 2. 核心概念
- 滞后（lag）：条件满足后，效果延迟 `lag_range` tick 才生效。滞后可以是最小值、最大值或范围。
- 累积（accumulation）：变量按 `accumulation_rate` 增长，按 `decay_rate` 衰减，超过 `threshold` 触发事件。
- 累积滞后：累积量超阈值后，还要再等 `trigger_lag` tick 才真正触发事件。
- 正反馈：累积导致环境变差，变差又加速累积（如植被退化 → 再生变慢 → 采集压力更大 → 更退化）。
- 负反馈：累积导致恢复力量增强，减缓累积（如旱情累积到一定程度，蒸发减少，累积变慢）。

## 3. 声明格式
每个子系统在规则里声明：
```
滞后：lag_range = [min, max] tick
累积：accumulation_rate、decay_rate、threshold、trigger_lag
```

## 4. 演化规则

### 4.1 滞后应用
```
条件：规则触发条件满足
效果：记录 pending_effect，到期 tick = 当前 tick + lag
      在到期 tick 执行效果
      到期前若条件消失，效果可取消（由规则声明是否可取消）
滞后：lag_range
影响范围：按规则
```

### 4.2 累积更新
```
条件：每 tick
效果：accumulation += accumulation_rate * driver_factor
      accumulation -= decay_rate
      accumulation 夹紧到 [0, max]
滞后：无
影响范围：按累积量
```

### 4.3 阈值触发
```
条件：accumulation > threshold
效果：记录 pending_trigger，到期 tick = 当前 tick + trigger_lag
      到期时生成触发事件
滞后：trigger_lag
影响范围：按累积量
```

### 4.4 正反馈与负反馈
```
条件：累积量影响自身或上游的累积速率
效果：accumulation_rate 乘以 feedback_factor
      feedback_factor > 1 为正反馈，< 1 为负反馈
      正反馈需要上限约束，防止失控
滞后：反馈因子变化有 1–3 tick 滞后
影响范围：按累积量
```

### 4.5 累积恢复
```
条件：驱动因子消失后
效果：accumulation 按 decay_rate 衰减
      衰减慢于累积（decay_rate < accumulation_rate）
      累积量降到 0 后停止
滞后：恢复慢于累积
影响范围：按累积量
```

## 5. 事件类型
- 本机制不单独生成事件，累积和触发事件由各子系统声明。
- 诊断事件：`accumulation_threshold_reached`：{unit_id, variable, value, threshold, trigger_tick}

## 6. 与其他系统的接口
- 02-climate 的旱涝累积、05-soil-and-fields 的 pest_risk、06-vegetation 的采集压力、07-fauna 的捕猎压力、08-hazards 的灾害触发滞后，都引用本机制。
- 实现时由 `core/dynamics.py` 提供 `schedule_lagged_effect()`、`update_accumulation()`、`check_threshold()` 函数。

## 7. 地点参数占位
- 各累积量的 accumulation_rate、decay_rate、threshold、max
- 各规则的 lag_range、trigger_lag
- 正反馈/负反馈因子
- 是否可取消滞后效果