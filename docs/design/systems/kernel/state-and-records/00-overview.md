# State and Records（状态与记录）

> **能力状态**（E1 审计 2026-11-22）：**与原描述矛盾，已修正口径**——状态/快照/事件流/查询的实现集中在内核（`core/{event_log, snapshots, snapshot_store, replay, state}`）与 `contracts/queries.py`、`observability/`，并非各子系统独立落地。本树保留的是环境侧与社会侧的**设计视角**。依据见[设计树对齐审计 §3](../../../audits/ecology-foundation/design-tree-alignment.md)。

## 定位

快照结构、事件流、查询接口的横切设计。原 natural-environment、human-environment、agents、interaction 四套 10-state-and-records 平行树按裁决 5 归并于此。

## 子树

- [environment/](environment/00-overview.md)——环境状态与记录设计（快照结构、事件流、查询接口）。
- [society/](society/00-overview.md)——社会侧状态与记录设计，含原 agents 与 interaction 的同名文档。

## 现状边界（真相源）

- **事件流是唯一真相**：先发事件，快照只是投影（项目铁律 1）。
- 实现真相：事件日志 `core/event_log.py`、快照 `core/snapshots.py` 与 `core/snapshot_store.py`、通用回放 `core/replay.py`、域投影在各域 `projection`、跨域查询在 `contracts/queries.py`、可读渲染在 `observability/`。
- 本树设计文档中与上述实现冲突的描述，以实现为准；待实现部分为规划。
