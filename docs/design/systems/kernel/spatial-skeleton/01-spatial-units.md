# 空间单元定义

## 1. 目的
精确定义每类空间单元的字段、属性和生命周期，作为数据结构和记录格式的依据。

## 2. 通用字段（所有单元共有）
| 字段 | 类型 | 说明 |
|---|---|---|
| unit_id | string | 唯一 ID，如 `brookvale/mill`、`field-east-1`、`river-upstream` |
| unit_type | enum | 镇域节点/田地片/河段/山层/资源点 |
| name | string | 显示名，如“磨坊”“东片田”“上游河段” |
| parent_id | string? | 所属父单元（资源点挂山层/河段，镇域节点挂镇域） |
| description | string | 自然侧写：地势、离河远近、周边植被、易涝与否 |
| links | list | 与其他单元的连接（见 02-distance-and-time） |
| state | dict | 各子系统挂载的状态变量（由子系统声明，本文件不重复） |

## 3. 各类型特有字段

### 3.1 镇域节点
- `node_kind`：建筑/场所/空地
- `elevation_band`：地势高低（低/中/高），影响易涝
- `distance_to_river`：离河远近（近/中/远）
- `surrounding_vegetation`：周边植被（无/稀疏/茂密）

### 3.2 田地片
- `position`：近河/远河、上游/下游
- `area`：面积等级（小/中/大），影响劳作时间
- `irrigation_source`：依赖哪个取水点/水渠

### 3.3 河段
- `order`：上下游顺序（1=最上游）
- `width_class`：河宽等级（窄/中/宽），影响渡河难度
- `crossing_points`：渡口/浅滩清单

### 3.4 山层
- `depth`：山脚/浅山/深山
- `elevation_range`：海拔范围（相对描述）
- `terrain_risk`：迷路/滑坡/野兽风险等级

### 3.5 资源点
- `resource_type`：草药/柴薪/猎物/鱼/石料等
- `species`：具体种类（如柴胡、石斛）
- `regeneration_rate`：再生速度（快/中/慢/极慢）
- `gathering_difficulty`：采集难度（低/中/高）
- `risk`：采集风险（无/低/中/高）

## 4. 单元生命周期
- 单元由地点配置创建，第一版不动态增删。
- 单元状态由各子系统更新，本子系统只维护结构。
- 扩展预留：允许“建筑损毁”“山路中断”等事件临时禁用单元或连接，但不删除单元本身。

## 5. 事件类型
- `unit_state_changed`：{unit_id, subsystem, variable, old, new}
- `unit_disabled` / `unit_enabled`：临时禁用/恢复（如山路中断、渡口关闭）

## 6. 与其他系统的接口
- 本文件只定义结构，不定义状态变量。状态变量由各子系统在自己的文档里声明，挂到 `state` 字典下。
- 记录系统按 `unit_id` 索引快照和事件。