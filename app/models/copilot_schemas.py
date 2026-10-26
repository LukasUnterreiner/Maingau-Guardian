"""Request and response models for Lighty's employee copilot endpoints."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Language = Literal["de", "en"]


class CopilotChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str = Field(..., min_length=1, max_length=20, examples=["MG-100004"])
    message: str = Field(..., min_length=1, max_length=2000, examples=["Wie sollte ich mit diesem Kunden umgehen?"])
    conversation_id: str | None = Field(None, max_length=64, description="Omit to start a new conversation.")
    language: Language = Field("de", description="Language of the guidance. Customer wording is always German.")
    require_llm: bool = Field(False, description="If true, answer 503 instead of the deterministic fallback when "
                                                 "the AI model is unavailable.")


class SourceReference(BaseModel):
    ref_id: str
    table: str = Field(..., description="Source table, 'event_stream' or 'lighty_engine' for computed values.")
    record_id: str | None = Field(None, description="Primary key of the record; null for an absence check "
                                                    "(see note).")
    fields: list[str]
    occurred_at: str | None = None
    note: str | None = None


class CopilotFact(BaseModel):
    fact_id: str
    key: str
    section: Literal["customer_information", "customer_experience", "marketing", "decision_intelligence"]
    kind: Literal["verified_fact", "engine_computed", "data_gap"]
    text: str
    value: Any = None
    source_refs: list[str]
    topics: list[str]


class CopilotWarning(BaseModel):
    code: str
    message: str


class Uncertainty(BaseModel):
    level: Literal["high", "medium", "low"] = Field(..., description="Confidence that the answer is fully covered "
                                                                     "by the data.")
    reasons: list[str]
    data_gaps: list[str]
    assumptions: list[str]


class RecommendedActionSummary(BaseModel):
    decision_id: str
    product_id: str = Field(..., description="Product id or NO_CONTACT.")
    product_name: str
    action_type: str
    channel: str
    process: str
    expected_dclv_eur: float
    current_clv_eur: float
    acceptance_probability: float | None
    required_service_workflow: bool
    requires_human_approval: bool
    approval_status: str
    sales_restricted: bool
    restriction_codes: list[str]
    engine_reason: str
    engine_version: str
    source: Literal["lighty_engine"]
    fact_ids: list[str]


class SuggestedCustomerMessage(BaseModel):
    kind: Literal["call_opening", "written_draft"]
    text: str
    subject: str | None = None
    channel: str | None = None
    tonality: Literal["du", "sie"]
    language: Literal["de"]
    source: Literal["template", "llm"]
    fact_ids: list[str]
    requires_human_approval: Literal[True]
    auto_send: Literal[False]
    decision_id: str | None = None
    validation: dict[str, Any]


class AnswerOrigin(BaseModel):
    response: Literal["deterministic_rules", "llm"]
    suggested_customer_message: Literal["template", "llm"] | None
    llm_used: bool
    model: str | None
    fallback_reason: str | None


class AnswerParts(BaseModel):
    verified_fact_ids: list[str]
    engine_computed_fact_ids: list[str]
    data_gap_fact_ids: list[str]
    generated_fields: list[str]


class CopilotChatResponse(BaseModel):
    conversation_id: str
    customer_id: str
    turn: int
    language: Language
    intents: list[str]
    response: str
    recommended_action: RecommendedActionSummary
    suggested_customer_message: SuggestedCustomerMessage | None
    supporting_facts: list[CopilotFact]
    source_references: list[SourceReference]
    warnings: list[CopilotWarning]
    confidence_or_uncertainty: Uncertainty
    answer_origin: AnswerOrigin
    answer_parts: AnswerParts
    created_at: str


class BriefingSection(BaseModel):
    title: str
    text: str
    items: list[str]
    fact_ids: list[str]


class BriefingSections(BaseModel):
    customer_overview: BriefingSection
    current_situation: BriefingSection
    recommended_approach: BriefingSection
    suggested_opening: BriefingSection
    what_to_avoid: BriefingSection
    next_best_action: BriefingSection
    economic_rationale: BriefingSection


class BriefingResponse(BaseModel):
    customer_id: str
    as_of: str
    language: Language
    tonality: Literal["du", "sie"]
    sections: BriefingSections
    recommended_action: RecommendedActionSummary
    suggested_customer_message: SuggestedCustomerMessage
    supporting_facts: list[CopilotFact]
    source_references: list[SourceReference]
    warnings: list[CopilotWarning]
    confidence_or_uncertainty: Uncertainty
    answer_origin: AnswerOrigin
    generated_at: str


class UntrustedCustomerText(BaseModel):
    text_id: str
    kind: str
    ref_id: str
    text: str
    flagged_as_instruction_like: bool
    label: str


class WithheldInfo(BaseModel):
    category: str
    count: int | None
    reason: str


class ContextSections(BaseModel):
    customer_information: list[CopilotFact]
    customer_experience: list[CopilotFact]
    marketing: list[CopilotFact]
    decision_intelligence: list[CopilotFact]


class CustomerContextResponse(BaseModel):
    customer_id: str
    as_of: str
    language: Language
    employee_role: str
    sections: ContextSections
    data_gaps: list[CopilotFact]
    withheld: list[WithheldInfo]
    untrusted_customer_texts: list[UntrustedCustomerText]
    source_references: list[SourceReference]
    recommended_action: RecommendedActionSummary
    selection: dict[str, Any] | None


class ConversationMessage(BaseModel):
    turn: int
    author: Literal["employee", "lighty"]
    content: str
    created_at: str
    payload: dict[str, Any] | None = Field(None, description="Full structured answer for 'lighty' messages.")


class ConversationResponse(BaseModel):
    conversation_id: str
    customer_id: str
    employee_id: str
    employee_role: str
    created_at: str
    updated_at: str
    turns: int
    messages: list[ConversationMessage]


class ConversationSummary(BaseModel):
    conversation_id: str
    customer_id: str
    employee_id: str
    employee_role: str
    created_at: str
    updated_at: str
    turns: int


class ConversationList(BaseModel):
    items: list[ConversationSummary]
    total: int


class SuggestedQuestion(BaseModel):
    question: str
    intent: str


class SuggestedQuestions(BaseModel):
    customer_id: str
    language: Language
    questions: list[SuggestedQuestion]


class EmployeeInfo(BaseModel):
    employee_id: str
    role: str
    auth_mode: str
    permissions: list[str]
