"""Churn drivers, reproduced from the documented value model.

`customer_value.churn_prob_12m` is the authoritative churn at the snapshot. The
value model behind it (verified against all 726 customers with active lines) is

    churn = mean(base churn of active contracts) * max(0.8^(lines-1), 0.5)
            + sum(additive driver increments from value_assumptions)
    churn = 0.95 if a cancellation was received

We do not re-implement the structural base (24 customers without active lines
use a base that is not documented). Instead:

    structural_churn = churn_prob_12m(snapshot) - sum(snapshot driver increments)

and the live churn is ``structural_churn + sum(live driver increments)``. This
keeps the dataset value exactly at the snapshot, lets events change drivers,
and lets actions remove specific drivers as required by `clv_method`.
"""
from __future__ import annotations

from dataclasses import dataclass

# driver code -> (value_assumptions parameter, human label, category)
# category "service" = removed by the service-resolution action P-SV-01
# (clv_method: open complaint, low CSAT, failed charges, dunning).
DRIVER_DEFS: dict[str, tuple[str, str, str]] = {
    "price_guarantee_ends_90d": ("price_guarantee_ends_90d", "Price guarantee ends within 90 days", "retention"),
    "open_complaint": ("open_complaint", "Open complaint", "service"),
    "tickets_12m_ge2": ("tickets_12m_ge2", "Two or more tickets in 12 months", "history"),
    "csat_le2": ("csat_le2", "Last CSAT rating 1 or 2", "service"),
    "dunning_ge2": ("dunning_ge2", "Dunning level 2 or higher", "service"),
    "failed_charges_30d_ge3": ("failed_charges_30d_ge3", "Three or more failed charging sessions in 30 days", "service"),
    "hems_user": ("hems_user", "HEMS user (churns less)", "structural"),
}
SERVICE_DRIVERS = {k for k, v in DRIVER_DEFS.items() if v[2] == "service"}
RETENTION_DRIVERS = {"price_guarantee_ends_90d"}
MAX_CHURN = 0.99


@dataclass(frozen=True)
class ChurnDriver:
    code: str
    label: str
    category: str
    increment: float
    evidence: str


@dataclass(frozen=True)
class ChurnFacts:
    price_guarantee_ends_90d: bool
    open_complaint: bool
    tickets_12m: int
    last_csat: float | None
    max_dunning_level: int | None
    failed_charges_30d: int
    hems_user: bool
    cancellation_pending: bool
    price_guarantee_until: str | None = None


def drivers_from_facts(f: ChurnFacts, assumptions: dict[str, float]) -> list[ChurnDriver]:
    out: list[ChurnDriver] = []

    def add(code: str, evidence: str) -> None:
        param, label, cat = DRIVER_DEFS[code]
        out.append(ChurnDriver(code, label, cat, float(assumptions[param]), evidence))

    if f.price_guarantee_ends_90d:
        add("price_guarantee_ends_90d", f"price_guarantee_until={f.price_guarantee_until}")
    if f.open_complaint:
        add("open_complaint", "open ticket with category 'complaint'")
    if f.tickets_12m >= 2:
        add("tickets_12m_ge2", f"{f.tickets_12m} tickets in last 12 months")
    if f.last_csat is not None and f.last_csat <= 2:
        add("csat_le2", f"last CSAT = {f.last_csat:g}")
    if f.max_dunning_level is not None and f.max_dunning_level >= 2:
        add("dunning_ge2", f"dunning level {f.max_dunning_level}")
    if f.failed_charges_30d >= 3:
        add("failed_charges_30d_ge3", f"{f.failed_charges_30d} failed charging sessions in 30 days")
    if f.hems_user:
        add("hems_user", "HEMS device registered")
    return out


def churn_from(structural: float | None, drivers: list[ChurnDriver], cancellation_pending: bool,
               assumptions: dict[str, float], exclude: set[str] | None = None,
               extra_increment: float = 0.0) -> float:
    if cancellation_pending:
        return float(assumptions["cancellation_pending"])
    base = structural or 0.0
    total = base + sum(d.increment for d in drivers if not exclude or d.code not in exclude) + extra_increment
    return min(max(total, 0.0), MAX_CHURN)
