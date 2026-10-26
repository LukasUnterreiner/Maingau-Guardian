"""Load and validate the MAINGAU workbook and the October event stream.

Design notes
------------
* Every sheet is linked through ``customer_id``. We index each customer table
  once (dict customer_id -> list of row dicts) so per-customer lookups are O(1).
* ``payment_method`` columns are dropped at load time. Hard rule 8 forbids
  using payment information for creditworthiness, and the engine has no other
  legitimate use for it, so it never reaches the decision logic.
* Missing values stay ``None`` (unknown). They are never coerced to False/0.
* Events are de-duplicated by ``event_id`` (the stream contains duplicates).
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)

REQUIRED_SHEETS: dict[str, list[str]] = {
    "customer_master": ["customer_id", "customer_since", "household_size", "portal_account", "app_installed"],
    "customer_value": ["customer_id", "annual_margin_eur", "cost_to_serve_12m_eur", "churn_prob_12m", "clv_eur"],
    "value_assumptions": ["group", "parameter", "value", "unit"],
    "product_catalog": ["product_id", "business_line", "action_type", "annual_margin_if_bought_eur", "churn_effect_if_bought"],
    "consent_status": ["customer_id", "consent_type", "status", "updated_at"],
    "energy_contracts": ["customer_id", "commodity", "tariff", "status", "price_guarantee_until", "dunning_level"],
    "mobile_contracts": ["customer_id", "plan", "status", "sim_count", "data_limit_reached_3m"],
    "autostrom_contracts": ["customer_id", "status"],
    "charge_sessions": ["customer_id", "started_at", "session_status", "cdr_received_at"],
    "shop_orders": ["customer_id", "product_name", "order_status"],
    "hems_devices": ["customer_id", "device_type", "connection_status"],
    "hems_telemetry_daily": ["customer_id", "date"],
    "newsletter_performance": ["customer_id", "campaign_id", "unsubscribed"],
    "newsletter_campaigns": ["campaign_id", "sent_at"],
    "portal_sessions": ["customer_id", "session_start"],
    "service_interactions": ["ticket_id", "customer_id", "created_at", "category", "status"],
    "call_transcripts": ["customer_id", "ticket_id", "transcript"],
    "service_nba_feedback": ["customer_id", "suggested_offer_id"],
    "nba_action_history": ["customer_id", "offer_id", "channel", "tonality", "control_group",
                           "delivery_status", "converted_within_14d", "consent_checked", "decided_at"],
}
DOC_SHEETS = ["README", "columns", "sources", "clv_method"]

DATE_COLUMNS = {
    "customer_master": ["customer_since", "record_updated_at"],
    "energy_contracts": ["start_date", "price_guarantee_until", "cancellation_received_at",
                         "last_meter_reading_at", "record_updated_at", "meter_deregistered_at"],
    "mobile_contracts": ["start_date", "min_term_end", "record_updated_at"],
    "autostrom_contracts": ["start_date", "cancelled_at", "record_updated_at"],
    "charge_sessions": ["started_at", "ended_at", "cdr_received_at"],
    "shop_orders": ["order_created_at", "record_updated_at"],
    "hems_devices": ["activated_at", "last_seen_at"],
    "hems_telemetry_daily": ["date"],
    "consent_status": ["updated_at", "double_opt_in_confirmed_at"],
    "newsletter_campaigns": ["sent_at"],
    "newsletter_performance": ["opened_at", "clicked_at"],
    "portal_sessions": ["session_start"],
    "service_interactions": ["created_at", "resolved_at"],
    "call_transcripts": ["call_started_at"],
    "service_nba_feedback": ["shown_at"],
    "nba_action_history": ["decided_at", "response_at"],
    "customer_value": ["clv_calc_date"],
}


class DataValidationError(RuntimeError):
    pass


def _clean(v: Any) -> Any:
    """Convert pandas missing values to None and timestamps to datetime."""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        try:
            return v.item()
        except (ValueError, AttributeError):
            return v
    return v


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    cols = list(df.columns)
    return [{c: _clean(v) for c, v in zip(cols, row)} for row in df.itertuples(index=False, name=None)]


@dataclass
class Event:
    event_id: str
    event_type: str
    source_system: str | None
    customer_id: str | None
    occurred_at: datetime
    ingested_at: datetime | None
    payload: dict[str, Any]


@dataclass
class Dataset:
    tables: dict[str, pd.DataFrame]
    by_customer: dict[str, dict[str, list[dict[str, Any]]]]
    customers: dict[str, dict[str, Any]]
    customer_value: dict[str, dict[str, Any]]
    assumptions: dict[str, float]
    assumption_rows: list[dict[str, Any]]
    products: dict[str, dict[str, Any]]
    campaigns: dict[str, dict[str, Any]]
    events: list[Event]
    events_by_customer: dict[str, list[Event]]
    documentation: dict[str, list[str]]
    snapshot_at: datetime
    quality_report: dict[str, Any] = field(default_factory=dict)

    def rows(self, table: str, customer_id: str) -> list[dict[str, Any]]:
        return self.by_customer.get(table, {}).get(customer_id, [])

    @property
    def latest_event_at(self) -> datetime:
        return max((e.occurred_at for e in self.events), default=self.snapshot_at)


def _load_events(path: Path) -> tuple[list[Event], dict[str, int]]:
    stats = {"lines": 0, "duplicates_dropped": 0, "invalid_dropped": 0}
    seen: set[str] = set()
    events: list[Event] = []
    if not path.exists():
        log.warning("event stream %s not found, continuing without events", path)
        return events, stats
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            stats["lines"] += 1
            try:
                raw = json.loads(line)
                eid = raw["event_id"]
                occurred = datetime.fromisoformat(raw["occurred_at"])
            except (ValueError, KeyError, TypeError):
                stats["invalid_dropped"] += 1
                continue
            if eid in seen:
                stats["duplicates_dropped"] += 1
                continue
            seen.add(eid)
            ingested = raw.get("ingested_at")
            events.append(Event(
                event_id=eid,
                event_type=raw.get("event_type", "unknown"),
                source_system=raw.get("source_system"),
                customer_id=raw.get("customer_id"),
                occurred_at=occurred,
                ingested_at=datetime.fromisoformat(ingested) if ingested else None,
                payload=raw.get("payload") or {},
            ))
    events.sort(key=lambda e: (e.occurred_at, e.event_id))
    return events, stats


def load_dataset(workbook: Path, event_stream: Path, snapshot_at: str) -> Dataset:
    if not workbook.exists():
        raise DataValidationError(f"Workbook not found: {workbook}")
    sheets = pd.read_excel(workbook, sheet_name=None)

    missing = [s for s in list(REQUIRED_SHEETS) + DOC_SHEETS if s not in sheets]
    if missing:
        raise DataValidationError(f"Workbook is missing sheets: {missing}")
    for sheet, cols in REQUIRED_SHEETS.items():
        absent = [c for c in cols if c not in sheets[sheet].columns]
        if absent:
            raise DataValidationError(f"Sheet {sheet} is missing columns {absent}")

    quality: dict[str, Any] = {"sheets": {}}
    tables: dict[str, pd.DataFrame] = {}
    for name, df in sheets.items():
        df = df.copy()
        if "payment_method" in df.columns:
            df = df.drop(columns=["payment_method"])  # hard rule 8
        for col in DATE_COLUMNS.get(name, []):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
        before = len(df)
        df = df.drop_duplicates()
        info = {"rows": len(df), "exact_duplicates_dropped": before - len(df)}
        if "customer_id" in df.columns:
            info["rows_without_customer_id"] = int(df["customer_id"].isna().sum())
        quality["sheets"][name] = info
        tables[name] = df

    customers = {r["customer_id"]: r for r in _records(tables["customer_master"])}
    cv = {r["customer_id"]: r for r in _records(tables["customer_value"])}
    unknown_cv = set(cv) - set(customers)
    if unknown_cv:
        raise DataValidationError(f"customer_value contains unknown customers: {sorted(unknown_cv)[:5]}")
    quality["customers_without_value_row"] = sorted(set(customers) - set(cv))

    by_customer: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for name, df in tables.items():
        if name in ("customer_master", "customer_value") or "customer_id" not in df.columns:
            continue
        idx: dict[str, list[dict[str, Any]]] = {}
        # Rows without customer_id (e.g. guest shop orders) cannot be attributed and are skipped.
        for rec in _records(df[df["customer_id"].notna()]):
            idx.setdefault(rec["customer_id"], []).append(rec)
        by_customer[name] = idx

    assumption_rows = _records(tables["value_assumptions"])
    assumptions = {r["parameter"]: float(r["value"]) for r in assumption_rows}
    for needed in ("discount_rate", "horizon_years", "contact_during_service_case", "service_resolution_cost_eur"):
        if needed not in assumptions:
            raise DataValidationError(f"value_assumptions is missing parameter {needed}")

    products = {r["product_id"]: r for r in _records(tables["product_catalog"])}
    campaigns = {r["campaign_id"]: r for r in _records(tables["newsletter_campaigns"])}

    events, ev_stats = _load_events(event_stream)
    quality["event_stream"] = ev_stats | {"events_loaded": len(events)}
    unknown_ev = {e.customer_id for e in events if e.customer_id and e.customer_id not in customers}
    quality["event_stream"]["events_for_unknown_customers"] = len(unknown_ev)
    events_by_customer: dict[str, list[Event]] = {}
    for e in events:
        if e.customer_id in customers:
            events_by_customer.setdefault(e.customer_id, []).append(e)

    docs = {name: [str(v) for v in sheets[name].astype(str).agg(" | ".join, axis=1).tolist()]
            for name in ("README", "clv_method")}

    return Dataset(
        tables=tables,
        by_customer=by_customer,
        customers=customers,
        customer_value=cv,
        assumptions=assumptions,
        assumption_rows=assumption_rows,
        products=products,
        campaigns=campaigns,
        events=events,
        events_by_customer=events_by_customer,
        documentation=docs,
        snapshot_at=datetime.fromisoformat(snapshot_at),
        quality_report=quality,
    )
