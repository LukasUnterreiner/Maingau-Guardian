"""Mandatory decision-logic scenarios (prompt section 11)."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.services.clv_engine import MARKETING_ACTION_TYPES, ScenarioParams
from app.services.eligibility_engine import MARKETING_CHANNELS
from app.services.recommendation_engine import POverrides


def _marketing(d) -> bool:
    return d.recommended is not None and d.recommended.channel in MARKETING_CHANNELS


# 1 ---------------------------------------------------------------------------
def test_open_complaint_never_gets_sales_offer(portfolio):
    with_complaint = [d for d in portfolio if d.state.open_complaint]
    assert len(with_complaint) >= 29
    for d in with_complaint:
        assert d.recommended is None or d.recommended.valuation.action_type not in MARKETING_ACTION_TYPES, d.customer_id
        for c in d.all_candidates:
            if c.valuation.action_type in MARKETING_ACTION_TYPES:
                assert not c.eligibility.allowed
                assert "OPEN_COMPLAINT_BLOCKS_MARKETING" in c.eligibility.exclusion_codes


def test_mg_100004_service_case(guardian):
    """Known customer with documented service issues."""
    r = guardian.recommend("MG-100004")
    assert r["recommended_action"] == "P-SV-01"
    assert r["action_type"] == "service"
    assert r["channel"] == "service_call"  # customer asked for a callback on 2026-10-01
    assert r["current_clv_eur"] == pytest.approx(167.05, abs=0.01)
    assert r["expected_dclv_eur"] > 0
    blocked = {b["product_id"]: b for b in r["blocked_actions"]}
    assert "P-MO-01" in blocked
    assert {"OPEN_COMPLAINT_BLOCKS_MARKETING", "DUNNING_BLOCKS_MARKETING"} <= set(blocked["P-MO-01"]["exclusion_reasons"])
    assert all(not b["executable"] for b in r["blocked_actions"])
    assert "service" in r["reason"].lower()


# 2 ---------------------------------------------------------------------------
def test_no_marketing_without_consent(portfolio):
    for d in portfolio:
        if not _marketing(d):
            continue
        ch = d.recommended.channel
        consent = MARKETING_CHANNELS[ch]["consent"]
        assert d.state.consents[consent].granted, (d.customer_id, ch)
        assert d.state.consents["profiling_analytics"].granted, d.customer_id


def test_customers_without_any_marketing_consent_get_no_marketing(portfolio):
    none_given = [d for d in portfolio
                  if not any(d.state.consents[spec["consent"]].granted for spec in MARKETING_CHANNELS.values())]
    assert none_given, "dataset should contain customers without marketing consent"
    for d in none_given:
        assert not _marketing(d), d.customer_id


# 3 ---------------------------------------------------------------------------
def test_withdrawn_consent_overrides_history(guardian):
    """MG-100003 withdraws profiling + newsletter consent on 2026-10-01 10:14 (event stream)."""
    before = guardian.engine.decide("MG-100003", datetime(2026, 10, 1, 10, 0), guardian.settings)
    after = guardian.engine.decide("MG-100003", datetime(2026, 10, 1, 10, 15), guardian.settings)
    assert before.state.consents["profiling_analytics"].status == "granted"
    assert any(c.valuation.action_type in MARKETING_ACTION_TYPES for c in before.ranked)
    assert after.state.consents["profiling_analytics"].status == "withdrawn"
    assert after.state.consents["newsletter_email"].status == "withdrawn"
    assert not any(c.valuation.action_type in MARKETING_ACTION_TYPES and c.eligibility.process == "marketing"
                   for c in after.ranked)
    assert not _marketing(after)


def test_unsubscribe_link_withdrawal_is_respected(guardian):
    for d in guardian.portfolio():
        if d.state.newsletter["unsubscribed"]:
            assert not d.state.consents["newsletter_email"].granted, d.customer_id


# 4 ---------------------------------------------------------------------------
def test_cross_selling_for_healthy_customer(portfolio, guardian):
    healthy = [d for d in portfolio if d.recommended and d.recommended.valuation.action_type in ("sales", "upsell")
               and not d.state.has_service_issue]
    assert healthy, "expected at least one healthy cross-sell customer in the dataset"
    best = max(healthy, key=lambda d: d.expected_dclv)
    assert best.expected_dclv > 0
    assert best.state.holdings.get(best.recommended_product) is not True
    assert best.recommended.eligibility.allowed
    print(f"healthy cross-sell example: {best.customer_id} -> {best.recommended_product} "
          f"via {best.recommended.channel}, dCLV {best.expected_dclv:.2f} EUR")


# 5 ---------------------------------------------------------------------------
def test_owned_products_are_never_recommended(portfolio):
    for d in portfolio:
        if d.recommended:
            assert d.state.holdings.get(d.recommended_product) is not True, d.customer_id
    mobile_holders = [d for d in portfolio if d.state.holdings.get("P-MO-01")]
    assert mobile_holders
    for d in mobile_holders:
        for c in d.all_candidates:
            if c.product_id == "P-MO-01":
                assert "PRODUCT_ALREADY_HELD" in c.eligibility.exclusion_codes


# 6 ---------------------------------------------------------------------------
def test_negative_value_never_outranks_no_contact(portfolio):
    for d in portfolio:
        if d.recommended is None:
            assert all(c.dclv <= 0 for c in d.ranked), d.customer_id
        elif not d.required_service_workflow:
            assert d.recommended.dclv > 0, d.customer_id
    assert any(d.recommended is None and d.ranked for d in portfolio), "expected customers whose options are all negative"


def test_required_service_workflow_takes_precedence(guardian):
    d = guardian.engine.decide("MG-100004", guardian.default_as_of, guardian.settings,
                               ScenarioParams(), POverrides(by_product={"P-SV-01": 0.0}))
    assert d.recommended.product_id == "P-SV-01"
    assert d.recommended.dclv < 0
    assert d.required_service_workflow is True


# 8 ---------------------------------------------------------------------------
def test_simulation_recalculates_correctly(guardian):
    base = guardian.engine.decide("MG-100004", guardian.default_as_of, guardian.settings)
    p = base.recommended.p_used
    sim = guardian.simulate("MG-100004", ScenarioParams(service_resolution_cost_eur=35.0), POverrides(), None, None)
    # dCLV falls by p * (35 - 15) exactly
    assert sim["scenario"]["expected_dclv_eur"] == pytest.approx(base.expected_dclv - p * 20.0, abs=0.01)
    assert sim["parameter_attribution"][0]["parameter"] == "service_resolution_cost_eur"
    sim2 = guardian.simulate("MG-100004", ScenarioParams(), POverrides(by_product={"P-SV-01": 0.0}), None, None)
    assert sim2["scenario"]["expected_dclv_eur"] == pytest.approx(-6.0)  # only the call cost remains


def test_simulation_can_flip_the_recommendation(guardian, portfolio):
    d = next(d for d in portfolio if d.recommended and d.recommended.valuation.action_type == "sales"
             and len(d.ranked) >= 2)
    top = d.recommended_product
    sim = guardian.simulate(d.customer_id, ScenarioParams(), POverrides(by_product={top: 0.0}), None, None)
    assert sim["recommendation_changed"] is True
    attr = sim["parameter_attribution"][0]
    assert attr["changes_recommendation"] is True and attr["delta_eur"] < 0


# 11 --------------------------------------------------------------------------
def test_prohibited_actions_stay_blocked_under_any_simulation(guardian):
    sim = guardian.simulate("MG-100004",
                            ScenarioParams(churn_now_override=0.9, contact_cost_overrides={"app_push": 0.0},
                                           contact_during_service_case=0.0),
                            POverrides(by_product={"P-MO-01": 1.0, "P-IN-01": 1.0}, multiplier=10.0), None, None)
    assert sim["scenario"]["recommended_action"] not in {"P-MO-01", "P-IN-01"}
    blocked = {b["product_id"] for b in sim["blocked_actions"]}
    assert {"P-MO-01", "P-IN-01"} <= blocked
    assert sim["compliance_unchanged"] is True
    executable = {r["product_id"] for r in sim["scenario"]["ranking"]}
    assert executable <= {"P-SV-01", "NO_CONTACT"}


# 12 --------------------------------------------------------------------------
def test_decision_records_contain_reasons_and_inputs(guardian):
    r = guardian.recommend("MG-100004")
    row = guardian.log.get(r["decision_id"])
    rec = row["record"]
    assert rec["reason"] and "churn" in rec["reason"]
    inputs = rec["inputs"]
    for key in ("annual_margin_eur", "cost_to_serve_eur", "churn_now", "drivers", "discount_rate", "consents"):
        assert key in inputs
    assert inputs["annual_margin_eur"] == pytest.approx(131.6)
    assert rec["eligibility_checks"] and rec["alternatives"]
    assert row["approval_status"] == "pending_approval"


def test_decisions_are_deterministic(guardian):
    a = guardian.engine.decide("MG-100002", guardian.default_as_of, guardian.settings)
    b = guardian.engine.decide("MG-100002", guardian.default_as_of, guardian.settings)
    assert a.decision_id == b.decision_id
    assert a.expected_dclv == b.expected_dclv


def test_customer_initiated_tariff_inquiry_is_service_process(guardian):
    """MG-100006 asked for a retention offer by phone on 2026-10-01."""
    r = guardian.recommend("MG-100006")
    assert r["recommended_action"] == "P-EN-02"
    assert r["process"] == "customer_inquiry_reply"
    assert r["channel"] == "service_call"
    assert r["requires_human_approval"] is True


def test_frequency_limit_blocks_marketing(guardian, portfolio):
    limited = [d for d in portfolio if any("CONTACT_FREQUENCY_LIMIT" in c.eligibility.exclusion_codes
                                           for c in d.all_candidates)]
    assert limited
    for d in limited:
        assert not _marketing(d), d.customer_id
