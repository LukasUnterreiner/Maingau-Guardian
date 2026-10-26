"""Copilot conversation store (SQLite).

A conversation belongs to exactly one employee and one customer. History is only
ever loaded by conversation id after both are checked, so one customer's
conversation can never feed another customer's prompt. Conversation ids are
random (uuid4), not derived from customer ids.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS copilot_conversations (
    conversation_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    employee_role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    turns INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_conv_employee ON copilot_conversations(employee_id, customer_id);
CREATE TABLE IF NOT EXISTS copilot_messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES copilot_conversations(conversation_id),
    turn INTEGER NOT NULL,
    author TEXT NOT NULL,
    content TEXT NOT NULL,
    payload_json TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_msg_conv ON copilot_messages(conversation_id, message_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ConversationStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)

    def create(self, customer_id: str, employee_id: str, role: str) -> dict[str, Any]:
        cid = "CONV-" + uuid.uuid4().hex
        now = _now()
        with self._lock, self._conn:
            self._conn.execute("INSERT INTO copilot_conversations VALUES (?,?,?,?,?,?,0)",
                               (cid, customer_id, employee_id, role, now, now))
        return self.get(cid)  # type: ignore[return-value]

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM copilot_conversations WHERE conversation_id = ?",
                                     (conversation_id,)).fetchone()
        return dict(row) if row else None

    def add_turn(self, conversation_id: str, question: str, answer: str, payload: dict[str, Any]) -> int:
        now = _now()
        with self._lock, self._conn:
            turn = self._conn.execute("SELECT turns FROM copilot_conversations WHERE conversation_id = ?",
                                      (conversation_id,)).fetchone()["turns"] + 1
            self._conn.execute("INSERT INTO copilot_messages (conversation_id, turn, author, content, payload_json,"
                               " created_at) VALUES (?,?,?,?,?,?)", (conversation_id, turn, "employee", question, None, now))
            self._conn.execute("INSERT INTO copilot_messages (conversation_id, turn, author, content, payload_json,"
                               " created_at) VALUES (?,?,?,?,?,?)",
                               (conversation_id, turn, "lighty", answer,
                                json.dumps(payload, default=str, ensure_ascii=False), now))
            self._conn.execute("UPDATE copilot_conversations SET turns = ?, updated_at = ? WHERE conversation_id = ?",
                               (turn, now, conversation_id))
        return turn

    def messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT turn, author, content, payload_json, created_at FROM copilot_messages"
                                      " WHERE conversation_id = ? ORDER BY message_id", (conversation_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            raw = d.pop("payload_json")
            d["payload"] = json.loads(raw) if raw else None
            out.append(d)
        return out

    def history(self, conversation_id: str, max_messages: int) -> list[dict[str, Any]]:
        """The last ``max_messages`` messages (oldest first) of this conversation only."""
        if max_messages <= 0:
            return []
        with self._lock:
            rows = self._conn.execute("SELECT author, content, payload_json FROM copilot_messages WHERE conversation_id"
                                      " = ? ORDER BY message_id DESC LIMIT ?", (conversation_id, max_messages)).fetchall()
        out = []
        for r in reversed(rows):
            payload = json.loads(r["payload_json"]) if r["payload_json"] else {}
            out.append({"author": r["author"], "content": r["content"], "intents": payload.get("intents", [])})
        return out

    def list(self, employee_id: str | None, customer_id: str | None, limit: int = 50) -> list[dict[str, Any]]:
        sql = "SELECT * FROM copilot_conversations WHERE 1=1"
        args: list[Any] = []
        if employee_id is not None:
            sql += " AND employee_id = ?"
            args.append(employee_id)
        if customer_id is not None:
            sql += " AND customer_id = ?"
            args.append(customer_id)
        sql += " ORDER BY updated_at DESC, conversation_id LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]
