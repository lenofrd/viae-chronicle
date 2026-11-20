# 测试覆盖审计（test-coverage-audit）

- **对应任务**：TASK-01 第 5 项
- **基线**：`c9f29a5`，Python 3.14，pytest 配置见 [pyproject.toml](file:///F:/viae-chronicle/pyproject.toml#L30-L38)
- **基线结果**：`python -m pytest -q -m "not long_run"` → **548 passed, 1 deselected, 1 warning in 869.34s (0:14:29)**
- **采集方式**：逐文件统计 `def test_` 数量 + `rebuild_state` 调用点 + 长程标记检索。

## 1. 规模与分布

测试函数 431 个（参数化后收集 548 项），分布在 33 个文件。按职责归类：

| 类别 | 文件（测试函数数） | 小计 |
|---|---|---|
| 架构敏感（内核/世界生成/领域边界） | scheduler 2、event_log 6、climate 5、ecology 1、environment 22、land 9、construction 8、tenancy_economy 12、governance 2、xigu_worldgen 9、xigu_events 1 | 77 |
| 人类行为与生命周期 | agents 17、task10_lifecycle_and_fishery 21、task12_life_course 29、task12_household_migration 15、task12_household_split 13、task15_social_conflict 21、task16_social_relations 17、task17_social_visibility 18、task18_impression_p1 14、task23_youth_labor 8、task25_impression_decision 6、task29_intraday 13、stage3_consumption 4、surplus_phase2 14 | 210 |
| 经济与资源 | economy_settlement 26、hunting_and_sustainability 24、task30_water 21、task11_movement_market_textile 40 | 111 |
| 观察层 | event_viewer 31 | 31 |
| 长程 | xigu_generational_sustainability 2（其中 1 个标 `long_run`） | 2 |
| 空文件 | full_tick 0、world_isolation 0 | 0 |

## 2. 架构敏感测试的实际覆盖

| 目标 | 现有测试 | 覆盖判断 |
|---|---|---|
| Scheduler 拓扑排序 | `test_scheduler.py`（2） | 覆盖依赖排序与异常隔离；**未覆盖环检测**（环只打警告）。 |
| 事件日志 | `test_event_log.py`（6） | 覆盖追加、查询、隔离；未覆盖 schema/版本（不存在）。 |
| 气候 | `test_climate.py`（5） | 覆盖季节/天气/水位演化。 |
| 生态资源池 | `test_ecology.py`（1） | 仅 1 项，覆盖再生基本路径；未覆盖采集额度与退化（退化字段不存在于运行时池）。 |
| 采集/狩猎 | `test_hunting_and_sustainability.py`（24） | 覆盖成功率、受伤、可持续性；**未断言猎物池与资源类型的对应关系**，因此 `game_trail` 永不被采集这一错配没被发现。 |
| 环境（人文社区服务） | `test_environment.py`（22） | 覆盖建造维护、需求、社区储备、效率修正；但被覆盖的多个入口在生产路径无调用者。 |
| 土地 | `test_land.py`（9） | 覆盖初始化、转移、继承。 |
| 建造 | `test_construction.py`（8） | 覆盖配方扣款、推进、回放；生产路径无触发者。 |
| 租约/借贷 | `test_tenancy_economy.py`（12） | 覆盖租金、借贷、催收。 |
| 治理 | `test_governance.py`（2） | 仅 2 项；选举、议事、申诉的大部分函数未被直接测试，且生产路径无调用者。 |
| 世界生成 | `test_xigu_worldgen.py`（9） | 覆盖节点、地形、道路、资源池结构；**未断言 `ResourcePool` 与 `SpatialNode.attributes` 一致**。 |
| 灾害/野遇 | `test_xigu_events.py`（1） | **仅 1 项**，而该模块直接改人物健康、田块长势与地力，是跨域写入最重的地方。 |

## 3. 回放覆盖

`rebuild_state` 出现在 13 个文件、41 处调用，覆盖：agents、construction、economy、environment、governance、land、household_migration、social_conflict、social_relations、social_visibility、impression_p1、youth_labor、water。

**未覆盖回放**：climate、ecology、xigu_events、hunting/fishery、market/weave 的产物一致性。若迁移时新增命令事件，这些空档会放大成"事件写入了但回放不知道"的错误。

## 4. 断言的薄弱点（迁移前必须补）

1. **无状态所有权断言**：没有任何测试在"非所有者模块写入他人字段"时失败。当前所有跨域写都能在测试下静默通过。
2. **无配置一致性断言**：`game_trail` 池与 `hunt.target_node` 的错配、`field_fertility` 与 `terrain_cells.soil_fertility` 的双份肥力，都没有测试守护。
3. **无守恒断言**：取水、农业产量、织布产量没有"来源=去向"的端到端断言（集市和借贷有）。
4. **长程仅 1 项**：`test_two_year_xigu_run_records_agent_driven_marriages_and_births`，2 年 720 tick，断言三指标（婚姻数、新生儿数、生育户分布）。40 年长程已按既有裁决停用。
5. **无事件 payload 契约测试**：`xigu_events` 依赖 `agent_action_taken` 的字段名，字段改名不会有测试失败。

## 5. 对迁移计划的直接约束

- 迁移任何状态字段前，先确认存在 `rebuild_state` 断言；没有就先补。
- 拆分状态容器时，`test_environment.py`（22 项，多数直接构造 WorldState 并调用函数库）会最先大面积变红，应作为第一批改造对象。
- 治理/建造/社区储备虽在生产路径不可达，但测试仍依赖其内部函数签名；重构时要么保留函数签名，要么同步改测试，不能删断言。
- `test_full_tick.py`、`test_world_isolation.py` 为空文件，属脚手架残留，迁移时可按需填充为跨模块 tick 冒烟测试，不要当作已有覆盖。
