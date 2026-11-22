# 土地地块与建筑空间模型

> systems / human-environment / social-spaces：通用空间机制；地点提供地块划分和参数。

## 1. 三层空间模型

1. TerrainCell：地形、坡度、水文、生态和风险。
2. LandParcel：连续或逻辑连通的土地范围，承载用途、权属和可建设条件。
3. Building：实际占地的建筑实体，具有 footprint、功能、耐久和容量。

地形格子不等于土地地块；地块不等于建筑。一个地块可以包含住宅、柴棚、菜地和院落通道等多个空间组成。

## 2. LandParcel 字段

| 字段 | 含义 |
|---|---|
| parcel_id | 唯一 ID |
| cell_ids / geometry | 覆盖格子或边界 |
| area | 面积 |
| land_use | 当前用途 |
| owner_type / owner_id | 所有权主体 |
| tenure_ids | 权利记录 |
| buildable_area | 可建设面积 |
| reserved_area | 已预留或不可再占面积 |
| access_points | 入口与道路连接 |
| boundary_markers | 田埂、界石、沟渠等 |
| risk_profile | 洪水、滑坡、火灾等风险 |
| protection_tags | 保护和禁建标签 |
| status | 有效、争议、废弃、待测界 |

## 3. Building 字段

building_id、building_type、parcel_id、footprint、entrance_cell、owner_type、owner_id、occupant_household_ids、capacity、condition、construction_status、built_tick、maintenance_state、access_rules。

一个宅基地可容纳多个互不重叠的建筑。建筑入口应连接道路、院落通道或合法步行路径。

## 4. 混合空间表达

- 建筑 footprint 必须落在实际地块或已授权公共用地上。
- 生产棚、晒场等可采用开放式 footprint，不必强制表示为封闭房屋。
- 道路、沟渠、河岸通道可采用线性通行权，不因穿越地块而把整块私有土地变为公共用地。
- 地标节点可关联建筑，但节点本身不替代地块和建筑占地。

## 5. 占地检查

选址时检查 footprint 是否完全位于候选地块或授权范围内、是否与现有建筑重叠、是否侵占道路水渠河道和第三方通行权、是否超过可建设面积、是否满足退界间距和风险阈值、是否违反保护标签和用途规划。

失败原因应可解释，例如 overlaps_existing_building、blocks_access、outside_parcel_boundary、insufficient_buildable_area 或 protected_land。

## 6. 边界与灾害

田埂、界石、沟渠和道路可作为地块边界标志。洪水、滑坡和人为改造可能使标志损坏，但不能自动把土地转给邻户。

边界模糊后标记 disputed 或 boundary_uncertain，暂停争议区域的新建和转让；允许测界、见证、协商和议事裁定；结果通过事件更新边界版本。

## 7. 与建筑节点的关系

既有建筑节点模型继续负责场所社会功能、开放状态、在场人物和活动。地块/建筑实体模型负责物理占地、权属、面积和施工状态。两者通过 building_id 关联，不互相替代。

## 8. 验收条件

1. 一个地块可包含多个互不重叠的建筑 footprint。
2. 一个建筑必须有合法地块或公共用地授权。
3. 地形格子、地块和建筑 ID 独立。
4. 地块边界变化不会静默转移产权。
5. 建筑入口有合法通达路径。
6. 占地检查可重复且确定性一致。
