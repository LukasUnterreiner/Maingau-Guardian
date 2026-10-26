"""Pydantic request/response models — the API contract (see API_CONTRACT.md)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CHANNELS = Literal["newsletter_email", "portal_popup", "app_push", "sms", "outbound_call", "service_email",
                   "service_call", "none"]


class ErrorResponse(BaseModel):
    error: str
    detail: Any = None


# ----------------------------------------------------------------- health
class HealthResponse(BaseModel):
    status: str
    customers_loaded: int
    products_loaded: int
    events_loaded: int
    snapshot_at: str
    default_as_of: str
    settings_version: int
    ai: dict[str, Any]
    data_quality: dict[str, Any]
    acceptance_model: dict[str, Any]
    employee_auth: dict[str, Any] = {}


# --------------------------------------------------------------- customers
class CustomerSummary(BaseModel):
    customer_id: str
    city: str | None
    customer_since: str | None
    business_lines: list[str]
    current_clv_eur: float
    churn_probability: float
    churn_drivers: list[str] = []
    clv_service_impact_reported_eur: float | None = None
    cancellation_pending: bool = False
    has_service_issue: bool
    open_complaint: bool
    tonality: Literal["du", "sie"]


class CustomerListResponse(BaseModel):
    items: list[CustomerSummary]
    page: int
    page_size: int
    total: int
    total_pages: int
    as_of: str


class Customer360Response(BaseModel):
    model_config = ConfigDict(extra="allow")
    customer_id: str
    as_of: str
    profile: dict[str, Any]
    business_lines: list[str]
    contracts: dict[str, list[dict[str, Any]]]
    products_held: list[str]
    product_holdings: dict[str, bool | None]
    shop_orders: list[dict[str, Any]]
    value: dict[str, Any]
    churn_drivers: list[dict[str, Any]]
    churn_drivers_snapshot: list[str]
    structural_churn: float | None
    service: dict[str, Any]
    marketing_history: dict[str, Any]
    communication: dict[str, Any]
    consents: dict[str, dict[str, Any]]
    signals: dict[str, Any]
    eligible_actions: list[dict[str, Any]]
    blocked_actions: list[dict[str, Any]]
    applied_events: list[dict[str, Any]]


# --------------------------------------------------------- recommendations
class EligibilityCheck(BaseModel):
    check: str
    passed: bool
    code: str | None
    detail: str


class ActionOption(BaseModel):
    product_id: str
    product_name: str
    action_type: str
    business_line: str | None
    channel: str
    process: Literal["marketing", "service", "customer_inquiry_reply", "none"]
    executable: bool
    acceptance_probability: float | None
    acceptance_source: str
    acceptance_observations: int
    control_group_rate: float | None
    contact_cost_eur: float
    churn_now: float
    churn_after_accept: float
    churn_after_reject: float
    clv_after_accept_eur: float
    clv_after_reject_eur: float
    expected_dclv_eur: float
    estimated_clv_after_eur: float
    added_annual_margin_eur: float
    one_off_margin_eur: float
    removed_churn_drivers: list[str]
    service_case_contact_penalty: bool
    exclusion_reasons: list[str]
    notes: list[str]
    value_label: str


class RecommendationResponse(BaseModel):
    customer_id: str
    decision_id: str
    as_of: str
    recommended_action: str
    recommended_action_name: str
    action_type: Literal["sales", "upsell", "one_off", "retention", "service", "no_contact"]
    product_id: str | None
    channel: str
    process: Literal["marketing", "service", "customer_inquiry_reply", "none"]
    tonality: Literal["du", "sie"]
    tonality_source: str
    current_clv_eur: float
    expected_dclv_eur: float
    estimated_clv_after_eur: float
    acceptance_probability: float | None
    churn_now: float
    churn_after_accept: float
    churn_after_reject: float
    required_service_workflow: bool
    requires_human_approval: bool
    approval_status: Literal["not_required", "pending_approval", "approved", "rejected"]
    reason: str
    alternatives: list[ActionOption]
    blocked_actions: list[ActionOption]
    eligibility_checks: list[EligibilityCheck]
    value_labels: dict[str, str]
    engine_version: str


# -------------------------------------------------------------- simulation
class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acceptance_probability_overrides: dict[str, float] = Field(default_factory=dict,
                                                               description="product_id -> probability in [0,1]")
    acceptance_probability_multiplier: float = Field(1.0, ge=0.0, le=10.0)
    contact_cost_overrides: dict[str, float] = Field(default_factory=dict, description="channel -> EUR >= 0")
    service_resolution_cost_eur: float | None = Field(None, ge=0, le=1000)
    churn_now_override: float | None = Field(None, ge=0, le=0.99)
    churn_delta: float = Field(0.0, ge=-0.5, le=0.5)
    contact_during_service_case: float | None = Field(None, ge=0, le=0.5)
    discount_rate: float | None = Field(None, ge=0, le=0.5)
    horizon_years: int | None = Field(None, ge=1, le=30)
    baseline_policy: Literal["conventional_sales_first", "no_contact"] | None = None
    as_of: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "SimulationRequest":
        for k, v in self.acceptance_probability_overrides.items():
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"acceptance probability for {k} must be in [0,1]")
        allowed = {"newsletter_email", "portal_popup", "app_push", "sms", "outbound_call", "service_email", "service_call"}
        for k, v in self.contact_cost_overrides.items():
            if k not in allowed:
                raise ValueError(f"unknown channel {k}")
            if not 0.0 <= v <= 1000:
                raise ValueError(f"contact cost for {k} must be in [0,1000]")
        return self


class SimulationResponse(BaseModel):
    customer_id: str
    decision_id: str
    base_decision_id: str
    as_of: str
    assumptions_applied: dict[str, Any]
    base: dict[str, Any]
    scenario: dict[str, Any]
    recommendation_changed: bool
    parameter_attribution: list[dict[str, Any]]
    blocked_actions: list[dict[str, Any]]
    compliance_unchanged: bool
    baseline: dict[str, Any]
    value_label: str


# --------------------------------------------------------------- marketing
class MarketingRecommendationItem(BaseModel):
    customer_id: str
    decision_id: str
    recommended_action: str
    recommended_action_name: str
    action_type: str
    business_line: str | None
    channel: str
    tonality: str
    current_clv_eur: float
    expected_dclv_eur: float
    acceptance_probability: float | None
    required_service_workflow: bool
    approval_status: str
    segment: str


class MarketingRecommendationList(BaseModel):
    items: list[MarketingRecommendationItem]
    page: int
    page_size: int
    total: int
    total_pages: int


class MarketingOverview(BaseModel):
    model_config = ConfigDict(extra="allow")
    total_customers_evaluated: int
    as_of: str | None
    marketing_actions: dict[str, Any]
    recommended_action_distribution: dict[str, int]
    recommended_by_action_type: dict[str, int]
    recommended_by_business_line: dict[str, int]
    recommended_by_channel: dict[str, int]
    customers_with_active_service_issues: int
    pending_approvals: int
    total_current_clv_eur: float
    total_projected_incremental_clv_eur: float
    baseline: dict[str, Any]
    projected_protected_customer_value_eur: float
    projected_protected_customer_value_label: str
    value_by_segment: dict[str, dict[str, Any]]
    value_by_clv_tier: dict[str, dict[str, Any]]
    settings_version: int


class SettingsResponse(BaseModel):
    version: int
    settings: dict[str, Any]
    known_product_ids: list[str]
    hard_rules_note: str


# ------------------------------------------------------------------ review
class ReviewRequest(BaseModel):
    reviewer: str | None = Field(None, max_length=100)
    note: str | None = Field(None, max_length=1000)


class ReviewResponse(BaseModel):
    decision_id: str
    customer_id: str
    approval_status: str
    reviewer: str | None
    review_note: str | None
    reviewed_at: str | None


# ---------------------------------------------------------------------- AI
class AIRequest(BaseModel):
    customer_id: str | None = None
    decision_id: str | None = None

    @model_validator(mode="after")
    def _one(self) -> "AIRequest":
        if not self.customer_id and not self.decision_id:
            raise ValueError("Provide customer_id or decision_id")
        return self


class ExplainResponse(BaseModel):
    customer_id: str
    decision_id: str
    recommended_action: str
    explanation: str
    source: Literal["llm", "template_fallback"]
    fallback_reason: str | None
    validation: dict[str, Any]
    facts_used: dict[str, Any]


class MessageResponse(BaseModel):
    customer_id: str
    decision_id: str
    message_id: int
    channel: str
    tonality: Literal["du", "sie"]
    language: str
    preferred_contact_language: str | None
    subject: str | None
    body: str
    source: Literal["llm", "template_fallback"]
    fallback_reason: str | None
    validation: dict[str, Any]
    approval_status: str
    requires_human_approval: bool
