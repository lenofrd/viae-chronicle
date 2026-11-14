# 河段定义

## 1. 目的
定义河段作为空间单元的字段、上下游关系和河段特有属性，作为水位、渡河、灌溉、淤积的挂载基础。

## 2. 核心概念
- **河段**：河流按上下游划分的空间单元。
- **上下游顺序**：河段有 `order` 字段，数值越小越靠上游。
- **河宽等级**：窄/中/宽，影响渡河难度、流速、淤积。
- **河道形态**：直/弯/分叉，影响流速和泥沙沉积。
- **子对象**：取水点、渡口、浅滩挂在河段下。

## 3. 河段字段
| 字段 | 类型 | 说明 |
|---|---|---|
| segment_id | string | 唯一 ID，如 `river-upstream`、`river-town`、`river-downstream` |
| name | string | 显示名，如“上游河段” |
| order | int | 上下游顺序，1=最上游 |
| width_class | enum | 窄/中/宽 |
| channel_form | enum | 直/弯/分叉 |
| base_level | float | 基准水位 |
| base_velocity | float | 基准流速 |
| upstream_id | string? | 上游相邻河段 ID，最上游为 null |
| downstream_id | string? | 下游相邻河段 ID，最下游为 null |
| intake_points | list | 取水点清单（见 irrigation.md） |
| crossing_points | list | 渡口/浅滩清单（见 crossing.md） |
| state | dict | 水位、流速、淤积等状态变量（由子系统声明） |

## 4. 上下游关系规则
- 上游水位变化向下游传播，有时滞 `propagation_delay` 和衰减 `propagation_attenuation`。
- 上游截水立即减少下游来水，但下游水位下降有滞后。
- 下游淤积不影响上游，但上游来沙会增加下游淤积速率。
- 最上游河段的水量由降水和山泉决定；最下游河段的水量还受镇域取水影响。

## 5. 河段生命周期
- 河段由地点配置创建，第一版不动态增删。
- 河段状态由本子系统更新，结构不变。
- 扩展预留：允许“河道改道”“渡口冲毁”等事件临时禁用子对象，但不删除河段本身。

## 6. 事件类型
- `segment_created` / `segment_disabled` / `segment_enabled`（第一版不触发，预留）

## 7. 与其他系统的接口
- 本文件只定义结构，状态变量由 water-level.md、crossing.md、irrigation.md、siltation.md 声明。
- 记录系统按 `segment_id` 索引快照和事件。
- 02-distance-and-time 读 `crossing_points` 计算渡河时间和风险。

## 8. 地点参数占位
- 河段清单：ID、名称、order、width_class、channel_form、base_level、base_velocity
- 上下游关系：upstream_id / downstream_id
- 取水点清单：ID、名称、位置描述、最大取水量
- 渡口清单：ID、名称、类型（渡船/浅滩）、通行时间、风险