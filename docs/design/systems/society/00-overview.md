# Society（人文域）

> **能力状态**（E1 审计 2026-11-22）：**部分实现，大量规划**——人物生理/决策/行动、亲缘/债务、经济租约等已落地；心理、信息、教育、阶层、家畜、会话交互等仅规划。逐子树状态见各自头注，依据见[设计树对齐审计 §3](../../audits/ecology-foundation/design-tree-alignment.md)。

## 定位与归位说明

人文域对应代码 `src/vale/domains/society/`（单一域，agents 总调度 + economy/land/social/governance/construction/households 等）。按 ADR 010 §2.6 与老板裁决 5，原 agents、human-environment、interaction 三棵子系统树与顶层三份文档归并到本域下：

- [agents/](agents/00-overview.md)——个体视角：生理、认知、需求、决策、行动、生命历程、人口婚姻。
- [human-environment/](human-environment/00-overview.md)——结构视角：社会空间、制度、关系、信息、教育、阶层、冲突、仪式、家畜。
- [interaction/](interaction/00-overview.md)——会话视角：谈判、重要性与节奏、结果与后果（整树仅规划）。
- [buildings-and-living-environment.md](buildings-and-living-environment.md)、[labor-productivity-and-fatigue.md](labor-productivity-and-fatigue.md)、[tenancy-economy-and-public-services.md](tenancy-economy-and-public-services.md)——建筑居住、劳动疲劳、租佃经济与服务。

三子树的划分是**设计视角**（结构 vs 个体 vs 会话），代码实现为单一 Society 域；动力学与状态记录的横切文档在 [kernel/](../kernel/00-overview.md)。

## 已知边界（不在人文域内补实现）

- 治理、建造、社区储备审批链：函数库存在、生产运行时无触发路径（2026-11-20 裁决：保留为正式目标，各自单列任务）。
- 家畜机制：全库无实现，`agents/06-actions.md` 中家畜动作清单为规划。
- 人文对生态的影响走显式契约（ADR 010 §2.4），本生态阶段不接入。
