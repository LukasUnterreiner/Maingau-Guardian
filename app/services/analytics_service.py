"""Marketing dashboard aggregations over the whole customer base."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from app.services.recommendation_engine import NO_CONTACT, Decision, RecommendationEngine


def _r(v: float) -> float:
    return float(round(v, 2))


def segment_of(d: Decision) -> str:
    lines = d.state.business_lines
    return "+".join(lines) if lines else "no_active_line"


def value_tier(clv_now: float) -> str:
    if clv_now < 0:
        return "negative_value"
    if clv_now < 500:
        return "clv_0_500"
    if clv_now < 1500:
        return "clv_500_1500"
    return "clv_1500_plus"


class AnalyticsService:
    def __init__(self, engine: RecommendationEngine):
        self.engine = engine

    def overview(self, decisions: list[Decision], statuses: dict[str, str], baseline_policy: str) -> dict[str, Any]:
        by_action = Counter()
        by_type = Counter()
        by_line = Counter()
        by_channel = Counter()
        eligible_mkt = blocked_mkt = 0
        exclusion = Counter()
        seg_val: dict[str, dict[str, float]] = defaultdict(lambda: {"customers": 0, "expected_dclv_eur": 0.0,
                                                                    "current_clv_eur": 0.0})
        tier_val: dict[str, dict[str, float]] = defaultdict(lambda: {"customers": 0, "expected_dclv_eur": 0.0})
        total_dclv = total_clv = total_baseline = 0.0
        service_issue = 0
        pending = 0
        baseline_actions = Counter()
        baseline_blocked = 0
        for d in decisions:
            rec = d.recommended
            by_action[d.recommended_product] += 1
            by_type[rec.valuation.action_type if rec else "no_contact"] += 1
            by_line[self.engine.products[rec.product_id]["business_line"] if rec else "none"] += 1
            by_channel[rec.channel if rec else "none"] += 1
            for c in d.ranked:
                if c.valuation.action_type != "service":
                    eligible_mkt += 1
            for c in d.blocked:
                if c.valuation.action_type != "service":
                    blocked_mkt += 1
                    for code in c.eligibility.exclusion_codes:
                        exclusion[code] += 1
            total_dclv += d.expected_dclv
            total_clv += d.clv_now_eur
            if d.state.has_service_issue:
                service_issue += 1
            if statuses.get(d.decision_id, "pending_approval" if rec else "not_required") == "pending_approval":
                pending += 1
            seg = seg_val[segment_of(d)]
            seg["customers"] += 1
            seg["expected_dclv_eur"] += d.expected_dclv
            seg["current_clv_eur"] += d.clv_now_eur
            tier = tier_val[value_tier(d.clv_now_eur)]
            tier["customers"] += 1
            tier["expected_dclv_eur"] += d.expected_dclv
            b = self.engine.baseline(d, baseline_policy)
            total_baseline += b.dclv if b else 0.0
            baseline_actions[b.product_id if b else NO_CONTACT] += 1
            if b and not b.eligibility.allowed:
                baseline_blocked += 1

        n = len(decisions)
        return {
            "total_customers_evaluated": n,
            "as_of": decisions[0].as_of if decisions else None,
            "marketing_actions": {"eligible_product_options": eligible_mkt, "blocked_product_options": blocked_mkt,
                                  "blocked_by_reason": dict(exclusion.most_common())},
            "recommended_action_distribution": dict(by_action.most_common()),
            "recommended_by_action_type": dict(by_type.most_common()),
            "recommended_by_business_line": dict(by_line.most_common()),
            "recommended_by_channel": dict(by_channel.most_common()),
            "customers_with_active_service_issues": service_issue,
            "pending_approvals": pending,
            "total_current_clv_eur": _r(total_clv),
            "total_projected_incremental_clv_eur": _r(total_dclv),
            "baseline": {
                "policy": baseline_policy,
                "total_expected_dclv_eur": _r(total_baseline),
                "action_distribution": dict(baseline_actions.most_common()),
                "baseline_actions_blocked_by_lighty_rules": baseline_blocked,
                "baseline_actions_blocked_by_guardian_rules": baseline_blocked,  # deprecated alias
            },
            "projected_protected_customer_value_eur": _r(total_dclv - total_baseline),
            "projected_protected_customer_value_label":
                "Model-based estimate: expected CLV under Lighty minus expected CLV under the baseline policy. "
                "Not realised savings and not proven causal uplift.",
            "value_by_segment": {k: {kk: _r(vv) if isinstance(vv, float) else vv for kk, vv in v.items()}
                                 for k, v in sorted(seg_val.items())},
            "value_by_clv_tier": {k: {kk: _r(vv) if isinstance(vv, float) else vv for kk, vv in v.items()}
                                  for k, v in sorted(tier_val.items())},
        }
