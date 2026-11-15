# 项目进度（面向协作者）

> 只记录已合入 main 的稳定事实。WIP 与未合入分支不在此列。
> 最后更新：2026-11-15；对应 main：`cfd1fa7`（PR #3 合入后）。

## 已合入 main

- 任务 12：家庭经济模型（Household、婚配从夫居、继承、分家、旧库重放）
- 任务 13：盈余经济补丁（work_node 回收、田产公式化、出生容量校验、weave 挤出修复）
- 任务 14：债务转移事件补 `debtor_household_id`（窄修，兼容旧回放）
- 任务 15：社会冲突最小切片（集市赊账 +「有粮赖账」2 轮私下催收 + 结算顺序修正）
- 可视化：Tkinter 本地图形界面与最新时间线跟随（PR #2）

## 事件 schema 稳定状态

- 已稳定：`events list/timeline` 字段、`household_id`、`debt_*` 全链路、`agent_born/died/married`、`household_*`。
- 已合入、可用：`conflict_started`、`conflict_negotiation_round`、`conflict_resolved`、`conflict_broken`、`debt_deferred`（PR #3 起可用；字段见 `03-debt-disputes.md` §8）。
- 字段字典：`docs/design/systems/observability/01-event-viewer-cli.md`。

## 可视化可用的数据源

- `tests/fixtures/legacy_events.json`、`legacy_events_expected.json`
- 只读 SQLite 事件库（向维护者索取样本）
- `events list --format json` / `events timeline --household <id>`

## 已知缺口（不挡使用）

- G1 家庭口粮承载力：任务 15 验收中 seed 1（10→2）、seed 123（10→4）后段人口下滑；留第 3 轮提产或设计补丁（`11-life-course.md` §18 G1）。
- 部分还款在自然流为 0：结构性低频，机制由单测覆盖，不调参。

## 正在 WIP，勿依赖

- 阶段三调参：无。
- 货币系统评估：未启动。

## 协作方式（面向人类协作者）

- `main` 受保护：所有改动走 **Pull Request**，需 1 人审核；请不要直接 push `main`。
- 有疑问、发现数据/可视化异常、想提需求：在 GitHub 仓库开 **Issue**，写清涉及的分支/commit、事件样本与复现步骤。
- 想改代码或文档：从 `main` 开分支 → 提 PR → 在网页上回复 Review 评论；合并由维护者操作。
- 讨论入口统一为 **Issue / PR 评论 / Review**，不另建本地问答文件。
- 不要依赖未合入分支或未稳定事件；事件可用性以本文件「事件 schema 稳定状态」为准。
