"""Eligibility and compliance engine.

Runs BEFORE any economic ranking. A candidate (product x channel) is
executable only if every check passes. Simulation parameters never reach this
module, so they cannot override it.

Hard rules implemented
----------------------
1  Marketing channel requires its consent        -> CONSENT_*
2  Withdrawn consent is effective immediately     -> consent state is replayed by occurred_at
3  Personalised NBA requires profiling consent    -> PROFILING_CONSENT_MISSING
4  Open complaint / dunning / pending cancellation block marketing
                                                  -> *_BLOCKS_MARKETING
5  Contact-frequency limits                       -> CONTACT_FREQUENCY_LIMIT / CONTACT_MIN_GAP
6  No duplicates / ineligible products            -> PRODUCT_ALREADY_HELD / PREREQUISITE_MISSING
7  No personalised prices or urgency              -> the engine never outputs prices; messages are validated
8  No payment data for creditworthiness           -> payment_method is dropped at load time
9  External communication needs human approval    -> every executable action starts "pending_approval"
10 Service and marketing are separate             -> service channels need no marketing consent but
                                                     only carry service content (P-SV-01)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable

from app.models.runtime_settings import RuntimeSettings
from app.services.churn_model import SERVICE_DRIVERS
from app.services.customer_service import CustomerState

MARKETING_CHANNELS: dict[str, dict[str, Any]] = {
    "newsletter_email": {"consent": "newsletter_email", "requires": None},
    "portal_popup": {"consent": "portal_app_personalisation", "requires": "portal_account"},
    "app_push": {"consent": "portal_app_personalisation", "requires": "app_installed"},
    "sms": {"consent": "marketing_sms", "requires": None},
    "outbound_call": {"consent": "marketing_phone", "requires": None},
}
SERVICE_CHANNELS = ["service_call", "service_email"]
PROFILING_CONSENT = "profiling_analytics"
INQUIRY_REPLY_PRODUCTS = {"P-EN-02"}  # retention offer in reply to the customer's own tariff inquiry


@dataclass
class Check:
    check: str
    passed: bool
    code: str | None = None
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"check": self.check, "passed": self.passed, "code": self.code, "detail": self.detail}


@dataclass
class CandidateEligibility:
    product_id: str
    channel: str
    checks: list[Check] = field(default_factory=list)
    process: str = "marketing"  # marketing | service | customer_inquiry_reply

    @property
    def allowed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def exclusion_codes(self) -> list[str]:
        return [c.code for c in self.checks if not c.passed and c.code]


Rule = Callable[[CustomerState], tuple[bool, str]]


def _prereq_rules() -> dict[str, Rule]:
    """Target-signal prerequisites from product_catalog.typical_target_signal.

    Where the catalogue states that the signal is unknown in the data
    (gas heating, balcony, internet holdings) we do not treat unknown as negative.
    """
    def has_energy(s):
        return bool(s.signals["has_electricity"] or s.signals["has_gas"])

    return {
        "P-EN-01": lambda s: (True, "customer without electricity contract"),
        "P-EN-02": lambda s: (s.churn_facts.price_guarantee_ends_90d,
                              f"price guarantee ends {s.churn_facts.price_guarantee_until}"
                              if s.churn_facts.price_guarantee_ends_90d else "no price guarantee ending within 90 days"),
        "P-EN-03": lambda s: (s.signals["has_electricity"] and (s.signals["heat_pump"] or s.signals["gas_meter_deregistered"]),
                              "heat pump signal or gas meter deregistration (new heating system)"),
        "P-EN-04": lambda s: (s.signals["has_electricity"] and not s.signals["gas_meter_deregistered"],
                              "electricity customer; gas heating is unknown in data (not treated as negative)"),
        "P-EN-05": lambda s: (s.signals["smart_meter"] and (s.signals["hems_gateway"] or s.signals["ev_driver"] or s.signals["heat_pump"]),
                              "requires smart meter (iMSys) plus HEMS, EV or heat pump"),
        "P-MO-01": lambda s: (has_energy(s), "energy customer without mobile"),
        "P-MO-02": lambda s: ((s.signals["mobile_data_limit_months_3m"] or 0) >= 2,
                              f"data limit reached {s.signals['mobile_data_limit_months_3m']} of 3 months (needs >= 2)"),
        "P-MO-03": lambda s: (bool(s.signals.get("mobile_sims_below_household")), "household_size > SIMs on contract"),
        "P-IN-01": lambda s: (has_energy(s) or "mobile" in s.business_lines,
                              "energy/mobile customer; internet holdings unknown in data"),
        "P-SL-01": lambda s: (s.signals["pv"] or s.signals["heat_pump"] or s.signals["ev_driver"],
                              "PV, heat pump or EV signal without HEMS"),
        "P-SL-02": lambda s: (s.signals["hems_gateway"] and s.signals["home_battery"], "HEMS + home battery"),
        "P-SL-03": lambda s: (s.signals["hems_gateway"] and (s.signals["wallbox_device"] or s.signals["ev_driver"]),
                              "HEMS + EV/wallbox"),
        "P-SH-01": lambda s: (not s.signals["pv"], "no PV; balcony unknown in data (not treated as negative)"),
        "P-SH-02": lambda s: (s.signals["ev_driver"], "EV driver (charging signals)"),
        "P-SH-03": lambda s: (s.signals["has_gas"] and not s.signals["gas_meter_deregistered"], "active gas heating"),
        "P-SH-04": lambda s: (bool(s.profile.get("portal_account") or s.profile.get("app_installed")),
                              "digital customer (portal or app)"),
        "P-AS-01": lambda s: (s.signals["ev_driver"], "EV driver signal (wallbox / EV charging telemetry)"),
    }


PREREQS = _prereq_rules()


class EligibilityEngine:
    def __init__(self, products: dict[str, dict[str, Any]]):
        self.products = products

    # ------------------------------------------------------------- helpers
    def marketing_contacts_window(self, s: CustomerState) -> tuple[int, float | None]:
        delivered = [c for c in s.marketing_contacts
                     if c.get("delivery_status") == "delivered" and not c.get("control_group")]
        n30 = sum(1 for c in delivered if c["decided_at"] > s.as_of - timedelta(days=30))
        last = max((c["decided_at"] for c in delivered), default=None)
        days_since = (s.as_of - last).total_seconds() / 86400 if last else None
        return n30, days_since

    def service_channel(self, s: CustomerState, inquiry: bool = False) -> str:
        if inquiry:
            t = self.open_tariff_inquiry(s)
            return "service_call" if t and t.get("channel") == "phone" else "service_email"
        latest_open = sorted(s.open_tickets, key=lambda t: t.get("created_at"))[-1:] if s.open_tickets else []
        if s.signals.get("callback_requested") or (latest_open and latest_open[0].get("channel") == "phone"):
            return "service_call"
        return "service_email"

    # -------------------------------------------------------- product checks
    @staticmethod
    def open_tariff_inquiry(s: CustomerState) -> dict[str, Any] | None:
        inquiries = [t for t in s.open_tickets if t.get("category") == "tariff"]
        return sorted(inquiries, key=lambda t: t.get("created_at"))[-1] if inquiries else None

    def product_checks(self, s: CustomerState, product_id: str, settings: RuntimeSettings,
                       inquiry_reply: bool = False) -> list[Check]:
        prod = self.products[product_id]
        atype = prod["action_type"]
        checks: list[Check] = []
        prio = settings.action_priorities.get(product_id)
        checks.append(Check("action_enabled", prio is None or prio.enabled,
                            None if prio is None or prio.enabled else "ACTION_DISABLED_BY_SETTINGS",
                            "enabled" if prio is None or prio.enabled else "disabled by marketing settings"))

        if atype == "service":
            service_issue = bool(s.open_tickets or (s.max_dunning_level or 0) >= 1
                                 or s.signals["failed_charges_30d"] > 0
                                 or any(d.code in SERVICE_DRIVERS for d in s.drivers))
            checks.append(Check("service_issue_present", service_issue, None if service_issue else "NO_SERVICE_ISSUE",
                                "open ticket, dunning, failed charging or service churn driver"
                                if service_issue else "nothing to resolve"))
            checks.append(Check("service_legal_basis", True, None,
                                "service contact under the existing contract; no marketing content allowed"))
            return checks

        held = s.holdings.get(product_id)
        checks.append(Check("not_already_held", held is not True, "PRODUCT_ALREADY_HELD" if held else None,
                            "already held" if held else ("holding unknown in data" if held is None else "not held")))
        ok, detail = PREREQS[product_id](s)
        checks.append(Check("target_prerequisite", bool(ok), None if ok else "PREREQUISITE_MISSING", detail))

        if inquiry_reply:
            # The customer asked for a tariff offer themselves (open 'tariff' ticket). Answering that request
            # is part of handling the customer's inquiry, not unsolicited advertising, so marketing consent,
            # profiling consent and contact-frequency limits do not apply. Service-state blocks still apply.
            inquiry = self.open_tariff_inquiry(s)
            checks.append(Check("customer_initiated_request", inquiry is not None,
                                None if inquiry else "NO_CUSTOMER_REQUEST",
                                f"open tariff inquiry {inquiry['ticket_id']} via {inquiry.get('channel')}"
                                if inquiry else "no open tariff inquiry from the customer"))
            checks += self._service_state_checks(s)
            return checks

        # Rule 3 — personalised selection requires profiling consent
        prof = s.consents[PROFILING_CONSENT]
        checks.append(Check("profiling_consent", prof.granted, None if prof.granted else f"PROFILING_CONSENT_{prof.status.upper()}",
                            f"profiling_analytics={prof.status} ({prof.effective_reason})"))
        # Rule 4 — service states block marketing
        checks += self._service_state_checks(s)
        # Rule 5 — frequency
        n30, days_since = self.marketing_contacts_window(s)
        pol = settings.contact_policy
        checks.append(Check("contact_frequency_30d", n30 < pol.max_marketing_contacts_30d,
                            None if n30 < pol.max_marketing_contacts_30d else "CONTACT_FREQUENCY_LIMIT",
                            f"{n30} marketing contacts in 30 days (limit {pol.max_marketing_contacts_30d})"))
        gap_ok = days_since is None or days_since >= pol.min_days_between_marketing_contacts
        checks.append(Check("contact_min_gap", gap_ok, None if gap_ok else "CONTACT_MIN_GAP",
                            "no previous marketing contact" if days_since is None else
                            f"{days_since:.1f} days since last contact (min {pol.min_days_between_marketing_contacts})"))
        return checks

    @staticmethod
    def _service_state_checks(s: CustomerState) -> list[Check]:
        checks: list[Check] = []
        checks.append(Check("no_open_complaint", not s.open_complaint,
                            "OPEN_COMPLAINT_BLOCKS_MARKETING" if s.open_complaint else None,
                            "open complaint ticket" if s.open_complaint else "no open complaint"))
        dun = s.max_dunning_level or 0
        checks.append(Check("no_dunning", dun == 0, "DUNNING_BLOCKS_MARKETING" if dun else None,
                            f"dunning level {dun}" if s.max_dunning_level is not None else "dunning unknown (no energy contract)"))
        checks.append(Check("no_pending_cancellation", not s.cancellation_pending,
                            "CANCELLATION_PENDING_BLOCKS_MARKETING" if s.cancellation_pending else None,
                            "cancellation received" if s.cancellation_pending else "no cancellation"))
        return checks

    # -------------------------------------------------------- channel checks
    def channel_checks(self, s: CustomerState, product_id: str, channel: str) -> list[Check]:
        if channel in SERVICE_CHANNELS:
            return [Check("service_channel", True, None, f"{channel}: service process, no marketing consent required")]
        spec = MARKETING_CHANNELS[channel]
        cons = s.consents[spec["consent"]]
        checks = []
        if cons.granted:
            checks.append(Check(f"consent_{spec['consent']}", True, None, f"granted ({cons.effective_reason})"))
        else:
            code = f"CONSENT_{cons.status.upper()}"
            if cons.status == "granted" and spec["consent"] == "newsletter_email":
                code = "CONSENT_DOI_MISSING"
            checks.append(Check(f"consent_{spec['consent']}", False, code,
                                f"{spec['consent']}={cons.status} ({cons.effective_reason})"))
        if spec["requires"]:
            ok = bool(s.profile.get(spec["requires"]))
            checks.append(Check(f"channel_available_{spec['requires']}", ok, None if ok else "CHANNEL_NOT_AVAILABLE",
                                f"{spec['requires']}={s.profile.get(spec['requires'])}"))
        return checks

    def candidates(self, s: CustomerState, settings: RuntimeSettings) -> list[CandidateEligibility]:
        out: list[CandidateEligibility] = []
        for pid, prod in self.products.items():
            pchecks = self.product_checks(s, pid, settings)
            channels = [self.service_channel(s)] if prod["action_type"] == "service" else list(MARKETING_CHANNELS)
            process = "service" if prod["action_type"] == "service" else "marketing"
            for ch in channels:
                out.append(CandidateEligibility(pid, ch, pchecks + self.channel_checks(s, pid, ch), process))
            if pid in INQUIRY_REPLY_PRODUCTS and self.open_tariff_inquiry(s) is not None:
                ch = self.service_channel(s, inquiry=True)
                out.append(CandidateEligibility(pid, ch, self.product_checks(s, pid, settings, inquiry_reply=True)
                                                + self.channel_checks(s, pid, ch), process="customer_inquiry_reply"))
        return out
