# 冲突子系统总览

## 1. 目的
定义 Brookvale 的冲突类型、触发条件、演化过程、解决方式、后果。冲突是制度被引用、被挑战、被修改的正常机制，也是关系变化、信息传播、地位升降的爆发点。

## 2. 核心概念
- **冲突类型**：水权纠纷、地界冲突、债务纠纷、违反村规、禁忌冲突。
- **触发条件**：制度被违反、关系恶化、恩怨累积、利益受损、谣言激化。
- **冲突阶段**：潜伏 → 触发 → 争执 → 调解/升级 → 解决/破裂。
- **拉扯**：冲突中的多轮交涉，每轮根据信任、利益、情绪、关系历史调整。
- **解决方式**：私下协商、第三方调解、公开执行、暴力、逃避。
- **后果**：关系变化、地位变化、制度强化或松动、信息传播、心理影响。
- **冲突与制度**：冲突是制度的显影剂，制度在冲突中被引用、被挑战、被修改。

## 3. 冲突类型与触发源
| 冲突 | 触发源 | 典型场景 | 解决方式 |
|---|---|---|---|
| 水权纠纷 | 02-institutions/01-water-rights | 旱季截水、轮灌争执 | 里正调解、公开执行、私下协商 |
| 地界冲突 | 02-institutions/02-land-boundaries | 越界、界石移动、灾害后地界模糊 | 里正调解、地契验证、公开执行 |
| 债务纠纷 | 03-relationships/03-debt | 逾期不还、赖账、讨债 | 私下协商、里正调解、公开执行 |
| 违反村规 | 02-institutions/04-village-rules | 偷盗、伤人、通奸、不孝 | 祠堂公开执行、私下调解 |
| 禁忌冲突 | 02-institutions/06-taboos | 冒犯神树、破坏禁忌 | 舆论谴责、仪式净化、社区排斥 |

## 4. 状态变量（按冲突挂载）
| 变量 | 类型 | 说明 | 变化速率 |
|---|---|---|---|
| conflict_type | enum | 水权/地界/债务/村规/禁忌 | 固定 |
| parties | list | 冲突各方 | 固定 |
| stage | enum | 潜伏/触发/争执/调解/解决/破裂 | 事件驱动 |
| intensity | float 0–1 | 冲突激烈程度 | 随事件变化 |
| cause_event | string | 触发事件 ID | 固定 |
| resolution | enum? | 解决方式 | 事件驱动 |
| consequences | dict | 后果记录 | 只追加 |

> consequences 为冲突后果的汇总字段（只追加）；各冲突类型在子文件中用各自字段记录具体后果，不强制统一结构。

## 5. 演化规则分类
- 事件驱动：违规、利益受损、谣言激化触发冲突。
- 累积效应：恩怨、债务、水权紧张累积到阈值触发冲突。
- 拉扯：冲突中的多轮交涉，每轮根据信任、利益、情绪调整。
- 外部注入：接口写入的冲突事件（如“外来者挑起争端”），标注为外部事件。

## 6. 事件类型
- `conflict_started`：{conflict_id, conflict_type, parties, cause}
- `conflict_escalated`：{conflict_id, old_intensity, new_intensity, cause}
- `conflict_negotiation_round`：{conflict_id, round, initiator, responder, proposal, response}
- `conflict_mediated`：{conflict_id, mediator_id, outcome}
- `conflict_resolved`：{conflict_id, resolution, terms}
- `conflict_broken`：{conflict_id, reason}
- `punishment_executed`：{conflict_id, violator_id, punishment_type, location, witnesses}

## 7. 与其他系统的接口
- 读：
  - 02-institutions：制度规则和违反判定。
  - 03-relationships：关系状态、恩怨、信任。
  - 04-information：谣言和传闻激化冲突。
  - 05-education：冲突中的规训和内化。
  - 自然环境：`03-hydrology` 水位、`05-soil-and-fields` 地力、`08-hazards` 灾害触发冲突。
  - 06-stratification：阶层差异和流动受阻触发冲突。
- 写：
  - 03-relationships：冲突改变关系（结怨、和解、信任变化）。
  - 02-institutions：冲突强化或松动制度。
  - 05-education：冲突作为规训事件。
  - 06-stratification：冲突影响地位和声誉。
  - 人物系统：冲突作为心理迁移和决策的父事件。
  - 记录系统：冲突作为人生关键节点。
- 因果链：旱季截水 → 下游发现 → 争执 → 里正调解 → 惩罚或包庇 → 关系恶化 → 制度松动或强化。

## 8. 地点参数占位
具体地点（如 Brookvale）需要提供：
- 各冲突类型的触发阈值
- 冲突阶段的演化规则
- 拉扯的轮数上限和回应选项
- 调解者的权限和成功率
- 解决方式的映射
- 后果的影响系数

## 9. 扩展预留
- 新冲突类型（如婚约纠纷、继承纠纷）：作为新文件扩展。
- 群体冲突（家族对家族、群体对群体）：作为扩展，第一版只做个体和家庭冲突。
- 暴力冲突：作为扩展，第一版以调解和舆论为主。
- 跨镇冲突：作为多地点扩展，第一版不做。

## 10. 横切机制引用

- 变化速率上限、滞后与累积、空间传播、可逆性规则见 `09-dynamics/`。
- 事件记录、快照结构、查询接口遵循 `10-state-and-records/`。
- 本子系统所有状态变化事件按 `10-state-and-records/event-stream.md` 的统一格式记录。