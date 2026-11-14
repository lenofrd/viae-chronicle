# 观察层：CLI 只读事件流查看器

## 1. 目的与定位

老板无法直接读 `events.db`；现有 `cli run` 只渲染部分叙事、`agent <name>` 只看最近 5 条。本观察层提供一套**只读** CLI，让老板能在终端完整、可读地查看事件流，并可按人 / 日期 / 事件类型筛选，导出 Markdown / CSV / JSONL。

**定位**：纯读侧工具，不是模拟机制。不写库、不建表、不改模拟逻辑、不改已批准参数。

## 2. 只读约束（如何保证）

- 用 SQLite 的 URI **只读模式**打开：`sqlite3.connect(f"file:{path}?mode=ro", uri=True)`，任何写操作都会被引擎拒绝。
- **不复用** `vale.core.event_log.EventLog` 类——它的 `_create_tables()` 会执行 `CREATE TABLE`（写），与只读约束冲突。观察层自建 `ReadonlyEventStore`，只做 `SELECT`。
- 文件不存在 / schema 不符 / 无读权限 → 转为明确可操作提示，不吞掉异常。
- 测试断言：运行观察层前后数据库文件哈希不变。

## 3. 命令清单

均挂在 `cli.py events` 子命令族下，全局可选 `--db <path>` 与 `--debug`（两者放在子命令前或后都生效）。

**默认库**：`data/worlds/brookvale-town-001/cli_run.db`，由 `python src/vale/cli.py run <days>` 生成，**每次 run 覆盖重建**。查看前需先跑一次 `run` 落盘。

**`--db` 用法**：指向任意事件库（只读打开），例如查看 `events.db`：

```powershell
python src/vale/cli.py events --db data/worlds/brookvale-town-001/events.db list --limit 10
```

库不存在或 schema 不符（缺 `events` 表）时给出明确提示并以非零码退出，绝不写库。

| 命令 | 作用 |
|---|---|
| `events list [筛选]` | 事件列表，每条一行摘要（id / 日期 / 类型 / 简述） |
| `events timeline <name> [筛选]` | 某人物的时间线（只看该人相关事件） |
| `events day <date> [筛选]` | 某一天的全部事件；`<date>` 接受 `1年7月1日` 或纯 tick 数字 |
| `events show <event_id>` | 单事件详情（完整 payload） |
| `events export <md|csv|jsonl> [筛选] -o <file>` | 导出，条数与同筛选下 `list` 一致 |

## 4. 筛选语义

所有筛选可组合，取交集；默认按事件 id（= 写入顺序 = tick 升序）排列。

| 参数 | 语义 |
|---|---|
| `--agent <name>` | 只保留 `payload.agent_name == name` 的事件（天气/换季事件无该字段，自然排除） |
| `--type <t>` | 按 `event_type` 过滤，可重复传或逗号分隔 |
| `--from <expr>` / `--to <expr>` | 范围下界 / 上界（**均包含**）。`<expr>` 为纯数字 → tick；含「年月日」→ 日期，换算成 tick 后比较 |
| `--limit <N>` | 最多返回 N 条；`--all` 全量（默认 limit=50 防刷屏） |
| `--reverse` | 倒序（最新在前） |

## 5. 日期解析（一律走 `calendar.py`）

- tick → 日期：复用 `calendar_from_tick(tick, start_tick, start_doy, start_year)`，参数从 `config` 读取（`world.start_tick` / `world.start_year` / `natural_params.climate_initial.season` + `season_progress`），**不硬编码世界数值**。
- 日期 → tick（用于 `--from/--to/--day` 的日期筛选）：用 `calendar.py` 的常量 `DAYS_PER_YEAR=360` / `DAYS_PER_MONTH=30` 反推，不重复定义日历常量。公式：
  `tick = start_tick + ((year - start_year)*360 + (month-1)*30 + day - 1) - (start_doy - 1)`
- 输入格式：`X年M月D日`（如 `1年7月1日`）；月/日越界 → 明确报错。

## 6. 字段字典（基于当前真实 DB schema）

> 当前 `events` 表实际列为 `(id, tick, event_type, payload TEXT, created_at)`；设计文档中的 `event_id/sequence/cause_event_id` 是未来规范，尚未落地，观察层按真实列工作。

| event_type | payload 关键字段 |
|---|---|
| `weather_changed` | `year, month, day, solar_term, season, weather, temperature_c, precipitation_mm, humidity_pct, drought_accumulation, drought_state` |
| `season_changed` | `from, to, year, month, day` |
| `agent_action_taken` | `agent_id, agent_name, action, target_node, hunger_before/after, grain_before/after, debt_before/after, field_growth_before/after, stamina_after, weather` |
| `agent_error` | `agent_id, agent_name, error, traceback`（结算阶段含 `phase`） |
| `debt_formed`（任务08） | `creditor_id, creditor_name, debtor_id, debtor_name, debt_type, amount, due_tick, originated_tick, debtor_grain_before/after, creditor_grain_before/after, debt_before/after` |
| `debt_collected`（任务08） | `creditor_id, creditor_name, debtor_id, debtor_name, amount_paid, remaining, overdue, debtor_grain_after, creditor_grain_after` |
| `debt_defaulted`（任务08） | `creditor_id, creditor_name, debtor_id, debtor_name, amount, overdue_ticks` |
| `debt_repaid`（任务08） | `creditor_id, creditor_name, debtor_id, debtor_name, amount, remaining, source, debtor_grain_after, creditor_grain_after` |
| `health_recovered`（任务08） | `agent_id, agent_name, before, after, reason, hunger, stamina` |
| `module_error`（调度器写入，未在要求覆盖列表） | `module, error, traceback` → 走未知类型兜底 |

## 7. 渲染与兜底

- 每条事件渲染成一行中文摘要；`show` 额外打印完整 payload。
- **已知覆盖**：9 种事件类型（`weather_changed` / `season_changed` / `agent_action_taken` / `agent_error` + 任务08 新增 `debt_formed` / `debt_collected` / `debt_defaulted` / `debt_repaid` / `health_recovered`）+ 动作 `eat/rest/farm/collect_water/harvest/borrow_grain`。
- **兜底（不崩）**：未知 event_type、未知 action、缺失字段、坏 JSON 载荷 → 输出可读占位（`未知` / `?` / 原始载荷键），并标记 `degraded`。
- 单条渲染失败（异常）→ 捕获，输出 `[渲染失败]` 行 + 计入降级，继续处理后续。

## 8. 降级与错误隔离

- 每次查看/导出末尾打印摘要：`共 N 条，其中降级 M 条`，**不静默丢数据**。
- `--debug` 开启后：渲染失败时输出异常类型与消息（默认关闭，面向老板保持可读）。
- 环境错误（文件不存在 / schema 不符 / 无权限）→ 明确提示 + 非零退出码，不抛裸堆栈。

## 9. 导出

- 三种格式：Markdown（表格）、CSV、JSONL。
- 导出的事件集合 = 同筛选条件下 `list` 的结果，**条数严格一致**（测试断言）。
- 导出末尾附元信息：筛选条件、总条数、降级条数，便于核对。
