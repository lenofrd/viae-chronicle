"""人文社会域（ADR 009 §2.3）：人口、家庭、土地、经济与治理。

P5-c（2026-11-21）：`land`、`community`、`social`、`governance`、`construction`、
`economy`（原 `tenancy_economy`）已迁入本包。
P5-d（2026-11-21）：`agents` 按职责拆入 `agents/` 子包——协调器保留日结算顺序，
人口生命周期、劳动、决策、动作、集市、死亡继承、婚配、分家生育、债务各自成模块。
状态所有者以 ``tests/test_architecture_boundaries.py`` 的登记为准。
"""
