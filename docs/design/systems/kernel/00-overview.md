# Kernel（内核视角设计）

> **能力状态**（E1 审计 2026-11-22）：内核本体**已实现**（阶段二重构后）；本树下三个子树状态不一，见各自头注。逐项依据见[设计树对齐审计](../../audits/ecology-foundation/design-tree-alignment.md)。

## 定位与归位说明

按 ADR 010 §2.6 与老板裁决 5（2026-11-22，方案 B2），跨域的内核视角设计统一归并到本树，不再散落各子系统平行建树：

- **空间骨架**（spatial-skeleton）：跨三域的空间基础设施——空间单元、距离与时间、可达性。
- **动力学**（dynamics）：横切的变化率、滞后累积、可逆性、空间传播等策略，按 environment / society 两侧分子树。
- **状态与记录**（state-and-records）：快照、事件流、查询接口的横切设计，按 environment / society 两侧分子树。

观察层（observability/）按裁决保留为**独立观察层**，不并入本树。

## 与实现的对应

内核实现集中在 `src/vale/core/`（calendar、config_loader、diagnostics、event_log、pools、replay、scheduler、snapshots、snapshot_store、state、world、world_registry）；观察工具在 `src/vale/observability/`；跨域查询契约在 `src/vale/contracts/`。本树文档描述的是**设计意图与规划**，落地状态以各子树头注与[架构审计](../../audits/layered-refactor-phase1/dependency-map.md)为准。

## 生态阶段注记

多分辨率模拟（Simulation LOD，ADR 010 §2.2）属内核级通用能力，其规范与实现将在 ECO-01 任务 E2 落地，届时在本树下增设 `lod/` 子树。
