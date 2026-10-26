"""Data integration and CLV methodology (clv_method sheet)."""
from __future__ import annotations

import pytest

from app.services.churn_model import SERVICE_DRIVERS
from app.services.clv_engine import ScenarioParams, clv

DRIVER_LABELS = {"price guarantee ends": "price_guarantee_ends_90d", "open complaint": "open_complaint",
                 "tickets in": "tickets_12m_ge2", "low CSAT": "csat_le2", "dunning level": "dunning_ge2",
                 "failed charges": "failed_charges_30d_ge3", "HEMS user": "hems_user"}


def test_workbook_loaded(dataset):
    assert len(dataset.customers) == 750
    assert len(dataset.products) == 18
    assert dataset.assumptions["discount_rate"] == pytest.approx(0.06)
    assert dataset.assumptions["horizon_years"] == 10


def test_payment_information_is_dropped(dataset):
    for name, df in dataset.tables.items():
        assert "payment_method" not in df.columns, name


def test_duplicate_events_are_dropped(dataset):
    stats = dataset.quality_report["event_stream"]
    assert stats["duplicates_dropped"] == 12
    assert len({e.event_id for e in dataset.events}) == len(dataset.events)


def test_clv_formula_reproduces_dataset_at_snapshot(guardian, dataset):
    """Inputs in customer_value are rounded, so allow a few EUR."""
    for cid in guardian.customers.customer_ids():
        s = guardian.customers.get_state(cid, dataset.snapshot_at)
        assert s.churn_now == pytest.approx(s.churn_snapshot, abs=1e-9)
        assert abs(s.clv_now_eur - s.clv_snapshot_reported_eur) < 3.5, cid


def test_churn_drivers_match_documented_drivers_for_all_customers(guardian, dataset):
    for cid in guardian.customers.customer_ids():
        s = guardian.customers.get_state(cid, dataset.snapshot_at)
        text = dataset.customer_value[cid].get("churn_drivers") or ""
        expected = {code for part in text.split("; ") for label, code in DRIVER_LABELS.items() if label in part}
        assert {d.code for d in s.drivers} == expected, cid
        assert s.cancellation_pending == ("cancellation pending" in text), cid


def test_higher_churn_lowers_clv_and_is_reflected(guardian):
    """Mandatory scenario 7."""
    values = [clv(200, 30, c, 0.06, 10) for c in (0.05, 0.15, 0.3, 0.6)]
    assert values == sorted(values, reverse=True)
    s = guardian.customers.get_state("MG-100002", guardian.default_as_of)
    base = guardian.clv.clv_now(s, ScenarioParams())
    higher = guardian.clv.clv_now(s, ScenarioParams(churn_delta=0.1))
    assert higher < base
    assert higher == pytest.approx(clv(s.annual_margin_eur, s.cost_to_serve_eur, s.churn_now + 0.1, 0.06, 10))


def test_service_action_removes_only_service_drivers_without_double_counting(guardian):
    s = guardian.customers.get_state("MG-100004", guardian.default_as_of)
    prod = guardian.ds.products["P-SV-01"]
    v = guardian.clv.value(s, prod, "service_email", 1.0, ScenarioParams())
    removed = sum(d.increment for d in s.drivers if d.code in SERVICE_DRIVERS)
    expected = clv(s.annual_margin_eur, s.cost_to_serve_eur, s.churn_now - removed, 0.06, 10) - 15.0
    assert v.clv_after_accept_eur == pytest.approx(expected)
    assert set(v.removed_drivers) == {"open_complaint", "dunning_ge2"}
    assert "tickets_12m_ge2" not in v.removed_drivers  # history is not undone by resolution
    assert v.expected_dclv_eur == pytest.approx(expected - v.clv_now_eur - v.contact_cost_eur)


def test_one_off_margin_counted_once(guardian):
    s = guardian.customers.get_state("MG-100002", guardian.default_as_of)
    prod = guardian.ds.products["P-SH-01"]
    v = guardian.clv.value(s, prod, "newsletter_email", 1.0, ScenarioParams())
    expected = clv(s.annual_margin_eur, s.cost_to_serve_eur, s.churn_now + prod["churn_effect_if_bought"], 0.06, 10) \
        + prod["annual_margin_if_bought_eur"]
    assert v.clv_after_accept_eur == pytest.approx(expected)
    assert v.added_annual_margin_eur == 0


def test_recurring_margin_is_an_annuity(guardian):
    s = guardian.customers.get_state("MG-100002", guardian.default_as_of)
    prod = guardian.ds.products["P-MO-01"]
    v = guardian.clv.value(s, prod, "newsletter_email", 1.0, ScenarioParams())
    expected = clv(s.annual_margin_eur + 54, s.cost_to_serve_eur, s.churn_now - 0.02, 0.06, 10)
    assert v.clv_after_accept_eur == pytest.approx(expected)


def test_sales_contact_during_service_case_is_penalised_on_reject(guardian):
    s = guardian.customers.get_state("MG-100004", guardian.default_as_of)
    v = guardian.clv.value(s, guardian.ds.products["P-MO-01"], "outbound_call", 0.1, ScenarioParams())
    assert v.service_case_contact_penalty
    assert v.churn_after_reject == pytest.approx(s.churn_now + 0.05)
    assert v.clv_after_reject_eur < v.clv_now_eur


def test_event_replay_updates_state(guardian, dataset):
    snap = guardian.customers.get_state("MG-100004", dataset.snapshot_at)
    live = guardian.customers.get_state("MG-100004", guardian.default_as_of)
    assert snap.max_dunning_level == 2 and live.max_dunning_level == 3
    assert live.signals["callback_requested"] is True
    assert any(e["event_type"] == "dunning_level_changed" for e in live.applied_events)
