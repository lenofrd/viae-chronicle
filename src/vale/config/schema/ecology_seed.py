"""Ecology Seed 契约的 Pydantic Schema（EX-0，老板 2026-11-26 裁决有条件批准）。

本文件只承载**冻结的内容**：`config/worlds/<world>/world.yaml` 的
`ecology_seed` 节，声明 Viae 侧认可的 Xigu Ecology Seed v1（生态/群落数据线）
契约——包身份、manifest.json 自身哈希（我方实测冻结，规避 Xigu 侧文档
误标）、8 个文件（7 CSV + 1 SQLite）的 size/sha256/rows/table、7 表行数
契约、来源与升级策略。机制（静态契约校验，含 SQLite↔CSV **全表逻辑
等价**）在 `src/vale/world/seed_contract.py`，二者分离。

范围边界（裁决 2026-11-26）：EX-0 只做契约冻结、静态校验与完整性验证；
E3/E4/E5 运行时消费暂缓。否决项为硬约束：不得用推测值填充初始状态
（包内 `initial_state.quantity_value` 全部 NULL 是被冻结的事实）、不得将
C 级关系线索数值化、不得改造既有 Wildlife 池；B 级记录不得解释为精确
空间分布、D 级假设保留假设身份不混入实测（证据等级口径见短文档 §2）。

结构约束（缺键、错型、格式非法）在配置加载时即抛 ValidationError
（坏配置启动即报错）；与 manifest 实物的比对在数据集成边界校验。
"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class EcologySeedSource(BaseModel):
    """数据包来源与升级策略（B 机制：Xigu 发布版本化数据包；Viae 零网络逻辑）。"""

    repository: str = Field(min_length=1)
    revision: str = Field(min_length=1, description="溯源基准提交（数据包对应的 Xigu 仓库提交，全哈希）")
    channel: str = Field(min_length=1, description="正式分发渠道")
    release: str | None = Field(default=None, description="Release 标签")
    license: str = Field(min_length=1, description="许可与来源说明（指向上游数据方条款，逐条见 manifest sources）")
    upgrade_policy: str = Field(default="版本显式切换，旧版本可追溯，不原地覆盖；学名/分类变更换新版本线")


class EcologySeedLocation(BaseModel):
    """本地缓存定位（C 机制）：与 environment_seed 共用缓存根，包目录隔离。"""

    package_dir: str = Field(min_length=1, description="数据包目录，相对缓存根（缓存根解析见 seed_contract.resolve_cache_root）")


class EcologySeedFile(BaseModel):
    """单个包文件的身份与完整性契约（冻结自 manifest files 条目，键 file/table/rows/sha256/bytes）。

    ``table`` 为该 CSV 导出的 SQLite 表名；SQLite 载体条目固定 ``table="*"``、
    ``rows`` 为空（其内容与 CSV 的一致性由全表逻辑等价校验保证，不再单独
    冻结行数）。
    """

    file: str = Field(min_length=1, description="包目录内文件名（manifest file 键为裸文件名，不带目录前缀）")
    table: str = Field(min_length=1, description="对应 SQLite 表名；SQLite 载体为 '*'")
    rows: int | None = Field(default=None, ge=0, description="CSV 数据行数（不含表头）；SQLite 载体为 None")
    bytes: int = Field(gt=0, description="文件字节数")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="冻结的 SHA-256（与 manifest 及实际文件三方一致）")


class EcologySeedManifestRef(BaseModel):
    """manifest.json 自身的完整性契约（我方实测冻结：Xigu 侧变更日志曾误标其哈希）。"""

    file: str = Field(min_length=1, description="manifest 文件名（包目录内）")
    bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="我方实测冻结的 manifest 自身 SHA-256")


class EcologySeedConfig(BaseModel):
    """世界可选的 Ecology Seed 冻结契约（world.yaml `ecology_seed` 节）。"""

    seed_id: str = Field(min_length=1, description="期望的 manifest package 身份（ecology_seed_v1；版本钉死，升级即显式换值）")
    version: str = Field(min_length=1, description="期望的 manifest version（\"1.0\"）")
    contract: str = Field(min_length=1, description="期望的 Xigu 数据契约名（含版本号）")
    schema_version: str = Field(min_length=1, description="期望的 manifest schema_version（包身份的组成部分）")
    world_ref: str = Field(min_length=1, description="绑定的 Viae world_id；须与 world_id 一致（校验器核对）")
    manifest: EcologySeedManifestRef
    files: list[EcologySeedFile] = Field(min_length=1, description="包文件清单（7 CSV + 1 SQLite）；缺失任一即拒绝")
    table_rows: dict[str, int] = Field(min_length=1, description="7 表行数契约（manifest counts、SQLite 行数、CSV 数据行数三方一致）")
    source: EcologySeedSource
    location: EcologySeedLocation

    @model_validator(mode="after")
    def _files_consistent(self) -> "EcologySeedConfig":
        names = [entry.file for entry in self.files]
        if len(names) != len(set(names)):
            duplicates = sorted({name for name in names if names.count(name) > 1})
            raise ValueError(f"files 存在重复 file：{duplicates}")

        carriers = [entry for entry in self.files if entry.table == "*"]
        if len(carriers) != 1:
            raise ValueError(f"files 必须恰好包含 1 个 SQLite 载体条目（table='*'），实际 {len(carriers)} 个")
        if carriers[0].rows is not None:
            raise ValueError("SQLite 载体条目（table='*'）的 rows 必须为空（行数按表冻结在 table_rows）")

        csv_tables = {entry.table for entry in self.files if entry.table != "*"}
        if csv_tables != set(self.table_rows):
            only_files = sorted(csv_tables - set(self.table_rows))
            only_rows = sorted(set(self.table_rows) - csv_tables)
            raise ValueError(
                f"CSV 文件表集与 table_rows 不一致：仅文件清单有 {only_files}，仅行数契约有 {only_rows}"
            )
        for entry in self.files:
            if entry.table != "*" and entry.rows != self.table_rows[entry.table]:
                raise ValueError(
                    f"files[{entry.file}].rows={entry.rows} 与 table_rows[{entry.table}]"
                    f"={self.table_rows[entry.table]} 不一致"
                )
        return self
