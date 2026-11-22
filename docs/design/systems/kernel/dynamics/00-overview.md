# Dynamics（横切动力学策略）

> **能力状态**（E1 审计 2026-11-22）：**规划**——本树描述的机制尚未实现；现有限幅逻辑散见于 `domains/environment/climate.py`。依据见[设计树对齐审计 §3](../../../audits/ecology-foundation/design-tree-alignment.md)。

## 定位

变化的时间尺度与过程策略：变化率、滞后与累积、可逆性、空间传播（环境侧）；制度变迁、关系变化、谣言传播、舆论形成（社会侧）。原 natural-environment 与 human-environment 两套 09-dynamics 平行树及 agents / interaction 的同名文档按裁决 5 归并于此。

## 子树

- [environment/](environment/00-overview.md)——环境侧动力学（变化率、滞后累积、可逆性、空间传播）。
- [society/](society/00-overview.md)——社会侧动力学（制度、关系、谣言、舆论），含原 agents 与 interaction 的动力学文档。

## 现状边界

- 实现层面仅有 climate 的季节/水位/旱情的限幅与累积；`core` 与各域均无通用动力学引擎。
- 本树为各域机制的**横切策略视角**，具体机制落地时归各域（如植被退化恢复属 Environment，见 ECO-01 E3）。
