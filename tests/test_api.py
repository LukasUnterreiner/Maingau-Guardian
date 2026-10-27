"""API contract, errors (scenario 9), approvals, settings and AI fallback (scenario 10)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.config.settings import AppSettings
from app.main import create_app
from app.services.ai_service import AIService
from app.services.decision_log import DecisionLog
from app.services.lighty import Lighty

REQUIRED_RECOMMENDATION_FIELDS = {
    "customer_id", "decision_id", "recommended_action", "action_type", "product_id", "channel", "tonality",
    "current_clv_eur", "expected_dclv_eur", "estimated_clv_after_eur", "acceptance_probability", "reason",
    "alternatives", "blocked_actions", "eligibility_checks", "approval_status",
}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["customers_loaded"] == 750
    assert body["acceptance_model"]["caveat"].startswith("Observational")



def test_recommendation_reason_in_german(client):
    """language=de changes only the reason text; the decision, its codes and the decision log stay the same."""
    en = client.get("/api/customers/MG-100004/recommendations").json()
    de = client.get("/api/customers/MG-100004/recommendations", params={"language": "de"}).json()
    assert en["reason"].startswith("Resolve the service issue first")
    assert de["reason"].startswith("Zuerst das Service-Anliegen lösen (Service-Only / No offer über Service-Anruf).")
    assert "von 38,0 % auf 18,0 %" in de["reason"] and "+66,50 EUR" in de["reason"]
    assert de["reason"].endswith("Marketing-Sperren aktiv: CONTACT_FREQUENCY_LIMIT, DUNNING_BLOCKS_MARKETING, "
                                 "OPEN_COMPLAINT_BLOCKS_MARKETING, PROFILING_CONSENT_NOT_GIVEN.")
    assert {k: v for k, v in de.items() if k != "reason"} == {k: v for k, v in en.items() if k != "reason"}
    assert client.get("/api/customers/MG-100004/recommendations").json()["reason"] == en["reason"]
    assert client.get("/api/customers/MG-100004/recommendations", params={"language": "fr"}).status_code == 422

def test_openapi_docs_available(client):
    assert client.get("/docs").status_code == 200
    assert "/api/customers/{customer_id}/simulate" in client.get("/openapi.json").json()["paths"]


def test_customer_pagination_and_filters(client):
    r = client.get("/api/customers", params={"page": 2, "page_size": 10})
    body = r.json()
    assert r.status_code == 200 and len(body["items"]) == 10 and body["total"] == 750 and body["total_pages"] == 75
    r = client.get("/api/customers", params={"has_service_issue": True, "page_size": 200})
    assert all(i["has_service_issue"] for i in r.json()["items"])
    assert client.get("/api/customers", params={"page_size": 1000}).status_code == 422


def test_customer_360(client):
    r = client.get("/api/customers/MG-100004")
    assert r.status_code == 200
    b = r.json()
    assert b["value"]["annual_margin_eur"] == 131.6
    assert b["service"]["open_complaint"] is True
    assert b["consents"]["marketing_email"]["status"] == "withdrawn"
    assert "payment_method" not in r.text


# 9 ---------------------------------------------------------------------------
def test_invalid_customer_ids_return_404(client):
    for method, url in [("get", "/api/customers/MG-000000"), ("get", "/api/customers/XYZ/recommendations"),
                        ("post", "/api/customers/MG-000000/simulate")]:
        r = client.request(method.upper(), url, json={} if method == "post" else None)
        assert r.status_code == 404, url
        assert r.json()["error"] == "not_found"
    assert client.post("/api/ai/explain", json={"customer_id": "NOPE"}).status_code == 404
    assert client.post("/api/decisions/DEC-unknown/approve").status_code == 404


def test_recommendation_contract(client):
    r = client.get("/api/customers/MG-100004/recommendations")
    assert r.status_code == 200
    body = r.json()
    assert REQUIRED_RECOMMENDATION_FIELDS <= set(body)
    assert body["alternatives"][-1]["product_id"] == "NO_CONTACT" or any(
        a["product_id"] == "NO_CONTACT" for a in body["alternatives"])
    for b in body["blocked_actions"]:
        assert b["executable"] is False and b["exclusion_reasons"]


def test_churn_risk_fields_for_the_web_app(client):
    """Churn before/after the recommended action and the dataset's service impact, used by the churn-risk views."""
    rec = client.get("/api/customers/MG-100004/recommendations").json()
    assert (rec["churn_now"], rec["churn_after_accept"]) == (0.38, 0.18)   # service drivers removed if resolved
    assert rec["churn_after_reject"] == rec["churn_now"]
    nc = next(c for c in client.get("/api/customers", params={"page_size": 200}).json()["items"]
              if c["customer_id"] == "MG-100004")
    assert nc["clv_service_impact_reported_eur"] == -357
    assert set(nc["churn_drivers"]) == {"Open complaint", "Two or more tickets in 12 months", "Dunning level 2 or higher"}


def test_simulate_validation(client):
    assert client.post("/api/customers/MG-100004/simulate",
                       json={"acceptance_probability_overrides": {"P-SV-01": 1.5}}).status_code == 422
    assert client.post("/api/customers/MG-100004/simulate", json={"unknown": 1}).status_code == 422
    assert client.post("/api/customers/MG-100004/simulate",
                       json={"contact_cost_overrides": {"carrier_pigeon": 1}}).status_code == 422
    r = client.post("/api/customers/MG-100004/simulate", json={"churn_delta": 0.1})
    assert r.status_code == 200 and r.json()["scenario"]["current_clv_eur"] < r.json()["base"]["current_clv_eur"]


def test_marketing_overview_and_list(client):
    o = client.get("/api/marketing/overview").json()
    assert o["total_customers_evaluated"] == 750
    assert sum(o["recommended_action_distribution"].values()) == 750
    assert "not realised savings" in o["projected_protected_customer_value_label"].lower()
    lst = client.get("/api/marketing/recommendations", params={"action_type": "service", "page_size": 5}).json()
    assert all(i["action_type"] == "service" for i in lst["items"])


def test_approval_flow(client):
    rec = client.get("/api/customers/MG-100004/recommendations").json()
    did = rec["decision_id"]
    assert rec["approval_status"] == "pending_approval"
    r = client.post(f"/api/decisions/{did}/reject", json={"reviewer": "qa", "note": "test"})
    assert r.status_code == 200 and r.json()["approval_status"] == "rejected"
    assert client.post(f"/api/decisions/{did}/approve").status_code == 409
    assert client.get("/api/customers/MG-100004/recommendations").json()["approval_status"] == "rejected"
    item = next(i for i in client.get("/api/marketing/recommendations",
                                      params={"approval_status": "rejected"}).json()["items"] if i["decision_id"] == did)
    assert item["reviewed_by"] == "qa" and item["reviewed_at"].endswith("+00:00")
    pending = client.get("/api/marketing/recommendations", params={"page_size": 5}).json()["items"]
    assert all(i["reviewed_by"] is None and i["reviewed_at"] is None for i in pending if i["decision_id"] != did)


def test_no_contact_cannot_be_approved_or_messaged(client, portfolio):
    d = next(d for d in portfolio if d.recommended is None)
    rec = client.get(f"/api/customers/{d.customer_id}/recommendations").json()
    assert rec["approval_status"] == "not_required" and rec["requires_human_approval"] is False
    assert client.post(f"/api/decisions/{rec['decision_id']}/approve").status_code == 409
    assert client.post("/api/ai/generate-message", json={"decision_id": rec["decision_id"]}).status_code == 409


def test_settings_validation_cannot_loosen_hard_rules(client):
    assert client.put("/api/marketing/settings",
                      json={"contact_policy": {"max_marketing_contacts_30d": 50}}).status_code == 422
    assert client.put("/api/marketing/settings",
                      json={"action_priorities": {"P-SV-01": {"enabled": False}}}).status_code == 422
    assert client.put("/api/marketing/settings",
                      json={"action_priorities": {"P-XX-99": {"enabled": False}}}).status_code == 422
    r = client.put("/api/marketing/settings", json={"action_priorities": {"P-MO-01": {"enabled": False}}})
    assert r.status_code == 200 and r.json()["version"] == 1
    lst = client.get("/api/marketing/recommendations", params={"page_size": 500}).json()
    assert all(i["recommended_action"] != "P-MO-01" for i in lst["items"])


def test_admin_token_enforced(settings, dataset, tmp_path):
    secured = settings.model_copy(update={"admin_token": __import__("pydantic").SecretStr("s3cret")})
    g = Lighty(secured, dataset=dataset, decision_log=DecisionLog(tmp_path / "x.sqlite3"))
    with TestClient(create_app(secured, g)) as c:
        assert c.put("/api/marketing/settings", json={}).status_code == 401
        assert c.put("/api/marketing/settings", json={}, headers={"X-Admin-Token": "wrong"}).status_code == 401
        assert c.put("/api/marketing/settings", json={}, headers={"X-Admin-Token": "s3cret"}).status_code == 200
        assert "s3cret" not in c.get("/api/health").text


# 10 --------------------------------------------------------------------------
def test_unavailable_ai_does_not_break_engine(settings, dataset, tmp_path):
    broken = settings.model_copy(update={"ai_api_key": __import__("pydantic").SecretStr("sk-test-secret"),
                                         "ai_base_url": "http://127.0.0.1:9", "ai_model": "unverified-model",
                                         "ai_timeout_s": 0.5})
    g = Lighty(broken, dataset=dataset, decision_log=DecisionLog(tmp_path / "ai.sqlite3"))
    with TestClient(create_app(broken, g)) as c:
        assert c.get("/api/health").json()["ai"]["enabled"] is True
        rec = c.get("/api/customers/MG-100004/recommendations")
        assert rec.status_code == 200
        ex = c.post("/api/ai/explain", json={"customer_id": "MG-100004"})
        assert ex.status_code == 200
        assert ex.json()["source"] == "template_fallback" and ex.json()["explanation"] == rec.json()["reason"]
        msg = c.post("/api/ai/generate-message", json={"customer_id": "MG-100004"})
        assert msg.status_code == 200 and msg.json()["source"] == "template_fallback"
        assert msg.json()["approval_status"] == "pending_approval"
        for r in (rec, ex, msg, c.get("/api/health")):
            assert "sk-test-secret" not in r.text


def test_message_draft_follows_tonality_and_rules(client, portfolio):
    for tone in ("du", "sie"):
        d = next(d for d in portfolio if d.recommended and d.state.tonality.value == tone
                 and d.recommended.channel == "newsletter_email")
        m = client.post("/api/ai/generate-message", json={"customer_id": d.customer_id}).json()
        assert m["tonality"] == tone and m["validation"]["passed"], m
        assert "€" not in m["body"] and "%" not in m["body"]


def test_validators_reject_invented_numbers_and_urgency():
    ai = AIService(AppSettings())
    facts = {"expected_dclv_eur": 66.5, "current_clv_eur": 167.05}
    assert ai.validate_explanation("Expected gain 66.5 EUR on a CLV of 167.05 EUR.", facts)["passed"]
    assert not ai.validate_explanation("Expected gain 120 EUR with 90% churn.", facts)["passed"]
    assert not ai.validate_message("Nur heute: 20 % Rabatt für Sie!", "sie", "newsletter_email")["passed"]
    assert not ai.validate_message("Hallo, wir haben ein Angebot für dich und Sie.", "du", "newsletter_email")["passed"]
    assert ai.validate_message("Guten Tag, Details finden Sie im Kundenportal.", "sie", "sms")["passed"]
