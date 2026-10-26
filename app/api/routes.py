"""Lighty REST API. Routes are thin: validation in, facade call, validated model out."""
from __future__ import annotations

import hmac
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from app.models.runtime_settings import RuntimeSettingsUpdate
from app.models.schemas import (
    AIRequest, Customer360Response, CustomerListResponse, ErrorResponse, ExplainResponse, HealthResponse,
    MarketingOverview, MarketingRecommendationList, MessageResponse, RecommendationResponse, RegionsResponse,
    ReviewRequest, ReviewResponse, SettingsResponse, SimulationRequest, SimulationResponse,
)
from app.services.clv_engine import ScenarioParams
from app.services.lighty import Lighty
from app.services.recommendation_engine import POverrides

router = APIRouter(prefix="/api")
ERRORS = {code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422)}


def lighty(request: Request) -> Lighty:
    return request.app.state.lighty


def customer_data_guard(request: Request, x_employee_token: str | None = Header(default=None),
                        x_employee_id: str | None = Header(default=None),
                        x_employee_role: str | None = Header(default=None)) -> None:
    """Employee auth on the customer/marketing/AI endpoints, only when PROTECT_CUSTOMER_ENDPOINTS=true."""
    if request.app.state.settings.protect_customer_endpoints:
        emp = request.app.state.lighty.access.authenticate(x_employee_token, x_employee_id, x_employee_role)
        emp.require("customer_context")


GUARD = [Depends(customer_data_guard)]


def require_admin(request: Request, x_admin_token: str | None = Header(default=None)) -> str:
    """Internal-user check for settings and approvals. Open when ADMIN_TOKEN is unset (local dev)."""
    expected = request.app.state.settings.admin_token
    if expected is None or not expected.get_secret_value():
        return "dev-unauthenticated"
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected.get_secret_value()):
        raise HTTPException(status_code=401, detail="Missing or invalid X-Admin-Token")
    return "admin-token"


# ------------------------------------------------------------------ health
@router.get("/health", response_model=HealthResponse, tags=["health"])
def health(g: Lighty = Depends(lighty)):
    return g.health()


# --------------------------------------------------------------- customers
@router.get("/customers", response_model=CustomerListResponse, tags=["customers"], dependencies=GUARD)
def list_customers(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
                   business_line: Literal["energy", "mobile", "e_mobility", "smart_living"] | None = None,
                   has_service_issue: bool | None = None, search: str | None = Query(None, max_length=20),
                   as_of: str | None = None, g: Lighty = Depends(lighty)):
    return g.list_customers(page, page_size, business_line, has_service_issue, search, as_of)


@router.get("/customers/{customer_id}", response_model=Customer360Response, responses=ERRORS, tags=["customers"],
            dependencies=GUARD)
def get_customer(customer_id: str, as_of: str | None = None, g: Lighty = Depends(lighty)):
    return g.customer_360(customer_id, as_of)


@router.get("/customers/{customer_id}/recommendations", response_model=RecommendationResponse, responses=ERRORS,
            tags=["lighty"], dependencies=GUARD)
def get_recommendation(customer_id: str, as_of: str | None = None, g: Lighty = Depends(lighty)):
    return g.recommend(customer_id, as_of)


@router.post("/customers/{customer_id}/simulate", response_model=SimulationResponse, responses=ERRORS,
             tags=["lighty"], dependencies=GUARD)
def simulate(customer_id: str, body: SimulationRequest, g: Lighty = Depends(lighty)):
    params = ScenarioParams(
        discount_rate=body.discount_rate, horizon_years=body.horizon_years,
        churn_now_override=body.churn_now_override, churn_delta=body.churn_delta,
        contact_cost_overrides=dict(body.contact_cost_overrides),
        service_resolution_cost_eur=body.service_resolution_cost_eur,
        contact_during_service_case=body.contact_during_service_case)
    unknown = set(body.acceptance_probability_overrides) - set(g.ds.products)
    if unknown:
        raise ValueError(f"Unknown product ids: {sorted(unknown)}")
    p_over = POverrides(by_product=dict(body.acceptance_probability_overrides),
                        multiplier=body.acceptance_probability_multiplier)
    return g.simulate(customer_id, params, p_over, body.baseline_policy, body.as_of)


# --------------------------------------------------------------- marketing
@router.get("/marketing/overview", response_model=MarketingOverview, tags=["marketing"], dependencies=GUARD)
def marketing_overview(g: Lighty = Depends(lighty)):
    return g.overview()


@router.get("/marketing/recommendations", response_model=MarketingRecommendationList, tags=["marketing"],
            dependencies=GUARD)
def marketing_recommendations(
        page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
        action_type: Literal["sales", "upsell", "one_off", "retention", "service", "no_contact"] | None = None,
        channel: str | None = None, business_line: str | None = None,
        approval_status: Literal["not_required", "pending_approval", "approved", "rejected"] | None = None,
        include_no_contact: bool = False, g: Lighty = Depends(lighty)):
    if action_type == "no_contact":
        include_no_contact = True
    return g.marketing_recommendations(page, page_size, action_type, channel, business_line, approval_status,
                                       include_no_contact)


@router.get("/marketing/regions", response_model=RegionsResponse, tags=["marketing"], dependencies=GUARD)
def marketing_regions(level: Literal["state", "city"] = "state",
                      state: str | None = Query(None, pattern=r"^(DE-[A-Z]{2}|unassigned)$"),
                      g: Lighty = Depends(lighty)):
    """Customers, churn risk, value and workload per state or city (reporting only, never used for decisions)."""
    return g.regions(level, state)


@router.get("/marketing/settings", response_model=SettingsResponse, tags=["marketing"])
def get_settings(g: Lighty = Depends(lighty)):
    return g.get_settings()


@router.put("/marketing/settings", response_model=SettingsResponse, responses={401: {"model": ErrorResponse}, **ERRORS},
            tags=["marketing"])
def put_settings(body: RuntimeSettingsUpdate, user: str = Depends(require_admin), g: Lighty = Depends(lighty)):
    return g.update_settings(body, user)


# ------------------------------------------------------------------ review
@router.post("/decisions/{decision_id}/approve", response_model=ReviewResponse,
             responses={401: {"model": ErrorResponse}, **ERRORS}, tags=["review"])
def approve(decision_id: str, body: ReviewRequest | None = None, user: str = Depends(require_admin),
            g: Lighty = Depends(lighty)):
    body = body or ReviewRequest()
    return g.review(decision_id, True, body.reviewer or user, body.note)


@router.post("/decisions/{decision_id}/reject", response_model=ReviewResponse,
             responses={401: {"model": ErrorResponse}, **ERRORS}, tags=["review"])
def reject(decision_id: str, body: ReviewRequest | None = None, user: str = Depends(require_admin),
           g: Lighty = Depends(lighty)):
    body = body or ReviewRequest()
    return g.review(decision_id, False, body.reviewer or user, body.note)


# ---------------------------------------------------------------------- AI
@router.post("/ai/explain", response_model=ExplainResponse, responses=ERRORS, tags=["ai"], dependencies=GUARD)
def ai_explain(body: AIRequest, g: Lighty = Depends(lighty)):
    return g.ai_explain(body.customer_id, body.decision_id)


@router.post("/ai/generate-message", response_model=MessageResponse, responses=ERRORS, tags=["ai"], dependencies=GUARD)
def ai_message(body: AIRequest, g: Lighty = Depends(lighty)):
    return g.ai_message(body.customer_id, body.decision_id)
