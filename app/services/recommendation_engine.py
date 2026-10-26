"""Lighty recommendation engine: eligibility first, then CLV ranking.

Decision rule
-------------
1. Build every (product x channel) candidate and run the eligibility engine.
2. Value every candidate with the CLV engine (blocked ones too, for the
   illustrative non-executable comparison).
3. Per product keep the best channel. Rank executable products by expected dCLV.
4. Recommend the top executable action if its dCLV beats no-contact (0) by more
   than ``min_expected_dclv_eur``. Otherwise recommend no contact — unless the
   customer has an open complaint, in which case the required service workflow
   (P-SV-01) takes precedence and is flagged as such.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from app.models.runtime_settings import RuntimeSettings
from app.services.acceptance_model import AcceptanceEstimate, AcceptanceModel
from app.services.churn_model import SERVICE_DRIVERS
from app.services.clv_engine import CLVEngine, MARKETING_ACTION_TYPES, ScenarioParams, Valuation
from app.services.customer_service import CustomerService, CustomerState
from app.services.eligibility_engine import CandidateEligibility, EligibilityEngine

ENGINE_VERSION = "lighty-1.1.0"
NO_CONTACT = "NO_CONTACT"


@dataclass(frozen=True)
class POverrides:
    """Simulation-only overrides of acceptance probabilities."""
    by_product: dict[str, float] = field(default_factory=dict)
    multiplier: float = 1.0


@dataclass
class ScoredCandidate:
    eligibility: CandidateEligibility
    acceptance: AcceptanceEstimate
    p_used: float
    p_overridden: bool
    valuation: Valuation
    priority: int

    @property
    def product_id(self) -> str:
        return self.eligibility.product_id

    @property
    def channel(self) -> str:
        return self.eligibility.channel

    @property
    def dclv(self) -> float:
        return self.valuation.expected_dclv_eur


@dataclass
class Decision:
    customer_id: str
    decision_id: str
    as_of: str
    state: CustomerState
    recommended: ScoredCandidate | None  # None = no contact
    required_service_workflow: bool
    ranked: list[ScoredCandidate]  # executable, best channel per product, sorted
    blocked: list[ScoredCandidate]  # products without any executable channel (best illustrative channel)
    all_candidates: list[ScoredCandidate]
    clv_now_eur: float
    reason: str
    params: ScenarioParams
    settings_snapshot: dict[str, Any]

    @property
    def expected_dclv(self) -> float:
        return self.recommended.dclv if self.recommended else 0.0

    @property
    def recommended_product(self) -> str:
        return self.recommended.product_id if self.recommended else NO_CONTACT


def _round(v: float, n: int = 2) -> float:
    return float(round(v, n))


def service_category(s: CustomerState) -> str:
    if s.open_complaint:
        return "complaint"
    if s.signals["failed_charges_30d"] > 0:
        return "autostrom"
    if (s.max_dunning_level or 0) >= 1:
        return "billing"
    if s.open_tickets:
        return s.open_tickets[-1].get("category") or "_all"
    return "_all"


class RecommendationEngine:
    def __init__(self, customers: CustomerService, eligibility: EligibilityEngine, clv_engine: CLVEngine,
                 acceptance: AcceptanceModel, products: dict[str, dict[str, Any]]):
        self.customers = customers
        self.eligibility = eligibility
        self.clv = clv_engine
        self.acceptance = acceptance
        self.products = products

    # ------------------------------------------------------------------ core
    def _p(self, s: CustomerState, cand: CandidateEligibility) -> AcceptanceEstimate:
        prod = self.products[cand.product_id]
        if prod["action_type"] == "service":
            return self.acceptance.service_resolution(service_category(s))
        return self.acceptance.offer(cand.product_id, cand.channel, s.tonality.value)

    def score(self, s: CustomerState, settings: RuntimeSettings, params: ScenarioParams,
              p_over: POverrides | None = None) -> list[ScoredCandidate]:
        p_over = p_over or POverrides()
        out = []
        for cand in self.eligibility.candidates(s, settings):
            est = self._p(s, cand)
            p = est.p
            overridden = False
            if cand.product_id in p_over.by_product:
                p, overridden = p_over.by_product[cand.product_id], True
            elif p_over.multiplier != 1.0:
                p, overridden = p * p_over.multiplier, True
            p = min(max(p, 0.0), 1.0)
            val = self.clv.value(s, self.products[cand.product_id], cand.channel, p, params)
            prio = settings.action_priorities.get(cand.product_id)
            out.append(ScoredCandidate(cand, est, p, overridden, val, prio.priority if prio else 0))
        return out

    @staticmethod
    def _sort_key(c: ScoredCandidate):
        return (-round(c.dclv, 6), -c.priority, c.product_id, c.channel)

    def decide(self, customer_id: str, as_of, settings: RuntimeSettings,
               params: ScenarioParams | None = None, p_over: POverrides | None = None) -> Decision:
        params = params or ScenarioParams()
        s = self.customers.get_state(customer_id, as_of)
        scored = self.score(s, settings, params, p_over)

        best_exec: dict[str, ScoredCandidate] = {}
        best_any: dict[str, ScoredCandidate] = {}
        for c in sorted(scored, key=self._sort_key):
            best_any.setdefault(c.product_id, c)
            if c.eligibility.allowed:
                best_exec.setdefault(c.product_id, c)
        ranked = sorted(best_exec.values(), key=self._sort_key)
        blocked = sorted([c for pid, c in best_any.items() if pid not in best_exec], key=self._sort_key)

        threshold = settings.simulation.min_expected_dclv_eur
        top = ranked[0] if ranked and ranked[0].dclv > threshold else None
        required = False
        if top is None and s.open_complaint and "P-SV-01" in best_exec:
            top, required = best_exec["P-SV-01"], True

        clv_now = self.clv.clv_now(s, params)
        settings_snapshot = settings.model_dump()
        decision_id = self.decision_id(customer_id, s.as_of.isoformat(), settings_snapshot, params, p_over)
        d = Decision(customer_id, decision_id, s.as_of.isoformat(sep=" "), s, top, required, ranked, blocked,
                     scored, clv_now, "", params, settings_snapshot)
        d.reason = self.explain(d)
        return d

    @staticmethod
    def decision_id(customer_id: str, as_of: str, settings: dict, params: ScenarioParams,
                    p_over: POverrides | None) -> str:
        blob = json.dumps({"c": customer_id, "t": as_of, "s": settings, "p": params.__dict__,
                           "o": (p_over or POverrides()).__dict__, "v": ENGINE_VERSION},
                          sort_keys=True, default=str)
        return "DEC-" + hashlib.sha256(blob.encode()).hexdigest()[:16]

    # ------------------------------------------------------------ reasoning
    def explain(self, d: Decision) -> str:
        s = d.state
        parts: list[str] = []
        if d.recommended is None:
            if d.ranked:
                best = d.ranked[0]
                parts.append(f"No contact: the best permitted action ({best.product_id} via {best.channel}) has an "
                             f"expected dCLV of {best.dclv:+.2f} EUR, which does not beat doing nothing (0.00 EUR).")
            else:
                parts.append("No contact: no action is permitted for this customer right now.")
        else:
            r = d.recommended
            v = r.valuation
            name = self.products[r.product_id]["product_name"]
            if r.valuation.action_type == "service":
                drivers = [dr.label for dr in s.drivers if dr.code in SERVICE_DRIVERS]
                parts.append(f"Resolve the service issue first ({name} via {r.channel}).")
                if drivers:
                    parts.append(f"Resolving removes the service churn drivers ({', '.join(drivers)}), lowering churn "
                                 f"from {v.churn_now:.1%} to {v.churn_after_accept:.1%} if successful "
                                 f"(estimated success probability {r.p_used:.0%}).")
                if d.required_service_workflow:
                    parts.append("The open complaint is a required service workflow, so it takes precedence even "
                                 f"though the expected dCLV is {r.dclv:+.2f} EUR.")
                else:
                    parts.append(f"Expected dCLV {r.dclv:+.2f} EUR versus no contact, after the "
                                 f"{v.contact_cost_eur:.2f} EUR contact cost and the resolution cost.")
            else:
                if r.eligibility.process == "customer_inquiry_reply":
                    parts.append("The customer asked for a tariff offer (open tariff inquiry), so the reply is "
                                 "handled in the service process, not as unsolicited marketing.")
                parts.append(f"Offer {name} via {r.channel}: expected dCLV {r.dclv:+.2f} EUR versus no contact "
                             f"(estimated acceptance {r.p_used:.1%}).")
                if v.added_annual_margin_eur:
                    parts.append(f"Adds {v.added_annual_margin_eur:.0f} EUR annual margin if accepted.")
                if v.one_off_margin_eur:
                    parts.append(f"One-off margin of {v.one_off_margin_eur:.0f} EUR if bought.")
                if v.removed_drivers:
                    parts.append(f"Removes churn driver(s): {', '.join(v.removed_drivers)}.")
            if len(d.ranked) > 1:
                alt = next((c for c in d.ranked if c.product_id != r.product_id), None)
                if alt:
                    parts.append(f"Next best permitted alternative: {alt.product_id} ({alt.dclv:+.2f} EUR).")
        sales_blocks = sorted({code for c in d.blocked for code in c.eligibility.exclusion_codes
                               if code.endswith("BLOCKS_MARKETING") or code.startswith(("PROFILING", "CONTACT_"))})
        if sales_blocks:
            parts.append("Marketing restrictions in force: " + ", ".join(sales_blocks) + ".")
        return " ".join(parts)

    # ----------------------------------------------------------- baselines
    def baseline(self, d: Decision, policy: str) -> ScoredCandidate | None:
        """Conventional marketing prioritisation.

        ``conventional_sales_first``: pick the sales/upsell/one-off offer with the highest
        expected first-year margin (p_accept x margin) among products the customer does not
        hold and whose target signal fits, on any channel with the channel consent. It
        ignores service state, profiling consent and contact frequency — like a
        campaign-driven engine — and is then valued with the full CLV method.
        ``no_contact``: the baseline is doing nothing.
        """
        if policy == "no_contact":
            return None
        best: tuple[float, ScoredCandidate] | None = None
        for c in d.all_candidates:
            prod = self.products[c.product_id]
            if prod["action_type"] not in MARKETING_ACTION_TYPES - {"retention"}:
                continue
            checks = {k.check: k for k in c.eligibility.checks}
            consent_ok = all(k.passed for k in c.eligibility.checks if k.check.startswith(("consent_", "channel_available")))
            if not (checks["not_already_held"].passed and checks["target_prerequisite"].passed and consent_ok):
                continue
            score = c.p_used * float(prod.get("annual_margin_if_bought_eur") or 0)
            if best is None or score > best[0] + 1e-12 or (abs(score - best[0]) < 1e-12 and c.product_id < best[1].product_id):
                best = (score, c)
        return best[1] if best else None

    # -------------------------------------------------------- serialisation
    def candidate_dict(self, c: ScoredCandidate, executable: bool) -> dict[str, Any]:
        v = c.valuation
        prod = self.products[c.product_id]
        return {
            "product_id": c.product_id,
            "product_name": prod["product_name"],
            "action_type": v.action_type,
            "business_line": prod["business_line"],
            "channel": c.channel,
            "process": c.eligibility.process,
            "executable": executable,
            "acceptance_probability": _round(c.p_used, 4),
            "acceptance_source": "simulated_override" if c.p_overridden else c.acceptance.source,
            "acceptance_observations": c.acceptance.deliveries,
            "control_group_rate": None if c.acceptance.control_rate is None else _round(c.acceptance.control_rate, 4),
            "contact_cost_eur": _round(v.contact_cost_eur, 2),
            "churn_now": _round(v.churn_now, 4),
            "churn_after_accept": _round(v.churn_after_accept, 4),
            "churn_after_reject": _round(v.churn_after_reject, 4),
            "clv_after_accept_eur": _round(v.clv_after_accept_eur),
            "clv_after_reject_eur": _round(v.clv_after_reject_eur),
            "expected_dclv_eur": _round(v.expected_dclv_eur),
            "estimated_clv_after_eur": _round(v.estimated_clv_after_eur),
            "added_annual_margin_eur": _round(v.added_annual_margin_eur),
            "one_off_margin_eur": _round(v.one_off_margin_eur),
            "removed_churn_drivers": v.removed_drivers,
            "service_case_contact_penalty": v.service_case_contact_penalty,
            "exclusion_reasons": c.eligibility.exclusion_codes,
            "notes": v.notes,
            "value_label": "estimated",
        }

    def channel_tonality(self, d: Decision) -> tuple[str, str]:
        if d.recommended is None:
            return "none", d.state.tonality.value
        return d.recommended.channel, d.state.tonality.value

    def to_response(self, d: Decision, approval_status: str) -> dict[str, Any]:
        s = d.state
        r = d.recommended
        channel, tone = self.channel_tonality(d)
        alternatives = [self.candidate_dict(c, True) for c in d.ranked if not r or c.product_id != r.product_id]
        alternatives.append(self.no_contact_dict(d))
        alternatives.sort(key=lambda a: -a["expected_dclv_eur"])
        rec_checks = r.eligibility.checks if r else []
        return {
            "customer_id": d.customer_id,
            "decision_id": d.decision_id,
            "as_of": d.as_of,
            "recommended_action": r.product_id if r else NO_CONTACT,
            "recommended_action_name": self.products[r.product_id]["product_name"] if r else "No contact",
            "action_type": r.valuation.action_type if r else "no_contact",
            "product_id": r.product_id if r else None,
            "channel": channel,
            "process": r.eligibility.process if r else "none",
            "tonality": tone,
            "tonality_source": s.tonality.source,
            "current_clv_eur": _round(d.clv_now_eur),
            "expected_dclv_eur": _round(d.expected_dclv),
            "estimated_clv_after_eur": _round(d.clv_now_eur + d.expected_dclv),
            "acceptance_probability": _round(r.p_used, 4) if r else None,
            "required_service_workflow": d.required_service_workflow,
            "requires_human_approval": r is not None,
            "approval_status": approval_status,
            "reason": d.reason,
            "alternatives": alternatives,
            "blocked_actions": [self.candidate_dict(c, False) for c in d.blocked],
            "eligibility_checks": [c.as_dict() for c in rec_checks],
            "value_labels": {
                "current_clv_eur": "estimated (clv_method on live churn)",
                "expected_dclv_eur": "estimated (model-based, not causal)",
                "acceptance_probability": "estimated (observational history, smoothed)",
            },
            "engine_version": ENGINE_VERSION,
        }

    def no_contact_dict(self, d: Decision) -> dict[str, Any]:
        return {
            "product_id": NO_CONTACT, "product_name": "No contact", "action_type": "no_contact",
            "business_line": None, "channel": "none", "process": "none", "executable": True, "acceptance_probability": None,
            "acceptance_source": "baseline", "acceptance_observations": 0, "control_group_rate": None,
            "contact_cost_eur": 0.0, "churn_now": _round(d.state.churn_now, 4),
            "churn_after_accept": _round(d.state.churn_now, 4), "churn_after_reject": _round(d.state.churn_now, 4),
            "clv_after_accept_eur": _round(d.clv_now_eur), "clv_after_reject_eur": _round(d.clv_now_eur),
            "expected_dclv_eur": 0.0, "estimated_clv_after_eur": _round(d.clv_now_eur),
            "added_annual_margin_eur": 0.0, "one_off_margin_eur": 0.0, "removed_churn_drivers": [],
            "service_case_contact_penalty": False, "exclusion_reasons": [],
            "notes": ["Explicit baseline: zero incremental intervention value."], "value_label": "baseline",
        }
