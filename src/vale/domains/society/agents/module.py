"""人物子系统协调器：保留日结算调度顺序，具体业务由各 mixin 子系统实现。"""

from __future__ import annotations

import random
import traceback
from typing import Optional

from vale.config.schema.agents import AgentTuning
from vale.core.household import home_node_of
from vale.core.state import AgentState
from vale.domains.society import social
from vale.domains.society.agents.actions import ActionMixin
from vale.domains.society.agents.debt import DebtMixin
from vale.domains.society.agents.decision import DecisionMixin
from vale.domains.society.agents.demographics import living_agents
from vale.domains.society.agents.household import HouseholdMixin
from vale.domains.society.agents.labor import LaborMixin
from vale.domains.society.agents.lifecycle import LifecycleMixin
from vale.domains.society.agents.market import MarketMixin
from vale.domains.society.agents.marriage import MarriageMixin
from vale.domains.society.agents.mortality import MortalityMixin
from vale.domains.society.agents.reproduction import ReproductionMixin
from vale.domains.society.agents.spatial import SpatialIndex
from vale.domains.society.community import settle_building_maintenance, update_building_needs


class AgentModule(
    LifecycleMixin,
    LaborMixin,
    DecisionMixin,
    ActionMixin,
    HouseholdMixin,
    MarketMixin,
    MortalityMixin,
    MarriageMixin,
    ReproductionMixin,
    DebtMixin,
):
    name = "agents"
    depends_on = ["climate", "ecology"]

    def __init__(self, rng=None) -> None:
        self._spatial: Optional[SpatialIndex] = None
        # 打猎成功率/受伤的随机源：默认独立 Random（故事流非确定），测试传 seeded 实例保证可复现
        self.rng = rng if rng is not None else random.Random()
        self._daily_task_assignments: dict[str, str] = {}
        # 当日结亲意向：agent_id -> target_id。日内由 court 动作写入，
        # 日末 _settle_courtship 结算互为目标的配对后清空。
        self._courtship_offers: dict[str, str] = {}

    def step(self, world) -> None:
        cfg = world.config.agents
        if self._spatial is None:
            self._spatial = SpatialIndex(world.config.spatial)
        self._ensure_agents(world, cfg)
        tuning = cfg.tuning
        # 任务16 阶段二：同户/亲缘默认 known（纯函数，运行时每 tick 与 replay 末尾共用，
        # 裁决 §3.1；不写事件避免开局刷屏）
        social.apply_kin_defaults(world.state, world.current_tick)
        # 阶段二 C：劳作点对账（家庭可分配田块 + 个人偏好失效回收），先于当日决策
        self._reconcile_work_nodes(world, tuning)
        # 家庭先协商当日分工，再由成员分别执行；生存动作仍可覆盖分工。
        self._daily_task_assignments = self._plan_household_work(world, tuning)
        # A1：主循环以 WorldState.agents 为唯一真相源；cfg.agents 只用于开局播种，
        # 运行时新增的新生儿下一 tick 即参与决策/结算/查询。
        for agent_id in list(world.state.human.agents.keys()):
            agent = world.state.human.agents[agent_id]
            try:
                self._process_one(world, agent, tuning)
            except Exception as exc:  # noqa: BLE001 — 模块隔离：单个人物失败不拖垮世界
                self._log_agent_error(world, agent, "daily_action", exc)
        # 共同居住/工作地点形成日常接触；双方各自记录认知，不写入短期互动记忆。
        self._record_shared_location_interactions(world, tuning)
        # 每日结算（任务 08/12）：死亡+继承 → 催收 → 集市 → 婚配 → 生育 → 回血
        self._settle(world, tuning)
        # 004 C1：日末回家——日内 location 已真实化（停在最后动作目标），结算后统一归位，
        # 使次日从家出发。集市结算先于归位，故仍能识别「当日是否在场 market」。
        for agent in living_agents(world.state.human.agents):
            agent.location = home_node_of(world, agent)
        self._settle_fatigue(world, tuning)
        settle_building_maintenance(world, tuning.environment)
        update_building_needs(world, tuning.environment)
        # 任务16 阶段二：低频遗忘清理（裁决 §3.5——批量删过期条目并写 forgot 事件；
        # 决策读取只过滤不写，保持诉求计算只读语义）
        soc = tuning.social
        if world.current_tick > 0 and world.current_tick % soc.cleanup_interval == 0:
            social.cleanup_forgotten(world, world.current_tick, soc.acquaintance_ttl)

    def _settle(self, world, tuning: AgentTuning) -> None:
        """tick 末尾统一结算。逐人错误隔离：单人结算失败写 agent_error，不拖垮世界。

        顺序（任务12 A3 固定）：死亡判定 → 继承（资产转移+债务继承/核销）→ 催收会话
        → 强制催收 → 集市 → 婚配 → 生育 → 健康回血。继承必须先于债务处理，否则债务无处继承。
        催收会话先于强制扣粮（任务15 阶段三修正）：让「有粮赖账」窗口先被会话看到，
        否则库存会被 _collect_debts 先扣走。死者/失能者不参与催收、集市、婚配、生育与回血。
        """
        dead_now: list[AgentState] = []
        for agent in list(world.state.human.agents.values()):
            try:
                was_alive = agent.alive
                self._process_death(world, agent, tuning)
                if was_alive and not agent.alive:
                    dead_now.append(agent)
            except Exception as exc:  # noqa: BLE001 — 单人结算失败不拖垮世界
                self._log_agent_error(world, agent, "death_settlement", exc)

        # A3/P0：死亡后先处理家庭生命周期（接任/最后成员继承），再催收与债务核销
        for agent in dead_now:
            try:
                self._handle_death(world, agent, tuning)
            except Exception as exc:  # noqa: BLE001
                self._log_agent_error(world, agent, "inheritance", exc)

        # 任务15 阶段三：催收会话先于强制扣粮，看到「有粮赖账」窗口（只有 market_credit 债务参与）
        try:
            self._settle_debt_disputes(world, tuning)
        except Exception as exc:  # noqa: BLE001 — 冲突结算失败不拖垮集市/婚配/回血
            world.event_log.append(
                world.current_tick,
                "agent_error",
                {
                    "agent_id": "_conflict",
                    "agent_name": "债务催收",
                    "phase": "debt_dispute",
                    "error": repr(exc),
                    "traceback": traceback.format_exc(limit=2),
                },
            )

        for agent in list(world.state.human.agents.values()):
            try:
                if not agent.alive:
                    continue
                # 失能者无收入、无法进食：不催收（避免对垂死之人重复刷违约），也不回血
                if agent.incapacitated:
                    continue
                self._collect_debts(world, agent, tuning)
            except Exception as exc:  # noqa: BLE001 — 单人结算失败不拖垮世界
                self._log_agent_error(world, agent, "debt_collection", exc)

        if self._is_market_day(world.current_tick, tuning):
            try:
                self._settle_market(world, tuning)
            except Exception as exc:  # noqa: BLE001 — 集市结算失败不拖垮回血与后续 tick
                world.event_log.append(
                    world.current_tick,
                    "agent_error",
                    {
                        "agent_id": "_market",
                        "agent_name": "集市",
                        "phase": "market_settlement",
                        "error": repr(exc),
                        "traceback": traceback.format_exc(limit=2),
                    },
                )

        try:
            self._settle_water(world, tuning)
        except Exception as exc:  # noqa: BLE001 — 用水结算失败不拖垮婚配/生育/回血
            world.event_log.append(
                world.current_tick,
                "agent_error",
                {
                    "agent_id": "_water",
                    "agent_name": "生活用水",
                    "phase": "water_settlement",
                    "error": repr(exc),
                    "traceback": traceback.format_exc(limit=2),
                },
            )

        try:
            # 婚配与生育已下沉为 court / try_for_child 动作；日末只结算"双向互选"的结亲意向，
            # 不再做系统贪心配对或概率抽签。
            self._settle_courtship(world, tuning)
        except Exception as exc:  # noqa: BLE001
            world.event_log.append(
                world.current_tick,
                "agent_error",
                {
                    "agent_id": "_marriage",
                    "agent_name": "婚配",
                    "phase": "courtship_settlement",
                    "error": repr(exc),
                    "traceback": traceback.format_exc(limit=2),
                },
            )

        try:
            self._settle_split(world, tuning)
        except Exception as exc:  # noqa: BLE001
            world.event_log.append(
                world.current_tick,
                "agent_error",
                {
                    "agent_id": "_split",
                    "agent_name": "分家",
                    "phase": "split_settlement",
                    "error": repr(exc),
                    "traceback": traceback.format_exc(limit=2),
                },
            )

        for agent in list(world.state.human.agents.values()):
            try:
                if not agent.alive or agent.incapacitated:
                    continue
                self._recover_health(world, agent, tuning)
            except Exception as exc:  # noqa: BLE001
                self._log_agent_error(world, agent, "health_recovery", exc)

    def _log_agent_error(self, world, agent: AgentState, phase: str, exc: Exception) -> None:
        world.event_log.append(
            world.current_tick,
            "agent_error",
            {
                "agent_id": agent.agent_id,
                "agent_name": agent.name,
                "phase": phase,
                "error": repr(exc),
                "traceback": traceback.format_exc(limit=2),
            },
        )
