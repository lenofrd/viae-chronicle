"""中文渲染纯函数（任务 07）。

单条事件 → 一行可读摘要。任何异常 / 未知类型 / 缺字段都降级为可读占位，绝不抛出。
返回 RenderResult，带 degraded 标记，供统计「不静默失败」。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

WEATHER_DESC = {
    "sunny": "晴",
    "cloudy": "多云",
    "light_rain": "小雨",
    "moderate_rain": "下雨",
    "heavy_rain": "大雨",
    "other": "天气变幻",
}

# 动作 → 中文动词（覆盖要求的 6 种；未知走兜底）
ACTION_VERB = {
    "eat": "进食",
    "rest": "歇息",
    "farm": "劳作",
    "collect_water": "打水",
    "harvest": "秋收",
    "borrow_grain": "借粮",
    "hunt": "打猎",
    "fish": "捕鱼",
    "weave": "织布",
}

# 作物/交易物品 → (量词, 存栏描述)。任务11：grain/vegetable 由田块 crop_type 决定。
ITEM_DESC = {
    "grain": ("石", "存粮"),
    "vegetable": ("担", "存菜"),
    "meat": ("斤", "肉存"),
    "fish": ("尾", "鱼存"),
    "cloth": ("匹", "布存"),
}


def _item_name(item: Optional[str]) -> str:
    return {"grain": "粮", "vegetable": "菜", "meat": "肉", "fish": "鱼", "cloth": "布"}.get(
        item or "", item or "?"
    )

# 采集类动作 → (动词, 产物名)。任务09：hunt 打猎产肉；任务10：fish 捕鱼产鱼。
# 新增采集生计只需在此加一行，gather_success/fail/injury 渲染自动复用，无需新增渲染函数。
GATHER_DESC = {
    "hunt": ("打猎", "肉"),
    "fish": ("捕鱼", "鱼"),
}


@dataclass
class RenderResult:
    text: str
    degraded: bool = False
    reason: Optional[str] = None  # 降级原因，便于 --debug / 摘要


def _num(v: Any, default: str = "?") -> str:
    if v is None:
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{f:.0f}" if f.is_integer() else f"{f:.2f}"


def _render_weather(payload: dict) -> tuple[str, bool]:
    w = payload.get("weather")
    temp = payload.get("temperature_c")
    precip = payload.get("precipitation_mm")
    drought = payload.get("drought_state")
    parts = [f"天气{WEATHER_DESC.get(w, w or '未知')}"]
    if temp is not None:
        parts.append(f"气温{_num(temp)}度")
    if precip is not None and float(precip or 0) > 0:
        parts.append(f"降水{_num(precip)}mm")
    if drought not in (None, "none", "NONE"):
        parts.append(f"旱情{drought}")
    text = "，".join(parts)
    degraded = "weather" not in payload
    return text, degraded


def _render_season(payload: dict) -> tuple[str, bool]:
    frm = payload.get("from", "?")
    to = payload.get("to", "?")
    text = f"季节由 {frm} 入 {to}"
    degraded = "from" not in payload or "to" not in payload
    return text, degraded


def _render_action(payload: dict, names: Optional[dict[str, str]]) -> tuple[str, bool]:
    name = payload.get("agent_name", "?")
    action = payload.get("action")
    target = payload.get("target_node")
    tname = (names or {}).get(target, target) if target else None
    degraded = False

    verb = ACTION_VERB.get(action)
    if verb is None:
        # 未知 action 兜底
        return f"[{name}] 执行了未知动作「{action or '?'}」", True

    if action == "eat":
        body = f"吃了些存粮（存粮剩 {_num(payload.get('grain_after'))} 石）"
    elif action == "rest":
        body = f"在家歇息（体力 {_num(payload.get('stamina_after'))}）"
    elif action == "farm":
        growth = payload.get("field_growth_after")
        body = f"在{tname or '?'}劳作（长势 {_num(growth)}）"
    elif action == "collect_water":
        body = f"去{tname or '?'}打了水"
    elif action == "harvest":
        crop = payload.get("crop") or "grain"
        unit, label = ITEM_DESC.get(crop, ("石", f"{crop}存"))
        gain = _safe_diff(payload.get(f"{crop}_after"), payload.get(f"{crop}_before"))
        after = payload.get(f"{crop}_after")
        repaid = _safe_diff(payload.get("debt_before"), payload.get("debt_after"))
        body = f"在{tname or '?'}秋收，打下 {gain} {unit}（{label}剩 {_num(after)}）"
        if repaid and repaid != "0":
            body += f"，还债 {repaid} 石"
    elif action == "borrow_grain":
        amount = _safe_diff(payload.get("grain_after"), payload.get("grain_before"))
        body = (f"去{tname or '?'}借了 {amount} 石粮"
                f"（存粮剩 {_num(payload.get('grain_after'))}，欠债 {_num(payload.get('debt_after'))}）")
    elif action == "hunt":
        body = f"去{tname or '?'}打猎（肉存 {_num(payload.get('meat_after'))}）"
    elif action == "fish":
        body = f"去{tname or '?'}捕鱼（鱼存 {_num(payload.get('fish_after'))}）"
    elif action == "weave":
        body = f"在{tname or '?'}织布（布存 {_num(payload.get('cloth_after'))} 匹）"
    else:  # 理论上不会到，兜底
        body = f"执行了 {action}"
        degraded = True

    if "agent_name" not in payload:
        degraded = True
    return f"[{name}] {body}", degraded


def _render_agent_error(payload: dict) -> tuple[str, bool]:
    name = payload.get("agent_name", payload.get("agent_id", "?"))
    err = payload.get("error", "?")
    return f"[{name}] 处理出错：{err}", "error" not in payload


def _safe_diff(after: Any, before: Any) -> str:
    try:
        return _num(float(after) - float(before))
    except (TypeError, ValueError):
        return "?"


def _render_debt_formed(payload: dict) -> tuple[str, bool]:
    debtor = payload.get("debtor_name") or payload.get("debtor_id") or "?"
    creditor = payload.get("creditor_name") or payload.get("creditor_id") or "?"
    amount = _num(payload.get("amount"))
    due = payload.get("due_tick")
    text = f"[{debtor}] 向 [{creditor}] 借粮 {amount} 石（到期 tick {due}）"
    degraded = not all(k in payload for k in ("creditor_id", "debtor_id", "amount", "due_tick"))
    return text, degraded


def _render_debt_collected(payload: dict) -> tuple[str, bool]:
    debtor = payload.get("debtor_name") or payload.get("debtor_id") or "?"
    creditor = payload.get("creditor_name") or payload.get("creditor_id") or "?"
    paid = _num(payload.get("amount_paid"))
    remaining = _num(payload.get("remaining"))
    if payload.get("overdue"):
        suffix = "（仍逾期）"
    else:
        try:
            suffix = "（已结清）" if float(payload.get("remaining", 0)) == 0 else ""
        except (TypeError, ValueError):
            suffix = ""
    text = f"[{creditor}] 向 [{debtor}] 催收，收回 {paid} 石（剩余 {remaining}）{suffix}"
    degraded = not all(k in payload for k in ("creditor_id", "debtor_id", "amount_paid"))
    return text, degraded


def _render_debt_defaulted(payload: dict) -> tuple[str, bool]:
    debtor = payload.get("debtor_name") or payload.get("debtor_id") or "?"
    creditor = payload.get("creditor_name") or payload.get("creditor_id") or "?"
    amount = _num(payload.get("amount"))
    overdue = payload.get("overdue_ticks")
    text = f"[{debtor}] 欠 [{creditor}] {amount} 石无力偿还，违约（逾期 {overdue} 天）"
    degraded = not all(k in payload for k in ("creditor_id", "debtor_id", "amount"))
    return text, degraded


def _render_debt_repaid(payload: dict) -> tuple[str, bool]:
    debtor = payload.get("debtor_name") or payload.get("debtor_id") or "?"
    creditor = payload.get("creditor_name") or payload.get("creditor_id") or "?"
    amount = _num(payload.get("amount"))
    remaining = _num(payload.get("remaining"))
    src = "（秋收）" if payload.get("source") == "harvest" else ""
    text = f"[{debtor}] 还 [{creditor}] {amount} 石{src}（剩余 {remaining}）"
    degraded = not all(k in payload for k in ("creditor_id", "debtor_id", "amount"))
    return text, degraded


def _render_health_recovered(payload: dict) -> tuple[str, bool]:
    name = payload.get("agent_name") or payload.get("agent_id") or "?"
    before = _num(payload.get("before"))
    after = _num(payload.get("after"))
    text = f"[{name}] 健康回升 {before} → {after}"
    degraded = not all(k in payload for k in ("agent_id", "before", "after"))
    return text, degraded


def _gather_verb_product(action: str) -> tuple[str, str]:
    return GATHER_DESC.get(action, (action or "采集", "产物"))


def _render_gather_success(payload: dict) -> tuple[str, bool]:
    name = payload.get("agent_name") or payload.get("agent_id") or "?"
    action = payload.get("action", "?")
    verb, product = _gather_verb_product(action)
    node = payload.get("resource_node", "?")
    amount = _num(payload.get("amount"))
    after = _num(payload.get("output_after"))
    text = f"[{name}] 去{node}{verb}，获得 {amount} {product}（{product}存 {after}）"
    degraded = not all(k in payload for k in ("agent_id", "action", "amount"))
    return text, degraded


def _render_gather_fail(payload: dict) -> tuple[str, bool]:
    name = payload.get("agent_name") or payload.get("agent_id") or "?"
    action = payload.get("action", "?")
    verb, _ = _gather_verb_product(action)
    node = payload.get("resource_node", "?")
    reason = payload.get("reason", "未果")
    text = f"[{name}] 去{node}{verb}，{reason}"
    degraded = not all(k in payload for k in ("agent_id", "action"))
    return text, degraded


def _render_gather_injury(payload: dict) -> tuple[str, bool]:
    name = payload.get("agent_name") or payload.get("agent_id") or "?"
    action = payload.get("action", "?")
    verb, _ = _gather_verb_product(action)
    loss = _num(payload.get("loss"))
    before = _num(payload.get("health_before"))
    after = _num(payload.get("health_after"))
    text = f"[{name}] {verb}时受伤，健康 {before} → {after}（损失 {loss}）"
    degraded = not all(k in payload for k in ("agent_id", "action", "loss"))
    return text, degraded


def _render_agent_incapacitated(payload: dict) -> tuple[str, bool]:
    name = payload.get("agent_name") or payload.get("agent_id") or "?"
    health = _num(payload.get("health"))
    grace = payload.get("death_grace_ticks")
    suffix = f"（{grace} 天后若未恢复将死亡）" if grace is not None else ""
    text = f"[{name}] 健康触底（{health}），失能卧床，不再行动{suffix}"
    degraded = not all(k in payload for k in ("agent_id", "health"))
    return text, degraded


# 死因中文映射（任务12）；未知值原样展示且不降级（兼容旧事件 health_bottomed）
CAUSE_DESC = {
    "starvation": "饿死",
    "aging": "衰老",
    "injury": "伤重",
    "illness": "病故",
    "health_bottomed": "健康耗尽",
}


def _render_agent_died(payload: dict) -> tuple[str, bool]:
    name = payload.get("agent_name") or payload.get("agent_id") or "?"
    cause = payload.get("cause", "?")
    debt = _num(payload.get("outstanding_debt"))
    text = f"[{name}] 死亡（{CAUSE_DESC.get(cause, cause)}），遗留债务 {debt} 石"
    degraded = not all(k in payload for k in ("agent_id", "died_tick"))
    return text, degraded


def _render_agent_aged(payload: dict) -> tuple[str, bool]:
    name = payload.get("agent_name") or payload.get("agent_id") or "?"
    age = _num(payload.get("age"))
    old_stage = payload.get("old_stage", "?")
    new_stage = payload.get("new_stage", "?")
    before = _num(payload.get("health_cap_before"))
    after = _num(payload.get("health_cap_after"))
    if payload.get("stage_changed"):
        text = f"[{name}] 年满 {age} 岁，入{new_stage}（健康上限 {before} → {after}）"
    else:
        text = f"[{name}] 年满 {age} 岁，仍在{new_stage}（健康上限 {before} → {after}）"
    if old_stage == "?":
        text = f"[{name}] 年满 {age} 岁（健康上限 {before} → {after}）"
    degraded = not all(k in payload for k in ("agent_id", "age", "health_cap_after"))
    return text, degraded


def _render_agent_married(payload: dict) -> tuple[str, bool]:
    name = payload.get("agent_name") or payload.get("agent_id") or "?"
    spouse = payload.get("spouse_name") or payload.get("spouse_id") or "?"
    dist = _num(payload.get("distance_tu"))
    text = f"[{name}] 与 [{spouse}] 结为夫妻（相距 {dist} TU）"
    degraded = not all(k in payload for k in ("agent_id", "spouse_id"))
    return text, degraded


def _render_agent_born(payload: dict) -> tuple[str, bool]:
    child = payload.get("child_name") or payload.get("agent_name") or payload.get("child_id") or "?"
    mother = payload.get("mother_name") or payload.get("mother_id") or "?"
    father = payload.get("father_name") or payload.get("father_id") or "?"
    pop = payload.get("population_after")
    suffix = f"，人口 {_num(pop)}" if pop is not None else ""
    text = f"[{child}] 出生（母 {mother}，父 {father}{suffix}）"
    degraded = not all(k in payload for k in ("child_id", "mother_id", "father_id"))
    return text, degraded


def _render_birth_asset_transfer(payload: dict) -> tuple[str, bool]:
    parent = payload.get("parent_name") or payload.get("parent_id") or "?"
    child = payload.get("child_name") or payload.get("child_id") or "?"
    items = payload.get("items") or {}
    parts = []
    if isinstance(items, dict):
        for item, qty in items.items():
            unit = ITEM_DESC.get(item, ("", ""))[0]
            parts.append(f"{_item_name(item)} {_num(qty)} {unit}".strip())
    text = f"[{parent}] 分给新生儿 [{child}] " + ("、".join(parts) if parts else "若干食物")
    degraded = not all(k in payload for k in ("parent_id", "child_id", "items"))
    return text, degraded


def _render_inheritance_executed(payload: dict) -> tuple[str, bool]:
    heir = payload.get("heir_name") or payload.get("heir_id") or "?"
    deceased = payload.get("deceased_name") or payload.get("deceased_id") or "?"
    item = payload.get("item")
    amount = _num(payload.get("amount"))
    unit = ITEM_DESC.get(item, ("", ""))[0]
    after = _num(payload.get("heir_after"))
    text = f"[{heir}] 继承 [{deceased}] 的{_item_name(item)} {amount} {unit}（继承后 {after}）".replace("  ", " ")
    degraded = not all(k in payload for k in ("heir_id", "deceased_id", "item", "amount"))
    return text, degraded


def _render_inheritance_escheated(payload: dict) -> tuple[str, bool]:
    deceased = payload.get("deceased_name") or payload.get("deceased_id") or "?"
    item = payload.get("item")
    amount = _num(payload.get("amount"))
    unit = ITEM_DESC.get(item, ("", ""))[0]
    text = f"[{deceased}] 的{_item_name(item)} {amount} {unit}无人继承，归公".replace("  ", " ")
    degraded = not all(k in payload for k in ("deceased_id", "item", "amount"))
    return text, degraded


def _render_debt_transferred(payload: dict) -> tuple[str, bool]:
    heir = payload.get("to_name") or payload.get("to_id") or "?"
    deceased = payload.get("from_name") or payload.get("from_id") or "?"
    creditor = payload.get("creditor_name") or payload.get("creditor_id") or "?"
    amount = _num(payload.get("amount"))
    text = f"[{heir}] 承继 [{deceased}] 欠 [{creditor}] 的债务 {amount} 石"
    degraded = not all(k in payload for k in ("from_id", "to_id", "creditor_id", "amount"))
    return text, degraded


def _render_household_merged(payload: dict) -> tuple[str, bool]:
    target = payload.get("target_household_id") or "?"
    source = payload.get("source_household_id") or "?"
    after_map = payload.get("target_assets_after") or {}
    after = after_map.get("grain") if isinstance(after_map, dict) else None
    members = len(payload.get("members_after") or [])
    text = f"家庭 {source} 并入 {target}（现有 {members} 人，存粮 {_num(after)} 石）"
    degraded = not all(k in payload for k in ("target_household_id", "source_household_id"))
    return text, degraded


def _render_household_split(payload: dict) -> tuple[str, bool]:
    source = payload.get("source_household_id") or "?"
    new_id = payload.get("new_household_id") or "?"
    head = payload.get("head_name") or payload.get("head_id") or "?"
    members = len(payload.get("members") or [])
    home = payload.get("home_node") or "?"
    text = f"家庭 {source} 分家：{head} 另立 {new_id}（{members} 人，住所 {home}）"
    degraded = not all(k in payload for k in ("source_household_id", "new_household_id"))
    return text, degraded


def _render_household_head_changed(payload: dict) -> tuple[str, bool]:
    household = payload.get("household_id") or "?"
    old_head = payload.get("old_head_name") or payload.get("old_head_id") or "?"
    new_head = payload.get("new_head_name") or payload.get("new_head_id") or "?"
    suffix = "（未成年户主）" if payload.get("head_is_minor") else ""
    text = f"家庭 {household} 户主由 [{old_head}] 变更为 [{new_head}]{suffix}"
    degraded = not all(k in payload for k in ("household_id", "new_head_id"))
    return text, degraded


def _render_household_dissolved(payload: dict) -> tuple[str, bool]:
    household = payload.get("household_id") or "?"
    last = payload.get("last_member_name") or payload.get("last_member_id") or "?"
    debts = payload.get("debts")
    text = f"家庭 {household} 因最后成员 [{last}] 死亡而消亡"
    if debts is not None:
        text += f"（遗留债务 {_num(debts)} 笔）"
    degraded = not all(k in payload for k in ("household_id", "last_member_id"))
    return text, degraded


def _render_household_work_nodes_changed(payload: dict) -> tuple[str, bool]:
    household = payload.get("household_id") or "?"
    before = payload.get("before") or []
    after = payload.get("after") or []
    workers = payload.get("work_capable_members")
    suffix = f"（可劳作 {_num(workers)} 人）" if workers is not None else ""
    text = (
        f"家庭 {household} 可分配田块由 {'/'.join(map(str, before)) or '无'} "
        f"调整为 {'/'.join(map(str, after)) or '无'}{suffix}"
    )
    degraded = not all(k in payload for k in ("household_id", "after"))
    return text, degraded


def _render_agent_work_node_changed(payload: dict) -> tuple[str, bool]:
    name = payload.get("agent_name") or payload.get("agent_id") or "?"
    before = payload.get("before") or "无"
    after = payload.get("after") or "家庭分配"
    text = f"[{name}] 劳作点由 {before} 改为 {after}"
    if payload.get("reason") == "preference_invalid":
        text += "（原偏好失效）"
    degraded = not all(k in payload for k in ("agent_id", "reason"))
    return text, degraded


def _render_birth_skipped(payload: dict) -> tuple[str, bool]:
    name = payload.get("agent_name") or payload.get("agent_id") or "?"
    household = payload.get("household_id") or "?"
    count = _num(payload.get("member_count"))
    cap = _num(payload.get("house_max_members"))
    text = f"家庭 {household} 已有 {count} 人达上限 {cap}，[{name}] 本次生育顺延"
    degraded = not all(k in payload for k in ("agent_id", "house_max_members"))
    return text, degraded


def _render_debt_written_off(payload: dict) -> tuple[str, bool]:
    creditor = payload.get("creditor_name") or payload.get("creditor_id") or "?"
    debtor = payload.get("debtor_name") or payload.get("debtor_id") or "?"
    amount = _num(payload.get("amount"))
    reason = payload.get("reason", "")
    text = f"[{debtor}] 欠 [{creditor}] 的 {amount} 石债务核销"
    if reason:
        text += f"（{reason}）"
    degraded = not all(k in payload for k in ("amount",))
    return text, degraded


def _render_debt_collection_attempt(payload: dict) -> tuple[str, bool]:
    debtor = payload.get("debtor_name") or payload.get("debtor_id") or "?"
    creditor = payload.get("creditor_name") or payload.get("creditor_id") or "?"
    amount = _num(payload.get("amount"))
    overdue = payload.get("overdue_ticks")
    text = f"[{creditor}] 向 [{debtor}] 催收 {amount} 石未果（已逾期 {overdue} 天）"
    degraded = not all(k in payload for k in ("creditor_id", "debtor_id", "amount"))
    return text, degraded


def _render_debt_forgiven(payload: dict) -> tuple[str, bool]:
    debtor = payload.get("debtor_name") or payload.get("debtor_id") or "?"
    creditor = payload.get("creditor_name") or payload.get("creditor_id") or "?"
    amount = _num(payload.get("amount"))
    cause = payload.get("cause", "?")
    text = f"[{creditor}] 核销 [{debtor}] 债务 {amount} 石（原因：{cause}）"
    degraded = not all(k in payload for k in ("creditor_id", "debtor_id", "amount"))
    return text, degraded


# -- 债务纠纷（任务15 阶段二：2 轮私下催收）-------------------------------- #
def _render_conflict_started(payload: dict) -> tuple[str, bool]:
    creditor = payload.get("creditor_name") or payload.get("creditor_id") or "?"
    debtor = payload.get("debtor_name") or payload.get("debtor_id") or "?"
    amount = _num(payload.get("amount"))
    overdue = payload.get("overdue_ticks")
    text = f"[{creditor}] 因 [{debtor}] 赊账逾期 {overdue} 天未还，私下上门讨债（欠 {amount} 石）"
    degraded = not all(
        k in payload for k in ("conflict_id", "creditor_id", "debtor_id", "amount")
    )
    return text, degraded


def _render_conflict_negotiation_round(payload: dict) -> tuple[str, bool]:
    creditor = payload.get("initiator") or "?"
    round_no = payload.get("round")
    proposal = payload.get("proposal")
    amount = _num(payload.get("proposal_amount"))
    if round_no == 1:
        demand = {"full": "全额偿还", "partial": "先还一部分", "deferral": "宽限些时日"}.get(
            proposal, "还债"
        )
        text = f"[{creditor}] 第 1 轮开口：{demand} {amount} 石" if amount else (
            f"[{creditor}] 第 1 轮开口：{demand}"
        )
    else:
        response = payload.get("response")
        reply = {
            "repay": "当场筹措还粮",
            "accept_deferral": "接受宽限",
            "request_deferral": "请求再延一期",
            "refuse": "一口回绝",
        }.get(response, "沉默")
        text = f"第 2 轮：债务人{reply}"
    degraded = not all(k in payload for k in ("conflict_id", "round"))
    return text, degraded


def _render_conflict_resolved(payload: dict) -> tuple[str, bool]:
    resolution = payload.get("resolution", "?")
    label = {"repaid": "已还清", "partial_repaid": "部分偿还", "deferred": "同意延期"}.get(
        resolution, resolution
    )
    if resolution == "deferred":
        text = f"[债务纠纷] 双方谈妥：延期至 tick {payload.get('new_due_tick', '?')}"
    else:
        text = f"[债务纠纷] 双方谈妥：{label}（本次还 {_num(payload.get('amount_paid'))} 石，余 {_num(payload.get('remaining'))}）"
    degraded = not all(k in payload for k in ("conflict_id", "resolution"))
    return text, degraded


def _render_conflict_broken(payload: dict) -> tuple[str, bool]:
    reason = payload.get("reason", "?")
    label = {"refused": "债务人拒不还债", "creditor_insists": "债主不肯再宽限"}.get(
        reason, reason
    )
    amount = _num(payload.get("amount"))
    text = f"[债务纠纷] 谈崩：{label}（欠 {amount} 石）"
    degraded = not all(k in payload for k in ("conflict_id", "reason"))
    return text, degraded


def _render_debt_deferred(payload: dict) -> tuple[str, bool]:
    debtor = payload.get("debtor_name") or payload.get("debtor_id") or "?"
    creditor = payload.get("creditor_name") or payload.get("creditor_id") or "?"
    amount = _num(payload.get("amount"))
    new_due = payload.get("new_due_tick")
    days = payload.get("deferral_days")
    text = f"[{debtor}] 欠 [{creditor}] 的 {amount} 石延期 {days} 天（新到期 tick {new_due}）"
    degraded = not all(
        k in payload for k in ("debtor_id", "creditor_id", "amount", "new_due_tick")
    )
    return text, degraded


def _render_trade_executed(payload: dict) -> tuple[str, bool]:
    buyer = payload.get("buyer_name") or payload.get("buyer_id") or "?"
    seller = payload.get("seller_name") or payload.get("seller_id") or "?"
    give = _item_name(payload.get("give_item"))
    take = _item_name(payload.get("take_item"))
    give_qty = _num(payload.get("give_qty"))
    take_qty = _num(payload.get("take_qty"))
    text = f"[{buyer}] 以 {take_qty} {take} 向 [{seller}] 换得 {give_qty} {give}（集市）"
    degraded = not all(
        k in payload for k in ("buyer_id", "seller_id", "give_item", "take_item", "give_qty", "take_qty")
    )
    return text, degraded


def _render_market_day_summary(payload: dict) -> tuple[str, bool]:
    count = _num(payload.get("participant_count"))
    trades = _num(payload.get("trade_count"))
    skipped = payload.get("skipped") or {}
    causes = []
    for key, label in (("too_far", "路远"), ("too_weak", "体力不足"), ("dead_or_incap", "亡故失能")):
        n = skipped.get(key, 0) if isinstance(skipped, dict) else 0
        if n:
            causes.append(f"{label} {_num(n)} 人")
    suffix = f"（{'，'.join(causes)}未至）" if causes else ""
    text = f"[集市] 集市日：{count} 人赴集，成交 {trades} 笔{suffix}"
    degraded = "participant_count" not in payload
    return text, degraded


def _render_weave_success(payload: dict) -> tuple[str, bool]:
    name = payload.get("agent_name") or payload.get("agent_id") or "?"
    amount = _num(payload.get("amount"))
    after = _num(payload.get("cloth_after"))
    text = f"[{name}] 织成 {amount} 匹布（布存 {after} 匹）"
    degraded = not all(k in payload for k in ("agent_id", "amount"))
    return text, degraded


def _render_weave_fail(payload: dict) -> tuple[str, bool]:
    name = payload.get("agent_name") or payload.get("agent_id") or "?"
    reason = payload.get("reason", "未成布")
    text = f"[{name}] 织布未成（{reason}）"
    degraded = not all(k in payload for k in ("agent_id", "reason"))
    return text, degraded


def _render_cold_exposure(payload: dict) -> tuple[str, bool]:
    name = payload.get("agent_name") or payload.get("agent_id") or "?"
    cloth = _num(payload.get("cloth"))
    before = _num(payload.get("health_before"))
    after = _num(payload.get("health_after"))
    text = f"[{name}] 家中只有 {cloth} 匹布，不足御寒，健康 {before} → {after}"
    degraded = not all(k in payload for k in ("agent_id", "health_before", "health_after"))
    return text, degraded


def render_event(evt: dict, names: Optional[dict[str, str]] = None) -> RenderResult:
    """渲染单条事件为一行中文摘要。永不抛出。"""
    if evt.get("_payload_broken"):
        return RenderResult(
            text=f"[#{evt.get('id','?')} tick={evt.get('tick','?')}] 载荷损坏（JSON 解析失败），原始片段见详情",
            degraded=True,
            reason="payload_broken_json",
        )
    event_type = evt.get("event_type")
    payload = evt.get("payload")
    if not isinstance(payload, dict):
        # 坏载荷：viewer 层已标 _payload_broken；这里给最小可读
        return RenderResult(
            text=f"[#{evt.get('id','?')} tick={evt.get('tick','?')}] 载荷损坏，无法渲染",
            degraded=True,
            reason="payload_not_dict",
        )

    try:
        if event_type == "weather_changed":
            text, degraded = _render_weather(payload)
            reason = "missing_weather_field" if degraded else None
        elif event_type == "season_changed":
            text, degraded = _render_season(payload)
            reason = "missing_season_field" if degraded else None
        elif event_type == "agent_action_taken":
            text, degraded = _render_action(payload, names)
            reason = "unknown_action_or_field" if degraded else None
        elif event_type == "agent_error":
            text, degraded = _render_agent_error(payload)
            reason = "missing_error_field" if degraded else None
        elif event_type == "debt_formed":
            text, degraded = _render_debt_formed(payload)
            reason = "missing_debt_field" if degraded else None
        elif event_type == "debt_collected":
            text, degraded = _render_debt_collected(payload)
            reason = "missing_debt_field" if degraded else None
        elif event_type == "debt_defaulted":
            text, degraded = _render_debt_defaulted(payload)
            reason = "missing_debt_field" if degraded else None
        elif event_type == "debt_repaid":
            text, degraded = _render_debt_repaid(payload)
            reason = "missing_debt_field" if degraded else None
        elif event_type == "health_recovered":
            text, degraded = _render_health_recovered(payload)
            reason = "missing_health_field" if degraded else None
        elif event_type == "gather_success":
            text, degraded = _render_gather_success(payload)
            reason = "missing_gather_field" if degraded else None
        elif event_type == "gather_fail":
            text, degraded = _render_gather_fail(payload)
            reason = "missing_gather_field" if degraded else None
        elif event_type == "gather_injury":
            text, degraded = _render_gather_injury(payload)
            reason = "missing_gather_field" if degraded else None
        elif event_type == "agent_incapacitated":
            text, degraded = _render_agent_incapacitated(payload)
            reason = "missing_life_field" if degraded else None
        elif event_type == "agent_died":
            text, degraded = _render_agent_died(payload)
            reason = "missing_life_field" if degraded else None
        elif event_type == "household_merged":
            text, degraded = _render_household_merged(payload)
        elif event_type == "household_split":
            text, degraded = _render_household_split(payload)
            reason = "missing_household_field" if degraded else None
        elif event_type == "household_head_changed":
            text, degraded = _render_household_head_changed(payload)
            reason = "missing_household_field" if degraded else None
        elif event_type == "household_dissolved":
            text, degraded = _render_household_dissolved(payload)
            reason = "missing_household_field" if degraded else None
        elif event_type == "household_work_nodes_changed":
            text, degraded = _render_household_work_nodes_changed(payload)
            reason = "missing_household_field" if degraded else None
        elif event_type == "agent_work_node_changed":
            text, degraded = _render_agent_work_node_changed(payload)
            reason = "missing_life_field" if degraded else None
        elif event_type == "birth_skipped":
            text, degraded = _render_birth_skipped(payload)
            reason = "missing_life_field" if degraded else None
        elif event_type == "debt_written_off":
            text, degraded = _render_debt_written_off(payload)
            reason = "missing_debt_field" if degraded else None
        elif event_type == "debt_collection_attempt":
            text, degraded = _render_debt_collection_attempt(payload)
            reason = "missing_debt_field" if degraded else None
        elif event_type == "debt_forgiven":
            text, degraded = _render_debt_forgiven(payload)
            reason = "missing_debt_field" if degraded else None
        elif event_type == "debt_deferred":
            text, degraded = _render_debt_deferred(payload)
            reason = "missing_debt_field" if degraded else None
        elif event_type == "conflict_started":
            text, degraded = _render_conflict_started(payload)
            reason = "missing_conflict_field" if degraded else None
        elif event_type == "conflict_negotiation_round":
            text, degraded = _render_conflict_negotiation_round(payload)
            reason = "missing_conflict_field" if degraded else None
        elif event_type == "conflict_resolved":
            text, degraded = _render_conflict_resolved(payload)
            reason = "missing_conflict_field" if degraded else None
        elif event_type == "conflict_broken":
            text, degraded = _render_conflict_broken(payload)
            reason = "missing_conflict_field" if degraded else None
        elif event_type == "trade_executed":
            text, degraded = _render_trade_executed(payload)
            reason = "missing_trade_field" if degraded else None
        elif event_type == "market_day_summary":
            text, degraded = _render_market_day_summary(payload)
            reason = "missing_market_field" if degraded else None
        elif event_type == "weave_success":
            text, degraded = _render_weave_success(payload)
            reason = "missing_weave_field" if degraded else None
        elif event_type == "weave_fail":
            text, degraded = _render_weave_fail(payload)
            reason = "missing_weave_field" if degraded else None
        elif event_type == "cold_exposure":
            text, degraded = _render_cold_exposure(payload)
            reason = "missing_cold_field" if degraded else None
        elif event_type == "agent_aged":
            text, degraded = _render_agent_aged(payload)
            reason = "missing_life_field" if degraded else None
        elif event_type == "agent_married":
            text, degraded = _render_agent_married(payload)
            reason = "missing_life_field" if degraded else None
        elif event_type == "agent_born":
            text, degraded = _render_agent_born(payload)
            reason = "missing_life_field" if degraded else None
        elif event_type == "birth_asset_transfer":
            text, degraded = _render_birth_asset_transfer(payload)
            reason = "missing_life_field" if degraded else None
        elif event_type == "inheritance_executed":
            text, degraded = _render_inheritance_executed(payload)
            reason = "missing_life_field" if degraded else None
        elif event_type == "inheritance_escheated":
            text, degraded = _render_inheritance_escheated(payload)
            reason = "missing_life_field" if degraded else None
        elif event_type == "debt_transferred":
            text, degraded = _render_debt_transferred(payload)
            reason = "missing_life_field" if degraded else None
        else:
            # 未知事件类型兜底：展示原始载荷键（截断），不崩
            keys = ", ".join(list(payload.keys())[:8])
            text = f"[未知事件类型「{event_type}」] 载荷键：{keys}"
            return RenderResult(text=text, degraded=True, reason="unknown_event_type")

        return RenderResult(text=text, degraded=degraded, reason=reason)
    except Exception as exc:  # noqa: BLE001 — 渲染单条失败不得拖垮整体
        return RenderResult(
            text=f"[#{evt.get('id','?')}] 渲染失败：{type(exc).__name__}: {exc}",
            degraded=True,
            reason=f"render_exception:{type(exc).__name__}",
        )


def payload_preview(evt: dict, max_len: int = 800) -> str:
    """用于 show 子命令的完整 payload 展示，坏 JSON 时给原始片段。"""
    raw = evt.get("_raw_payload")
    if raw is not None:
        return raw[:max_len]
    payload = evt.get("payload")
    try:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(payload)[:max_len]
