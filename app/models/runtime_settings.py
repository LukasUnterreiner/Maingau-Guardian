"""Runtime settings editable by authorised internal users.

Validation bounds make sure the settings can only tighten, never loosen, the
hard compliance rules (e.g. the contact limit has a hard upper cap, the
service action cannot be disabled, consent rules are not configurable at all).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

HARD_MAX_CONTACTS_30D = 4  # upper cap: settings cannot allow more marketing contacts than this


class ContactPolicy(BaseModel):
    max_marketing_contacts_30d: int = Field(
        2, ge=0, le=HARD_MAX_CONTACTS_30D,
        description="Maximum delivered marketing actions per customer in the trailing 30 days. "
                    "Policy default (the dataset defines no limit).")
    min_days_between_marketing_contacts: int = Field(
        7, ge=0, le=90, description="Minimum days since the last delivered marketing action.")


class ActionPriority(BaseModel):
    enabled: bool = True
    priority: int = Field(0, ge=-10, le=10, description="Tie-breaker only; never changes the economic value.")


class SimulationDefaults(BaseModel):
    pseudo_count: float = Field(20.0, ge=0.0, le=500.0, description="Beta-prior strength for p_accept smoothing.")
    p_accept_mode: Literal["observed_conversion", "net_of_control"] = "observed_conversion"
    exclude_unconsented_history: bool = True
    baseline_policy: Literal["conventional_sales_first", "no_contact"] = "conventional_sales_first"
    min_expected_dclv_eur: float = Field(0.0, ge=0.0, le=100.0,
                                         description="A proactive action must beat no-contact by at least this.")


class RuntimeSettings(BaseModel):
    contact_policy: ContactPolicy = ContactPolicy()
    action_priorities: dict[str, ActionPriority] = Field(default_factory=dict)
    simulation: SimulationDefaults = SimulationDefaults()

    @field_validator("action_priorities")
    @classmethod
    def _service_cannot_be_disabled(cls, v: dict[str, ActionPriority]) -> dict[str, ActionPriority]:
        sv = v.get("P-SV-01")
        if sv is not None and not sv.enabled:
            raise ValueError("P-SV-01 (service resolution) is a required service workflow and cannot be disabled")
        return v


class RuntimeSettingsUpdate(BaseModel):
    """Partial update; omitted sections stay unchanged."""
    contact_policy: ContactPolicy | None = None
    action_priorities: dict[str, ActionPriority] | None = None
    simulation: SimulationDefaults | None = None
