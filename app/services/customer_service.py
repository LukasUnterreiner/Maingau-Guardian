"""Customer 360 data engine.

Builds a point-in-time ``CustomerState`` for a customer:

    snapshot (workbook, 2026-09-30 23:59) + events with occurred_at <= as_of

Time handling
-------------
* The effective time of an event is ``occurred_at`` (e.g. a consent withdrawal
  is binding from the moment it happened, even if ingested later).
* Charging sessions only count once their CDR has arrived
  (``cdr_received_at <= as_of``); late roaming CDRs are not known earlier.
* Windows ("12 months", "30 days", "90 days") are measured back/forward from
  ``as_of``.

Unknown stays unknown: a missing CSAT, a missing consent row or missing
telemetry is reported as ``None``/"unknown", never as a negative signal.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from dateutil.relativedelta import relativedelta

from app.data.loader import Dataset, Event
from app.services.churn_model import ChurnDriver, ChurnFacts, churn_from, drivers_from_facts
from app.services.clv_engine import clv
from app.services.tonality import Tonality, customer_lines_from_transcript, derive_tonality

CONSENT_TYPES = ["newsletter_email", "marketing_email", "marketing_phone", "marketing_sms",
                 "portal_app_personalisation", "profiling_analytics"]

SHOP_PRODUCT_NAMES = {  # product_catalog product_id -> shop_orders.product_name prefix
    "P-SH-01": "Balkonkraftwerk 800 W",
    "P-SH-02": "Wallbox 11 kW",
    "P-SH-03": "Smarte Thermostate",
    "P-SH-04": "Smart Plug 4er-Set",
}
ACTIVE_ENERGY_STATUSES = {"active", "cancellation_pending"}
# shop_orders.product_category 'e_mobility' (Wallbox 11 kW, Ladekabel Typ 2); event orders carry only the name.
EV_SHOP_PRODUCT_NAMES = ("Wallbox 11 kW", "Ladekabel Typ 2")
KEPT_ORDER_STATUSES = {"delivered", "placed"}


@dataclass
class ConsentState:
    consent_type: str
    status: str  # granted | withdrawn | not_given | unknown
    updated_at: datetime | None
    source: str | None
    double_opt_in_confirmed: bool | None
    effective_reason: str  # where the effective status comes from

    @property
    def granted(self) -> bool:
        if self.status != "granted":
            return False
        if self.consent_type == "newsletter_email":
            return bool(self.double_opt_in_confirmed)
        return True


@dataclass
class CustomerState:
    customer_id: str
    as_of: datetime
    profile: dict[str, Any]
    energy_contracts: list[dict[str, Any]]
    mobile_contracts: list[dict[str, Any]]
    autostrom_contracts: list[dict[str, Any]]
    hems_devices: list[dict[str, Any]]
    shop_orders: list[dict[str, Any]]
    tickets: list[dict[str, Any]]
    charge_sessions: list[dict[str, Any]]
    consents: dict[str, ConsentState]
    marketing_contacts: list[dict[str, Any]]
    newsletter: dict[str, Any]
    portal: dict[str, Any]
    telemetry: dict[str, Any]
    signals: dict[str, Any]
    holdings: dict[str, bool | None]
    tonality: Tonality
    churn_facts: ChurnFacts
    snapshot_drivers: list[ChurnDriver]
    drivers: list[ChurnDriver]
    structural_churn: float | None
    churn_snapshot: float
    churn_now: float
    annual_margin_eur: float
    cost_to_serve_eur: float
    service_cost_12m_eur: float | None
    clv_snapshot_reported_eur: float
    clv_service_impact_reported_eur: float | None
    clv_now_eur: float
    value_model_version: str | None
    business_lines: list[str]
    applied_events: list[dict[str, Any]] = field(default_factory=list)
    service_notes: list[str] = field(default_factory=list)

    @property
    def open_complaint(self) -> bool:
        return self.churn_facts.open_complaint

    @property
    def max_dunning_level(self) -> int | None:
        return self.churn_facts.max_dunning_level

    @property
    def cancellation_pending(self) -> bool:
        return self.churn_facts.cancellation_pending

    @property
    def open_tickets(self) -> list[dict[str, Any]]:
        return [t for t in self.tickets if t.get("status") == "open"]

    @property
    def has_service_issue(self) -> bool:
        return bool(self.open_tickets or (self.max_dunning_level or 0) >= 1 or self.cancellation_pending
                    or self.churn_facts.failed_charges_30d > 0
                    or any(d.category == "service" for d in self.drivers))


def _parse_dt(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


class CustomerService:
    def __init__(self, ds: Dataset):
        self.ds = ds
        self._cache: dict[tuple[str, datetime], CustomerState] = {}

    # ------------------------------------------------------------------ public
    def customer_ids(self) -> list[str]:
        return sorted(self.ds.customers)

    def exists(self, customer_id: str) -> bool:
        return customer_id in self.ds.customers

    def resolve_as_of(self, as_of: str | datetime | None, default: str) -> datetime:
        value = as_of if as_of is not None else default
        if isinstance(value, datetime):
            return value
        if value == "latest":
            return max(self.ds.latest_event_at, self.ds.snapshot_at)
        if value == "snapshot":
            return self.ds.snapshot_at
        return datetime.fromisoformat(value)

    def get_state(self, customer_id: str, as_of: datetime) -> CustomerState:
        key = (customer_id, as_of)
        if key not in self._cache:
            self._cache[key] = self._build(customer_id, as_of)
        return self._cache[key]

    def clear_cache(self) -> None:
        self._cache.clear()

    # --------------------------------------------------------------- building
    def _build(self, cid: str, as_of: datetime) -> CustomerState:
        ds = self.ds
        A = ds.assumptions
        snap = ds.snapshot_at
        profile = dict(ds.customers[cid])
        value = ds.customer_value.get(cid)
        if value is None:
            raise KeyError(f"No customer_value row for {cid}")

        energy = copy.deepcopy(ds.rows("energy_contracts", cid))
        mobile = copy.deepcopy(ds.rows("mobile_contracts", cid))
        autostrom = copy.deepcopy(ds.rows("autostrom_contracts", cid))
        devices = copy.deepcopy(ds.rows("hems_devices", cid))
        orders = copy.deepcopy(ds.rows("shop_orders", cid))
        tickets = copy.deepcopy(ds.rows("service_interactions", cid))
        sessions = [s for s in copy.deepcopy(ds.rows("charge_sessions", cid))
                    if s.get("cdr_received_at") is None or s["cdr_received_at"] <= as_of]
        transcripts = [t for t in ds.rows("call_transcripts", cid)
                       if t.get("call_started_at") is None or t["call_started_at"] <= as_of]
        consents = self._snapshot_consents(cid, as_of)
        signals: dict[str, Any] = {"mobile_data_threshold_events": 0, "cart_abandoned": [],
                                   "agent_feedback": [], "recent_portal_logins": 0}
        texts: list[str] = [t["message_text"] for t in tickets if t.get("message_text")]
        texts += [customer_lines_from_transcript(t["transcript"]) for t in transcripts if t.get("transcript")]
        notes: list[str] = []

        applied: list[dict[str, Any]] = []
        for ev in ds.events_by_customer.get(cid, []):
            if ev.occurred_at > as_of:
                continue
            if self._apply_event(ev, energy, devices, orders, tickets, sessions, consents, signals, texts, notes):
                applied.append({"event_id": ev.event_id, "event_type": ev.event_type,
                                "occurred_at": ev.occurred_at.isoformat(sep=" "),
                                "ingested_at": ev.ingested_at.isoformat(sep=" ") if ev.ingested_at else None})

        # gas meters whose deregistration has become effective are no longer active
        for c in energy:
            dereg = _parse_dt(c.get("meter_deregistered_at"))
            if dereg and dereg <= as_of and c.get("status") == "active" and c.get("commodity") == "gas":
                c["status"] = "terminated_meter_deregistration"

        snapshot_facts = self._churn_facts(cid, snap, ds.rows("energy_contracts", cid),
                                           ds.rows("service_interactions", cid),
                                           [s for s in ds.rows("charge_sessions", cid)
                                            if s.get("cdr_received_at") is None or s["cdr_received_at"] <= snap],
                                           ds.rows("hems_devices", cid))
        facts = self._churn_facts(cid, as_of, energy, tickets, sessions, devices)
        snapshot_drivers = drivers_from_facts(snapshot_facts, A)
        drivers = drivers_from_facts(facts, A)
        churn_snapshot = float(value["churn_prob_12m"])
        structural = None if snapshot_facts.cancellation_pending else \
            churn_snapshot - sum(d.increment for d in snapshot_drivers)
        if structural is None and not facts.cancellation_pending:
            # cancellation withdrawn after the snapshot: structural part is not recoverable
            structural = churn_snapshot
            notes.append("Cancellation no longer pending; structural churn unknown, snapshot churn kept.")
        churn_now = churn_from(structural, drivers, facts.cancellation_pending, A)

        margin = float(value["annual_margin_eur"])
        cts = float(value["cost_to_serve_12m_eur"])
        clv_now = clv(margin, cts, churn_now, A["discount_rate"], int(A["horizon_years"]))

        active_energy = [c for c in energy if c.get("status") in ACTIVE_ENERGY_STATUSES]
        lines = []
        if active_energy:
            lines.append("energy")
        if any(m.get("status") == "active" for m in mobile):
            lines.append("mobile")
        if any(a.get("status") == "active" for a in autostrom):
            lines.append("e_mobility")
        if devices:
            lines.append("smart_living")

        state = CustomerState(
            customer_id=cid, as_of=as_of, profile=profile,
            energy_contracts=energy, mobile_contracts=mobile, autostrom_contracts=autostrom,
            hems_devices=devices, shop_orders=orders, tickets=tickets, charge_sessions=sessions,
            consents=consents,
            marketing_contacts=self._marketing_contacts(cid, as_of),
            newsletter=self._newsletter_summary(cid, as_of),
            portal=self._portal_summary(cid, as_of, signals),
            telemetry=self._telemetry_summary(cid, as_of),
            signals=signals, holdings={}, tonality=derive_tonality(texts),
            churn_facts=facts, snapshot_drivers=snapshot_drivers, drivers=drivers,
            structural_churn=structural, churn_snapshot=churn_snapshot, churn_now=churn_now,
            annual_margin_eur=margin, cost_to_serve_eur=cts,
            service_cost_12m_eur=value.get("service_cost_12m_eur"),
            clv_snapshot_reported_eur=float(value["clv_eur"]),
            clv_service_impact_reported_eur=value.get("clv_service_impact_eur"),
            clv_now_eur=clv_now, value_model_version=value.get("model_version"),
            business_lines=lines, applied_events=applied, service_notes=notes,
        )
        state.signals.update(self._derived_signals(state))
        state.holdings = self._holdings(state)
        return state

    # ---------------------------------------------------------------- consent
    def _snapshot_consents(self, cid: str, as_of: datetime) -> dict[str, ConsentState]:
        out: dict[str, ConsentState] = {}
        rows = sorted(self.ds.rows("consent_status", cid), key=lambda r: r.get("updated_at") or datetime.min)
        for r in rows:  # latest row per type wins
            upd = r.get("updated_at")
            if upd is not None and upd > as_of:
                continue  # not yet effective at as_of; status before is unknown
            out[r["consent_type"]] = ConsentState(
                consent_type=r["consent_type"], status=r.get("status") or "unknown", updated_at=upd,
                source=r.get("source"), double_opt_in_confirmed=r.get("double_opt_in_confirmed_at") is not None,
                effective_reason="consent_status snapshot")
        # Defensive: an unsubscribe via a newsletter after the last consent update means withdrawn.
        nl = out.get("newsletter_email")
        for p in self.ds.rows("newsletter_performance", cid):
            if not p.get("unsubscribed"):
                continue
            camp = self.ds.campaigns.get(p["campaign_id"], {})
            sent = camp.get("sent_at")
            if sent is None or sent > as_of:
                continue
            if nl is None or (nl.status == "granted" and (nl.updated_at is None or nl.updated_at < sent)):
                out["newsletter_email"] = nl = ConsentState(
                    "newsletter_email", "withdrawn", sent, "newsletter_unsubscribe_link", None,
                    f"unsubscribed via campaign {p['campaign_id']}")
        for t in CONSENT_TYPES:
            out.setdefault(t, ConsentState(t, "unknown", None, None, None, "no consent record"))
        return out

    # ----------------------------------------------------------------- events
    def _apply_event(self, ev: Event, energy, devices, orders, tickets, sessions, consents, signals,
                     texts, notes) -> bool:
        p = ev.payload
        t = ev.event_type
        if t == "consent_changed":
            ctype, status = p.get("consent_type"), p.get("new_status")
            if ctype and status:
                prev = consents.get(ctype)
                consents[ctype] = ConsentState(
                    ctype, status, ev.occurred_at, p.get("source"),
                    (prev.double_opt_in_confirmed if prev and status == "granted" else None),
                    f"event {ev.event_id}")
                return True
        elif t == "dunning_level_changed":
            new = p.get("new_level")
            targets = [c for c in energy if c.get("dunning_level") == p.get("old_level")] or \
                      sorted(energy, key=lambda c: c.get("dunning_level") or 0)[-1:]
            for c in targets:
                c["dunning_level"] = new
            return bool(targets)
        elif t == "contract_cancellation_received":
            targets = [c for c in energy if c.get("commodity") == p.get("commodity") and c.get("status") == "active"]
            for c in targets:
                c["status"] = "cancellation_pending"
                c["cancellation_received_at"] = ev.occurred_at
            return bool(targets)
        elif t == "gas_meter_deregistration_received":
            for c in energy:
                if c.get("commodity") == "gas" and c.get("status") == "active":
                    c["meter_deregistered_at"] = _parse_dt(p.get("effective_date")) or ev.occurred_at
            notes.append(f"Gas meter deregistration received (effective {p.get('effective_date')}).")
            return True
        elif t == "ticket_created":
            tickets.append({
                "ticket_id": p.get("ticket_id") or f"EV-{ev.event_id[:8]}", "customer_id": ev.customer_id,
                "created_at": ev.occurred_at, "channel": p.get("channel"), "category": p.get("category"),
                "message_text": p.get("message_text"), "call_note": p.get("note"), "status": "open",
                "resolved_at": None, "csat_1to5": None, "source": "event_stream", "event_id": ev.event_id})
            if p.get("message_text"):
                texts.append(p["message_text"])
            return True
        elif t == "ticket_updated":
            tid = p.get("ticket_id")
            match = [x for x in tickets if x.get("ticket_id") == tid]
            if not match:  # placeholder ids: attach to the latest open ticket
                match = sorted([x for x in tickets if x.get("status") == "open"],
                               key=lambda x: x.get("created_at") or datetime.min)[-1:]
            for x in match:
                if p.get("status"):
                    x["status"] = p["status"]
                if p.get("note"):
                    x["latest_note"] = p["note"]
                    x["latest_note_event_id"] = ev.event_id
            if p.get("note"):
                notes.append(f"Ticket update: {p['note']}")
            return True
        elif t == "charge_session_failed":
            sessions.append({"session_id": f"EV-{ev.event_id[:8]}", "started_at": ev.occurred_at,
                             "session_status": "failed", "failure_reason": p.get("failure_reason"),
                             "charge_type": p.get("charge_type"), "cdr_received_at": ev.ingested_at,
                             "source": "event_stream", "event_id": ev.event_id})
            return True
        elif t == "call_transcript_ready":
            if p.get("transcript"):
                texts.append(customer_lines_from_transcript(p["transcript"]))
            return True
        elif t == "order_placed":
            orders.append({"order_id": f"EV-{ev.event_id[:8]}", "order_created_at": ev.occurred_at,
                           "product_name": p.get("product_name"), "order_status": "placed",
                           "source": "event_stream", "event_id": ev.event_id})
            return True
        elif t == "cart_abandoned":
            signals["cart_abandoned"].append(p.get("product_name"))
            return True
        elif t == "mobile_data_threshold":
            signals["mobile_data_threshold_events"] += 1
            return True
        elif t == "agent_nba_feedback":
            signals["agent_feedback"].append(p)
            return True
        elif t == "hems_device_offline":
            for d in devices:
                if d.get("device_type") == p.get("device_type"):
                    d["connection_status"] = "offline"
            return True
        elif t == "portal_login":
            signals["recent_portal_logins"] += 1
            return True
        return t in {"page_viewed", "newsletter_opened", "newsletter_clicked", "charge_session_started",
                     "charge_session_completed", "meter_reading_submitted", "hems_daily_summary"}

    # ------------------------------------------------------------ churn facts
    def _churn_facts(self, cid, as_of, energy, tickets, sessions, devices) -> ChurnFacts:
        active = [c for c in energy if c.get("status") in ACTIVE_ENERGY_STATUSES]
        pg_dates = [(_parse_dt(c.get("price_guarantee_until")), c) for c in active]
        start = as_of.replace(hour=0, minute=0, second=0, microsecond=0)
        pg_end = [d for d, _ in pg_dates if d is not None and start <= d <= as_of + timedelta(days=90)]
        created = [t for t in tickets if t.get("created_at") is not None and t["created_at"] <= as_of]
        t12 = [t for t in created if t["created_at"] > as_of - relativedelta(months=12)]
        rated = sorted([t for t in created if t.get("csat_1to5") is not None], key=lambda t: t["created_at"])
        dunning_levels = [c.get("dunning_level") for c in active if c.get("dunning_level") is not None]
        failed = [s for s in sessions if s.get("session_status") == "failed" and s.get("started_at")
                  and as_of - timedelta(days=30) < s["started_at"] <= as_of]
        return ChurnFacts(
            price_guarantee_ends_90d=bool(pg_end),
            open_complaint=any(t.get("status") == "open" and t.get("category") == "complaint" for t in created),
            tickets_12m=len(t12),
            last_csat=rated[-1]["csat_1to5"] if rated else None,
            max_dunning_level=max(dunning_levels) if dunning_levels else None,
            failed_charges_30d=len(failed),
            hems_user=bool(devices),
            cancellation_pending=any(c.get("status") == "cancellation_pending" for c in energy),
            price_guarantee_until=min(pg_end).date().isoformat() if pg_end else None,
        )

    # -------------------------------------------------------------- summaries
    def _marketing_contacts(self, cid: str, as_of: datetime) -> list[dict[str, Any]]:
        out = []
        for r in self.ds.rows("nba_action_history", cid):
            if r.get("decided_at") and r["decided_at"] <= as_of:
                out.append({k: r.get(k) for k in ("action_id", "decided_at", "offer_id", "channel", "tonality",
                                                  "control_group", "delivery_status", "response",
                                                  "converted_within_14d", "consent_checked", "rule_id")})
        return sorted(out, key=lambda r: r["decided_at"], reverse=True)

    def _newsletter_summary(self, cid: str, as_of: datetime) -> dict[str, Any]:
        rows = self.ds.rows("newsletter_performance", cid)
        human_opens = sum(1 for r in rows if r.get("opened_at") and r.get("open_client_class") == "human")
        machine_opens = sum(1 for r in rows if r.get("opened_at") and r.get("open_client_class") == "apple_mpp_prefetch")
        return {
            "delivered": sum(1 for r in rows if r.get("delivered")),
            "human_opens": human_opens,
            "machine_opens_ignored": machine_opens,
            "clicks": sum(1 for r in rows if r.get("clicked_at")),
            "conversions_7d": sum(1 for r in rows if r.get("converted_within_7d")),
            "unsubscribed": any(r.get("unsubscribed") for r in rows),
        }

    def _portal_summary(self, cid: str, as_of: datetime, signals: dict[str, Any]) -> dict[str, Any]:
        rows = [r for r in self.ds.rows("portal_sessions", cid) if r.get("session_start") and r["session_start"] <= as_of]
        pages: dict[str, int] = {}
        for r in rows:
            for pg in (r.get("pages_viewed") or "").split("|"):
                if pg:
                    pages[pg] = pages.get(pg, 0) + 1
        return {"sessions_jul_sep": len(rows), "page_views": pages,
                "last_session": max((r["session_start"] for r in rows), default=None)}

    def _telemetry_summary(self, cid: str, as_of: datetime) -> dict[str, Any]:
        rows = [r for r in self.ds.rows("hems_telemetry_daily", cid) if r.get("date") and r["date"] <= as_of]
        if not rows:
            return {"days": 0}

        def total(col):
            vals = [r[col] for r in rows if r.get(col) is not None]
            return round(sum(vals), 1) if vals else None
        return {"days": len(rows), "pv_generation_kwh": total("pv_generation_kwh"),
                "ev_charging_kwh": total("ev_charging_kwh"), "heat_pump_kwh": total("heat_pump_kwh"),
                "grid_export_kwh": total("grid_export_kwh")}

    def _derived_signals(self, s: CustomerState) -> dict[str, Any]:
        dev_types = {d.get("device_type") for d in s.hems_devices}
        active_energy = [c for c in s.energy_contracts if c.get("status") in ACTIVE_ENERGY_STATUSES]
        tel = s.telemetry
        ev_orders = [o for o in s.shop_orders if o.get("order_status") in KEPT_ORDER_STATUSES
                     and (o.get("product_category") == "e_mobility"
                          or (o.get("product_name") or "").startswith(EV_SHOP_PRODUCT_NAMES))]
        ev_signal = bool(any(a.get("status") == "active" for a in s.autostrom_contracts)
                         or "wallbox" in dev_types or (tel.get("ev_charging_kwh") or 0) > 0 or ev_orders)
        failed_30d = [x for x in s.charge_sessions if x.get("session_status") == "failed" and x.get("started_at")
                      and s.as_of - timedelta(days=30) < x["started_at"] <= s.as_of]
        return {
            "has_electricity": any(c.get("commodity") == "electricity" for c in active_energy),
            "has_gas": any(c.get("commodity") == "gas" for c in active_energy),
            "gas_meter_deregistered": any(c.get("meter_deregistered_at") for c in s.energy_contracts
                                          if c.get("commodity") == "gas"),
            "smart_meter": any(c.get("meter_type") == "smart_meter_imsys" for c in active_energy),
            "pv": bool(any(c.get("feed_in_meter") for c in active_energy) or "pv_inverter" in dev_types
                       or (tel.get("pv_generation_kwh") or 0) > 0),
            "heat_pump": bool("heat_pump" in dev_types or (tel.get("heat_pump_kwh") or 0) > 0
                              or any(c.get("tariff") == "StromWärme" for c in active_energy)),
            "ev_driver": ev_signal,
            "hems_gateway": "hems_gateway" in dev_types,
            "home_battery": "home_battery" in dev_types,
            "wallbox_device": "wallbox" in dev_types,
            "ev_shop_orders": sorted(o.get("order_id") for o in ev_orders),
            "hems_offline_devices": sorted(d.get("device_type") for d in s.hems_devices
                                           if d.get("connection_status") == "offline"),
            "failed_charges_30d": len(failed_30d),
            "failed_charge_reasons_30d": sorted({x.get("failure_reason") for x in failed_30d if x.get("failure_reason")}),
            "mobile_data_limit_months_3m": max((m.get("data_limit_reached_3m") or 0 for m in s.mobile_contracts
                                                if m.get("status") == "active"), default=None),
            "mobile_sims_below_household": any(
                m.get("status") == "active" and (s.profile.get("household_size") or 0) > 1
                and (m.get("sim_count") or 0) < s.profile["household_size"] for m in s.mobile_contracts),
            "callback_requested": any("rückruf" in (t.get("latest_note") or t.get("call_note") or "").lower()
                                      for t in s.open_tickets),
        }

    def _holdings(self, s: CustomerState) -> dict[str, bool | None]:
        active_energy = [c for c in s.energy_contracts if c.get("status") in ACTIVE_ENERGY_STATUSES]
        tariffs = {c.get("tariff") for c in active_energy}
        mobile = [m for m in s.mobile_contracts if m.get("status") == "active"]
        owned_shop = set()
        for o in s.shop_orders:
            if o.get("order_status") in KEPT_ORDER_STATUSES:
                for pid, name in SHOP_PRODUCT_NAMES.items():
                    if (o.get("product_name") or "").startswith(name):
                        owned_shop.add(pid)
        if s.signals["wallbox_device"]:
            owned_shop.add("P-SH-02")
        return {
            "P-EN-01": s.signals["has_electricity"],
            "P-EN-02": None,  # retention offer: eligibility depends on the guarantee end date
            "P-EN-03": "StromWärme" in tariffs,
            "P-EN-04": s.signals["has_gas"],
            "P-EN-05": False,  # no dynamic tariff appears in energy_contracts
            "P-MO-01": bool(mobile),
            "P-MO-02": any(m.get("plan") == "Mobil L" for m in mobile) if mobile else None,
            "P-MO-03": None,  # SIM count vs household handled by eligibility
            "P-IN-01": None,  # no internet holdings in the mock data (unknown, not "no")
            "P-SL-01": s.signals["hems_gateway"],
            "P-SL-02": None,  # add-on subscriptions are not in the data
            "P-SL-03": None,
            "P-SH-01": "P-SH-01" in owned_shop,
            "P-SH-02": "P-SH-02" in owned_shop,
            "P-SH-03": "P-SH-03" in owned_shop,
            "P-SH-04": "P-SH-04" in owned_shop,
            "P-AS-01": any(a.get("status") == "active" for a in s.autostrom_contracts),
            "P-SV-01": None,
        }
