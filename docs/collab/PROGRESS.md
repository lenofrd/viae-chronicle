# 项目进度（面向协作者）

> 只记录已合入 main 的稳定事实。WIP 与未合入分支不在此列。
> 最后更新：2026-11-15；对应 main：`dd7a18c`（PR #2 合入后）。任务 14/15 的 PR 尚未合入，见「待合 PR」段。

## 已合入 main

- 任务 12：家庭经济模型（Household、婚配从夫居、继承、分家、旧库重放）
- 任务 13：盈余经济补丁（work_node 回收、田产公式化、出生容量校验、weave 挤出修复）
- 可视化：Tkinter 本地图形界面与最新时间线跟随（PR #2）

## 事件 schema 稳定状态

- 已稳定：`events list/timeline` 字段、`household_id`、`debt_*` 全链路、`agent_born/died/married`、`household_*`。
- 未合入、勿依赖：`conflict_started`、`conflict_negotiation_round`、`conflict_resolved`、`conflict_broken`、`debt_deferred`（任务 15 PR 合入前不消费）。
- 字段字典：`docs/design/systems/observability/01-event-viewer-cli.md`。

## 可视化可用的数据源

- `tests/fixtures/legacy_events.json`、`legacy_events_expected.json`
- 只读 SQLite 事件库（向维护者索取样本）
- `events list --format json` / `events timeline --household <id>`

## 待合 PR（未合入，勿依赖）

- 任务 14 + 任务 15：分支 `task-15-social-conflict`，基于 `610bf4e`（任务 14 窄修：`debt_transferred` 补 `debtor_household_id`）rebase 到最新 `origin/main`。
  - 任务 15：集市赊账（`market.credit`）+「有粮赖账」2 轮私下催收（`conflict.debt_dispute`）+ 结算顺序修正。
  - 5 种子 × 3600 验收：人口 5/5、34 次会话、全额 13/延期 11/拒绝 8、无错误/负值、守恒 gap 全 0、同 tick 双重扣粮 0。
  - 合入前，`conflict_*` 与 `debt_deferred` 不作为可视化数据源；合入后再更新本文件的「已合入」与「未合入」段及对应 main commit。

## 正在 WIP，勿依赖

- 阶段三调参：无。
- 货币系统评估：未启动。

## 有疑问

写 `docs/collab/QUESTIONS.md`，等架构师裁决。不自行扩大授权、不改 `src/`、不跑模拟。
