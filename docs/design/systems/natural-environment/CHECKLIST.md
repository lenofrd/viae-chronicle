# 自然环境设计自检清单

> 按 `检查.md` 执行。检查日期：2026-11-14。检查范围：`natural-environment/` 下全部 47 个 Markdown 文件。
> `[x]` = 通过；`[ ]` = 待修；`△` = 部分/存疑。每条问题改完后把 `[ ]` 改成 `[x]`。

---

## 第一层：文件完整性 —— 文档地图上的文件都在吗？

- [x] `01-spatial-skeleton/`：`00-overview.md`、`01-spatial-units.md`、`02-distance-and-time.md`、`03-accessibility.md`（4/4）
- [x] `02-climate/`：`00-overview.md`、`seasons.md`、`weather.md`、`drought-flood.md`、`extreme-events.md`（5/5）
- [x] `03-hydrology/`：6/6
- [x] `04-terrain/`：4/4
- [x] `05-soil-and-fields/`：4/4
- [x] `06-vegetation/`：5/5
- [x] `07-fauna/`：4/4
- [x] `08-hazards/`：6/6
- [x] `09-dynamics/`：5/5
- [x] `10-state-and-records/`：4/4
- [x] 无空文件（最小文件 `01-spatial-skeleton/03-accessibility.md` 为 1612 字节）

**结论：第一层全部通过。**

---

## 第二层：子系统内部一致性 —— 每本子系统 00 说的东西，子文件里都写了吗？

### 01-spatial-skeleton（结构性）
- △ `00-overview.md` 没有「状态变量表」与「事件类型清单」段（§3 是单元类型表，§5 是接口）。子文件 `01-spatial-units.md §5` 声明了 `unit_state_changed` / `unit_disabled` / `unit_enabled`，`02-distance-and-time.md`、`03-accessibility.md` 声明了 `movement_blocked` / `movement_rerouted`，但 00 未汇总。
- [x] 建议在 `00-overview.md` 增补事件清单段（与 02–08 对齐），或显式说明本子系统不拥有演化状态。

### 02-climate
- [x] `climate_trend`：`00-overview.md §3` 声明为状态变量，但子文件只定义了 `weather_trend`（`weather.md`），`climate_trend` 无定义，命名不一致。
- [x] 其余状态变量（season / temperature / precipitation / humidity / wind / drought_accumulation / flood_accumulation）被子文件覆盖。
- [x] 00 §5 声明的事件全部被 `seasons.md` / `weather.md` / `drought-flood.md` / `extreme-events.md` 覆盖。
- [x] §7 地点参数被子文件覆盖。

### 03-hydrology
- [x] **`flood_risk` 与 `flood_risk_changed` 在 `00-overview.md §3/§5` 声明，但全子系统无任何子文件定义其更新规则或该事件**（grep 仅命中 00 两处）。`flood_risk` 实际由 08-hazards 侧判定，03 不应声明为自有状态变量；要么从 00 移除，要么在 `water-level.md` 补定义。
- [x] 其余状态变量（water_level / flow_velocity / turbidity → water-level.md；crossing_state → crossing.md；intake_status / irrigation_state → irrigation.md；siltation → siltation.md）均覆盖。
- [x] `upstream_withdrawal`（irrigation.md）、`silt_cleared`（siltation.md）已覆盖。
- [x] §7 地点参数基本覆盖（"山洪触发阈值"更偏 08 参数）。

### 04-terrain
- [x] **`snow_cover` 与 `snow_cover_changed` 在 `00-overview.md §3/§5` 声明，但无任何子文件定义**（grep 仅命中 00 两处）。
- [x] **`soil_stability` 在 `00-overview.md §3` 声明为自有状态变量，但 04 无子文件定义其更新规则**；`06-vegetation/forest-zones.md` 只提供 `soil_stability_factor`，04 侧无消费逻辑。
- △ **`vegetation_cover` 所有权矛盾**：`04 00 §3` 把它列为 04 自有状态变量、§5 列了 `vegetation_cover_changed` 事件，但实际更新规则在 `06-vegetation/forest-zones.md`；`04 00 §6` 又写"读 06-vegetation 的植被覆盖"。自相矛盾——应明确 vegetation_cover 归 06，04 只读取。
- [x] `landslide_risk` / `trail_state` 由 `landslide-risk.md` 覆盖。
- [x] 因 snow_cover 未定义，§7 中的"积雪季节性曲线"也无对应参数。

### 05-soil-and-fields
- [x] 状态变量全部覆盖（soil_moisture → soil-moisture.md；fertility → fertility.md；crop_type / growth_stage / growth_health / pest_risk / expected_yield → crops.md；`irrigation_state` 明确标注"从水文读取"，非自有）。
- [x] 事件全部覆盖。
- [x] §7 地点参数全部覆盖。
- **结论：05 内部一致性完整。**

### 06-vegetation
- [x] 状态变量全部覆盖（vegetation_cover / vegetation_type → forest-zones.md；resource_stock / regeneration_rate / gathering_pressure / degradation_state → regeneration.md 及 herbs / firewood）。
- [x] 事件全部覆盖。
- [x] **`resource_degraded` 事件 payload 不一致**：`00-overview.md §5` 写 `{point_id, severity}`，`regeneration.md §5` 写 `{point_id, old_state, new_state}`，需统一。
- [x] §7 地点参数全部覆盖。

### 07-fauna
- [x] 状态变量全部覆盖（population / carrying_capacity / regeneration_rate / hunting_pressure / activity_state → fish-and-birds.md / game.md；aggression → dangerous-animals.md）。
- [x] 事件全部覆盖（`wildlife_incident` / `wildlife_descended` 在 dangerous-animals.md 与 08 wildlife-incidents.md 双重定义，payload 基本一致）。
- [x] §7 地点参数全部覆盖。
- **结论：07 内部一致性完整。**

### 08-hazards
- [x] **`disaster_ongoing` 事件在 `00-overview.md §6` 声明，但 5 个子文件无一定义或使用**（grep 仅命中 00 一处）。
- △ `00-overview.md §4` 声明统一字段 `damage_record`，但各子文件用各自字段（casualties / crop_loss / affected_*）替代，未对齐；建议在 00 说明或统一。
- [x] §8 地点参数各子文件覆盖。

### 09-dynamics / 10-state-and-records（横切层）
- [x] 子文件各自定义机制 / 格式，内部自洽。
- [x] `09-dynamics/00-overview.md §3` 的机制–子系统对应表与各子系统实际使用基本吻合（详见第四层引用问题）。

---

## 第三层：跨子系统接口（最重要，最容易出问题）

下表按「写方声明 → 读方是否确认」核对。依据：各子系统 `00-overview.md` 的接口段 + 顶层 `00-overview.md §4` 依赖图。

| # | 写方 → 读方 | 写方声明 | 读方确认 | 结果 |
|---|------------|---------|---------|------|
| 1 | 02 → 03 降水/温度/季节 | ✓ | ✓ 03 00 §6 读列 02 | [x] |
| 2 | 02 → 05 降水/温度/季节 | ✓ | ✓ 05 00 §6 读列 02 | [x] |
| 3 | 02 → 04 暴雨 | ✓ | ✓ 04 00 §6 读列 02 | [x] |
| 4 | 02 → 08 旱涝/极端天气 | ✓ | ✓ 08 00 §7 读列 02 | [x] |
| 5 | 03 → 05 灌溉/水位 | ✓ | ✓ 05 00 §6 读列 03 | [x] |
| 6 | 03 → 06 河边湿地水位 | ✓ | ✓ 06 00 §6 读列 03 | [x] |
| 7 | 03 → 07 水位/流速/浑浊 | ✓ | ✓ 07 00 §6 读列 03 | [x] |
| 8 | 03 → 08 山洪风险 | ✓ | ✓ 08 00 §7 读列 03 | [x] |
| 9 | 04 → 06 坡向/坡度 | ✓ | ✓ 06 00 §6 读列 04 | [x] |
| 10 | 04 → 08 滑坡风险 | ✓ | ✓ 08 00 §7 读列 04 | [x] |
| 11 | 05 → 06 地力/湿度（田边植被） | ✓ 05 00 §6 写 | **✗ 06 00 §6 读未列 05，子文件亦无** | [x] |
| 12 | 05 → 08 虫害风险 | ✓ | ✓ 08 00 §7 读列 05 | [x] |
| 13 | 06 → 04 植被覆盖 | ✓ | ✓ 04 00 §6 读列 06 | [x] |
| 14 | 06 → 05 水土保持 | ✓ 06 00 §6 写 | **✗ 05 00 §6 读未列 06，子文件亦无** | [x] |
| 15 | 06 → 07 植被类型/覆盖 | ✓ | ✓ 07 00 §6 读列 06 | [x] |
| 16 | 06 → 08 干燥度/退化 | ✓ | ✓ 08 00 §7 读列 06 | [x] |
| 17 | 07 → 08 食物短缺/攻击性/下山 | ✓ | ✓ 08 00 §7 读列 07 | [x] |
| 18 | 08 → 03 山洪改变水位/冲毁取水点 | ✓ 08 00 §7 写 | **✗ 03 00 §6 读未列 08，子文件亦无** | [x] |
| 19 | 08 → 04 改变山路 | ✓ 08 00 §7 写 | **✗ 04 00 §6 读未列 08，子文件亦无** | [x] |
| 20 | 08 → 05 冲毁田/旱降地力/虫害降收成 | ✓ | △ `crops.md` 子文件读了 08，但 `05 00 §6 读` 未列 08 | [x] |
| 21 | 08 → 06 火灾/山洪改变植被 | ✓ | △ 仅 `06 00 §8 扩展预留` 提及"读取火灾后果"，`§6 读` 未列 08 | [x] |
| 22 | 08 → 07 改变栖息地/种群 | ✓ 08 00 §7 写 | **✗ 07 00 §6 读未列 08，子文件亦无** | [x] |
| 23 | 03 ← 04 坡度/河道形态（反向） | △ 03 00 §6 读列 04 | ✗ 04 00 §6 写未列 03（且河道形态 `channel_form` 实为 03 自有） | [x] |

**断裂汇总（写方声称、读方不确认）：**

1. [x] **#11 05 → 06**：05 说写田边植被受地力湿度影响，06 读列表没有 05。
2. [x] **#14 06 → 05**：06 说写水土保持给 05，05 读列表没有 06。
   > 注：#11 与 #14 互为反向，两边都声称写给对方、但谁都没在自己的「读」里确认对方——属于典型的悬空接口。
3. [x] **#18 08 → 03**：08 说写山洪改变水位/冲毁取水点，03 不读 08。
4. [x] **#19 08 → 04**：08 说写改变山路，04 不读 08。
5. [x] **#22 08 → 07**：08 说写改变栖息地/种群，07 不读 08。

**部分不对齐（子文件有、00 汇总漏列 / 存疑）：**

6. [x] **#20**：`05/crops.md` 已读 08，但 `05/00-overview.md §6 读` 没把 08 列进去——补一行即可。
7. [x] **#21**：06 只在扩展预留提了读 08 火灾后果，未进 `§6 读` 主列表。
8. [x] **#23**：03 声称读 04 的坡度/河道形态，但 04 未声明写给 03；且 `channel_form` 实际在 03 自己的 `river-segments.md` 定义，03 不该从 04 读它。

> 模式总结：**08-hazards 对下游（03/04/06/07）的反馈写入普遍未被下游在「读」列表中确认**，只有 05 部分覆盖。这正是 `检查.md` 预警的"08 说写、下游没说读"的典型断裂。

---

## 第四层：09/10 横切层引用 —— 子系统提到了吗？

- [x] **01–08 全部未显式引用 `09-dynamics` 或 `10-state-and-records`**（grep 命中仅顶层 `00-overview.md` 和 `09/change-rates.md` 内部一处）。顶层总览引用了，但各子系统 00/子文件均无链回。
- [x] **"记录系统"（10 的隐式引用）覆盖不均**：08 全有、07 有 3/4、01 有 2/4、05 有 2/4、03 仅 1/6、06 仅 1/5；**02-climate 和 04-terrain 完全未提"记录系统"**。
- [x] **`max_delta`（09 变化速率）声明不全**：只出现在 03 / 05 / 06；02 / 04 / 07 / 08 用散文描述速率上限但未用标准术语，也未声明每变量的 `max_delta`。09 要求所有演化状态变量都声明。
- △ 滞后 / 可逆 / 空间传播概念在 03–08 散文中广泛存在，但未标注"见 `09-dynamics/...`"，读者无法跳转。

**建议**：每个子系统 00 末尾或接口段补一句："变化速率上限/滞后/传播/可逆规则见 `09-dynamics/`，事件记录与快照结构遵循 `10-state-and-records/`。"

---

## 待修清单总览

第二层（6 项）：
1. [x] 02 `climate_trend` 声明未定义（或与 `weather_trend` 统一）
2. [x] 03 `flood_risk` / `flood_risk_changed` 声明未定义
3. [x] 04 `snow_cover` / `snow_cover_changed` 声明未定义
4. [x] 04 `soil_stability` 声明但无更新规则
5. [x] 04 `vegetation_cover` 所有权矛盾（应明确归 06）
6. [x] 06 `resource_degraded` payload 不一致
7. [x] 08 `disaster_ongoing` 声明未覆盖
8. [x] 08 各文件未对齐 `damage_record` 统一字段
9. [x] 01 缺事件清单汇总段

第三层（8 项）：见上表 #11 / #14 / #18 / #19 / #20 / #21 / #22 / #23。

第四层（3 项）：显式引用 09/10、补齐"记录系统"提及、补齐 `max_delta` 声明。

---

*检查方法：全量阅读 47 个文件 + 针对性 grep（`09-dynamics|10-state-and-records`、`记录系统`、`max_delta`、`flood_risk|snow_cover|soil_stability|disaster_ongoing|climate_trend`、`08-hazards`）。文件存在性与大小由 `Get-ChildItem` 核对。*
