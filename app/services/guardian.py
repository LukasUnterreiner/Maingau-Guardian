"""Application facade: wires the engines together and owns caches and runtime settings.

API routes only talk to this class; business logic lives in the engines.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from app.config.settings import AppSettings
from app.data.loader import Dataset, load_dataset
from app.models.runtime_settings import RuntimeSettings, RuntimeSettingsUpdate
from app.services.acceptance_model import AcceptanceModel
from app.services.ai_service import AIService
from app.services.analytics_service import AnalyticsService, segment_of
from app.services.clv_engine import CLVEngine, ScenarioParams
from app.services.counterfactual_engine import CounterfactualEngine
from app.services.customer_service import CustomerService, CustomerState
from app.services.decision_log import DecisionLog
from app.services.eligibility_engine import EligibilityEngine
from app.services.recommendation_engine import Decision, POverrides, RecommendationEngine, service_category

log = logging.getLogger(__name__)


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


def _iso(v: Any) -> Any:
    return v.isoformat(sep=" ") if isinstance(v, datetime) else v


class Guardian:
    def __init__(self, settings: AppSettings, dataset: Dataset | None = None, decision_log: DecisionLog | None = None):
        self.cfg = settings
        self.ds = dataset or load_dataset(settings.workbook_path, settings.event_stream_path, settings.snapshot_at)
        self.log = decision_log or DecisionLog(settings.sqlite_path)
        self.settings, self.settings_version = self.log.load_settings()
        self.customers = CustomerService(self.ds)
        self.clv = CLVEngine(self.ds.assumptions)
        self.eligibility = EligibilityEngine(self.ds.products)
        self.ai = AIService(settings)
        self._lock = threading.RLock()
        self._portfolio: list[Decision] | None = None
        self._build_engines()
        self.default_as_of = self.customers.resolve_as_of(None, settings.evaluation_as_of)

    def _build_engines(self) -> None:
        sim = self.settings.simulation
        self.acceptance = AcceptanceModel(self.ds.tables["nba_action_history"], self.ds.tables["service_interactions"],
                                          pseudo_count=sim.pseudo_count, exclude_unconsented=sim.exclude_unconsented_history,
                                          mode=sim.p_accept_mode)
        self.engine = RecommendationEngine(self.customers, self.eligibility, self.clv, self.acceptance, self.ds.products)
        self.counterfactual = CounterfactualEngine(self.engine)
        self.analytics = AnalyticsService(self.engine)
        self._portfolio = None

    # ---------------------------------------------------------------- utils
    def _require(self, customer_id: str) -> None:
        if not self.customers.exists(customer_id):
            raise NotFound(f"Customer {customer_id} not found")

    def as_of(self, value: str | None) -> datetime:
        if value is None:
            return self.default_as_of
        try:
            return self.customers.resolve_as_of(value, self.cfg.evaluation_as_of)
        except ValueError as exc:
            raise ValueError(f"Invalid as_of '{value}': use 'latest', 'snapshot' or an ISO timestamp") from exc

    # ------------------------------------------------------------ customers
    def customer_summary(self, s: CustomerState) -> dict[str, Any]:
        return {
            "customer_id": s.customer_id,
            "city": s.profile.get("city"),
            "customer_since": _iso(s.profile.get("customer_since")),
            "business_lines": s.business_lines,
            "current_clv_eur": round(s.clv_now_eur, 2),
            "churn_probability": round(s.churn_now, 4),
            "has_service_issue": s.has_service_issue,
            "open_complaint": s.open_complaint,
            "tonality": s.tonality.value,
        }

    def list_customers(self, page: int, page_size: int, business_line: str | None, has_service_issue: bool | None,
                       search: str | None, as_of: str | None) -> dict[str, Any]:
        t = self.as_of(as_of)
        rows = []
        for cid in self.customers.customer_ids():
            if search and search.upper() not in cid.upper():
                continue
            s = self.customers.get_state(cid, t)
            if business_line and business_line not in s.business_lines:
                continue
            if has_service_issue is not None and s.has_service_issue != has_service_issue:
                continue
            rows.append(self.customer_summary(s))
        total = len(rows)
        start = (page - 1) * page_size
        return {"items": rows[start:start + page_size], "page": page, "page_size": page_size, "total": total,
                "total_pages": (total + page_size - 1) // page_size, "as_of": t.isoformat(sep=" ")}

    def customer_360(self, customer_id: str, as_of: str | None) -> dict[str, Any]:
        self._require(customer_id)
        t = self.as_of(as_of)
        s = self.customers.get_state(customer_id, t)
        d = self.engine.decide(customer_id, t, self.settings)
        p = s.profile
        n30, days_since = self.eligibility.marketing_contacts_window(s)

        def clean(rows, keys):
            return [{k: _iso(r.get(k)) for k in keys} for r in rows]

        return {
            "customer_id": customer_id,
            "as_of": t.isoformat(sep=" "),
            "profile": {
                "customer_type": p.get("customer_type"), "customer_since": _iso(p.get("customer_since")),
                "birth_year": p.get("birth_year"), "postal_code_prefix": p.get("postal_code_prefix"),
                "city": p.get("city"), "household_size": p.get("household_size"),
                "portal_account": p.get("portal_account"), "app_installed": p.get("app_installed"),
                "preferred_contact_language": p.get("preferred_contact_language"),
                "segment": segment_of(d),
            },
            "business_lines": s.business_lines,
            "contracts": {
                "energy": clean(s.energy_contracts, ["contract_id", "commodity", "tariff", "status", "start_date",
                                                     "price_guarantee_until", "annual_consumption_kwh", "meter_type",
                                                     "feed_in_meter", "dunning_level", "cancellation_received_at",
                                                     "meter_deregistered_at"]),
                "mobile": clean(s.mobile_contracts, ["contract_id", "plan", "data_volume_gb", "sim_count", "status",
                                                     "min_term_end", "avg_data_used_gb_3m", "data_limit_reached_3m"]),
                "autostrom": clean(s.autostrom_contracts, ["contract_id", "status", "start_date", "cancelled_at",
                                                           "car_brand", "car_model", "charge_cards", "app_user"]),
                "hems_devices": clean(s.hems_devices, ["device_id", "device_type", "connection_status", "last_seen_at"]),
            },
            "products_held": sorted(pid for pid, held in s.holdings.items() if held),
            "product_holdings": s.holdings,
            "shop_orders": clean(s.shop_orders, ["order_id", "order_created_at", "product_name", "order_status"]),
            "value": {
                "annual_margin_eur": s.annual_margin_eur,
                "cost_to_serve_12m_eur": s.cost_to_serve_eur,
                "service_cost_12m_eur": s.service_cost_12m_eur,
                "net_annual_value_eur": round(s.annual_margin_eur - s.cost_to_serve_eur, 2),
                "churn_probability_snapshot": s.churn_snapshot,
                "churn_probability_now": round(s.churn_now, 4),
                "clv_reported_snapshot_eur": s.clv_snapshot_reported_eur,
                "clv_service_impact_reported_eur": s.clv_service_impact_reported_eur,
                "current_clv_eur": round(s.clv_now_eur, 2),
                "value_model_version": s.value_model_version,
                "labels": {
                    "annual_margin_eur": "observed (customer_value)",
                    "cost_to_serve_12m_eur": "observed (customer_value)",
                    "churn_probability_snapshot": "observed (customer_value model output)",
                    "churn_probability_now": "estimated (snapshot churn + event-driven driver changes)",
                    "current_clv_eur": "estimated (clv_method on churn_probability_now)",
                },
            },
            "churn_drivers": [{"code": dr.code, "label": dr.label, "category": dr.category,
                               "increment": dr.increment, "evidence": dr.evidence} for dr in s.drivers],
            "churn_drivers_snapshot": [dr.code for dr in s.snapshot_drivers],
            "structural_churn": None if s.structural_churn is None else round(s.structural_churn, 4),
            "service": {
                "has_service_issue": s.has_service_issue,
                "open_complaint": s.open_complaint,
                "max_dunning_level": s.max_dunning_level,
                "cancellation_pending": s.cancellation_pending,
                "open_tickets": clean(s.open_tickets, ["ticket_id", "created_at", "channel", "category", "status",
                                                       "latest_note"]),
                "tickets_12m": s.churn_facts.tickets_12m,
                "last_csat": s.churn_facts.last_csat,
                "failed_charges_30d": s.signals["failed_charges_30d"],
                "failed_charge_reasons_30d": s.signals["failed_charge_reasons_30d"],
                "hems_offline_devices": s.signals["hems_offline_devices"],
                "notes": s.service_notes,
            },
            "marketing_history": {
                "contacts_last_30d": n30,
                "days_since_last_contact": None if days_since is None else round(days_since, 1),
                "recent_actions": [{k: _iso(v) for k, v in c.items()} for c in s.marketing_contacts[:10]],
                "newsletter": s.newsletter,
                "portal": {**s.portal, "last_session": _iso(s.portal.get("last_session"))},
            },
            "communication": {
                "tonality": s.tonality.value, "tonality_source": s.tonality.source,
                "preferred_contact_language": p.get("preferred_contact_language"),
                "service_channel": self.eligibility.service_channel(s),
            },
            "consents": {k: {"status": c.status, "effective": c.granted, "updated_at": _iso(c.updated_at),
                             "source": c.source, "double_opt_in_confirmed": c.double_opt_in_confirmed,
                             "effective_reason": c.effective_reason} for k, c in s.consents.items()},
            "signals": {k: v for k, v in s.signals.items() if k != "agent_feedback"},
            "eligible_actions": [{"product_id": c.product_id, "channel": c.channel,
                                  "expected_dclv_eur": round(c.dclv, 2)} for c in d.ranked],
            "blocked_actions": [{"product_id": c.product_id, "exclusion_reasons": c.eligibility.exclusion_codes}
                                for c in d.blocked],
            "applied_events": s.applied_events,
        }

    # ------------------------------------------------------ recommendations
    def _record(self, d: Decision) -> dict[str, Any]:
        resp = self.engine.to_response(d, "pending_approval" if d.recommended else "not_required")
        s = d.state
        resp["inputs"] = {
            "annual_margin_eur": s.annual_margin_eur, "cost_to_serve_eur": s.cost_to_serve_eur,
            "churn_now": round(s.churn_now, 4), "structural_churn": s.structural_churn,
            "drivers": [dr.code for dr in s.drivers],
            "discount_rate": self.ds.assumptions["discount_rate"], "horizon_years": self.ds.assumptions["horizon_years"],
            "consents": {k: c.status for k, c in s.consents.items()},
            "tonality": s.tonality.value, "settings_version": self.settings_version,
        }
        return resp

    def recommend(self, customer_id: str, as_of: str | None = None) -> dict[str, Any]:
        self._require(customer_id)
        d = self.engine.decide(customer_id, self.as_of(as_of), self.settings)
        record = self._record(d)
        status = self.log.upsert(record)
        record["approval_status"] = status
        record.pop("inputs")
        return record

    def portfolio(self) -> list[Decision]:
        with self._lock:
            if self._portfolio is None:
                self._portfolio = [self.engine.decide(cid, self.default_as_of, self.settings)
                                   for cid in self.customers.customer_ids()]
            return self._portfolio

    def marketing_recommendations(self, page: int, page_size: int, action_type: str | None, channel: str | None,
                                  business_line: str | None, approval_status: str | None,
                                  include_no_contact: bool) -> dict[str, Any]:
        statuses = self.log.statuses()
        rows = []
        for d in self.portfolio():
            r = d.recommended
            if r is None and not include_no_contact:
                continue
            atype = r.valuation.action_type if r else "no_contact"
            line = self.ds.products[r.product_id]["business_line"] if r else None
            status = statuses.get(d.decision_id, "pending_approval" if r else "not_required")
            if action_type and atype != action_type:
                continue
            if channel and (r.channel if r else "none") != channel:
                continue
            if business_line and line != business_line:
                continue
            if approval_status and status != approval_status:
                continue
            rows.append({
                "customer_id": d.customer_id, "decision_id": d.decision_id, "recommended_action": d.recommended_product,
                "recommended_action_name": self.ds.products[r.product_id]["product_name"] if r else "No contact",
                "action_type": atype, "business_line": line, "channel": r.channel if r else "none",
                "tonality": d.state.tonality.value, "current_clv_eur": round(d.clv_now_eur, 2),
                "expected_dclv_eur": round(d.expected_dclv, 2),
                "acceptance_probability": round(r.p_used, 4) if r else None,
                "required_service_workflow": d.required_service_workflow, "approval_status": status,
                "segment": segment_of(d),
            })
        rows.sort(key=lambda x: (-x["expected_dclv_eur"], x["customer_id"]))
        total = len(rows)
        start = (page - 1) * page_size
        return {"items": rows[start:start + page_size], "page": page, "page_size": page_size, "total": total,
                "total_pages": (total + page_size - 1) // page_size}

    def overview(self) -> dict[str, Any]:
        out = self.analytics.overview(self.portfolio(), self.log.statuses(), self.settings.simulation.baseline_policy)
        out["settings_version"] = self.settings_version
        return out

    # ----------------------------------------------------------- simulation
    def simulate(self, customer_id: str, params: ScenarioParams, p_over: POverrides, baseline_policy: str | None,
                 as_of: str | None) -> dict[str, Any]:
        self._require(customer_id)
        return self.counterfactual.simulate(customer_id, self.as_of(as_of), self.settings, params, p_over,
                                            baseline_policy or self.settings.simulation.baseline_policy)

    # --------------------------------------------------------------- review
    def review(self, decision_id: str, approve: bool, reviewer: str | None, note: str | None) -> dict[str, Any]:
        row = self.log.get(decision_id)
        if row is None:
            raise NotFound(f"Decision {decision_id} not found")
        if row["approval_status"] == "not_required":
            raise Conflict("No-contact decisions have nothing to approve")
        if row["approval_status"] in ("approved", "rejected"):
            raise Conflict(f"Decision already {row['approval_status']}")
        if approve:
            # Re-check compliance on the latest known state before approving.
            rec = row["record"]
            s = self.customers.get_state(rec["customer_id"], self.default_as_of)
            pid, ch = rec["recommended_action"], rec["channel"]
            inquiry = rec.get("process") == "customer_inquiry_reply"
            checks = self.eligibility.product_checks(s, pid, self.settings, inquiry_reply=inquiry) + \
                self.eligibility.channel_checks(s, pid, ch)
            failing = [c.code for c in checks if not c.passed]
            if failing:
                raise Conflict(f"Action is no longer permitted: {', '.join(failing)}")
        status = "approved" if approve else "rejected"
        self.log.set_status(decision_id, status, reviewer, note)
        out = self.log.get(decision_id)
        return {"decision_id": decision_id, "customer_id": out["customer_id"], "approval_status": out["approval_status"],
                "reviewer": out["reviewer"], "review_note": out["review_note"], "reviewed_at": out["reviewed_at"]}

    # ------------------------------------------------------------- settings
    def get_settings(self) -> dict[str, Any]:
        return {"version": self.settings_version, "settings": self.settings.model_dump(),
                "known_product_ids": sorted(self.ds.products),
                "hard_rules_note": "Consent, profiling, service-state blocks and approval are not configurable."}

    def update_settings(self, update: RuntimeSettingsUpdate, updated_by: str | None) -> dict[str, Any]:
        unknown = set(update.action_priorities or {}) - set(self.ds.products)
        if unknown:
            raise ValueError(f"Unknown product ids in action_priorities: {sorted(unknown)}")
        merged = self.settings.model_dump()
        for key, val in update.model_dump(exclude_none=True).items():
            if key == "action_priorities":
                merged["action_priorities"] = {**merged["action_priorities"], **val}
            else:
                merged[key] = val
        try:
            new = RuntimeSettings.model_validate(merged)
        except ValidationError as exc:
            raise ValueError("; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())) from None
        with self._lock:
            self.settings = new
            self.settings_version = self.log.save_settings(new, updated_by)
            self._build_engines()
        return self.get_settings()

    # ------------------------------------------------------------------- AI
    def _decision_response(self, customer_id: str | None, decision_id: str | None) -> dict[str, Any]:
        if decision_id:
            row = self.log.get(decision_id)
            if row is None:
                raise NotFound(f"Decision {decision_id} not found")
            rec = dict(row["record"])
            rec["approval_status"] = row["approval_status"]
            return rec
        if customer_id:
            return self.recommend(customer_id)
        raise ValueError("Provide customer_id or decision_id")

    def ai_explain(self, customer_id: str | None, decision_id: str | None) -> dict[str, Any]:
        resp = self._decision_response(customer_id, decision_id)
        res = self.ai.explain(resp)
        return {"customer_id": resp["customer_id"], "decision_id": resp["decision_id"],
                "recommended_action": resp["recommended_action"], "explanation": res.text, "source": res.source,
                "fallback_reason": res.fallback_reason, "validation": res.validation,
                "facts_used": self.ai.fact_sheet(resp)}

    def ai_message(self, customer_id: str | None, decision_id: str | None) -> dict[str, Any]:
        resp = self._decision_response(customer_id, decision_id)
        if resp["recommended_action"] == "NO_CONTACT":
            raise Conflict("The decision is 'no contact': no customer communication is generated")
        s = self.customers.get_state(resp["customer_id"], self.default_as_of)
        issue = None
        if resp["action_type"] == "service":
            cat = service_category(s)
            issue = {"autostrom": "charging", "billing": "billing", "complaint": "complaint"}.get(cat)
        res = self.ai.generate_message(resp, issue)
        msg_id = self.log.add_message(resp["decision_id"], resp["channel"], resp["tonality"], res.source,
                                      res.subject, res.text)
        return {"customer_id": resp["customer_id"], "decision_id": resp["decision_id"], "message_id": msg_id,
                "channel": resp["channel"], "tonality": resp["tonality"], "language": "de",
                "preferred_contact_language": s.profile.get("preferred_contact_language"),
                "subject": res.subject, "body": res.text, "source": res.source, "fallback_reason": res.fallback_reason,
                "validation": res.validation, "approval_status": "pending_approval", "requires_human_approval": True}

    # --------------------------------------------------------------- health
    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "customers_loaded": len(self.ds.customers),
            "products_loaded": len(self.ds.products),
            "events_loaded": len(self.ds.events),
            "snapshot_at": self.ds.snapshot_at.isoformat(sep=" "),
            "default_as_of": self.default_as_of.isoformat(sep=" "),
            "settings_version": self.settings_version,
            "ai": self.ai.status(),
            "data_quality": self.ds.quality_report,
            "acceptance_model": self.acceptance.describe(),
        }
