"""CLV calculation engine — implements the `clv_method` sheet literally.

    CLV  = sum_{t=1..H} (annual_margin - cost_to_serve) * (1 - churn)^(t-1) / (1 + r)^t
    dCLV = p * (CLV_accept - CLV_now) + (1 - p) * (CLV_reject - CLV_now) - contact_cost

* r and H come from value_assumptions (discount_rate, horizon_years).
* sales/upsell: margin += annual_margin_if_bought, churn += churn_effect_if_bought
* one_off (shop): margin added ONCE (undiscounted, purchase happens now) + churn effect
* retention P-EN-02: the 'price guarantee ends' churn driver is removed
  (the catalogue churn effect describes the same thing and is NOT added again)
* service P-SV-01: service churn drivers removed, minus service_resolution_cost_eur.
  cost_to_serve and clv_service_impact_eur are NOT adjusted in addition — that
  would count the service effect twice.
* reject: CLV_now, except a marketing contact during an open complaint or dunning,
  which adds `contact_during_service_case` to churn.
* no_contact: explicit baseline, dCLV = 0 by definition.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.services.churn_model import RETENTION_DRIVERS, SERVICE_DRIVERS, MAX_CHURN

if TYPE_CHECKING:
    from app.services.customer_service import CustomerState

MARKETING_ACTION_TYPES = {"sales", "upsell", "one_off", "retention"}

CHANNEL_COST_PARAM = {
    "newsletter_email": "contact_cost_email_eur",
    "sms": "contact_cost_sms_eur",
    "portal_popup": "contact_cost_popup_eur",
    "app_push": "contact_cost_popup_eur",  # value_assumptions: "Portal/app pop-up"
    "outbound_call": "contact_cost_call_eur",
    "service_email": "contact_cost_email_eur",
    "service_call": "contact_cost_call_eur",
    "none": None,
}


def clv(annual_margin: float, cost_to_serve: float, churn: float, discount_rate: float, horizon: int) -> float:
    net = annual_margin - cost_to_serve
    churn = min(max(churn, 0.0), 1.0)
    return sum(net * (1 - churn) ** (t - 1) / (1 + discount_rate) ** t for t in range(1, horizon + 1))


@dataclass(frozen=True)
class ScenarioParams:
    """Economic assumptions; defaults = value_assumptions. Never touches compliance."""
    discount_rate: float | None = None
    horizon_years: int | None = None
    churn_now_override: float | None = None
    churn_delta: float = 0.0
    contact_cost_overrides: dict[str, float] = field(default_factory=dict)
    service_resolution_cost_eur: float | None = None
    contact_during_service_case: float | None = None

    def resolved(self, A: dict[str, float]) -> dict[str, Any]:
        return {
            "discount_rate": A["discount_rate"] if self.discount_rate is None else self.discount_rate,
            "horizon_years": int(A["horizon_years"] if self.horizon_years is None else self.horizon_years),
            "service_resolution_cost_eur": A["service_resolution_cost_eur"]
            if self.service_resolution_cost_eur is None else self.service_resolution_cost_eur,
            "contact_during_service_case": A["contact_during_service_case"]
            if self.contact_during_service_case is None else self.contact_during_service_case,
        }


@dataclass
class Valuation:
    product_id: str
    action_type: str
    channel: str
    p_accept: float
    contact_cost_eur: float
    churn_now: float
    churn_after_accept: float
    churn_after_reject: float
    clv_now_eur: float
    clv_after_accept_eur: float
    clv_after_reject_eur: float
    expected_dclv_eur: float
    one_off_margin_eur: float = 0.0
    added_annual_margin_eur: float = 0.0
    removed_drivers: list[str] = field(default_factory=list)
    service_case_contact_penalty: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def estimated_clv_after_eur(self) -> float:
        return self.clv_now_eur + self.expected_dclv_eur


class CLVEngine:
    def __init__(self, assumptions: dict[str, float]):
        self.A = assumptions

    def contact_cost(self, channel: str, params: ScenarioParams) -> float:
        if channel in params.contact_cost_overrides:
            return float(params.contact_cost_overrides[channel])
        param = CHANNEL_COST_PARAM.get(channel)
        return float(self.A[param]) if param else 0.0

    def churn_now(self, s: "CustomerState", params: ScenarioParams) -> float:
        base = s.churn_now if params.churn_now_override is None else params.churn_now_override
        return min(max(base + params.churn_delta, 0.0), MAX_CHURN)

    def clv_now(self, s: "CustomerState", params: ScenarioParams) -> float:
        r = params.resolved(self.A)
        return clv(s.annual_margin_eur, s.cost_to_serve_eur, self.churn_now(s, params), r["discount_rate"], r["horizon_years"])

    def value(self, s: "CustomerState", product: dict[str, Any], channel: str, p_accept: float,
              params: ScenarioParams) -> Valuation:
        r = params.resolved(self.A)
        dr, H = r["discount_rate"], r["horizon_years"]
        m, cts = s.annual_margin_eur, s.cost_to_serve_eur
        churn0 = self.churn_now(s, params)
        clv0 = clv(m, cts, churn0, dr, H)
        pid, atype = product["product_id"], product["action_type"]
        effect = float(product.get("churn_effect_if_bought") or 0.0)
        add_margin = float(product.get("annual_margin_if_bought_eur") or 0.0)
        notes: list[str] = []
        removed: list[str] = []
        one_off = 0.0
        added_annual = 0.0

        def remove(codes: set[str]) -> float:
            present = [d for d in s.drivers if d.code in codes]
            removed.extend(d.code for d in present)
            if s.cancellation_pending:
                notes.append("Cancellation pending: churn stays at the documented 0.95 override.")
                return churn0
            return min(max(churn0 - sum(d.increment for d in present), 0.0), MAX_CHURN)

        if atype == "service":
            churn_a = remove(SERVICE_DRIVERS)
            clv_a = clv(m, cts, churn_a, dr, H) - r["service_resolution_cost_eur"]
            notes.append(f"Service resolution cost {r['service_resolution_cost_eur']:.2f} EUR deducted on success.")
        elif atype == "retention":
            churn_a = remove(RETENTION_DRIVERS)
            clv_a = clv(m, cts, churn_a, dr, H)
        elif atype == "one_off":
            churn_a = min(max(churn0 + effect, 0.0), MAX_CHURN)
            one_off = add_margin
            clv_a = clv(m, cts, churn_a, dr, H) + one_off
            notes.append("One-off shop margin counted once, not as an annuity.")
        else:  # sales / upsell: recurring margin
            churn_a = min(max(churn0 + effect, 0.0), MAX_CHURN)
            added_annual = add_margin
            clv_a = clv(m + add_margin, cts, churn_a, dr, H)

        penalty = atype in MARKETING_ACTION_TYPES and (s.open_complaint or (s.max_dunning_level or 0) >= 1)
        if penalty:
            churn_r = min(churn0 + r["contact_during_service_case"], MAX_CHURN)
            clv_r = clv(m, cts, churn_r, dr, H)
            notes.append("Sales contact during open complaint/dunning raises churn on rejection.")
        else:
            churn_r, clv_r = churn0, clv0

        cost = self.contact_cost(channel, params)
        dclv = p_accept * (clv_a - clv0) + (1 - p_accept) * (clv_r - clv0) - cost
        return Valuation(pid, atype, channel, p_accept, cost, churn0, churn_a, churn_r, clv0, clv_a, clv_r, dclv,
                         one_off, added_annual, removed, penalty, notes)
