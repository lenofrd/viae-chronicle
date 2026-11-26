# Xigu Environment Seed 接入计划

> **状态：规划；当前建议只推进 P0–P2。** 本文是 ADR 011 的实施分解，不代表相关代码或导入验收已完成。

## 1. 数据源基线

- 仓库：`lenofrd/Xigu-Ecology-Data`
- 基线分支/提交：`main` / `52e0d5517ea7d3d83c5641b9cf714d26fefe2944`
- Seed：Environment Seed v2，发布清单 `processed/environment_seed_v2/seed_manifest_v3.json`
- 数据契约文档：`Documentation/Environment_Seed_v1_数据契约.md`（文档版本 v3，2026-11-25）
- Viae 基线：`ecology-foundation` / `db6bf72be9c4936777b6a03a25645eb1c151e29f`

该基线包含 30 m 地形/地形衍生/WorldCover/范围掩膜/流域掩膜及河段矢量；土壤与气候作为独立数据集分别以 250 m、900 m 发布。数据资产、manifest 和 SQLite 登记属于 Xigu 仓库；本计划不要求将数据二进制提交到 Viae。

## 2. 阶段计划

### P0 — 数据契约与世界身份冻结

**任务**
- 核对 Viae 既有 Brookvale Location/World 生成身份与 Xigu `brookvale-town-001` 的映射，确认唯一 world/location identity。
- 固定 Seed manifest 版本、数据包获取方式、许可与来源、资产清单、SHA-256。
- 明确 CRS 完整定义、Transform、尺寸、分辨率、单位、NoData、模拟范围 Mask、河段几何裁剪口径。
- 明确外部数据包在运行环境中的定位方式；不把本地绝对路径写入世界配置或事件。
- 明确 Seed 升级策略：版本显式切换，旧版本可追溯，不原地覆盖。

**验收**
- 有一份被 Viae 识别的 Seed 描述及校验规则。
- 合法 Seed 可通过静态契约验证；错误版本、哈希、CRS、Transform、Mask 或必需资产缺失时明确拒绝。
- 不需要启动生态模拟，也不修改 Xigu 原始/处理数据。

### P1 — Kernel GridSpace 最小能力

**任务**
- 定义 GridSpec、CellRef、稳定网格身份、坐标/像元互转。
- 定义边界、NoData/无效 Cell、轴序、像元中心/边界约定。
- 实现最小点定位、四/八邻域与窗口查询。
- 定义现有 Spatial Unit/SpatialNode 与 Cell/Cell 集合的显式映射。
- 保持 SpatialIndex、DistanceEdge、Dijkstra/可达性与移动时间语义不变。

**验收**
- 同一坐标与同一 GridSpec 稳定映射到同一 Cell；越界与 Mask 外位置可明确识别。
- 多分辨率 GridSpec 不会因相同 row/col 被误认为同一 Cell。
- 河段/田块/聚落节点可以引用栅格位置或覆盖范围。
- 现有移动路径和成本基线不受影响。
- 不创建每像元一个 SpatialNode。

### P2 — Environment Seed Loader

**任务**
- Loader 放在 World Assembly / 数据集成边界，不放进 Environment 领域内部。
- 读取权威 manifest，校验版本、资产路径、SHA-256、CRS、Transform、尺寸、单位、NoData、Mask 和数据来源。
- 首批接入 DEM、slope、aspect、TPI、WorldCover、sim_extent_mask、watershed 与 rivers。
- SoilGrids 250 m、CHELSA 900 m 以独立 GridSpec 加载；按目标数据网格显式处理 Mask，不伪装为 30 m。
- Loader 输出与领域 IO 解耦的只读数据视图/初始输入；Environment 将其解释为自身状态。

**验收**
- 同一 Seed、同一配置可重复加载，网格身份、索引和摘要一致。
- 哈希或空间契约不符时失败关闭；NoData 不被当作零。
- 圆形模拟范围由 `sim_extent_mask` 决定；watershed 不被误用为全域 Mask。
- 加载过程只读 Xigu 数据，不复制 GIS 分析管线，不修改源资产。
- 能报告未支持的资产或变量，不静默丢弃。

### P3 — Environment 动态状态（后续阶段）

- 将静态输入转换为 Environment 拥有的地形、土壤、水文、气候、植被初始状态。
- 明确每个变量采用栅格、斑块、河段、田块或混合表达的依据。
- 建立 Environment 独立于 Human Society 的初始化、推进、观察、回放闭环。
- 不把 WorldCover 类别直接当作森林生物量/年龄结构；不把 CHELSA 气候态当作逐日天气；不把 SOC 静态值当作动态碳循环。

### P4 — Wildlife 与跨域生态循环（后续阶段）

- Wildlife 使用环境查询获取栖息地/食物/水条件；动物个体或种群不强制一像元一实体。
- 明确种群空间分布、觅食、饮水、迁移和死亡表达。
- 通过跨域影响契约处理植被消耗、排泄、尸体、分解与养分回归。
- 以守恒、确定性、回放和多物种生态闭环验收。

## 3. 当前优先级裁决

| 阶段 | 当前决定 | 原因 |
|---|---|---|
| P0 | **立即推进** | 不冻结数据/身份契约，后续导入会产生不可追溯耦合 |
| P1 | **在 P0 契约明确后推进** | 先补通用空间能力，避免将栅格误塞进现有移动拓扑 |
| P2 | **P1 最小能力通过后推进** | 证明真实 Seed 可验证、可重复加载 |
| P3 | 暂缓 | 先验证真实数据与状态模型边界，不提前扩张生态复杂度 |
| P4 | 暂缓 | 依赖 Environment 状态模型和 Ecology Seed，不能由静态地理 Seed 直接推出 |

## 4. 明确不做

- 不把 Xigu 仓库整体并入 Viae，也不把原始/处理栅格、矢量或 SQLite 复制进 Viae Git。
- 不在 Viae 重做 DEM、TPI、流域、河网等 GIS 生产管线。
- 不把 30 m 像元转成 SpatialNode/Agent。
- 不把所有变量重采样到 30 m；不虚增土壤/气候精度。
- 不将静态地理资产标记为已实现的动态生态状态。
- 不在本轮实现复杂自适应 LOD；数据分辨率与 Simulation LOD 分离。
- 不因接入 Xigu 而重写现有 DistanceEdge、路径、可达性或 Location 身份系统。

## 5. 未决事项与风险门禁

1. **Brookvale 身份映射**：在读取并核对 Viae Location/World 配置前，`brookvale-town-001` 仅是候选外部锚点 ID。
2. **模拟范围与流域范围**：314.1 km² 圆形模拟范围、bbox 存储范围、8.55 km² 核心流域是三个不同概念。
3. **多分辨率与 NoData**：250 m/900 m 网格有独立 Transform/尺寸和缺失值规则，必须保留源语义。
4. **静态数据与动态状态**：Seed 只提供初始化输入/边界条件，不代表 Ecology-only 或生态循环验收通过。
5. **数据包分发**：Viae 运行环境如何获得与校验外部资产需在 P0 定义；不得依赖开发机绝对路径。

## 6. 当前实现状态声明

截至本计划引用的 Viae 与 Xigu 提交：

- Xigu Environment Seed v2 已发布并登记；其发布核验属于 Xigu 侧结果。
- Viae 侧 Seed 导入、GridSpace、Loader 与 Ecology-only 初始化验收**尚未据此证明完成**。
- 本文冻结的是接入方向与分阶段验收，不声明任何 Viae 代码能力已实现。

## 7. 落地注记（2026-11-26，P0）

P0（数据契约与世界身份冻结）已落地，范围与偏差如下：

- **Seed 描述与冻结**：`config/worlds/brookvale-town-001/world.yaml` 新增可选
  `environment_seed` 节（schema：`src/vale/config/schema/environment_seed.py`），
  冻结 seed_id `environment-seed-v3`、10 个必需资产（含 SHA-256 与 size）、
  网格契约（CRS PROJ 串 + WKT 参数片段、668×666、30 m、Transform）、
  锚点、模拟范围/流域口径、来源与升级策略。真实 SHA-256 冻结前已对
  本机实际发布文件（Xigu 工作区）逐件复算核验一致（10/10）。
- **身份映射结论**：Viae 唯一世界 `brookvale-town-001`（溪谷镇）与 Xigu
  锚点 `brookvale-town-001（候选 6）` ID 级一致，锚点坐标
  104.126366°E / 35.875187°N（Albers -394804.54, 327448.73）经
  P0 核验后进入世界级契约（`anchor.world_ref` 必须等于 `world_id`，
  由 `seed_world_binding_errors` 核对）；两侧均无平行世界身份。
  过程性坐标在 Viae 既有生成身份（本地 64×40 过程网格）与 Albers
  668×666 网格之间**尚无几何映射**——那是 P1 显式映射的范畴，本节不隐含。
- **静态契约校验**：机制在 `src/vale/world/seed_contract.py`（可复用模块，
  数据集成边界，P2 Loader 复用；不依赖 GDAL/Rasterio）；CLI 入口
  `scripts/check_seed.py`（`--world` / `--contract` / `--cache-root`，
  退出码 0/1/2）。校验失败关闭：版本、哈希（manifest 与实际文件双重）、
  CRS、Transform、网格尺寸、NoData 语义、必需资产缺失均明确拒绝；
  manifest 中冻结清单外的资产（如 `watershed_legacy_nofix`）显式报告、
  不作通过条件。专项测试 `tests/test_seed_contract.py`（38 项，fixture 驱动）。
- **B+C 分发定位**：部署环境把包挂载到缓存根（环境变量 `VALE_SEED_CACHE`，
  缺省 `<仓库根>/data/seed-cache`），包内资产以 manifest 所在目录 +
  basename 解析（兼容整仓镜像与仅挂载包目录两种布局）。**待裁决**：该
  缓存根解析规则为老板 2026-11-26「有条件采纳」的临时实现，条件明示前
  不改语义；世界配置不含任何机器绝对路径。
- **与 §2/§P0 清单的偏差**：① 矢量资产（rivers）在真实 manifest 中不写
  `status` 键（惯例：仅非 active 资产显式标注），校验器按 active 处理并
  在报告中显式说明；② Xigu 侧正式 GitHub Release 标签尚未发布，
  `source.release` 暂为 null（发布后回填）；③ GridSpace/Loader/导入
  本身属 P1/P2，本节不声明完成（见 §6）。
