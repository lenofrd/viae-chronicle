# GridSpace：连续栅格空间契约

> **状态：规划（ADR 011）**。本文定义目标契约，不代表 GridSpace 或 Xigu Loader 已实现。

## 1. 定位

GridSpace 是 Kernel 的通用空间定位与索引能力，用于描述有规则网格的地理数据。它与现有离散空间拓扑并存：

- Spatial Unit / SpatialNode：具有业务身份、生命周期或移动语义的世界对象。
- DistanceEdge：表达可通行连接、成本和风险。
- Grid Cell：表达某个网格中的空间位置，不自动成为实体、地点或移动节点。

## 2. GridSpec

每个网格必须显式声明：

| 字段 | 含义 |
|---|---|
| `grid_id` | 世界内稳定且唯一的网格身份 |
| `crs` | 完整 CRS 定义与轴序/单位；不得为自定义投影伪造 EPSG 代码 |
| `transform` | 像元到地图坐标的仿射变换，包含原点、像元尺寸和旋转项 |
| `width / height` | 列数与行数 |
| `pixel_size` | 地图单位下的像元尺寸 |
| `nodata` | 数据集自身的 NoData 语义；Kernel 记录定义，不把 NoData 解释为领域数值 |
| `version` | 网格定义/来源版本，便于稳定引用与迁移 |

网格身份与数据集身份不同：同一 GridSpec 可被多个数据资产引用；同一地区的 30 m、250 m、900 m 网格是不同 GridSpec。

## 3. CellRef 与坐标映射

CellRef 至少由 `grid_id`、`row`、`col` 组成。要求：

- 行列从零开始，边界约定明确；越界返回明确无效结果，不静默夹取。
- 明确坐标轴顺序、地图单位和像元中心/边界约定。
- 坐标→像元与像元→坐标在同一 GridSpec 下确定且可复现。
- 对旋转网格要么正确支持完整仿射逆变换，要么在首版明确拒绝；不得假设所有 GeoTIFF 都无旋转。
- CellRef 是位置引用，不承载地形、土壤、植被或动物状态。

## 4. 邻域、覆盖与映射

按阶段提供：

1. 单点坐标定位。
2. 四邻域/八邻域及窗口查询。
3. 点、线、面几何与 Cell 的相交/覆盖查询。
4. Spatial Unit 到 Cell 集合/覆盖范围的显式映射。
5. 多个 GridSpec 之间通过地理坐标/几何关系进行映射；禁止假设不同比例尺网格的 row/col 可直接对应。

栅格邻接只表示空间邻近，不表示可通行。人物移动仍由现有 DistanceEdge 与可达性规则决定。

## 5. Xigu Environment Seed v2 基线示例

以 Xigu-Ecology-Data 的发布契约为基线（ADR 011 引用的 2026-11-25 提交）：

- 30 m Seed 网格：668 列 × 666 行，项目自定义 WGS84 Albers Equal Area，米制；Transform 原点 (-404820, 337440)，像元 30 m，无旋转。
- 圆形模拟范围约 314.1 km²，必须使用 `sim_extent_mask`；存储 bbox 不是有效范围。
- 8.55 km² watershed 是核心水文单元，不等于整个模拟范围。
- SoilGrids 处理数据为 250 m；CHELSA 月气候态为 900 m。二者保留各自网格、单位和 NoData 规则。
- 河段是矢量几何，不应强制栅格化后丢失其线状身份。

以上值是该 Seed 版本的输入契约，不是 Kernel 的全局默认网格参数。

## 6. 状态所有权

Kernel 只管理 GridSpec、CellRef、坐标变换、邻域与空间索引。环境栅格值及其演化状态归 Environment；动物状态归 Wildlife。Kernel 不读取领域语义、不执行重采样策略、不拥有栅格数据文件。

## 7. 首版非目标

- 不把每个 Cell 转成 SpatialNode 或 Agent。
- 不创建第二套路径/移动图。
- 不在 Kernel 内实现 DEM 派生、地形分析、流域划分、土壤/气候模型。
- 不强制所有数据集对齐到同一分辨率。
- 不将 GridSpace 的 30 m/250 m/900 m 解释为 Simulation LOD 档位。
- 不预先冻结所有环境变量的最终空间离散方式；斑块、河段、田块和栅格可按变量语义混合使用。
