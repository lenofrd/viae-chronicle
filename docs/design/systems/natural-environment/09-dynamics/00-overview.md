# 演化机制总览

## 1. 目的
统一定义自然环境所有子系统共用的演化机制：变化速率上限、滞后与累积、空间传播、可逆性。01–08 各子系统在自己的文档里声明“本子系统受哪些通用机制约束”，但不重复定义机制本身。

## 2. 核心概念
- 变化速率（change rate）：每个状态变量每 tick 的最大变化量，禁止瞬移。
- 滞后（lag）：条件满足后，效果延迟若干 tick 才显现。
- 累积（accumulation）：变量不瞬时生效，而是按 tick 累积，超过阈值才触发下一阶段。
- 空间传播（spatial propagation）：一个单元的变化沿连接传播到其他单元，有时滞和衰减。
- 可逆性（reversibility）：变化分可逆、准不可逆、不可逆三类，各带不同的恢复条件和时间。
- 外部注入（external injection）：接口写入的事件，同样受以上四条约束，但标注来源为外部。

## 3. 各机制与子系统的对应
| 机制 | 主要约束的子系统 | 典型例子 |
|---|---|---|
| 变化速率 | 全部 | 水位每 tick 变化不超过 X |
| 滞后 | 02-climate、03-hydrology、04-terrain、05-soil-and-fields、08-hazards | 施肥后下一季才见效；山洪触发滞后 1–3 tick |
| 累积 | 02-climate、05-soil-and-fields、06-vegetation、07-fauna、08-hazards | 旱情累积；采集压力累积；捕猎压力累积 |
| 空间传播 | 03-hydrology、04-terrain、06-vegetation、08-hazards | 上游水位向下游传播；山洪沿河段传播；火灾沿植被传播 |
| 可逆性 | 03-hydrology、04-terrain、05-soil-and-fields、06-vegetation、08-hazards | 田埂可修；古树被砍不可逆；植被类型退化准不可逆 |

## 4. 通用约定
- 所有状态变量必须声明 `max_delta_per_tick`（或 per season），未声明的按子系统默认值处理。
- 所有带滞后的规则必须显式声明 `lag_range`，不能隐式延迟。
- 所有累积量必须声明 `accumulation_rate`、`decay_rate`、`threshold`。
- 所有跨单元影响必须声明 `propagation_delay`、`propagation_attenuation`。
- 所有状态变化必须标记 `reversibility_class`（reversible / quasi-irreversible / irreversible）。

## 5. 与其他系统的接口
- 本目录是横切层，被 01–08 所有子系统引用。
- 01–08 在自己文档里只写“本子系统受 change-rates 约束”“本规则有 1–3 tick 滞后”，不重复机制定义。
- 实现时，本目录的机制由 `src/vale/core/dynamics.py` 提供通用函数，各模块调用。

## 6. 地点参数占位
具体地点（如 Brookvale）需要提供：
- 各状态变量的 max_delta_per_tick
- 各规则的 lag_range
- 各累积量的 accumulation_rate、decay_rate、threshold
- 各传播路径的 propagation_delay、propagation_attenuation
- 各状态变化的 reversibility_class
这些参数分散在各子系统的地点参数里，本目录不单独汇总。

## 7. 扩展预留
- 新机制（如“惯性”“反馈回路”）：作为新文件加入本目录。
- 更复杂的传播模型（如二维扩散）：在 spatial-propagation.md 里扩展，第一版只做一维沿路径传播。
- 随机性机制：本目录只做确定性机制，随机性由各子系统在触发时处理。