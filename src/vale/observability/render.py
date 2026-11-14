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
        gain = _safe_diff(payload.get("grain_after"), payload.get("grain_before"))
        repaid = _safe_diff(payload.get("debt_before"), payload.get("debt_after"))
        body = f"在{tname or '?'}秋收，打下 {gain} 石（存粮剩 {_num(payload.get('grain_after'))}）"
        if repaid and repaid != "0":
            body += f"，还债 {repaid} 石"
    elif action == "borrow_grain":
        amount = _safe_diff(payload.get("grain_after"), payload.get("grain_before"))
        body = (f"去{tname or '?'}借了 {amount} 石粮"
                f"（存粮剩 {_num(payload.get('grain_after'))}，欠债 {_num(payload.get('debt_after'))}）")
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
