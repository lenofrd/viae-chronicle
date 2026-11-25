# ADR 011：Xigu 地理环境数据接入与双空间模型

- **状态**：Accepted
- **日期**：2026-11-25
- **适用范围**：World Kernel、Environment、World Orchestration、Location/Scenario 配置及外部地理数据集成
- **依据**：
  - Viae Chronicle `ecology-foundation`：`db6bf72be9c4936777b6a03a25645eb1c151e29f`
  - Xigu-Ecology-Data `main`：`52e0d5517ea7d3d83c5641b9cf714d26fefe2944`
  - ADR 009「自然环境与人文系统的分层及领域边界」
  - ADR 010「Ecology Foundation and Simulation LOD」
- **关联设计**：[Kernel 空间骨架](../systems/kernel/spatial-skeleton/00-overview.md)、[GridSpace 契约](../systems/kernel/spatial-skeleton/04-grid-space.md)、[Environment Seed 接入计划](../systems/environment/01-xigu-environment-seed-integration.md)

## 1. 背景

Viae Chronicle 已有离散空间单元、连接、距离成本、可达性与空间索引。Xigu-Ecology-Data 则已发布 Environment Seed v2（权威 manifest v3），提供试点地理环境栅格、河段矢量，以及独立分辨率的土壤和气候数据。

两者解决的问题不同：

- Xigu 负责真实地理数据的获取、GIS 处理、质量控制、资产登记和版本发布。
- Viae 负责把数据装配为一个可模拟的世界，并由 Environment/Wildlife 等领域持续演化状态。

若只沿用离散节点，会丢失连续地理场；若把每个栅格像元转成 SpatialNode，则会把地理采样单元误作移动拓扑节点并造成不必要的实体膨胀。必须明确支持两种空间表示共存。

## 2. 决策

### 2.1 双空间模型：离散拓扑与连续栅格并存

Kernel 同时支持：

1. **离散拓扑空间**：现有 SpatialNode/Spatial Unit、DistanceEdge、SpatialIndex、路径与可达性机制。用于聚落节点、田块、河段、场所、移动和通行成本。
2. **连续栅格空间（GridSpace）**：具有明确网格身份、CRS、仿射变换、行列尺寸、像元尺度和 NoData 语义的地理数据空间。用于地形、土壤、气候、土地覆盖等空间场定位与查询。

两种空间共享世界空间身份和显式映射关系，但不能互相替代。既有移动拓扑继续有效，不因引入栅格而重写。

### 2.2 GridSpace 的内核职责

Kernel 负责通用、域中立的空间机制：

- GridSpec：稳定的 grid_id、CRS 定义、仿射 Transform、宽高、像元尺寸、轴向/旋转约束及版本标识。
- CellRef / Cell ID：由 grid_id 与 row/col 等稳定字段组成；索引越界和无效区域必须可判定。
- 坐标与像元互转：明确像元中心/边界约定、坐标轴顺序、单位和边界行为。
- 邻域与覆盖查询：四/八邻域、窗口、点定位、几何与像元相交查询；具体能力按阶段实现。
- 与现有空间对象的映射：Spatial Unit、河段、田块、聚落节点可引用 Cell 或覆盖范围；映射必须显式、可复现。
- 空间索引：支持离散对象索引与栅格索引协作，不复制一套移动图。

Kernel **不拥有** DEM 数值、土壤属性、气候变量、植被覆盖、生物量、水文状态等领域数据，也不依赖 Xigu 的仓库目录、SQLite Schema 或 GIS 处理脚本。

### 2.3 栅格 Cell 不是 SpatialNode

- 不得将 Environment Seed 的每个 30 m 像元创建为一个 SpatialNode 或移动实体。
- Cell ID 是地理数据的空间引用，不自动拥有实体生命周期、移动边或社会行为。
- 既有 SpatialNode 可映射到一个或多个 Cell；一个 Cell 也可被多个领域查询引用。
- 人物移动仍通过 DistanceEdge / 路径 / 可达性机制；栅格邻接不等于可通行连接。
- 不得把连续栅格压缩成少量地形、河流或资源节点，从而丢失需要保留的空间差异。

### 2.4 多分辨率数据必须保留原生语义

Xigu 当前发布基线（以所引用提交为准）：

| 数据 | 原生/发布空间尺度 | 使用约束 |
|---|---:|---|
| Environment Seed v2 地形、坡度、坡向、TPI、WorldCover、模拟范围掩膜、流域掩膜 | 30 m | 共享 668 × 666 网格与同一 Transform；先应用 `sim_extent_mask` |
| 河段 | 矢量 LineString | 保留完整几何；按分析范围显式裁剪，不以 bbox 代替模拟范围 |
| SoilGrids 2.0（土壤四属性） | 250 m | 保留独立网格、单位、NoData；不可冒充 30 m 实测精度 |
| CHELSA v2.1（月气候态 tas/pr，1981–2010） | 900 m | 属气候态而非逐日/逐年时间序列；不可冒充 30 m 或当前天气 |

规则：

1. 不得默认把所有输入重采样到 30 m。
2. 重采样/聚合必须由数据语义决定，记录方法、目标网格、NoData 与掩膜规则；派生数据须标记来源和 `derived` 状态。
3. 掩膜需重采样到目标数据网格时，必须显式指定方法；类别/掩膜使用适当的离散方法，连续变量按契约处理。
4. 不得用 SoilGrids SOC 直接宣称已实现动态碳循环；不得把 WorldCover Tree cover 直接等同森林年龄、生物量或群落结构。
5. 数据空间分辨率与 Simulation LOD（fine/normal/coarse）完全独立。LOD 决定模拟计算细节，不改变源数据精度。

### 2.5 状态所有权与依赖方向

| 职责/状态 | 所有者 |
|---|---|
| CRS、GridSpec、Cell ID、坐标变换、空间索引与映射机制 | World Kernel |
| 地形、气候、水文、土壤、植被等环境状态及其动态演化 | Environment |
| 动物个体、种群、行为与动物侧生态状态 | Wildlife |
| Seed 版本、数据资产、原始/处理文件、manifest、质量报告 | Xigu-Ecology-Data |
| Seed 选择、世界装配、加载生命周期和运行配置 | World Orchestration / World Assembly |

Xigu 数据被加载后只是 Environment 初始化与边界条件的输入。Environment 必须拥有并结算运行时动态状态；Kernel 不能成为环境数据仓库或第二套领域状态存储。跨域影响继续遵循 ADR 009/010 的契约和状态所有权规则。

### 2.6 数据接入边界

- Xigu 仓库是外部数据产品源；Viae 不复制其原始/处理栅格、矢量、SQLite 数据库或 GIS 管线。
- Viae 通过受版本控制的 Seed manifest 和数据包位置读取资产。运行时不能依赖 Xigu 仓库内部数据库 Schema 作为唯一接口。
- Loader 位于 World Assembly / 数据集成边界，不放入 Environment 领域内部；Environment 不依赖 Xigu 文件目录、GDAL/Rasterio 等具体 IO 实现。
- Loader 在构建世界状态前校验 manifest 版本、资产路径、SHA-256、CRS、Transform、尺寸、分辨率、单位、NoData、Mask、许可/来源和必需资产。
- 加载失败必须明确报错；禁止静默忽略资产、隐式改变 CRS、隐式重采样或把 NoData 当成零值。
- 数据资产只读；数据修订由 Xigu 发布新版本，Viae 通过显式升级 Seed 引用。

### 2.7 地点身份与模拟范围

- Xigu 当前锚点为 `brookvale-town-001`，候选坐标 104.126366°E、35.875187°N。该锚点与 Viae 既有 Brookvale 世界/地点身份的对应关系必须在接入前核验；在核验完成前不得创建第二个平行世界身份或将候选坐标写死为全局事实。
- Environment Seed 模拟范围是以锚点为圆心、半径 10 km 的圆形（约 314.1 km²），不是 bbox，也不是核心流域。
- 核心水文流域为 8.55 km²，仅占模拟范围的一部分；不得把 watershed mask 当成完整模拟范围。
- 判断模拟范围必须使用 `sim_extent_mask`；bbox 只描述存储窗口。
- 河段几何可能超出 bbox；按具体查询/统计目标显式裁剪。

## 3. 实施顺序与范围

详细任务和验收口径见 [Environment Seed 接入计划](../systems/environment/01-xigu-environment-seed-integration.md)。

- **P0：契约与身份冻结**——核对 Brookvale 身份、Seed manifest、版本、校验和、CRS、Transform、范围与许可；暂不运行生态模拟。
- **P1：Kernel GridSpace**——建立 GridSpec、CellRef、坐标/像元互转、邻域查询及与现有 Spatial Unit 的映射；不重写移动拓扑。
- **P2：Environment Seed Loader**——按 manifest 校验并加载当前发布资产；保留 30/250/900 m 不同尺度；不复制 GIS 处理管线。
- **P3：Environment 动态模型**——把输入转为 Environment 拥有的初始状态，逐步建立可独立推进的环境演化闭环。
- **P4：Wildlife 与跨域生态循环**——在 P3 基础上接入种群、栖息地、取食、分解和养分循环。

当前优先推进 P0–P2；P3–P4 不因 Seed 发布而自动启动。

## 4. 明确不做

- 不将全部 30 m 像元转成 SpatialNode。
- 不以少量离散节点替代连续地理场。
- 不把所有数据强制重采样到 30 m。
- 不在 Viae 重做 DEM、TPI、河网提取、流域划分等 GIS 处理。
- 不把静态 Seed 当成动态生态模拟，不把静态分类直接当成生物量/种群。
- 不在本决策中冻结最终所有环境变量的计算单元；栅格、斑块、河段或混合表达由真实试点验证。
- 不在本轮引入复杂自适应 LOD 或大规模物种数据库。

## 5. 后果

- Viae 获得连续地理场表达能力，同时保留已有地点节点、路径与移动成本模型。
- Kernel 与 Environment 的状态边界清晰：前者拥有空间机制，后者拥有环境状态。
- 多分辨率数据可以按其真实精度参与环境查询，避免虚假精度。
- Xigu 与 Viae 通过稳定、可验证的 Seed 契约协作，避免重复 GIS 管线和数据双写。
- 这项决策只冻结架构方向和接入边界，不表示 GridSpace、Loader 或 Ecology-only 运行能力已经实现。
