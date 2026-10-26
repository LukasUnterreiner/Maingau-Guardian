"""Lighty employee copilot API. Every route authenticates the employee first."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Request

from app.models.copilot_schemas import (
    BriefingResponse, ConversationList, ConversationResponse, CopilotChatRequest, CopilotChatResponse,
    CustomerContextResponse, EmployeeInfo, Language, SuggestedQuestions,
)
from app.models.schemas import ErrorResponse
from app.services.access_control import Employee
from app.services.lighty import Lighty

router = APIRouter(prefix="/api")
ERRORS = {code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422)}


def lighty(request: Request) -> Lighty:
    return request.app.state.lighty


def current_employee(request: Request,
                     x_employee_token: str | None = Header(default=None),
                     x_employee_id: str | None = Header(default=None, description="Dev mode only"),
                     x_employee_role: str | None = Header(default=None, description="Dev mode only")) -> Employee:
    return lighty(request).access.authenticate(x_employee_token, x_employee_id, x_employee_role)


@router.get("/copilot/me", response_model=EmployeeInfo, responses=ERRORS, tags=["copilot"])
def me(employee: Employee = Depends(current_employee)):
    return employee.public()


@router.post("/copilot/chat", response_model=CopilotChatResponse, responses={**ERRORS, 503: {"model": ErrorResponse}},
             tags=["copilot"])
def chat(body: CopilotChatRequest, employee: Employee = Depends(current_employee), g: Lighty = Depends(lighty)):
    return g.copilot.chat(employee, body.customer_id, body.message, body.conversation_id, body.language,
                          body.require_llm)


@router.get("/customers/{customer_id}/briefing", response_model=BriefingResponse, responses=ERRORS, tags=["copilot"])
def briefing(customer_id: str, language: Language = "de", use_ai: bool = True,
             employee: Employee = Depends(current_employee), g: Lighty = Depends(lighty)):
    return g.copilot.briefing(employee, customer_id, language, use_ai)


@router.get("/customers/{customer_id}/context", response_model=CustomerContextResponse, responses=ERRORS,
            tags=["copilot"])
def context(customer_id: str, question: str | None = Query(None, max_length=2000), language: Language = "de",
            include_product_status: bool = False, employee: Employee = Depends(current_employee),
            g: Lighty = Depends(lighty)):
    return g.copilot.context(employee, customer_id, question, language, include_product_status)


@router.get("/copilot/conversations", response_model=ConversationList, responses=ERRORS, tags=["copilot"])
def conversations(customer_id: str | None = None, all_employees: bool = False,
                  employee: Employee = Depends(current_employee), g: Lighty = Depends(lighty)):
    return g.copilot.conversations(employee, customer_id, all_employees)


@router.get("/copilot/conversations/{conversation_id}", response_model=ConversationResponse, responses=ERRORS,
            tags=["copilot"])
def conversation(conversation_id: str, employee: Employee = Depends(current_employee), g: Lighty = Depends(lighty)):
    return g.copilot.conversation(employee, conversation_id)


@router.get("/copilot/suggested-questions", response_model=SuggestedQuestions, responses=ERRORS, tags=["copilot"])
def suggested_questions(customer_id: str, language: Language = "de", employee: Employee = Depends(current_employee),
                        g: Lighty = Depends(lighty)):
    return g.copilot.suggested_questions(employee, customer_id, language)
