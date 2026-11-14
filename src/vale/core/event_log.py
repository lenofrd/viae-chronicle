"""事件日志（Event Sourcing 的唯一真相源）。

只追加（append-only）：任何状态变化都先发事件写入此表，再由事件投影出快照。
使用内置 sqlite3；测试用内存数据库（":memory:"）。
"""
from __future__ import annotations

import datetime
import json
import sqlite3
from typing import Any, Optional


class EventLog:
    def __init__(self, db_path: str = ":memory:") -> None:
        # check_same_thread=False 便于测试/调度在不同上下文访问；生产可按需收紧
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    # ------------------------------------------------------------------
    # schema
    # ------------------------------------------------------------------
    def _create_tables(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                tick        INTEGER NOT NULL,
                event_type  TEXT    NOT NULL,
                payload     TEXT    NOT NULL DEFAULT '{}',
                created_at  TEXT    NOT NULL
            )
            """
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # write
    # ------------------------------------------------------------------
    def append(self, tick: int, event_type: str, payload: Optional[dict[str, Any]] = None) -> int:
        """追加一条事件，返回事件 id。tick 缺失会被拒绝。"""
        if tick is None:
            raise ValueError("event 'tick' must not be None")
        if not isinstance(tick, int):
            raise TypeError(f"event 'tick' must be int, got {type(tick).__name__}")
        if not event_type:
            raise ValueError("event 'event_type' must not be empty")

        payload_json = json.dumps(payload or {}, ensure_ascii=False)
        created_at = datetime.datetime.now().isoformat(timespec="seconds")
        cur = self.conn.execute(
            "INSERT INTO events (tick, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            (tick, event_type, payload_json, created_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    # ------------------------------------------------------------------
    # read
    # ------------------------------------------------------------------
    def _row_to_event(self, row: sqlite3.Row) -> dict[str, Any]:
        evt = dict(row)
        evt["payload"] = json.loads(evt["payload"])
        return evt

    def get(self, event_id: int) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        return self._row_to_event(row) if row else None

    def all(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM events ORDER BY id"
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def by_type(self, event_type: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE event_type = ? ORDER BY id", (event_type,)
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def close(self) -> None:
        self.conn.close()
