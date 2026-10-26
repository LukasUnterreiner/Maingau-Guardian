"""Counterfactual decision simulator.

For one customer it recomputes the full ranking under changed economic
assumptions and explains what changed. Compliance is untouched: scenario
parameters only enter the CLV engine and the acceptance probabilities, never
the eligibility engine, so a blocked action stays blocked under any scenario.

Attribution: every changed parameter is also applied on its own (one at a
time) to show which variable flips the recommendation and by how much it moves
the expected dCLV of the originally recommended action.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.models.runtime_settings import RuntimeSettings
from app.services.clv_engine import ScenarioParams
from app.services.recommendation_engine import NO_CONTACT, Decision, POverrides, RecommendationEngine


def _r(v: float | None, n: int = 2) -> float | None:
    return None if v is None else float(round(v, n))


class CounterfactualEngine:
    def __init__(self, engine: RecommendationEngine):
        self.engine = engine

    @staticmethod
    def changed_parameters(params: ScenarioParams, p_over: POverrides) -> list[tuple[str, ScenarioParams, POverrides]]:
        """Split a scenario into single-parameter scenarios for attribution."""
        default = ScenarioParams()
        singles: list[tuple[str, ScenarioParams, POverrides]] = []
        for name in ("discount_rate", "horizon_years", "churn_now_override", "service_resolution_cost_eur",
                     "contact_during_service_case"):
            if getattr(params, name) is not None:
                singles.append((name, replace(default, **{name: getattr(params, name)}), POverrides()))
        if params.churn_delta:
            singles.append(("churn_delta", replace(default, churn_delta=params.churn_delta), POverrides()))
        for ch, cost in params.contact_cost_overrides.items():
            singles.append((f"contact_cost_overrides.{ch}", replace(default, contact_cost_overrides={ch: cost}), POverrides()))
        for pid, p in p_over.by_product.items():
            singles.append((f"acceptance_probability_overrides.{pid}", default, POverrides(by_product={pid: p})))
        if p_over.multiplier != 1.0:
            singles.append(("acceptance_probability_multiplier", default, POverrides(multiplier=p_over.multiplier)))
        return singles

    def _value_of(self, d: Decision, product_id: str) -> float | None:
        if product_id == NO_CONTACT:
            return 0.0
        for c in d.ranked + d.blocked:
            if c.product_id == product_id:
                return c.dclv
        return None

    def _ranking(self, d: Decision) -> list[dict[str, Any]]:
        rows = [{"product_id": c.product_id, "channel": c.channel, "expected_dclv_eur": _r(c.dclv),
                 "acceptance_probability": _r(c.p_used, 4), "executable": True} for c in d.ranked]
        rows.append({"product_id": NO_CONTACT, "channel": "none", "expected_dclv_eur": 0.0,
                     "acceptance_probability": None, "executable": True})
        rows.sort(key=lambda r: -r["expected_dclv_eur"])
        for i, r in enumerate(rows, 1):
            r["rank"] = i
        return rows

    def simulate(self, customer_id: str, as_of, settings: RuntimeSettings, params: ScenarioParams,
                 p_over: POverrides, baseline_policy: str) -> dict[str, Any]:
        eng = self.engine
        base = eng.decide(customer_id, as_of, settings)
        scen = eng.decide(customer_id, as_of, settings, params, p_over)

        base_top, scen_top = base.recommended_product, scen.recommended_product
        changes = []
        for name, sp, po in self.changed_parameters(params, p_over):
            single = eng.decide(customer_id, as_of, settings, sp, po)
            before = self._value_of(base, base_top)
            after = self._value_of(single, base_top)
            changes.append({
                "parameter": name,
                "recommended_action_alone": single.recommended_product,
                "changes_recommendation": single.recommended_product != base_top,
                "dclv_of_base_recommendation_before_eur": _r(before),
                "dclv_of_base_recommendation_after_eur": _r(after),
                "delta_eur": _r(None if before is None or after is None else after - before),
            })

        # Strategy comparison under the scenario
        guardian_value = scen.expected_dclv
        strategies = []
        for row in self._ranking(scen):
            strategies.append({**row, "difference_to_recommended_eur": _r(row["expected_dclv_eur"] - guardian_value)})
        illustrative = [{"product_id": c.product_id, "channel": c.channel, "expected_dclv_eur": _r(c.dclv),
                         "exclusion_reasons": c.eligibility.exclusion_codes, "executable": False,
                         "label": "illustrative, non-executable"} for c in scen.blocked]

        base_line = eng.baseline(scen, baseline_policy)
        baseline_value = base_line.dclv if base_line else 0.0

        # Integrity check: blocked set is identical between base and scenario
        blocked_base = {(c.product_id, c.channel) for c in base.all_candidates if not c.eligibility.allowed}
        blocked_scen = {(c.product_id, c.channel) for c in scen.all_candidates if not c.eligibility.allowed}
        if blocked_base != blocked_scen:
            raise RuntimeError("simulation must not change compliance outcomes")

        return {
            "customer_id": customer_id,
            "decision_id": scen.decision_id,
            "base_decision_id": base.decision_id,
            "as_of": scen.as_of,
            "assumptions_applied": {
                **{k: v for k, v in params.__dict__.items() if v not in (None, {}, 0.0)},
                "acceptance_probability_overrides": p_over.by_product,
                "acceptance_probability_multiplier": p_over.multiplier,
            },
            "base": {"recommended_action": base_top, "expected_dclv_eur": _r(base.expected_dclv),
                     "current_clv_eur": _r(base.clv_now_eur), "ranking": self._ranking(base)},
            "scenario": {"recommended_action": scen_top, "expected_dclv_eur": _r(scen.expected_dclv),
                         "current_clv_eur": _r(scen.clv_now_eur), "ranking": strategies,
                         "reason": scen.reason, "required_service_workflow": scen.required_service_workflow},
            "recommendation_changed": base_top != scen_top,
            "parameter_attribution": changes,
            "blocked_actions": illustrative,
            "compliance_unchanged": True,
            "baseline": {
                "policy": baseline_policy,
                "action": base_line.product_id if base_line else NO_CONTACT,
                "channel": base_line.channel if base_line else "none",
                "executable_under_guardian_rules": bool(base_line and base_line.eligibility.allowed),
                "expected_dclv_eur": _r(baseline_value),
                "projected_protected_value_eur": _r(guardian_value - baseline_value),
            },
            "value_label": "simulated (model-based estimate; not realised savings or proven causal uplift)",
        }
