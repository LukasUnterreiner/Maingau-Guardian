"""Thin client for the Lighty backend (see API_CONTRACT.md). No Streamlit imports, so it can be tested on its own.

The base URL comes from LIGHTY_API_URL (default http://localhost:8000). The employee token is passed in per call;
it is never logged or put into a URL.
"""
from __future__ import annotations

import os
from typing import Any

import requests

API_URL = os.environ.get("LIGHTY_API_URL", "http://localhost:8000").rstrip("/")
ADMIN_TOKEN = os.environ.get("LIGHTY_ADMIN_TOKEN", "")   # only needed when the backend sets ADMIN_TOKEN
TIMEOUT_S = 15
CHAT_TIMEOUT_S = 35        # a little above the backend's AI_TIMEOUT_S (20 s), see API_CONTRACT.md §5.1

# The four decision groups of the Lighty design, keyed by the backend's action_type.
DECISION_GROUP = {"sales": "Offer", "upsell": "Offer", "one_off": "Offer", "service": "Resolve an issue",
                  "retention": "Strengthen loyalty", "no_contact": "Do not contact"}


class LightyError(Exception):
    """An error answer from the backend, or the backend could not be reached (status 0)."""

    def __init__(self, status: int, error: str, detail: Any):
        self.status, self.error, self.detail = status, error, detail
        super().__init__(f"{status} {error}: {detail}")

    @property
    def message(self) -> str:
        if self.status == 0:
            return "Lighty is not reachable right now. Please try again in a moment."
        if isinstance(self.detail, list):   # validation_error: [{loc, msg, type}]
            return "; ".join(str(d.get("msg", d)) for d in self.detail)
        return str(self.detail)


def _request(method: str, path: str, token: str | None = None, *, admin: bool = False,
             timeout: float = TIMEOUT_S, **kwargs) -> dict:
    headers = {}
    if token:
        headers["X-Employee-Token"] = token
    if admin and ADMIN_TOKEN:
        headers["X-Admin-Token"] = ADMIN_TOKEN
    try:
        resp = requests.request(method, f"{API_URL}{path}", headers=headers, timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        raise LightyError(0, "unreachable", type(exc).__name__) from None
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.status_code >= 400:
        raise LightyError(resp.status_code, body.get("error", "http_error"), body.get("detail", resp.reason))
    return body


def health() -> dict:
    return _request("GET", "/api/health")


def me(token: str) -> dict:
    return _request("GET", "/api/copilot/me", token)


def overview(token: str) -> dict:
    return _request("GET", "/api/marketing/overview", token, timeout=60)


def decisions(token: str, *, approval_status: str | None = "pending_approval", action_type: str | None = None,
              channel: str | None = None, page: int = 1, page_size: int = 100) -> dict:
    params = {"page": page, "page_size": page_size, "approval_status": approval_status,
              "action_type": action_type, "channel": channel}
    return _request("GET", "/api/marketing/recommendations", token, timeout=60,
                    params={k: v for k, v in params.items() if v is not None})


def customers(token: str, *, search: str | None = None, has_service_issue: bool | None = None,
              page: int = 1, page_size: int = 50) -> dict:
    params = {"page": page, "page_size": page_size, "search": search or None, "has_service_issue": has_service_issue}
    return _request("GET", "/api/customers", token, params={k: v for k, v in params.items() if v is not None})


def recommendation(token: str, customer_id: str) -> dict:
    return _request("GET", f"/api/customers/{customer_id}/recommendations", token)


def suggested_questions(token: str, customer_id: str) -> list[dict]:
    return _request("GET", "/api/copilot/suggested-questions", token,
                    params={"customer_id": customer_id}).get("questions", [])


def review(token: str, decision_id: str, approve: bool, reviewer: str, note: str | None = None) -> dict:
    """Approve or reject one decision. 409 means it was already reviewed or is no longer permitted."""
    action = "approve" if approve else "reject"
    return _request("POST", f"/api/decisions/{decision_id}/{action}", token, admin=True,
                    json={"reviewer": reviewer, "note": note})


def chat(token: str, customer_id: str, message: str, conversation_id: str | None = None) -> dict:
    body = {"customer_id": customer_id, "message": message}
    if conversation_id:
        body["conversation_id"] = conversation_id
    return _request("POST", "/api/copilot/chat", token, json=body, timeout=CHAT_TIMEOUT_S)
