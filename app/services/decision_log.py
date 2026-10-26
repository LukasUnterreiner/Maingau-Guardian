"""SQLite persistence: decision log, approval states, message drafts, runtime settings.

Decision ids are deterministic (hash of customer, as_of, settings, scenario and
engine version), so regenerating the same recommendation upserts the same row
and keeps its approval state.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models.runtime_settings import RuntimeSettings

APPROVAL_STATES = {"not_required", "pending_approval", "approved", "rejected"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    as_of TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    action_type TEXT NOT NULL,
    channel TEXT NOT NULL,
    expected_dclv_eur REAL NOT NULL,
    approval_status TEXT NOT NULL,
    reviewer TEXT,
    review_note TEXT,
    reviewed_at TEXT,
    record_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_decisions_customer ON decisions(customer_id);
CREATE INDEX IF NOT EXISTS ix_decisions_status ON decisions(approval_status);
CREATE TABLE IF NOT EXISTS messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    channel TEXT NOT NULL,
    tonality TEXT NOT NULL,
    source TEXT NOT NULL,
    subject TEXT,
    body TEXT NOT NULL,
    approval_status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT,
    settings_json TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DecisionLog:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)

    # ------------------------------------------------------------ decisions
    def upsert(self, record: dict[str, Any]) -> str:
        """Insert a decision if new; keep the approval state of an existing one. Returns the status."""
        with self._lock, self._conn:
            row = self._conn.execute("SELECT approval_status FROM decisions WHERE decision_id = ?",
                                     (record["decision_id"],)).fetchone()
            if row:
                return row["approval_status"]
            status = "pending_approval" if record["requires_human_approval"] else "not_required"
            self._conn.execute(
                "INSERT INTO decisions (decision_id, customer_id, created_at, as_of, recommended_action, action_type,"
                " channel, expected_dclv_eur, approval_status, record_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (record["decision_id"], record["customer_id"], _now(), record["as_of"], record["recommended_action"],
                 record["action_type"], record["channel"], record["expected_dclv_eur"], status,
                 json.dumps(record, default=str, ensure_ascii=False)))
            return status

    def get(self, decision_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM decisions WHERE decision_id = ?", (decision_id,)).fetchone()
        if not row:
            return None
        out = dict(row)
        out["record"] = json.loads(out.pop("record_json"))
        return out

    def statuses(self) -> dict[str, str]:
        with self._lock:
            rows = self._conn.execute("SELECT decision_id, approval_status FROM decisions").fetchall()
        return {r["decision_id"]: r["approval_status"] for r in rows}

    def set_status(self, decision_id: str, status: str, reviewer: str | None, note: str | None) -> None:
        assert status in APPROVAL_STATES
        with self._lock, self._conn:
            self._conn.execute("UPDATE decisions SET approval_status=?, reviewer=?, review_note=?, reviewed_at=?"
                               " WHERE decision_id=?", (status, reviewer, note, _now(), decision_id))
            self._conn.execute("UPDATE messages SET approval_status=? WHERE decision_id=? AND approval_status="
                               "'pending_approval'", (status, decision_id))

    def count_by_status(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute("SELECT approval_status, COUNT(*) n FROM decisions GROUP BY approval_status").fetchall()
        return {r["approval_status"]: r["n"] for r in rows}

    # ------------------------------------------------------------- messages
    def add_message(self, decision_id: str, channel: str, tonality: str, source: str, subject: str | None,
                    body: str) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO messages (decision_id, created_at, channel, tonality, source, subject, body,"
                " approval_status) VALUES (?,?,?,?,?,?,?, 'pending_approval')",
                (decision_id, _now(), channel, tonality, source, subject, body))
            return int(cur.lastrowid)

    # ------------------------------------------------------------- settings
    def load_settings(self) -> tuple[RuntimeSettings, int]:
        with self._lock:
            row = self._conn.execute("SELECT version, settings_json FROM runtime_settings WHERE id = 1").fetchone()
        if not row:
            return RuntimeSettings(), 0
        return RuntimeSettings.model_validate_json(row["settings_json"]), int(row["version"])

    def save_settings(self, settings: RuntimeSettings, updated_by: str | None) -> int:
        _, version = self.load_settings()
        version += 1
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO runtime_settings (id, version, updated_at, updated_by, settings_json) VALUES (1,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET version=excluded.version, updated_at=excluded.updated_at,"
                " updated_by=excluded.updated_by, settings_json=excluded.settings_json",
                (version, _now(), updated_by, settings.model_dump_json()))
        return version

    def close(self) -> None:
        self._conn.close()
