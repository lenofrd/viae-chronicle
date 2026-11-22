# 季节机制

## 1. 目的
定义季节如何推进、如何渐变、如何影响下游子系统。

## 2. 核心概念
- **季节**：春/夏/秋/冬。
- **季节长度**：由地点参数提供，如 30 tick/季。
- **季节进度**：0–1，当前季节已过比例。
- **过渡期**：季节切换前后若干 tick，气候变量按插值渐变，不跳变。
- **季节系数**：每个季节对水位、地力、作物、通行的影响系数，由地点参数提供。

## 3. 状态变量
| 变量 | 类型 | 说明 |
|---|---|---|
| season | enum | 当前季节 |
| season_progress | float 0–1 | 当前季节进度 |
| transition_state | enum | none / entering / leaving |
| transition_progress | float 0–1 | 过渡期进度 |

## 4. 演化规则
### 4.1 tick 驱动：季节推进
- 条件：每 tick
- 效果：season_progress += 1 / season_length
- 若 season_progress >= 1：
- season = next_season(season)
- season_progress = 0
- 生成 season_changed 事件
- 进入过渡期（若配置了过渡）
- 滞后：无
- 影响范围：全局（所有空间单元共享季节）

### 4.2 过渡规则
- 规则：季节系数应用
- 条件：每 tick
- 效果：向 03-hydrology 提供 season_water_factor
- 向 05-soil-and-fields 提供 season_growth_factor
- 向 04-terrain 提供 season_traffic_factor
- 滞后：无（系数即时生效，但下游变量有自身变化速率上限）
- 影响范围：按空间单元分别计算

## 5. 事件类型
- `season_changed`：{old_season, new_season, tick}
- `season_transition_started`：{from_season, to_season, duration}
- `season_transition_ended`：{season}

## 6. 与其他系统的接口
- 写：03-hydrology、05-soil-and-fields、04-terrain 读季节系数。
- 因果链：季节变化是慢变量，通常作为父事件影响后续环境事件，但本身不直接触发灾害。

## 7. 地点参数占位
- 每季长度（tick）
- 季节过渡期长度（tick）
- 季节顺序（默认春夏秋冬）
- 各季节对水位/地力/作物/通行的修正系数
- 雨季/旱季对应的季节