# 溪古镇世界生成内容迁移说明

> 本文件为历史设计内容的迁移索引，不再定义独立地点、世界配置或运行时输出。

溪古镇沿用仓库既有地点身份 `brookvale-town` / `brookvale-town-001`。依据 ADR 003 与 ADR 005，不得创建平行的 `xigu-town` 地点目录、`xigu-town-001` 世界 ID 或第二套空间节点身份。

本文件原先记录的地形布局、三大开放生计区、路网与可达性、生态资源循环、季节灾害和社会事件，现统一归入既有地点文档：

- 地点定位、空间骨架与三大生计区：`docs/design/locations/brookvale-town/00-overview.md`
- 镇内节点、聚落分区与路网约束：`docs/design/locations/brookvale-town/01-geography/01-town-core.md`
- 田地节点、12 块水浇田、9 块坡旱地及河渔/山林生计区：`docs/design/locations/brookvale-town/01-geography/04-fields.md`
- 初始人口、住宅槽位、治理迁移与世界生成约束：`docs/design/locations/brookvale-town/05-setup/01-initial-state.md`
- 通用建筑、生态、事件与 Replay 机制：`docs/design/systems/`

地图布局采用翠溪南北向位于地图西侧、聚落和田地位于东岸；但空间节点 ID、水文上下游关系、既有地标和运行时配置继续沿用 Brookvale。栅格仅可作为既有空间节点的细化，不得替代或复制地点身份。

任何世界生成脚本、事件数据库和配置输出都必须使用 Brookvale 既有世界身份。历史命令和路径仅供迁移追溯，不再作为新增世界的目标路径。
