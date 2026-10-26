"""Employee authentication and role-based access for Lighty's copilot.

Tokens come from ``EMPLOYEE_TOKENS`` ("token:employee_id:role,..."). The token is
sent in the ``X-Employee-Token`` header and compared in constant time. With no
tokens configured, requests are refused unless ``ALLOW_DEV_AUTH=true`` (local
development), where ``X-Employee-Id`` / ``X-Employee-Role`` are trusted as sent.

Roles and what they may see
---------------------------
* service_agent  customer context incl. ticket texts and call transcripts, copilot
* sales_agent    customer context without free text, copilot
* marketing      customer context without free text, copilot
* admin          everything, incl. every employee's conversations
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass

from app.config.settings import AppSettings

ROLES = ("service_agent", "sales_agent", "marketing", "admin")
PERMISSIONS: dict[str, frozenset[str]] = {
    "service_agent": frozenset({"customer_context", "copilot", "free_text"}),
    "sales_agent": frozenset({"customer_context", "copilot"}),
    "marketing": frozenset({"customer_context", "copilot"}),
    "admin": frozenset({"customer_context", "copilot", "free_text", "all_conversations"}),
}


class Unauthorized(Exception):
    pass


class Forbidden(Exception):
    pass


@dataclass(frozen=True)
class Employee:
    employee_id: str
    role: str
    auth_mode: str  # "token" | "dev"

    def can(self, permission: str) -> bool:
        return permission in PERMISSIONS.get(self.role, frozenset())

    def require(self, permission: str) -> None:
        if not self.can(permission):
            raise Forbidden(f"Role '{self.role}' may not use '{permission}'")

    def public(self) -> dict[str, object]:
        return {"employee_id": self.employee_id, "role": self.role, "auth_mode": self.auth_mode,
                "permissions": sorted(PERMISSIONS.get(self.role, frozenset()))}


def parse_tokens(raw: str) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        parts = item.split(":")
        if len(parts) != 3 or not all(p.strip() for p in parts):
            raise ValueError("EMPLOYEE_TOKENS entries must look like token:employee_id:role")
        token, emp, role = (p.strip() for p in parts)
        if role not in ROLES:
            raise ValueError(f"Unknown role '{role}' in EMPLOYEE_TOKENS; use one of {', '.join(ROLES)}")
        if len(token) < 12:
            raise ValueError("EMPLOYEE_TOKENS tokens must be at least 12 characters")
        out[token] = (emp, role)
    return out


class AccessControl:
    def __init__(self, settings: AppSettings):
        raw = settings.employee_tokens.get_secret_value() if settings.employee_tokens else ""
        self._tokens = parse_tokens(raw)
        self._allow_dev = settings.allow_dev_auth

    @property
    def mode(self) -> str:
        if self._tokens:
            return "token"
        return "dev" if self._allow_dev else "not_configured"

    def authenticate(self, token: str | None, dev_employee_id: str | None = None,
                     dev_role: str | None = None) -> Employee:
        if self._tokens:
            if token:
                for known, (emp, role) in self._tokens.items():
                    if hmac.compare_digest(token.encode(), known.encode()):
                        return Employee(emp, role, "token")
            raise Unauthorized("Missing or invalid X-Employee-Token")
        if self._allow_dev:
            role = dev_role or "service_agent"
            if role not in ROLES:
                raise Unauthorized(f"Unknown X-Employee-Role '{role}'")
            emp = (dev_employee_id or "dev-employee").strip()[:64] or "dev-employee"
            return Employee(emp, role, "dev")
        raise Unauthorized("Employee authentication is not configured: set EMPLOYEE_TOKENS "
                           "(or ALLOW_DEV_AUTH=true for local development only)")
