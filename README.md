# Vale Chronicle

修仙界边缘凡人小镇 Brookvale 的文字人生模拟器。

世界按逻辑时间 Tick 自演化，NPC 自主生活、拉扯、成长；任何角色从出生到死亡的全部经历——流水账、关键转折、传记——都可随时查阅。

**这不是种田游戏，也不是挂机 RPG。** 核心产物是「可持续产出、因果可追溯的个体人生档案」。

## 设计哲学

**环境是主语，人是谓语。** 气候、灾害、制度逼迫人做选择，选择累积又改变环境；命运必须因果可循。

- 纯规则驱动，不接 LLM 实时推理；LLM 只做事后叙事渲染。
- 确定性、可重放、低算力，可快进跑几百年。
- 事件是真相，状态是投影；所有状态改变写入 SQLite 事件流。
- 机制与配置分离；业务数值在 YAML，schema 用 Pydantic。

## 仓库结构

```text
src/vale/              模拟核心
  core/                事件库、世界状态、调度器、日历、回放、快照、世界注册
  modules/             可插拔模拟模块（climate 气候、agents 人物/家庭/经济）
  observability/       只读观察层（事件查询、文本渲染、导出、CLI viewer）
  cli.py, main.py      命令行入口（events list / timeline / run 等）
  api/                 HTTP/查询接口占位（routes），当前非主要入口

config/                世界配置与校验
  schema/              Pydantic schema（配置缺省值、启动期校验）
  shared/              跨世界共享参数
  worlds/              具体世界实例（brookvale-town-001）与 _template

docs/                  设计与协作文档（核心资产，深度远超当前代码）
  design/              设计图纸：agents / human-environment / interaction / observability 等
  collab/              面向人类协作者的进度文件（PROGRESS.md）

tests/                 pytest 测试与事件流 fixture（旧库回放样本）
viz/                   Tkinter 本地可视化（只读事件库，不写状态）
scripts/               世界创建/冻结、文档与 schema 一致性检查
data/                  运行时世界实例与 SQLite 事件库（不入 Git）
.ai/                   本地 AI 工作区：STATUS、任务裁决、验收报告（不入 Git）
.check/                本地诊断/长程验收脚本与输出（不入 Git）
.trae/                 本地 Agent 规则（不入 Git）
```

`docs/design/` 已有 130+ 份设计。**代码按图纸逐步落地，新增机制前先查 `docs/` 是否已有设计。**

## 快速开始

```bash
python -m pytest -q
```

模拟运行、事件查询与字段字典见 `docs/design/systems/observability/01-event-viewer-cli.md`。

## 当前进展（2026-11-16）

- 已合入 `main`：环境基座 → 人物生存 → 时间现实化 → 观察层 → 经济闭环 → 打猎 → 死亡/失能/渔业 → 移动校准/赶集/纺织/蔬菜 → 家庭经济模型（任务 12）→ 盈余经济补丁（任务 13）→ 债务转移窄修（任务 14）→ 社会冲突最小切片（任务 15）→ Tkinter 可视化（PR #2）→ 社会认知与关系层（任务 16，PR #7）。
- 任务 15：集市赊账 +「有粮赖账」2 轮私下催收；5 种子 × 3600 验收通过（三种结果、守恒与无负值）。
- 任务 16：两级认知（unknown → met → known）+ 短期交互记忆（容量环形缓冲）+ TTL 遗忘 + 债争结果写回双方记忆；`acquaintance_changed` 事件与 `events timeline <姓名>` 的参与人匹配可用。
- 本 PR（任务 17，观察层接线）：债争开口写只读成因（`social_adjustment` / `proposal_basis`）与双方姓名（`initiator_name` / `responder_name`），文案可读出「为何开这个口」；人物时间线识别债争/认知事件的成对字段；viz 识别人名并把认知变化归入关系关注点；修复 `household_merged` 渲染降级。
- 已知技术债：G1 家庭口粮承载力（长程个别种子后段人口下滑）；部分还款自然流结构性低频（机制由单测覆盖）；窄条件记忆调节在真实链路不可达（催收要求逾期 ⇒ 债务人几乎必有违约前科），已记录为任务 18 前置信号。
- 下一阶段方向：任务 18 印象沉淀层（先 P1 进档案、后 P2 决策接入）；阶段三调参后置；货币系统评估、派生系统前置（教育/地位）、G1 承载力提产。
- 协作者请看 [`docs/collab/PROGRESS.md`](docs/collab/PROGRESS.md)；最新内部状态以维护者提供的 STATUS 为准。

## 协作方式

本仓库面向多人协作，`main` 受保护，**所有改动走 Pull Request**。

- **有疑问、发现数据异常、想提需求**：在 GitHub 仓库开 **Issue**，写清涉及的分支/commit、事件样本、复现步骤。
- **想改代码或文档**：从 `main` 开分支 → 提 PR → 在网页上回复 Review 评论；不要直接 push `main`。
- **合并**：至少 1 人审核通过后由维护者合并；PR 作者不能自审。
- **讨论入口**：Issue / PR 评论 / Review；不另建本地问答文件。
- 不依赖未合入分支或未稳定事件；`conflict_*` / `debt_deferred` 等事件自任务 15 合入起可用；`acquaintance_changed` 自任务 16 起可用；`conflict_negotiation_round` 的 `social_adjustment` / `proposal_basis`（round=1）与 `initiator_name` / `responder_name`（round=1/2）自任务 17 起可用（只读元数据，旧库事件缺字段时渲染自动回退）。

## 可视化 / 展示层

目标是一个**图形交互界面（GUI）**，用来观察世界运行、翻阅人生档案，而不是命令行输出。

### 界面形态

- 桌面窗口应用或本地 Web UI 均可，优先能离线打开样本数据。
- 主窗口至少包含：**事件流面板**、**筛选/显示控制**、**关注点面板**、**运行控制栏**。
- 不依赖运行中的模拟也能浏览已保存的事件库。

### 功能要求

1. **事件流面板**：按 tick 顺序显示事件，支持滚动、选中、查看事件详情（字段、参与者、家庭、地点）。
2. **显示调节按钮**：按事件类型/角色/家庭/地点/时间范围筛选；时间粒度切换（逐 tick / 按天 / 按事件簇）；暂停时单步、跳转指定 tick。
3. **关注点**：标记/收藏角色、家庭或事件；高亮出生、婚配、生育、死亡、继承、债务违约、迁徙等关键转折。
4. **世界运行控制**：运行 / 暂停 / 单步 / 速度；运行控制通过模拟子进程或 CLI 控制接口实现，不直接写事件库。
5. **角色与家庭视图**：角色档案（生卒、家庭、事件时间线）、家庭视图（按 `household_id` 聚合）。

### 数据来源

- 事件真相源：SQLite `events` 表（只读连接）。
- 稳定接口：`events list` / `events timeline <姓名>` 的 JSON 输出。
- 字段字典：`docs/design/systems/observability/01-event-viewer-cli.md`。
- 样本数据：`tests/fixtures/legacy_events.json`、`legacy_events_expected.json`。

### 边界要求

1. **事件库只读**：不写 SQLite、不建表、不改写事件；运行控制不得绕开模拟核心直接写状态。
2. **不依赖内部 state schema**：不 import `src/vale/core/state.py`，只按事件 schema 编程。
3. **只动 `viz/`**：不修改 `src/`、`config/`、`tests/`；不改 `events list` 默认行为。
4. **不接 LLM 实时推理**；叙事渲染可后置。
5. 分支开发、PR 审核合入，不直接推 `main`。

## 文档

- `docs/design/00-overview.md`：设计总索引。
- `docs/design/decisions/`：架构决策记录。
- `docs/design/systems/observability/`：事件查看器与字段字典。
- `docs/design/systems/agents/11-life-course.md`：生命历程与家庭模型。
- `docs/design/locations/brookvale-town/`：溪谷镇剧本。
- `docs/collab/PROGRESS.md`：面向协作者的已合入事实与 WIP 边界。

## 红线

1. 不接 LLM 实时推理。
2. 事件溯源：状态是投影，事件是真相；不改写旧事件。
3. 机制与配置分离，不硬编码业务数值。
4. 观察层只读：不写库、不建表；运行控制只控制模拟进程，不直接写状态。
5. 守恒与可追溯：资源与债务不得凭空产生或消失。
6. 不擅自修改已批准参数；改动单列「原值→新值→理由→影响」。
