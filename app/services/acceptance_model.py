"""Acceptance probability estimates (p_accept).

Sales/upsell/retention/one-off offers
-------------------------------------
Observed 14-day conversion rates from `nba_action_history`, hierarchical
Bayesian shrinkage (Beta prior as pseudo-counts):

    global -> offer -> offer x channel -> offer x channel x tonality

    p_level = (conversions + k * p_parent) / (deliveries + k)

Only delivered, non-control actions are used. Actions that the legacy engine
sent without checking consent are excluded by default (we do not learn from
contacts that should not have happened). Offers without any history fall back
to the global rate and are flagged as such.

These are OBSERVATIONAL rates, not causal effects. The control group gives a
naive comparison; "net_of_control" mode uses max(0, treated - control) as a
conservative alternative. Both are labelled "estimated".

Service resolution (P-SV-01)
----------------------------
There is no history for proactive resolution. We use an observational proxy
from `service_interactions`: the share of closed tickets of the relevant
category that were resolved without escalation and without a repeat contact,
smoothed toward the all-category rate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

ESCALATION_CODES = {"escalated", "escalated_to_cpo"}


@dataclass(frozen=True)
class AcceptanceEstimate:
    p: float
    source: str
    deliveries: int
    conversions: int
    control_rate: float | None
    label: str = "estimated"


class AcceptanceModel:
    def __init__(self, history: pd.DataFrame, tickets: pd.DataFrame, pseudo_count: float = 20.0,
                 exclude_unconsented: bool = True, mode: str = "observed_conversion"):
        self.k = float(pseudo_count)
        self.mode = mode
        self.exclude_unconsented = exclude_unconsented
        h = history.copy()
        treated = h[(~h["control_group"].astype(bool)) & (h["delivery_status"] == "delivered")]
        if exclude_unconsented:
            treated = treated[treated["consent_checked"].astype(bool)]
        control = h[h["control_group"].astype(bool)]
        self.excluded_unconsented = int(((~h["control_group"].astype(bool)) & (~h["consent_checked"].astype(bool))).sum())
        conv = treated["converted_within_14d"].astype(bool)
        self.global_n = len(treated)
        self.global_c = int(conv.sum())
        self.global_p = self.global_c / self.global_n if self.global_n else 0.0
        t = treated.assign(conv=conv.astype(int))
        self.by_offer = t.groupby("offer_id")["conv"].agg(["sum", "count"]).to_dict("index")
        self.by_oc = t.groupby(["offer_id", "channel"])["conv"].agg(["sum", "count"]).to_dict("index")
        self.by_oct = t.groupby(["offer_id", "channel", "tonality"])["conv"].agg(["sum", "count"]).to_dict("index")
        c = control.assign(conv=control["converted_within_14d"].astype(bool).astype(int))
        self.control_global_p = c["conv"].mean() if len(c) else 0.0
        self.control_by_offer = c.groupby("offer_id")["conv"].agg(["sum", "count"]).to_dict("index")
        self._service = self._service_rates(tickets)

    # ---------------------------------------------------------------- offers
    def _shrink(self, stats: dict[str, Any] | None, prior: float) -> float:
        if not stats:
            return prior
        return (stats["sum"] + self.k * prior) / (stats["count"] + self.k)

    def control_rate(self, offer_id: str) -> float | None:
        st = self.control_by_offer.get(offer_id)
        if not st:
            return None
        return (st["sum"] + self.k * self.control_global_p) / (st["count"] + self.k)

    def offer(self, offer_id: str, channel: str, tonality: str) -> AcceptanceEstimate:
        if offer_id not in self.by_offer:
            return AcceptanceEstimate(self.global_p, "fallback_global_rate_no_offer_history", 0, 0, None)
        p_offer = self._shrink(self.by_offer[offer_id], self.global_p)
        st_oc = self.by_oc.get((offer_id, channel))
        p_oc = self._shrink(st_oc, p_offer)
        st = self.by_oct.get((offer_id, channel, tonality))
        p = self._shrink(st, p_oc)
        level = "offer_channel_tonality" if st else ("offer_channel" if st_oc else "offer")
        n = (st or st_oc or self.by_offer[offer_id])["count"]
        conv = (st or st_oc or self.by_offer[offer_id])["sum"]
        ctrl = self.control_rate(offer_id)
        if self.mode == "net_of_control" and ctrl is not None:
            return AcceptanceEstimate(max(0.0, p - ctrl), f"net_of_control_{level}", int(n), int(conv), ctrl)
        return AcceptanceEstimate(p, f"history_smoothed_{level}", int(n), int(conv), ctrl)

    # --------------------------------------------------------------- service
    def _service_rates(self, tickets: pd.DataFrame) -> dict[str, tuple[float, int]]:
        repeated = set(tickets["repeat_of_ticket_id"].dropna()) if "repeat_of_ticket_id" in tickets else set()
        closed = tickets[tickets["status"] == "closed"]
        ok = (~closed["resolution_code"].isin(ESCALATION_CODES)) & (~closed["ticket_id"].isin(repeated))
        all_p = float(ok.mean()) if len(closed) else 0.0
        out = {"_all": (all_p, len(closed))}
        for cat, grp in closed.assign(ok=ok).groupby("category"):
            out[cat] = ((grp["ok"].sum() + self.k * all_p) / (len(grp) + self.k), len(grp))
        return out

    def service_resolution(self, category: str) -> AcceptanceEstimate:
        p, n = self._service.get(category, self._service["_all"])
        src = f"service_resolution_proxy_{category}" if category in self._service else "service_resolution_proxy_all"
        return AcceptanceEstimate(float(p), src, int(n), 0, None)

    def describe(self) -> dict[str, Any]:
        return {
            "method": "Beta-smoothed observed 14-day conversion, global > offer > channel > tonality",
            "pseudo_count": self.k, "mode": self.mode,
            "exclude_unconsented_history": self.exclude_unconsented,
            "excluded_unconsented_actions": self.excluded_unconsented,
            "global_treated_rate": round(self.global_p, 4), "global_control_rate": round(float(self.control_global_p), 4),
            "treated_deliveries": self.global_n,
            "caveat": "Observational rates; not proven causal uplift.",
        }
