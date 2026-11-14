"""导出纯函数（任务 07）：Markdown / CSV / JSONL。

导出的事件集合 = 传入的已筛选 events，条数与查看结果严格一致。
每条先渲染，统计降级数，末尾附元信息（筛选条件 / 总条数 / 降级条数）。
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any, Optional

from .render import render_event


def _render_all(events: list[dict], names: Optional[dict[str, str]]):
    rows = []
    degraded = 0
    for evt in events:
        r = render_event(evt, names)
        if r.degraded:
            degraded += 1
        rows.append((evt, r))
    return rows, degraded


def _meta(filter_desc: str, total: int, degraded: int) -> str:
    return (f"\n<!-- meta: filter={filter_desc} total={total} degraded={degraded} -->\n"
            if filter_desc else f"\n<!-- meta: total={total} degraded={degraded} -->\n")


def export_markdown(events: list[dict], names: Optional[dict[str, str]] = None,
                    date_of=None, filter_desc: str = "") -> str:
    rows, degraded = _render_all(events, names)
    buf = io.StringIO()
    buf.write("# 事件流导出\n\n")
    buf.write(f"- 总条数：{len(rows)}\n")
    buf.write(f"- 降级条数：{degraded}\n")
    if filter_desc:
        buf.write(f"- 筛选：{filter_desc}\n")
    buf.write("\n| id | tick | 日期 | 类型 | 摘要 | 降级 |\n")
    buf.write("|---|---|---|---|---|---|\n")
    for evt, r in rows:
        date = date_of(evt["tick"]) if date_of else ""
        buf.write(f"| {evt.get('id')} | {evt.get('tick')} | {date} | "
                  f"{evt.get('event_type')} | {r.text} | {'是' if r.degraded else ''} |\n")
    buf.write(_meta(filter_desc, len(rows), degraded))
    return buf.getvalue()


def export_csv(events: list[dict], names: Optional[dict[str, str]] = None,
               date_of=None, filter_desc: str = "") -> str:
    rows, degraded = _render_all(events, names)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "tick", "date", "event_type", "summary", "degraded"])
    for evt, r in rows:
        date = date_of(evt["tick"]) if date_of else ""
        w.writerow([evt.get("id"), evt.get("tick"), date,
                    evt.get("event_type"), r.text, "1" if r.degraded else "0"])
    # 元信息作为注释行（CSV 无标准注释，放末尾两行）
    w.writerow(["# meta", f"total={len(rows)}", f"degraded={degraded}",
                f"filter={filter_desc}", "", ""])
    return buf.getvalue()


def export_jsonl(events: list[dict], names: Optional[dict[str, str]] = None,
                 date_of=None, filter_desc: str = "") -> str:
    rows, degraded = _render_all(events, names)
    buf = io.StringIO()
    for evt, r in rows:
        date = date_of(evt["tick"]) if date_of else None
        obj = {
            "id": evt.get("id"),
            "tick": evt.get("tick"),
            "date": date,
            "event_type": evt.get("event_type"),
            "summary": r.text,
            "degraded": r.degraded,
            "degrade_reason": r.reason,
            "payload": evt.get("payload"),
        }
        buf.write(json.dumps(obj, ensure_ascii=False) + "\n")
    buf.write(json.dumps({"_meta": {"total": len(rows), "degraded": degraded,
                                    "filter": filter_desc}}, ensure_ascii=False) + "\n")
    return buf.getvalue()


EXPORT_FORMATS = {"md": export_markdown, "csv": export_csv, "jsonl": export_jsonl}
