"""Regional view: GET /api/marketing/regions adds up the same portfolio as the cockpit, per state and per city."""
from __future__ import annotations

from app.services.region_service import high_risk_threshold, load_places, regions

STATES = {"DE-HE": 311, "DE-BY": 124, "DE-BE": 73, "DE-NW": 73, "DE-HH": 64, "DE-RP": 56, "DE-BW": 49}


def test_every_dataset_city_is_in_the_city_table(settings, dataset):
    places = load_places(settings.city_regions_path)
    cities = set(dataset.tables["customer_master"]["city"].dropna())
    assert cities and cities <= set(places)
    assert all(p.state_code.startswith("DE-") and 47 < p.latitude < 55 and 5 < p.longitude < 16
               for p in places.values())


def test_states_add_up_to_the_portfolio(client):
    r = client.get("/api/marketing/regions")
    assert r.status_code == 200
    body = r.json()
    assert body["level"] == "state" and body["unassigned_customers"] == 0
    assert {g["id"]: g["customers"] for g in body["regions"]} == STATES
    t = body["totals"]
    assert t["customers"] == 750
    assert t["likely_to_cancel"] == 204 and round(t["clv_at_stake_eur"]) == 64426   # same as the Churn risk page
    assert t["pending_approvals"] == client.get("/api/marketing/overview").json()["pending_approvals"]
    for key in ("likely_to_cancel", "clv_at_stake_eur", "service_issues", "pending_approvals", "expected_dclv_eur"):
        assert abs(sum(g[key] for g in body["regions"]) - t[key]) < 0.05, key
    hessen = next(g for g in body["regions"] if g["id"] == "DE-HE")
    assert hessen["name"] == "Hessen" and hessen["likely_to_cancel"] == 83


def test_cities_inside_one_state_carry_their_position(client):
    body = client.get("/api/marketing/regions", params={"level": "city", "state": "DE-HE"}).json()
    names = {g["name"] for g in body["regions"]}
    assert names == {"Darmstadt", "Frankfurt", "Hanau", "Obertshausen", "Offenbach", "Wiesbaden"}
    assert all(g["state_code"] == "DE-HE" and g["latitude"] and g["longitude"] for g in body["regions"])
    assert body["totals"]["customers"] == 311


def test_invalid_parameters_are_rejected(client):
    assert client.get("/api/marketing/regions", params={"level": "district"}).status_code == 422
    assert client.get("/api/marketing/regions", params={"state": "Hessen"}).status_code == 422


def test_unknown_city_is_counted_as_unassigned(portfolio, settings):
    places = load_places(settings.city_regions_path)
    places.pop("Mainz")
    threshold = high_risk_threshold(d.state.churn_now for d in portfolio)
    body = regions(portfolio, {}, places, "state", None, threshold)
    assert body["unassigned_customers"] == 56
    other = next(g for g in body["regions"] if g["id"] == "unassigned")
    assert other["name"] == "Unassigned" and other["customers"] == 56 and other["state_code"] is None
    assert body["totals"]["customers"] == 750


def test_missing_city_table_keeps_every_customer(portfolio, tmp_path):
    body = regions(portfolio, {}, load_places(tmp_path / "missing.csv"), "city", None, 0.24)
    assert body["unassigned_customers"] == 750 and body["totals"]["customers"] == 750
