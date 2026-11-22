# Scenarios（场景层）

> **能力状态**（E1 审计 2026-11-22）：溪古场景注入**已实现**（`src/vale/world/scenarios/xigu/events.py`，注册名 `xigu_events`，调度阶段 PHASE_IMPACT）。本树按裁决 5 新设，收拢「世界特定事件注入」类设计。

## 定位

场景层负责**世界特定的外生事件注入**：把某个世界（如溪古镇）特有的灾害、遭遇、消息以显式概率规则注入事件流。它与两层相邻概念的区别：

- **≠ 环境机制**：环境域的累积状态与触发（如旱情累积）属 [environment/08-hazards](../systems/environment/08-hazards/00-overview.md)；场景注入不拥有环境状态。
- **≠ 地点内容**：[locations/](../locations/brookvale-town/00-overview.md) 描述静态地点结构；本树描述注入机制与规则。

## 文档

- [hazard-injection.md](hazard-injection.md)——灾害类注入的现状与口径（山洪、滑坡、野兽遭遇等）。
- [wildlife-incidents.md](wildlife-incidents.md)——野兽遭遇事件（原环境灾害树拆入）。

## 现状边界

- 现有实现仅溪古一套（`XiguEventsModule`）：洪涝、旱情强化、滑坡、野兽遭遇、谣言等按季节与概率注入，经依赖（agents、ecology）作用于当轮。
- 新场景按「机制与内容分离」：注入机制进 `src/vale/world/scenarios/`，世界参数进 `config/`。
