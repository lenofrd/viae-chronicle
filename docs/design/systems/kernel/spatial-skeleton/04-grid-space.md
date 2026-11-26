# GridSpace：连续栅格空间契约

> **状态：部分实现（ADR 011 · P1，2026-11-26）**。§2 GridSpec、§3 CellRef 与坐标映射、§4 第 1/2/4 项已落地于 `src/vale/core/grid_space.py`（专项测试 `tests/test_p1_grid_space.py`，落地口径见 §8）。§4 第 3 项（几何相交/覆盖查询）与第 5 项（多 GridSpec 间映射）仍为规划；Xigu Loader 未实现（P2）。

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

1. 单点坐标定位。**（P1 已实现：`GridSpace.locate`）**
2. 四邻域/八邻域及窗口查询。**（P1 已实现：`GridSpace.neighbors` / `window`）**
3. 点、线、面几何与 Cell 的相交/覆盖查询。（未实现，后续阶段）
4. Spatial Unit 到 Cell 集合/覆盖范围的显式映射。**（P1 已实现：`GridBinding`）**
5. 多个 GridSpec 之间通过地理坐标/几何关系进行映射；禁止假设不同比例尺网格的 row/col 可直接对应。（未实现，后续阶段）

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

## 8. 落地注记（P1，2026-11-26）

实现于 `src/vale/core/grid_space.py`，专项测试 `tests/test_p1_grid_space.py`（16 项），域中立静态检查并入架构闸 `tests/test_p8_architecture_gates.py` 第 13 条（core 无 `domains/` 导入、无 Xigu 仓库/文件依赖、无环境变量语义）。实现口径与偏差：

- **仿射系数序**：`transform` 为 `(a, b, c, d, e, f)`，`x = a*col + b*row + c`、`y = d*col + e*row + f`，`(c, f)` 为像元 (0,0) 左上角——与 `world.yaml` seed 网格冻结的 transform 同序（P2 Loader 可直接由冻结值构造 GridSpec）。
- **旋转网格**：按 §3「二选一」取**明确拒绝**——`b`/`d` 非零在 GridSpec 构造时即报错；非北向上（`a ≤ 0` 或 `e ≥ 0`）同样显式拒绝，由数据入栈侧翻转，Kernel 不换算。
- **方形像元假定**：`pixel_size` 与 `a`、`-e` 做一致性校验，非方形网格显式报错（首版范围内所有已知网格均为方形；非方形需求出现时另行裁决）。
- **边界约定**：内部边界归属行/列号较大的一侧；网格外沿（x ≥ x_max 或 y ≤ y_min）越界。`locate` 对越界坐标返回 `None`（不静默夹取）；`validity` 三态明确区分 `out_of_bounds` / `masked` / `valid`。
- **Mask 注入**：Mask 不由 Kernel 读取（§6），以 `GridSpace(spec, valid_cells=...)` 显式注入；`valid_cells=None` 表示未定义 Mask（与「全网格有效」语义区分，由调用方保证口径）。
- **GridBinding**：单元→Cell 集合显式映射；只要求像元界内（是否要求 Mask 内由调用方决定）；重复绑定、跨网格 CellRef、越界像元、空输入显式报错，绑定原子。与 `SpatialIndex` 的「协作」仅为并行使用——`travel_tu` 仍全部由 DistanceEdge 节点图给出，Cell 不进入移动图。
- **邻域/窗口**：只表达几何邻近（Mask 外像元照常返回，是否过滤由调用方决定）；结果按 (row, col) 行主序排序，确定性可复现；窗口越界部分按边界裁剪属集合枚举语义，不影响 `locate`/`validity` 的越界判定。
- **网格数值定义不入 config**：P1 为纯机制，GridSpec 由调用方构造（测试用冻结值副本）；P2 Loader 将由 `world.yaml` 冻结契约装配真实网格。
- **无新增待裁决项**；几何相交查询与多 GridSpec 映射留后续阶段。
