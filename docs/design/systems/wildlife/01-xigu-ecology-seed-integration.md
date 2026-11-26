# Xigu Ecology Seed v1 接入（E 轨数据线）短设计

> **能力状态**：EX-0 已实现（2026-11-26 老板裁决有条件批准后落地：契约冻结、静态校验、完整性验证，落地注记见 §5）；E3–E5 运行时消费未实现（裁决**暂缓**），EX-1/2/3 与落格消费保持规划。
> 依据：ADR 010（生态基础）、ADR 011（Xigu 接入与 GridSpace，P3/P4 定义与「不因 Seed 发布自动启动」约束）、任务书 §三 E3–E5、Xigu「Ecology Seed v1 数据契约 v1.1」（`Xigu-Ecology-Data @ 0343844`，外部仓库 `Documentation/Ecology_Seed_v1_数据契约.md`）、Environment Seed P0 冻结契约（`config/worlds/brookvale-town-001/world.yaml` `environment_seed` 节）。
> 上游环境基线 = P0 已冻结的 Environment Seed v2（manifest v3）；本文是**生态/群落数据线**（物种、出现记录、性状、功能组、种间关系、初始状态）的接入设计，服务 E3–E5（ADR 011 P3/P4）。

## 1. 数据包现状（2026-11-26 摸底，证据齐）

- **发布**：GitHub Release `ecology-seed-v1.0`（B 渠道首次实际行使），资产 `ecology_seed_v1.zip`（181,835 B，sha256 `bc74f400…a7bc5a8`，API digest 与 Xigu 变更日志一致）。本地发布件 `Xigu-Ecology-Data/processed/ecology_seed_v1/`：`manifest.json` + `ecology_seed_v1.sqlite`（1.27 MB）+ 7 个导出 CSV（注：Xigu 变更日志写「8 CSV」，实际 7 CSV + 1 SQLite，以 manifest 为准）。
- **可核验性（P0 口径复算）**：manifest 声明的 8 个文件**哈希与字节数 9/9 一致**（含 manifest.json 自身实测 sha256 `27d30b76…f5b44`）；SQLite↔CSV↔manifest **行数 7/7 全等**（taxa 14 / species_records 1,254 / functional_groups 5 / traits 14 / ecological_interactions 30 / habitat_associations 24 / initial_state 53）。
- **数据实况**：
  - **taxa（14）**：植物 9（producer：乔木 6、灌木 2、草本 1；4 条为 COL 同物异名）+ 鸟 5（predator：红尾伯劳、灰背伯劳；herbivore：麻雀、金翅雀、雉鸡）。**无鱼、无兽**——与 full profile 既有 wildlife 池物种类（fox/rabbit/boar/serpent 等）不重合。
  - **functional_groups（5）**：FG_PLANT_SEED（producer 聚合，C）、FG_INSECT_PREY（herbivore 聚合，C）、FG_PLANT_LITTER（substrate，D）、FG_SOIL_DECOMPOSER（decomposer，D，experimental）、FG_NUTRIENT_POOL（substrate，D）。后三个为本地推导（`SRC_VIAE_LOCAL_DERIVED`），无外部证据。
  - **interactions（30）**：鸟类→种子/昆虫取食（GloBI，C 级 global）；植物→种子/凋落物 produces/senescesTo（D 级模拟假设）；凋落物→分解者→养分池（D 级）；另含 3 条反向 eatenBy。食物链闭合：植物→（种子/凋落物）→鸟/分解者→养分。
  - **occurrences（1,254）**：GBIF/eBird 为主（CC BY 4.0），A2 级仅 2 条、B 级 1,252 条（坐标不确定度缺失或超阈）；WGS84 经纬度；每条带 habitat_class（WorldCover 类别）与 habitat_share（500 m 邻域占比统计）。
  - **traits（14）**：植物 growth_form（tree/shrub/herb，B 级文献）、鸟类 diet（carnivore/omnivore/granivore，C 级 GloBI 归纳）。
  - **habitat_associations（24）**：按 taxa × `simulation_circle+LC30/LC40/LC50` 的 500 m 邻域 WorldCover 占比（A2/B 级；LC50 建成区按 Xigu 侧裁决保留统计但标低可信度）。
  - **initial_states（53）**：L1（simulation_circle）/L2（core_watershed）/L3（circle+WorldCover 类）三级视图，quantity_type（cover/density/biomass）与 unit 齐备，**quantity_value 全部 NULL + unknown_reason**（「无本地实测，不能据此估计绝对盖度/密度」）。
- **升级契约**：学名/分类变更须换新版本线（契约 §11）；当前 1.0.0。
- **Xigu 侧文档疏漏（供老板转告 Xigu 侧，不影响数据本身）**：① 变更日志把 manifest.json 的哈希误写为 SQLite 的哈希（`fdeda401…c495` 实为 `ecology_seed_v1.sqlite`；manifest.json 实测 `27d30b76…f5b44`）；②「8 CSV」计数与 manifest 不符（7 CSV + 1 SQLite）。

## 2. 身份与空间绑定

- **世界绑定**：包内 spatial_ref 三级（`simulation_circle` / `core_watershed` / L3 = circle+WorldCover 类）即 P0 冻结的圆形模拟范围与核心流域口径；Viae 侧契约须带 `world_ref == world_id` 绑定核对（同 P0 模式）。
- **坐标事实**：occurrences 为 WGS84 经纬度；落到 30 m Albers 网格需 WGS84→自定义 Albers 变换（P1 GridSpace 职责）。**静态结构接入不依赖落格**（spatial_ref 已按范围/流域分级，L3 按类别聚合）。
- **证据等级 Viae 使用口径**（契约 §6 映射）：A1/A2 → 存在与生境统计依据；B → 存在依据（空间精度有限，不据此定位个体）；C → 关系/归纳线索（食物网结构可用，强度不可用）；D → 模拟假设，**必须显式标注为假设**，不冒充数据。

## 3. 消费映射（运行时归属按 ADR 010 §2.3，数据不拥有状态）

| 数据对象 | 运行时归属 | 消费点 | 用法与约束 |
|---|---|---|---|
| taxa 植物（9） | Environment（植被物种身份） | E3 | 物种清单 + growth_form；对应 ADR 011 P3「Environment 动态模型」初始状态来源裁决的候选 |
| taxa 鸟（5） | Wildlife（物种目录） | E4 | 物种清单 + diet；种群机制 E4 主题（ADR 011 P4） |
| occurrences（1,254） | 证据层，不进运行时状态 | E3/E4 | 分布/存在依据（B 级为主）；落格依赖 P1；不据此生成种群数值 |
| traits（14） | 参数线索 | E3/E4 | 映射为域参数**取值建议**；数值仍由老板裁决 |
| habitat_associations（24） | Environment | E3 | 按类别的生境统计；LC50 低可信度不用于偏好推断 |
| FG_PLANT_LITTER / FG_NUTRIENT_POOL / FG_SOIL_DECOMPOSER | Environment（凋落物/养分/分解者） | E5 | ADR 010 §2.3 明确归 Environment；D 级假设 |
| FG_PLANT_SEED / FG_INSECT_PREY | 资源聚合概念 | E4 | 与既有 fish/game 资源池的对应属 E4 短文档范畴（池为过渡机制，ADR 010 §2.3） |
| interactions（30） | 跨域关系，无第三所有者 | E5 | 食物网链接表；C/D 级强度仅供结构，数值化待 E5 |
| initial_states（53） | 各域初始状态**结构** | E3/E4/E5 | L1/L2/L3 视图 + quantity_type/unit；**数值全 NULL，Viae 不得编造**（NoData 不当零的同族铁律：unknown 不当 0） |

## 4. 与既有机制的衔接边界

- **LOD**：L1/L2/L3 是**统计视图**（初始状态三级，禁止相加/互校/平摊，契约 §4.7），与 Simulation LOD（fine/normal/coarse，E2 规范 §10）**不对应**；两套词不得混用。
- **资源池（E1 过渡）**：full/base_town/viz profile 的 wildlife 池（鸟兽混合、物种类与包内 5 鸟不重合）**不动**；ecology 数据消费另立口径，物种类合并/并存留 E4 短文档裁决。
- **首发范围**：本档只冻结数据契约与校验（EX-0），不改运行时；「Seed 输入 → Environment/Wildlife 拥有的初始状态」转换口径按 ADR 011 §4 约束（不反向改契约、验证器裁决生态口径等）留 E3/E4 各自短文档。

## 5. 冻结与校验方案（EX-0，复用 P0 模式）

- **配置**：`world.yaml` 第二个可选节 `ecology_seed`（schema 新文件，同 `environment_seed` 模式）：seed_id/version（1.0.0）、manifest 定位、**manifest.json 自身 sha256**（我方实测冻结，规避 Xigu 侧文档误标）、必需文件清单（SQLite + 7 CSV，逐文件 size/sha256/rows/table）、行数契约（14/1254/5/14/30/24/53）、source（repo `Xigu-Ecology-Data` @ `0343844`、release `ecology-seed-v1.0`、许可：GBIF/eBird CC BY 4.0 + GloBI/文献按各自条款 + 本地推导组无外部许可）、升级策略同款（版本显式切换，学名变更换线）。
- **校验**：扩展 `src/vale/world/seed_contract.py`（同一可复用模块、同一数据集成边界）：manifest 结构/版本/行数、逐文件哈希复算（SQLite 含逐表行数与 CSV 对照——契约 §9–11 的 Viae 侧执行）、失败关闭；清单外表（registry 类）显式报告不作通过条件。CLI 复用 `scripts/check_seed.py` 入口（增加生态包分支）。
- **缓存定位**：与 environment_seed **共用**缓存根（`VALE_SEED_CACHE` / 缺省 `data/seed-cache`），包目录 `ecology_seed_v1`——与 P0 待裁决项①一并裁决。
- **边界申明**：校验通过 ≠ 运行时接入；E3/E4/E5 消费各自经短文档裁决（ADR 011「P3–P4 不因 Seed 发布而自动启动」）。

**落地注记（2026-11-26 · EX-0 已实现）**：按本节方案落地，与裁决对齐的偏差如下。

- **配置**：`world.yaml` `ecology_seed` 可选节（schema 新文件 `src/vale/config/schema/ecology_seed.py`，`WorldConfig` 挂载）；冻结值为 manifest 的 `version="1.0"`（Xigu 契约文档口语中的「1.0.0」指同一发布）、manifest.json 自身 sha256 我方实测（`27d30b76…f5b44`）、8 文件逐条 `bytes/sha256/rows/table`（SQLite 载体 `table='*'`、rows 置空，行数按表冻结于 `table_rows`）、source 含全哈希 revision `0343844…c7bfa` 与 release `ecology-seed-v1.0`。
- **校验**：`src/vale/world/seed_contract.py` 扩展 `validate_ecology_seed_package`（同一可复用模块、同一数据集成边界、失败关闭）。SQLite↔CSV 按裁决升级为**全表逻辑等价**（否决本档原建议的抽样口径）：逐表按单列主键匹配（7 表均为单列 PK）、全字段逻辑等价（NULL↔空串、数值按值、文本精确）、行数三方一致（manifest rows/counts、SQLite、CSV）；两载体行序实测不同，比对按主键而非行位置。清单外表（8 张 registry/过程表）显式报告，不作通过条件。
- **CLI**：`scripts/check_seed.py` 增 `--seed {environment|ecology|all}`，缺省 `environment` 保持 P0 行为兼容；两线共用缓存根（`--seed all` 一次校验）。
- **测试**：`tests/test_ecology_seed_contract.py` 33 项（合法包、各项拒绝、逻辑等价全分支、口径单测、确定性、坏配置、在库契约、CLI）。
- **真实包验收**：`python scripts/check_seed.py --world brookvale-town-001 --seed all --cache-root F:\viae_sim\Xigu-Ecology-Data\processed` 两线通过；生态包 8 文件哈希复算、7 表 **1394 行**全表逻辑等价比对全部命中。

## 6. 分阶段切分（建议）

| 阶段 | 内容 | 前置 |
|---|---|---|
| **EX-0** | 数据契约冻结 + 校验扩展 + fixture 专项测试（零运行时改动，类比 P0） | 已裁决通过并实现（2026-11-26，见 §5 落地注记） |
| **EX-1**（随 E3） | 植物物种/生长型/生境关联进 Environment 初始状态候选 | E3 短文档（含「既有配置 vs Seed 数据」裁决） |
| **EX-2**（随 E4） | 鸟物种目录、食性、食物链接进 Wildlife；初始数值 = D 级假设参数清单（老板逐项拍板） | E4 短文档 |
| **EX-3**（随 E5） | 分解链功能组进 Environment 循环（P4） | E5 短文档 |
| 落格消费 | occurrences 空间落位 | P1 GridSpace；生境栅格消费需 P2 Loader |

## 7. 待裁决项

**裁决（2026-11-26，有条件批准 EX-0）**——原 1–4 项全部有结论：

1. **EX-0 开工**：**批准**（契约冻结、静态校验、完整性验证；已实现，见 §5 落地注记）。
2. **初始数值口径**：结构先行、数值留空——**否决**用推测值填充 `initial_state`（包内 `quantity_value` 全 NULL 是被冻结的事实）；证据等级铁律：B 级记录不解释为精确空间分布、C 级关系不转化为相互作用强度、D 级假设保留假设身份、不混入实测数据；D 级假设参数清单随 E4 逐项拍板。
3. **SQLite↔CSV 校验深度**：**全表逻辑等价**——否决抽样（不足以保证两种载体一致）。
4. **缓存根共用**：**共用现有 seed 缓存根 + 隔离版本目录**（`environment_seed_v2` / `ecology_seed_v1` 同根不同目录；已落地）。

范围裁定：**批准** = EX-0 契约冻结、静态校验、完整性验证；**暂缓** = E3/E4/E5 运行时消费；**否决** = 用推测值填充初始状态、将关系线索数值化、改造现有 Wildlife 池。核心判断：先建立可信的数据接入边界，不急于参与模拟。台账见 `.ai/DECISIONS.md` 2026-11-26。

尚未裁决：

5. **物种类并存**（包内 5 鸟 vs full profile 鸟兽池）与 FG→资源池映射：**留 E4 短文档**，本文仅登记不裁决。
