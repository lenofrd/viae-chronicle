# 灾害注入（场景层）

> **能力状态**（E1 审计 2026-11-22）：**已实现**——由 `src/vale/world/scenarios/xigu/events.py`（`XiguEventsModule`，注册名 `xigu_events`，调度阶段 PHASE_IMPACT，依赖 agents 与 ecology）按规则注入。本文件由原 `natural-environment/08-hazards` 拆出（老板裁决 5-③）：**场景概率注入不得描述成已实现的环境灾害机制**。

## 现状（已实现，溪古镇）

按固定种子与规则在每轮注入：

| 注入 | 机制要点 |
|---|---|
| 洪涝损害（`_apply_flood_damage`） | 概率触发，经 climate 水位对田地/资产施加损害 |
| 旱情损害（`_apply_drought_damage`） | 概率触发，经 climate 旱情标量施加损害 |
| 滑坡（`_apply_landslide`） | 概率触发，作用于坡地相关对象 |
| 野兽遭遇（`_apply_wildlife_encounter`） | 概率触发，产生遭遇事件 |
| 社会回声（`_social_echoes`） | 场景消息在人群中的回响 |

种子默认 `20261118`（溪古验收口径）；具体参数外置于世界配置。

## 与环境机制的边界

- 环境侧的**累积状态与触发机制**（旱情如何累积、洪涝阈值如何形成）属环境域：见 [environment/08-hazards](../systems/environment/08-hazards/00-overview.md)。
- 本层只做**注入**：读取当轮环境状态（如水位、旱情）作为触发条件之一，但不改写环境内部状态所有权。
- 未来环境灾害机制落地（累积触发、阈值演化）后，场景注入应退化为「世界参数 + 触发口径」的配置内容，机制归环境域。
