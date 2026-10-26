# Lighty — API Contract v1.1

**Lighty — Smarter decisions. Better conversations.** (formerly *MAINGAU Guardian*)

This is the contract for the frontend team. Response structures in this document are
stable for `engine_version = lighty-1.1.0`. New fields may be **added**; existing fields
will not be renamed, removed or change type without a version bump. What changed from v1
(Guardian) is listed in [section 7](#7-changes-in-v11-lighty); no existing endpoint or field was removed.

Interactive docs: `GET /docs` (Swagger UI) and `GET /openapi.json`.
All JSON examples below are real responses from the dataset (arrays shortened with `…`).

## 1. Conventions

| Topic | Rule |
|---|---|
| Base URL | Local: `http://localhost:8000`. Server (wsvm39): `http://130.83.85.181:39080` (→ VM port 80 → container 8000). |
| Prefix | Every endpoint lives under `/api`. |
| Content type | `application/json; charset=utf-8`. German text is UTF‑8. |
| Money | `*_eur` fields are floats in EUR, rounded to 2 decimals. |
| Probabilities | Floats in `[0, 1]` (`0.1099` = 10.99 %). `churn_*` are 12‑month probabilities. |
| Timestamps | Strings `YYYY-MM-DD HH:MM:SS` (dataset local time, no time zone). Review timestamps are ISO‑8601 UTC. |
| Unknown values | `null` means *unknown*, never *no*. E.g. `product_holdings["P-IN-01"] = null` = holding not in data. |
| Value labels | Every money/probability figure is **observed** (from the dataset), **estimated** (model) or **simulated** (scenario). See `value_labels` / `value_label`. Lighty values are model-based estimates, not realised savings or causal uplift. |
| Point in time | Optional `as_of` query/body parameter: `latest` (default, snapshot + full event stream), `snapshot` (2026‑09‑30 23:59:59, no events) or an ISO timestamp such as `2026-10-01T10:15:00`. |
| Pagination | `page` (≥1) and `page_size`; responses carry `items`, `page`, `page_size`, `total`, `total_pages`. |
| CORS | Allowed origins come from `CORS_ORIGINS` (default `http://localhost:3000,http://localhost:5173`). |
| Auth (admin) | `PUT /api/marketing/settings` and the approve/reject endpoints require header `X-Admin-Token` **when** the server sets `ADMIN_TOKEN`. In local dev (no token set) they are open. |
| Auth (employees) | Copilot, briefing and context endpoints always require an employee: header `X-Employee-Token` (tokens and roles from `EMPLOYEE_TOKENS`). Local development only: with `ALLOW_DEV_AUTH=true` and no tokens configured, send `X-Employee-Id` and `X-Employee-Role` instead. If `PROTECT_CUSTOMER_ENDPOINTS=true`, the customer, marketing-list and AI endpoints need the same header. `GET /api/health` → `employee_auth.mode` tells the frontend which mode is active (`token`, `dev`, `not_configured`). |
| Roles | `service_agent` (incl. ticket texts and call transcripts), `sales_agent`, `marketing` (no free text), `admin` (everything, all conversations). |

### Errors

All errors share one shape:

```json
{ "error": "not_found", "detail": "Customer MG-000000 not found" }
```

| HTTP | `error` | When |
|---|---|---|
| 401 | `http_error` | Missing/invalid `X-Admin-Token` (only if `ADMIN_TOKEN` is configured). |
| 401 | `unauthorized` | Missing/invalid `X-Employee-Token`, unknown dev role, or employee auth not configured on the server. |
| 403 | `forbidden` | The employee's role may not do this (e.g. listing other employees' conversations). |
| 404 | `not_found` | Unknown customer id, decision id or conversation id. A conversation of another employee is also reported as 404. |
| 409 | `conflict` | Approving an already reviewed decision, approving/messaging a no‑contact decision, approving an action that is no longer permitted (e.g. consent was withdrawn meanwhile), continuing a conversation with a different `customer_id`, or the conversation turn limit (`COPILOT_MAX_TURNS`, default 40) is reached. |
| 503 | `ai_unavailable` | Only when a chat request sets `require_llm: true` and the AI model is not configured or failed. Without that flag the copilot answers deterministically instead. |
| 422 | `validation_error` | Request failed schema validation. `detail` is a list of `{loc, msg, type}`. |
| 422 | `invalid_request` | Semantically invalid input (unknown product id, a setting that would loosen a hard rule…). `detail` is a string. |

```json
{ "error": "validation_error",
  "detail": [ { "loc": ["body", "churn_delta"], "msg": "Input should be less than or equal to 0.5", "type": "less_than_equal" } ] }
```

## 2. Endpoint overview

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness, data load stats, data-quality report, AI status |
| GET | `/api/customers` | Paginated customer list with filters |
| GET | `/api/customers/{customer_id}` | Customer 360° view |
| GET | `/api/customers/{customer_id}/recommendations` | Lighty decision (Next Best Action) |
| POST | `/api/customers/{customer_id}/simulate` | Counterfactual simulation |
| GET | `/api/marketing/overview` | Dashboard aggregates incl. Projected Protected Customer Value |
| GET | `/api/marketing/recommendations` | Paginated list of decisions across all customers |
| GET | `/api/marketing/settings` | Current runtime settings |
| PUT | `/api/marketing/settings` | Update runtime settings (validated, cannot loosen hard rules) |
| POST | `/api/decisions/{decision_id}/approve` | Human approval |
| POST | `/api/decisions/{decision_id}/reject` | Human rejection |
| POST | `/api/ai/explain` | Natural-language explanation (LLM or deterministic fallback) |
| POST | `/api/ai/generate-message` | German customer draft (always pending approval) |
| POST | `/api/copilot/chat` | **Employee copilot**: grounded answer to an employee's question about one customer, multi-turn |
| GET | `/api/customers/{customer_id}/briefing` | **Pre-call briefing** in seven sections |
| GET | `/api/customers/{customer_id}/context` | **Customer context** as typed, sourced facts (optionally only those relevant to a question) |
| GET | `/api/copilot/conversations` | The employee's conversations (filter by customer) |
| GET | `/api/copilot/conversations/{conversation_id}` | One conversation with all turns |
| GET | `/api/copilot/suggested-questions` | Starter questions for a customer (chips in the chat UI) |
| GET | `/api/copilot/me` | Who the server thinks the caller is (employee id, role, permissions) |

## 3. Enumerations

**`action_type`**: `sales` · `upsell` · `one_off` (shop) · `retention` · `service` · `no_contact`

**`process`**: `marketing` (needs marketing + profiling consent, frequency limits) · `service` (P‑SV‑01, service process, no sales content) · `customer_inquiry_reply` (retention offer answering the customer's own open tariff inquiry) · `none` (no contact)

**`channel`**: marketing: `newsletter_email`, `portal_popup`, `app_push`, `sms`, `outbound_call` · service: `service_email`, `service_call` · `none`

**`tonality`**: `du` · `sie` (derived from the customer's own words; `tonality_source = default_formal` when there is no text signal)

**`approval_status`**: `not_required` (no contact) · `pending_approval` · `approved` · `rejected`

**`recommended_action` / `product_id`**: product ids from `product_catalog` (`P-EN-01` … `P-SV-01`) or `NO_CONTACT`.

**Exclusion reason codes** (`exclusion_reasons[]`, `eligibility_checks[].code`):

| Code | Meaning |
|---|---|
| `CONSENT_WITHDRAWN` / `CONSENT_NOT_GIVEN` / `CONSENT_UNKNOWN` | Channel consent missing (`newsletter_email`, `marketing_sms`, `marketing_phone`, `portal_app_personalisation`). |
| `CONSENT_DOI_MISSING` | Newsletter consent without double opt-in. |
| `PROFILING_CONSENT_WITHDRAWN` / `_NOT_GIVEN` / `_UNKNOWN` | Personalised NBA needs `profiling_analytics`. |
| `OPEN_COMPLAINT_BLOCKS_MARKETING` | Open complaint ticket. |
| `DUNNING_BLOCKS_MARKETING` | Dunning level ≥ 1. |
| `CANCELLATION_PENDING_BLOCKS_MARKETING` | Cancellation received. |
| `CONTACT_FREQUENCY_LIMIT` | Max marketing contacts in 30 days reached. |
| `CONTACT_MIN_GAP` | Last marketing contact too recent. |
| `PRODUCT_ALREADY_HELD` | Customer already holds the product. |
| `PREREQUISITE_MISSING` | Target signal / technical prerequisite missing (e.g. smart meter for dynamic tariff). |
| `CHANNEL_NOT_AVAILABLE` | No portal account / app for that channel. |
| `ACTION_DISABLED_BY_SETTINGS` | Disabled by a marketing user. |
| `NO_SERVICE_ISSUE` | P‑SV‑01 without anything to resolve. |
| `NO_CUSTOMER_REQUEST` | Inquiry-reply path without an open tariff inquiry. |

## 4. Endpoints

### 4.1 `GET /api/health`

```json
{
  "status": "ok",
  "customers_loaded": 750,
  "products_loaded": 18,
  "events_loaded": 635,
  "snapshot_at": "2026-09-30 23:59:59",
  "default_as_of": "2026-10-02 02:03:52",
  "settings_version": 0,
  "ai": { "configured": false, "protocol": "openai_chat_completions", "enabled": false, "protocol_verified": false, "model": null },
  "employee_auth": { "mode": "dev", "protect_customer_endpoints": false },
  "data_quality": { "sheets": { "customer_master": { "rows": 750, "exact_duplicates_dropped": 0, "rows_without_customer_id": 0 }, "…": {} },
                    "event_stream": { "lines": 647, "duplicates_dropped": 12, "invalid_dropped": 0, "events_loaded": 635, "events_for_unknown_customers": 0 } },
  "acceptance_model": { "method": "Beta-smoothed observed 14-day conversion, global > offer > channel > tonality", "pseudo_count": 20.0,
                        "mode": "observed_conversion", "exclude_unconsented_history": true, "excluded_unconsented_actions": 297,
                        "global_treated_rate": 0.0342, "global_control_rate": 0.0202, "treated_deliveries": 1725,
                        "caveat": "Observational rates; not proven causal uplift." }
}
```

### 4.2 `GET /api/customers`

Query: `page` (default 1), `page_size` (1–200, default 25), `business_line` (`energy|mobile|e_mobility|smart_living`), `has_service_issue` (bool), `search` (substring of the customer id), `as_of`.

```json
{
  "items": [
    { "customer_id": "MG-100001", "city": "Köln", "customer_since": "2013-11-22 00:00:00", "business_lines": ["energy"],
      "current_clv_eur": 261.36, "churn_probability": 0.18, "has_service_issue": false, "open_complaint": false, "tonality": "sie" }
  ],
  "page": 1, "page_size": 2, "total": 750, "total_pages": 375, "as_of": "2026-10-02 02:03:52"
}
```

### 4.3 `GET /api/customers/{customer_id}` — Customer 360°

Query: `as_of`. Sections:

| Field | Description |
|---|---|
| `profile` | CRM master data (anonymised) + `segment` (business-line mix). |
| `business_lines` | Active lines: `energy`, `mobile`, `e_mobility`, `smart_living`. |
| `contracts.energy/mobile/autostrom/hems_devices` | All contracts incl. status, price guarantee, dunning level. Payment data is never exposed. |
| `products_held` / `product_holdings` | Catalog products held (`true`), not held (`false`), unknown (`null`). |
| `value` | Observed margin/cost to serve/churn and reported CLV; estimated live churn and CLV. |
| `churn_drivers` | Active drivers with documented increment and evidence; `churn_drivers_snapshot` = drivers on 2026‑09‑30. |
| `service` | Open tickets, dunning, cancellation, failed charging (30 d), CSAT, HEMS offline devices. |
| `marketing_history` | Delivered marketing contacts (30 d), last actions, newsletter engagement (machine opens excluded), portal usage. |
| `communication` | Tonality, language, service channel. |
| `consents` | Effective status per consent type incl. `effective_reason` (snapshot / unsubscribe / event id). |
| `eligible_actions` / `blocked_actions` | Short version of the decision. |
| `applied_events` | Events from the stream applied up to `as_of`. |

```json
{
  "customer_id": "MG-100004",
  "as_of": "2026-10-02 02:03:52",
  "profile": { "customer_type": "B2C", "customer_since": "2019-08-23 00:00:00", "birth_year": 1997, "postal_code_prefix": 641,
               "city": "Darmstadt", "household_size": 2, "portal_account": true, "app_installed": false,
               "preferred_contact_language": "de", "segment": "energy" },
  "business_lines": ["energy"],
  "contracts": { "energy": [ { "contract_id": "EN-500715", "commodity": "electricity", "tariff": "StromKomfort", "status": "active",
                               "start_date": "2022-07-01 00:00:00", "price_guarantee_until": "2027-07-01 00:00:00",
                               "annual_consumption_kwh": 3800, "meter_type": "conventional", "feed_in_meter": false,
                               "dunning_level": 3, "cancellation_received_at": null, "meter_deregistered_at": null } ],
                 "mobile": [], "autostrom": [], "hems_devices": [] },
  "products_held": ["P-EN-01"],
  "product_holdings": { "P-EN-01": true, "P-IN-01": null, "P-MO-01": false, "…": null },
  "shop_orders": [],
  "value": { "annual_margin_eur": 131.6, "cost_to_serve_12m_eur": 57.75, "service_cost_12m_eur": 45.75, "net_annual_value_eur": 73.85,
             "churn_probability_snapshot": 0.38, "churn_probability_now": 0.38, "clv_reported_snapshot_eur": 167.0,
             "clv_service_impact_reported_eur": -357, "current_clv_eur": 167.05, "value_model_version": "clv_simple_v1",
             "labels": { "annual_margin_eur": "observed (customer_value)", "current_clv_eur": "estimated (clv_method on churn_probability_now)", "…": "" } },
  "churn_drivers": [
    { "code": "open_complaint", "label": "Open complaint", "category": "service", "increment": 0.12, "evidence": "open ticket with category 'complaint'" },
    { "code": "tickets_12m_ge2", "label": "Two or more tickets in 12 months", "category": "history", "increment": 0.04, "evidence": "2 tickets in last 12 months" },
    { "code": "dunning_ge2", "label": "Dunning level 2 or higher", "category": "service", "increment": 0.08, "evidence": "dunning level 3" }
  ],
  "churn_drivers_snapshot": ["open_complaint", "tickets_12m_ge2", "dunning_ge2"],
  "structural_churn": 0.14,
  "service": { "has_service_issue": true, "open_complaint": true, "max_dunning_level": 3, "cancellation_pending": false,
               "open_tickets": [ { "ticket_id": "TK-200772", "created_at": "2026-09-22 11:05:00", "channel": "email",
                                   "category": "complaint", "status": "open", "latest_note": "Kunde fordert Rückruf" } ],
               "tickets_12m": 2, "last_csat": null, "failed_charges_30d": 0, "failed_charge_reasons_30d": [],
               "hems_offline_devices": [], "notes": ["Ticket update: Kunde fordert Rückruf"] },
  "marketing_history": { "contacts_last_30d": 2, "days_since_last_contact": 22.8, "recent_actions": ["…"],
                         "newsletter": { "delivered": 13, "human_opens": 2, "machine_opens_ignored": 1, "clicks": 0, "conversions_7d": 0, "unsubscribed": false },
                         "portal": { "sessions_jul_sep": 5, "page_views": { "dashboard": 5, "installment": 1, "offers": 1, "…": 1 }, "last_session": "2026-09-13 21:59:39" } },
  "communication": { "tonality": "sie", "tonality_source": "derived_from_customer_text", "preferred_contact_language": "de", "service_channel": "service_call" },
  "consents": { "marketing_email": { "status": "withdrawn", "effective": false, "updated_at": "2024-11-05 08:00:11", "source": "portal",
                                     "double_opt_in_confirmed": false, "effective_reason": "consent_status snapshot" }, "…": {} },
  "signals": { "has_electricity": true, "smart_meter": false, "ev_driver": false, "callback_requested": true, "…": null },
  "eligible_actions": [ { "product_id": "P-SV-01", "channel": "service_call", "expected_dclv_eur": 66.5 } ],
  "blocked_actions": [ { "product_id": "P-MO-01", "exclusion_reasons": ["PROFILING_CONSENT_NOT_GIVEN", "OPEN_COMPLAINT_BLOCKS_MARKETING", "DUNNING_BLOCKS_MARKETING", "CONTACT_FREQUENCY_LIMIT", "CHANNEL_NOT_AVAILABLE"] } ],
  "applied_events": [ { "event_id": "61eb8bf0-…", "event_type": "dunning_level_changed", "occurred_at": "2026-10-01 01:00:00", "ingested_at": "2026-10-02 02:29:32" } ]
}
```

### 4.4 `GET /api/customers/{customer_id}/recommendations` — Lighty decision

Query: `as_of`. Calling it logs the decision in SQLite (idempotent: same inputs → same `decision_id`, approval state is kept).

| Field | Type | Description |
|---|---|---|
| `customer_id` | string | |
| `decision_id` | string | Deterministic id `DEC-<16 hex>`; use it for approve/reject/AI. |
| `as_of` | string | Point in time evaluated. |
| `recommended_action` | string | Product id or `NO_CONTACT`. |
| `recommended_action_name` | string | Catalog name or `No contact`. |
| `action_type` | enum | See §3. |
| `product_id` | string\|null | `null` for no contact. |
| `channel` | enum | Channel to execute, `none` for no contact. |
| `process` | enum | `marketing` / `service` / `customer_inquiry_reply` / `none`. |
| `tonality` / `tonality_source` | enum / string | Du/Sie and how it was derived. |
| `current_clv_eur` | float | Estimated CLV now (clv_method on current churn). |
| `expected_dclv_eur` | float | Expected incremental CLV of the recommended action vs. no contact (0 for no contact). |
| `estimated_clv_after_eur` | float | `current_clv_eur + expected_dclv_eur`. |
| `acceptance_probability` | float\|null | p used (service: estimated resolution success). |
| `required_service_workflow` | bool | `true` if P‑SV‑01 was chosen because of an open complaint although its value is ≤ 0. |
| `requires_human_approval` | bool | `true` for every external communication. |
| `approval_status` | enum | See §3. |
| `reason` | string | Deterministic English explanation built from the computed values. |
| `alternatives` | ActionOption[] | Other **executable** options incl. `NO_CONTACT`, sorted by `expected_dclv_eur` desc. |
| `blocked_actions` | ActionOption[] | Non‑executable options (best channel per product), with `exclusion_reasons`. Illustrative only. |
| `eligibility_checks` | Check[] | All checks of the recommended candidate (`[]` for no contact). |
| `value_labels` | object | Label per headline figure. |
| `engine_version` | string | |

**ActionOption**

| Field | Description |
|---|---|
| `product_id`, `product_name`, `action_type`, `business_line`, `channel`, `process` | Identity of the option. |
| `executable` | `false` in `blocked_actions`. |
| `acceptance_probability`, `acceptance_source`, `acceptance_observations`, `control_group_rate` | p used, where it came from (`history_smoothed_offer_channel_tonality`, `…_offer_channel`, `…_offer`, `fallback_global_rate_no_offer_history`, `service_resolution_proxy_<category>`, `net_of_control_*`, `simulated_override`), number of deliveries behind it, smoothed control-group conversion for the offer. |
| `contact_cost_eur` | From value_assumptions by channel. |
| `churn_now`, `churn_after_accept`, `churn_after_reject` | 12‑month churn in each branch. |
| `clv_after_accept_eur`, `clv_after_reject_eur` | CLV in each branch. |
| `expected_dclv_eur` | `p·(CLV_accept−CLV_now) + (1−p)·(CLV_reject−CLV_now) − contact_cost`. |
| `estimated_clv_after_eur` | `CLV_now + expected_dclv_eur`. |
| `added_annual_margin_eur` / `one_off_margin_eur` | Recurring vs one-off margin if accepted. |
| `removed_churn_drivers` | Drivers removed by retention/service. |
| `service_case_contact_penalty` | `true` if rejection raises churn (sales contact during complaint/dunning). |
| `exclusion_reasons` | Codes from §3 (empty if executable). |
| `notes`, `value_label` | Method notes; `estimated` or `baseline`. |

**Check**: `{ "check": string, "passed": bool, "code": string|null, "detail": string }`

Example — service case (MG‑100004):

```json
{
  "customer_id": "MG-100004",
  "decision_id": "DEC-48c1817e05fdc73d",
  "as_of": "2026-10-02 02:03:52",
  "recommended_action": "P-SV-01",
  "recommended_action_name": "Service-Only / No offer",
  "action_type": "service",
  "product_id": "P-SV-01",
  "channel": "service_call",
  "process": "service",
  "tonality": "sie",
  "tonality_source": "derived_from_customer_text",
  "current_clv_eur": 167.05,
  "expected_dclv_eur": 66.5,
  "estimated_clv_after_eur": 233.55,
  "acceptance_probability": 0.7105,
  "required_service_workflow": false,
  "requires_human_approval": true,
  "approval_status": "pending_approval",
  "reason": "Resolve the service issue first (Service-Only / No offer via service_call). Resolving removes the service churn drivers (Open complaint, Dunning level 2 or higher), lowering churn from 38.0% to 18.0% if successful (estimated success probability 71%). Expected dCLV +66.50 EUR versus no contact, after the 6.00 EUR contact cost and the resolution cost. Marketing restrictions in force: CONTACT_FREQUENCY_LIMIT, DUNNING_BLOCKS_MARKETING, OPEN_COMPLAINT_BLOCKS_MARKETING, PROFILING_CONSENT_NOT_GIVEN.",
  "alternatives": [
    { "product_id": "NO_CONTACT", "product_name": "No contact", "action_type": "no_contact", "business_line": null, "channel": "none",
      "process": "none", "executable": true, "acceptance_probability": null, "acceptance_source": "baseline", "acceptance_observations": 0,
      "control_group_rate": null, "contact_cost_eur": 0.0, "churn_now": 0.38, "churn_after_accept": 0.38, "churn_after_reject": 0.38,
      "clv_after_accept_eur": 167.05, "clv_after_reject_eur": 167.05, "expected_dclv_eur": 0.0, "estimated_clv_after_eur": 167.05,
      "added_annual_margin_eur": 0.0, "one_off_margin_eur": 0.0, "removed_churn_drivers": [], "service_case_contact_penalty": false,
      "exclusion_reasons": [], "notes": ["Explicit baseline: zero incremental intervention value."], "value_label": "baseline" }
  ],
  "blocked_actions": [
    { "product_id": "P-MO-01", "product_name": "Mobil S / M / L", "action_type": "sales", "business_line": "mobile", "channel": "app_push",
      "process": "marketing", "executable": false, "acceptance_probability": 0.1099,
      "acceptance_source": "history_smoothed_offer_channel_tonality", "acceptance_observations": 10, "control_group_rate": 0.0092,
      "contact_cost_eur": 0.0, "churn_now": 0.38, "churn_after_accept": 0.36, "churn_after_reject": 0.43,
      "clv_after_accept_eur": 302.45, "clv_after_reject_eur": 150.41, "expected_dclv_eur": 0.06, "estimated_clv_after_eur": 167.11,
      "added_annual_margin_eur": 54.0, "one_off_margin_eur": 0.0, "removed_churn_drivers": [], "service_case_contact_penalty": true,
      "exclusion_reasons": ["PROFILING_CONSENT_NOT_GIVEN", "OPEN_COMPLAINT_BLOCKS_MARKETING", "DUNNING_BLOCKS_MARKETING", "CONTACT_FREQUENCY_LIMIT", "CHANNEL_NOT_AVAILABLE"],
      "notes": ["Sales contact during open complaint/dunning raises churn on rejection."], "value_label": "estimated" },
    "…"
  ],
  "eligibility_checks": [
    { "check": "action_enabled", "passed": true, "code": null, "detail": "enabled" },
    { "check": "service_issue_present", "passed": true, "code": null, "detail": "open ticket, dunning, failed charging or service churn driver" },
    { "check": "service_legal_basis", "passed": true, "code": null, "detail": "service contact under the existing contract; no marketing content allowed" },
    { "check": "service_channel", "passed": true, "code": null, "detail": "service_call: service process, no marketing consent required" }
  ],
  "value_labels": { "current_clv_eur": "estimated (clv_method on live churn)", "expected_dclv_eur": "estimated (model-based, not causal)",
                    "acceptance_probability": "estimated (observational history, smoothed)" },
  "engine_version": "lighty-1.1.0"
}
```

Example — healthy cross-sell (MG‑100127, abbreviated):

```json
{ "customer_id": "MG-100127", "decision_id": "DEC-e59557ab51f337cf", "recommended_action": "P-MO-01", "recommended_action_name": "Mobil S / M / L",
  "action_type": "sales", "product_id": "P-MO-01", "channel": "app_push", "process": "marketing", "tonality": "sie", "tonality_source": "default_formal",
  "current_clv_eur": 3263.46, "expected_dclv_eur": 66.0, "estimated_clv_after_eur": 3329.46, "acceptance_probability": 0.1099,
  "required_service_workflow": false, "requires_human_approval": true, "approval_status": "pending_approval",
  "reason": "Offer Mobil S / M / L via app_push: expected dCLV +66.00 EUR versus no contact (estimated acceptance 11.0%). Adds 54 EUR annual margin if accepted. Next best permitted alternative: P-IN-01 (+40.47 EUR).",
  "alternatives": [ { "product_id": "P-IN-01", "channel": "portal_popup", "expected_dclv_eur": 40.47, "…": "…" }, "…", { "product_id": "NO_CONTACT", "expected_dclv_eur": 0.0, "…": "…" } ],
  "blocked_actions": [ { "product_id": "P-EN-03", "exclusion_reasons": ["PREREQUISITE_MISSING"], "…": "…" } ],
  "eligibility_checks": ["…"], "value_labels": {"…": "…"}, "engine_version": "lighty-1.1.0" }
```

### 4.5 `POST /api/customers/{customer_id}/simulate` — Counterfactual simulator

Request (all fields optional; unknown fields are rejected):

| Field | Type / range | Effect |
|---|---|---|
| `acceptance_probability_overrides` | `{product_id: 0..1}` | Replace p for a product. |
| `acceptance_probability_multiplier` | 0..10 (default 1) | Multiply all p (capped at 1). |
| `contact_cost_overrides` | `{channel: 0..1000}` | Replace contact cost per channel. |
| `service_resolution_cost_eur` | 0..1000 | Replace the 15 EUR resolution cost. |
| `churn_now_override` | 0..0.99 | Replace current churn. |
| `churn_delta` | −0.5..0.5 | Add to current churn. |
| `contact_during_service_case` | 0..0.5 | Replace the churn penalty of a sales contact during a service case. |
| `discount_rate` | 0..0.5 | Replace 6 %. |
| `horizon_years` | 1..30 | Replace 10. |
| `baseline_policy` | `conventional_sales_first` \| `no_contact` | Baseline used for protected value. |
| `as_of` | string | Point in time. |

Scenario parameters never change eligibility: `blocked_actions` stay blocked (`compliance_unchanged: true`).

```json
// request
{ "acceptance_probability_overrides": { "P-SV-01": 0.5 }, "service_resolution_cost_eur": 30 }
// response
{
  "customer_id": "MG-100004",
  "decision_id": "DEC-70b3740207206d71",
  "base_decision_id": "DEC-48c1817e05fdc73d",
  "as_of": "2026-10-02 02:03:52",
  "assumptions_applied": { "service_resolution_cost_eur": 30.0, "acceptance_probability_overrides": { "P-SV-01": 0.5 }, "acceptance_probability_multiplier": 1.0 },
  "base": { "recommended_action": "P-SV-01", "expected_dclv_eur": 66.5, "current_clv_eur": 167.05,
            "ranking": [ { "product_id": "P-SV-01", "channel": "service_call", "expected_dclv_eur": 66.5, "acceptance_probability": 0.7105, "executable": true, "rank": 1 },
                         { "product_id": "NO_CONTACT", "channel": "none", "expected_dclv_eur": 0.0, "acceptance_probability": null, "executable": true, "rank": 2 } ] },
  "scenario": { "recommended_action": "P-SV-01", "expected_dclv_eur": 37.52, "current_clv_eur": 167.05,
                "ranking": [ { "product_id": "P-SV-01", "channel": "service_call", "expected_dclv_eur": 37.52, "acceptance_probability": 0.5, "executable": true, "rank": 1, "difference_to_recommended_eur": 0.0 },
                             { "product_id": "NO_CONTACT", "channel": "none", "expected_dclv_eur": 0.0, "acceptance_probability": null, "executable": true, "rank": 2, "difference_to_recommended_eur": -37.52 } ],
                "reason": "Resolve the service issue first (…)", "required_service_workflow": false },
  "recommendation_changed": false,
  "parameter_attribution": [
    { "parameter": "service_resolution_cost_eur", "recommended_action_alone": "P-SV-01", "changes_recommendation": false,
      "dclv_of_base_recommendation_before_eur": 66.5, "dclv_of_base_recommendation_after_eur": 55.84, "delta_eur": -10.66 },
    { "parameter": "acceptance_probability_overrides.P-SV-01", "recommended_action_alone": "P-SV-01", "changes_recommendation": false,
      "dclv_of_base_recommendation_before_eur": 66.5, "dclv_of_base_recommendation_after_eur": 45.02, "delta_eur": -21.48 }
  ],
  "blocked_actions": [ { "product_id": "P-MO-01", "channel": "app_push", "expected_dclv_eur": 0.06,
                         "exclusion_reasons": ["PROFILING_CONSENT_NOT_GIVEN", "…"], "executable": false, "label": "illustrative, non-executable" } ],
  "compliance_unchanged": true,
  "baseline": { "policy": "conventional_sales_first", "action": "P-SH-01", "channel": "portal_popup",
                "executable_under_lighty_rules": false, "executable_under_guardian_rules": false,
                "expected_dclv_eur": -8.81, "projected_protected_value_eur": 46.33 },
  "value_label": "simulated (model-based estimate; not realised savings or proven causal uplift)"
}
```

`parameter_attribution` applies each changed parameter **alone** and reports whether it flips the recommendation and how it moves the dCLV of the base recommendation.

### 4.6 `GET /api/marketing/overview`

| Field | Description |
|---|---|
| `total_customers_evaluated` | All customers. |
| `marketing_actions.eligible_product_options` / `blocked_product_options` | Count of (customer × product) marketing options executable / blocked. |
| `marketing_actions.blocked_by_reason` | Code → count (a blocked option can carry several codes). |
| `recommended_action_distribution` | Product id / `NO_CONTACT` → customers. |
| `recommended_by_action_type`, `recommended_by_business_line`, `recommended_by_channel` | Breakdowns. |
| `customers_with_active_service_issues` | Open ticket, dunning, cancellation, failed charging or service driver. |
| `pending_approvals` | Decisions waiting for review. |
| `total_current_clv_eur` | Sum of current CLV. |
| `total_projected_incremental_clv_eur` | Sum of Lighty expected dCLV. |
| `baseline` | Baseline policy, its total expected dCLV, action mix and how many of its actions Lighty's rules would block (`baseline_actions_blocked_by_lighty_rules`; the old name `baseline_actions_blocked_by_guardian_rules` is still sent with the same value and is deprecated). |
| `projected_protected_customer_value_eur` | Lighty total − baseline total. **Model-based estimate.** |
| `value_by_segment`, `value_by_clv_tier` | Customers, expected dCLV (and current CLV) per business-line mix / CLV tier. |
| `settings_version` | Version of the settings used. |

```json
{
  "total_customers_evaluated": 750,
  "as_of": "2026-10-02 02:03:52",
  "marketing_actions": { "eligible_product_options": 1729, "blocked_product_options": 11021,
                         "blocked_by_reason": { "PREREQUISITE_MISSING": 7551, "CHANNEL_NOT_AVAILABLE": 3962, "PROFILING_CONSENT_NOT_GIVEN": 3349, "…": 0 } },
  "recommended_action_distribution": { "NO_CONTACT": 337, "P-MO-01": 127, "P-SV-01": 118, "P-EN-01": 69, "P-IN-01": 66, "P-EN-02": 24, "P-EN-04": 7, "P-EN-03": 2 },
  "recommended_by_action_type": { "no_contact": 337, "sales": 271, "service": 118, "retention": 24 },
  "recommended_by_business_line": { "none": 337, "mobile": 127, "service": 118, "energy": 102, "internet": 66 },
  "recommended_by_channel": { "none": 337, "newsletter_email": 119, "service_email": 110, "app_push": 85, "portal_popup": 71, "outbound_call": 17, "service_call": 10, "sms": 1 },
  "customers_with_active_service_issues": 227,
  "pending_approvals": 413,
  "total_current_clv_eur": 412035.44,
  "total_projected_incremental_clv_eur": 15982.06,
  "baseline": { "policy": "conventional_sales_first", "total_expected_dclv_eur": 8022.89,
                "action_distribution": { "P-SH-01": 374, "P-MO-01": 181, "NO_CONTACT": 63, "…": 0 },
                "baseline_actions_blocked_by_lighty_rules": 360, "baseline_actions_blocked_by_guardian_rules": 360 },
  "projected_protected_customer_value_eur": 7959.17,
  "projected_protected_customer_value_label": "Model-based estimate: expected CLV under Lighty minus expected CLV under the baseline policy. Not realised savings and not proven causal uplift.",
  "value_by_segment": { "energy": { "customers": 393, "expected_dclv_eur": 8315.87, "current_clv_eur": 200964.09 }, "…": {} },
  "value_by_clv_tier": { "clv_0_500": { "customers": 343, "expected_dclv_eur": 6635.03 }, "…": {} },
  "settings_version": 0
}
```

### 4.7 `GET /api/marketing/recommendations`

Query: `page`, `page_size` (1–500, default 50), `action_type`, `channel`, `business_line`, `approval_status`, `include_no_contact` (default `false`). Sorted by `expected_dclv_eur` desc.

```json
{
  "items": [
    { "customer_id": "MG-100315", "decision_id": "DEC-82dd59dce7bdc3c5", "recommended_action": "P-SV-01",
      "recommended_action_name": "Service-Only / No offer", "action_type": "service", "business_line": "service",
      "channel": "service_email", "tonality": "sie", "current_clv_eur": 898.31, "expected_dclv_eur": 223.09,
      "acceptance_probability": 0.879, "required_service_workflow": false, "approval_status": "pending_approval", "segment": "energy+mobile" }
  ],
  "page": 1, "page_size": 2, "total": 413, "total_pages": 207
}
```

### 4.8 `GET /api/marketing/settings` and `PUT /api/marketing/settings`

`PUT` takes a partial update; omitted sections stay unchanged. `action_priorities` entries are merged per product.

| Setting | Range | Default | Notes |
|---|---|---|---|
| `contact_policy.max_marketing_contacts_30d` | 0..4 | 2 | Hard cap 4. The dataset defines no limit, the default is a policy choice. |
| `contact_policy.min_days_between_marketing_contacts` | 0..90 | 7 | |
| `action_priorities.{product_id}.enabled` | bool | true | `P-SV-01` cannot be disabled. |
| `action_priorities.{product_id}.priority` | −10..10 | 0 | Tie-breaker only, never changes values. |
| `simulation.pseudo_count` | 0..500 | 20 | Strength of p smoothing. |
| `simulation.p_accept_mode` | `observed_conversion` \| `net_of_control` | `observed_conversion` | `net_of_control` = max(0, treated − control). |
| `simulation.exclude_unconsented_history` | bool | true | Ignore legacy actions sent without consent check when estimating p. |
| `simulation.baseline_policy` | `conventional_sales_first` \| `no_contact` | `conventional_sales_first` | |
| `simulation.min_expected_dclv_eur` | 0..100 | 0 | A proactive action must beat no contact by more than this. |

Consent rules, profiling, service-state blocks and human approval are **not** configurable.

```json
// PUT body
{ "contact_policy": { "max_marketing_contacts_30d": 1 }, "action_priorities": { "P-SH-04": { "enabled": false } } }
// response (GET has the same shape)
{ "version": 1,
  "settings": { "contact_policy": { "max_marketing_contacts_30d": 1, "min_days_between_marketing_contacts": 7 },
                "action_priorities": { "P-SH-04": { "enabled": false, "priority": 0 } },
                "simulation": { "pseudo_count": 20.0, "p_accept_mode": "observed_conversion", "exclude_unconsented_history": true,
                                "baseline_policy": "conventional_sales_first", "min_expected_dclv_eur": 0.0 } },
  "known_product_ids": ["P-AS-01", "P-EN-01", "…"],
  "hard_rules_note": "Consent, profiling, service-state blocks and approval are not configurable." }
```

Changing settings changes `decision_id`s (settings are part of the id), so fetch recommendations again afterwards.

### 4.9 `POST /api/decisions/{decision_id}/approve` and `/reject`

Body (optional): `{ "reviewer": "marketing.lead", "note": "ok" }`. Approval re-checks eligibility on the latest data; if the action is no longer permitted the call returns 409 with the failing codes.

```json
{ "decision_id": "DEC-48c1817e05fdc73d", "customer_id": "MG-100004", "approval_status": "approved",
  "reviewer": "marketing.lead", "review_note": "ok", "reviewed_at": "2026-10-26T14:57:42+00:00" }
```

### 4.10 `POST /api/ai/explain`

Body: `{ "decision_id": "DEC-…" }` or `{ "customer_id": "MG-…" }` (computes the current decision).

```json
{ "customer_id": "MG-100004", "decision_id": "DEC-48c1817e05fdc73d", "recommended_action": "P-SV-01",
  "explanation": "Resolve the service issue first (…)", "source": "template_fallback", "fallback_reason": "AI not configured",
  "validation": { "passed": true },
  "facts_used": { "recommended_action": "Service-Only / No offer", "action_type": "service", "channel": "service_call",
                  "expected_dclv_eur": 66.5, "current_clv_eur": 167.05, "acceptance_probability_pct": 71.0,
                  "required_service_workflow": false, "alternatives": [], "blocked_reasons": ["…"], "engine_reason": "…" } }
```

`source` is `llm` only if the model answer passed validation (no numbers that are not in `facts_used`).

### 4.11 `POST /api/ai/generate-message`

Same body as 4.10. Returns 409 for a no-contact decision. Drafts are stored and are **always** `pending_approval`.

```json
{ "customer_id": "MG-100127", "decision_id": "DEC-e59557ab51f337cf", "message_id": 1, "channel": "app_push", "tonality": "sie",
  "language": "de", "preferred_contact_language": "de", "subject": null,
  "body": "MAINGAU: Passend zu Ihrem Vertrag stellen wir Ihnen unsere Mobilfunktarife vor. Details im Kundenportal. Abmeldung jederzeit im Portal möglich.",
  "source": "template_fallback", "fallback_reason": "AI not configured",
  "validation": { "passed": true, "problems": [], "length": 143 },
  "approval_status": "pending_approval", "requires_human_approval": true }
```

For `service_call` / `outbound_call` the body is a call guide for the agent, not a message. Validation rejects numbers, prices, percentages, urgency phrases, wrong Du/Sie and over-long texts.

### 4.12 Copilot overview

Lighty's copilot is **internal**: it helps an employee prepare and run a conversation with one customer. It never
contacts customers, never sends anything and never changes the engine decision. Every answer separates four kinds of
content:

| Kind | Where in the response | Source |
|---|---|---|
| Verified database facts | `supporting_facts[]` with `kind = "verified_fact"` | Workbook tables and event stream, each with `source_refs` → `source_references[]` (table + record id) |
| Engine results | `recommended_action`, `supporting_facts[]` with `kind = "engine_computed"` | Lighty engine (CLV, churn, eligibility, NBA) — the same decision as `GET /recommendations` |
| Generated communication | `response`, `suggested_customer_message` | Deterministic rules/templates, or the LLM when configured and its output passed validation; see `answer_origin` |
| Assumptions and uncertainty | `confidence_or_uncertainty`, `supporting_facts[]` with `kind = "data_gap"` | Missing data, withheld data, model assumptions |

`answer_parts` lists the fact ids per kind so the UI can render them in separate blocks.

**Fact object** (`CopilotFact`): `fact_id` (`F1`… stable for the same customer, data and role), `key` (machine key such
as `open_ticket:TK-200772`, `consent:profiling_analytics`, `product_status:P-AS-01`), `section`
(`customer_information` · `customer_experience` · `marketing` · `decision_intelligence`), `kind`, `text` (in the
requested language), `value` (structured), `source_refs` (ids into `source_references`), `topics`.

**Source reference**: `{ "ref_id": "R6", "table": "service_interactions", "record_id": "TK-200772", "fields": [...],
"occurred_at": "2026-09-22 11:05:00", "note": null }`. `table` is a workbook sheet, `event_stream` (record id =
`event_id`) or `lighty_engine` (record id = `decision_id`). `record_id = null` with a `note` documents an absence
check, e.g. *no row for customer_id=MG-100023* in `autostrom_contracts`.

### 4.13 `POST /api/copilot/chat`

Headers: `X-Employee-Token` (or dev headers, see §1). Body:

| Field | Type | Notes |
|---|---|---|
| `customer_id` | string | Required. 404 if unknown. |
| `message` | string 1–2000 | The employee's question, German or English. |
| `conversation_id` | string \| null | Omit for a new conversation; send the returned id for follow-ups. Must belong to the same employee (else 404) and the same customer (else 409). |
| `language` | `de` (default) \| `en` | Language of the guidance. Customer wording is always German. |
| `require_llm` | bool, default `false` | `true` → 503 `ai_unavailable` instead of the deterministic fallback. |

Response fields: `conversation_id`, `customer_id`, `turn`, `language`, `intents` (what Lighty understood:
`approach`, `opening`, `service`, `retention`, `compensation`, `offer`, `product`, `consent`, `why`, `value`, `avoid`,
`draft`, `history`, `briefing`, `general`), `response` (plain text, `- ` bullet lines, no HTML), `recommended_action`,
`suggested_customer_message` (or `null`), `supporting_facts`, `source_references`, `warnings`,
`confidence_or_uncertainty`, `answer_origin`, `answer_parts`, `created_at`.

`suggested_customer_message.kind` is `call_opening` (spoken opening for the employee) or `written_draft` (approved
template for the engine's action, asked for with words like "Entwurf"/"draft"). It always has
`requires_human_approval: true` and `auto_send: false`; `validation` shows the checks (no numbers, prices,
percentages or urgency; Du/Sie).

Warning codes: `sales_restricted` (open service case, no offers), `withheld_free_text`,
`withheld_behavioural_marketing` (no profiling consent), `untrusted_text_flagged` / `untrusted_text_excluded`
(customer text that looks like instructions was not used), `llm_unavailable`, `llm_output_rejected`,
`llm_message_rejected` (AI output failed validation; deterministic text used).

Example — frustrated customer with an open complaint (MG‑100004, service agent, real response, facts shortened):

```json
// request
{ "customer_id": "MG-100004", "message": "Wie sollte ich mit diesem Kunden umgehen?" }
// response
{
  "conversation_id": "CONV-fce14ed04fc0467db7f47d39da2a44b9",
  "customer_id": "MG-100004", "turn": 1, "language": "de", "intents": ["approach"],
  "response": "- Aktuelle Situation: eine offene Beschwerde; der Kunde wünscht einen Rückruf; Mahnstufe 3.\n- Lighty empfiehlt den Service-Prozess (P-SV-01, ohne Angebot) über service_call, erwarteter dCLV +66.50 EUR. Erst lösen; Angebote bewertet Lighty danach neu.\n- Keine Verkaufsangebote während des offenen Service-Falls (OPEN_COMPLAINT_BLOCKS_MARKETING, DUNNING_BLOCKS_MARKETING). Erst das Problem lösen.\n- Anrede: Sie. Zuhören, das Anliegen zusammenfassen, nächste Schritte verbindlich, aber ohne Zusagen zu Ergebnissen vereinbaren.",
  "recommended_action": {
    "decision_id": "DEC-48c1817e05fdc73d", "product_id": "P-SV-01", "product_name": "Service-Only / No offer",
    "action_type": "service", "channel": "service_call", "process": "service", "expected_dclv_eur": 66.5,
    "current_clv_eur": 167.05, "acceptance_probability": 0.7105, "required_service_workflow": false,
    "requires_human_approval": true, "approval_status": "pending_approval", "sales_restricted": true,
    "restriction_codes": ["CHANNEL_NOT_AVAILABLE", "CONSENT_NOT_GIVEN", "CONTACT_FREQUENCY_LIMIT", "DUNNING_BLOCKS_MARKETING",
                          "OPEN_COMPLAINT_BLOCKS_MARKETING", "PROFILING_CONSENT_NOT_GIVEN"],
    "engine_reason": "Resolve the service issue first (Service-Only / No offer via service_call). Resolving removes the service churn drivers (Open complaint, Dunning level 2 or higher), lowering churn from 38.0% to 18.0% if successful …",
    "engine_version": "lighty-1.1.0", "source": "lighty_engine", "fact_ids": ["F20", "F22"]
  },
  "suggested_customer_message": {
    "kind": "call_opening",
    "text": "Ich sehe, dass Ihr Anliegen bei uns noch nicht abschließend geklärt ist und Sie um einen Rückruf gebeten haben. Das tut mir leid. Ich kümmere mich jetzt persönlich darum.",
    "subject": null, "channel": "conversation", "tonality": "sie", "language": "de", "source": "template",
    "fact_ids": ["F6", "F7", "F2"], "requires_human_approval": true, "auto_send": false, "decision_id": null,
    "validation": { "passed": true, "problems": [], "length": 170 }
  },
  "supporting_facts": [
    { "fact_id": "F6", "key": "open_ticket:TK-200772", "section": "customer_experience", "kind": "verified_fact",
      "text": "Offenes Ticket (complaint) seit 2026-09-22 über email. Letzte Agenten-Notiz: \"Kunde fordert Rückruf\".",
      "value": { "ticket_id": "TK-200772", "category": "complaint", "channel": "email", "created_at": "2026-09-22 11:05:00",
                 "status": "open", "latest_note": "Kunde fordert Rückruf" },
      "source_refs": ["R6", "R7"], "topics": ["complaint", "service"] },
    { "fact_id": "F3", "key": "contract:EN-500715", "section": "customer_information", "kind": "verified_fact",
      "text": "Energievertrag electricity (StromKomfort), Status active, seit 2022-07-01, Preisgarantie bis 2027-07-01, Zähler conventional, Abschlag 127.00 EUR, Mahnstufe 3.",
      "value": { "tariff": "StromKomfort", "dunning_level": 3, "…": "…" }, "source_refs": ["R2"], "topics": ["billing", "energy", "products", "restrictions", "retention"] },
    { "fact_id": "F20", "key": "nba", "section": "decision_intelligence", "kind": "engine_computed",
      "text": "Next Best Action laut Lighty: Service-Only / No offer (P-SV-01) über service_call (Service-Prozess); erwarteter dCLV +66.50 EUR, geschätzte Erfolgs-/Annahmewahrscheinlichkeit 71.1 %; Freigabe durch einen Menschen erforderlich (pending_approval).",
      "value": { "decision_id": "DEC-48c1817e05fdc73d", "recommended_action": "P-SV-01", "…": "…" }, "source_refs": ["R5"], "topics": ["products", "recommendation"] },
    "…"
  ],
  "source_references": [
    { "ref_id": "R5", "table": "lighty_engine", "record_id": "DEC-48c1817e05fdc73d", "fields": ["recommended_action", "channel", "expected_dclv_eur", "…"], "occurred_at": null, "note": null },
    { "ref_id": "R6", "table": "service_interactions", "record_id": "TK-200772", "fields": ["created_at", "channel", "category", "status"], "occurred_at": "2026-09-22 11:05:00", "note": null },
    { "ref_id": "R7", "table": "event_stream", "record_id": "c2e98605-5d4c-8eb0-1931-376479dab01c", "fields": ["note"], "occurred_at": null, "note": null },
    { "ref_id": "R2", "table": "energy_contracts", "record_id": "EN-500715", "fields": ["…"], "occurred_at": null, "note": null },
    "…"
  ],
  "warnings": [
    { "code": "sales_restricted", "message": "Open service case: no sales offers (OPEN_COMPLAINT_BLOCKS_MARKETING, DUNNING_BLOCKS_MARKETING)." },
    { "code": "withheld_behavioural_marketing", "message": "profiling_analytics consent is not_given: newsletter engagement, portal page views and abandoned carts are not used for personalisation." }
  ],
  "confidence_or_uncertainty": {
    "level": "medium",
    "reasons": ["profiling_analytics consent is not_given: newsletter engagement, portal page views and abandoned carts are not used for personalisation."],
    "data_gaps": [],
    "assumptions": ["Geldwerte und Wahrscheinlichkeiten sind Modellschätzungen (CLV-Methode, beobachtete Quoten), keine garantierten Ergebnisse und kein Kausalnachweis."]
  },
  "answer_origin": { "response": "deterministic_rules", "suggested_customer_message": "template", "llm_used": false, "model": null, "fallback_reason": "AI not configured" },
  "answer_parts": { "verified_fact_ids": ["F6", "F7", "F3"], "engine_computed_fact_ids": ["F20", "F22", "F2"], "data_gap_fact_ids": [], "generated_fields": ["response", "suggested_customer_message"] },
  "created_at": "2026-10-26T16:41:15+00:00"
}
```

Follow-up in the same conversation (send the `conversation_id`):

```json
// request
{ "customer_id": "MG-100004", "conversation_id": "CONV-fce14ed04fc0467db7f47d39da2a44b9",
  "message": "Kann ich ihm als Entschädigung einen Rabatt anbieten?" }
// response (abridged)
{ "turn": 2, "intents": ["compensation"],
  "response": "- Zuerst das eigentliche Anliegen klären: eine offene Beschwerde; der Kunde wünscht einen Rückruf; Mahnstufe 3.\n- Lighty kann keine Rabatte, Gutschriften, Erstattungen oder Kulanz zusagen; im Datensatz sind dafür keine freigegebenen Konditionen hinterlegt. Bei berechtigtem Anliegen den internen Kulanzprozess nutzen und vor der Freigabe nichts zusagen.",
  "suggested_customer_message": null, "…": "…" }
```

Example — cross-sell check for a wallbox buyer (MG‑100023):

```json
// request
{ "customer_id": "MG-100023", "message": "Der Kunde hat eine Wallbox gekauft. Hat er schon Autostrom?" }
// response (abridged)
{ "intents": ["product"],
  "response": "- Der Kunde hat Wallbox 11 kW gekauft (2025-08-14, Status delivered). MAINGAU Autostrom: kein aktiver Vertrag.\n- MAINGAU Autostrom (P-AS-01): zulässig über portal_popup, erwarteter dCLV +0.35 EUR, geschätzte Annahmewahrscheinlichkeit 0.1 % (Rang 6 der zulässigen Aktionen). Nicht die Next Best Action; nur erwähnen, wenn der Kunde Interesse zeigt.\n- Wallbox 11 kW (P-SH-02): bereits vorhanden.\n- Wallbox-Integration (P-SL-03): nicht zulässig (PREREQUISITE_MISSING, CHANNEL_NOT_AVAILABLE). Bestand ist im Datensatz unbekannt. Nicht aktiv anbieten. Fragt der Kunde selbst danach, allgemein informieren und auf das Kundenportal verweisen.",
  "supporting_facts": [ { "fact_id": "F5", "key": "order:SO-900005", "kind": "verified_fact", "…": "…" },
                        { "fact_id": "F4", "key": "autostrom:none", "kind": "verified_fact", "…": "…" },
                        { "fact_id": "F25", "key": "product_status:P-AS-01", "kind": "engine_computed",
                          "value": { "product_id": "P-AS-01", "status": "permitted", "channel": "portal_popup", "expected_dclv_eur": 0.35, "acceptance_probability": 0.0011 } }, "…" ],
  "source_references": [ { "ref_id": "R4", "table": "shop_orders", "record_id": "SO-900005", "…": "…" },
                         { "ref_id": "R3", "table": "autostrom_contracts", "record_id": null, "fields": ["customer_id"], "note": "no row for customer_id=MG-100023" }, "…" ],
  "confidence_or_uncertainty": { "level": "high", "reasons": [], "data_gaps": [],
                                 "assumptions": ["Anrede Sie ist ein Standard, nicht aus Kundentexten abgeleitet.", "…"] } }
```

Example — information that is not in the data:

```json
{ "customer_id": "MG-100023", "message": "Wie heißt der Kunde?" }
// → "response": "- Der Name des Kunden ist im Datensatz nicht enthalten (pseudonymisierte Kundennummer).",
//   "confidence_or_uncertainty": { "level": "low", "data_gaps": ["…", "Der Name des Kunden ist im Datensatz nicht enthalten (pseudonymisierte Kundennummer)."], … }
```

### 4.14 `GET /api/customers/{customer_id}/briefing`

Query: `language` (`de` default, `en`), `use_ai` (default `true`; only used when an AI model is configured — it may
rephrase *current situation* and *recommended approach*, validated like chat answers). Same headers as chat.

Seven sections, each `{ title, text, items[], fact_ids[] }`: `customer_overview`, `current_situation`,
`recommended_approach`, `suggested_opening` (German, Du/Sie), `what_to_avoid`, `next_best_action`,
`economic_rationale`. Plus `recommended_action`, `suggested_customer_message` (the opening), `supporting_facts`,
`source_references`, `warnings`, `confidence_or_uncertainty`, `answer_origin`, `generated_at`.

Example — charging problems (MG‑100009, real, texts only):

```json
{
  "customer_id": "MG-100009", "as_of": "2026-10-02 02:03:52", "language": "de", "tonality": "sie",
  "sections": {
    "customer_overview": { "title": "Kundenüberblick", "text": "B2C, Kunde seit 2016-12-03 (9 Jahre); aktive Geschäftsbereiche: e_mobility; Haushaltsgröße 2; Kundenportal: ja, App: ja. Kundenwert: Jahresmarge 200.11 EUR, Cost-to-Serve 37.50 EUR (beides customer_value); aktueller CLV laut Lighty 402.96 EUR (Modellschätzung).", "items": [], "fact_ids": ["F1", "F4", "F3"] },
    "current_situation": { "title": "Aktuelle Situation", "text": "Aktuell: 4 fehlgeschlagene Ladevorgänge in den letzten 30 Tagen; ein offenes Ticket zum Thema Autostrom/Laden.", "items": [], "fact_ids": ["F9", "F5"] },
    "recommended_approach": { "title": "Empfohlenes Vorgehen", "text": "Mit dem offenen Anliegen beginnen, Verständnis zeigen, Lösung und nächste Schritte vereinbaren. Zufriedenheit und Gründe für einen möglichen Wechsel offen ansprechen, ohne Druck und ohne Konditionen zuzusagen. Lighty empfiehlt den Service-Prozess (P-SV-01, ohne Angebot) über service_call, erwarteter dCLV +77.13 EUR. Erst lösen; Angebote bewertet Lighty danach neu. Anrede: Sie.", "items": ["…"], "fact_ids": ["…"] },
    "suggested_opening": { "title": "Vorgeschlagener Einstieg (Deutsch)", "text": "Ich sehe, dass es zuletzt Probleme mit Ihren Ladevorgängen gab. Das tut mir leid. Lassen Sie uns das zuerst gemeinsam klären.", "items": [], "fact_ids": ["F9", "F2"] },
    "what_to_avoid": { "title": "Was vermeiden", "text": "…", "items": ["Keine Produkt- oder Tarifangebote, solange der Service-Fall offen ist.", "Keine Rabatte, Gutschriften, Kulanz oder Konditionen zusagen, die nicht freigegeben sind, und keine Ergebnisse garantieren.", "Vorsicht mit Angeboten: Frühere Vorschläge stießen auf Verärgerung.", "Den Kunden nicht alles erneut schildern lassen; die Vorgeschichte ist bekannt.", "Anrede konsequent in der Sie-Form halten."], "fact_ids": ["…"] },
    "next_best_action": { "title": "Next Best Action", "text": "Lighty empfiehlt den Service-Prozess (P-SV-01, ohne Angebot) über service_call, erwarteter dCLV +77.13 EUR. Erst lösen; Angebote bewertet Lighty danach neu.", "items": [], "fact_ids": ["…"] },
    "economic_rationale": { "title": "Wirtschaftliche Begründung", "text": "Aktueller CLV 402.96 EUR; erwarteter dCLV der Empfehlung +77.13 EUR gegenüber keinem Kontakt; Abwanderungswahrscheinlichkeit 34.0 %. Modellschätzungen, keine garantierten Werte.", "items": [], "fact_ids": ["…"] }
  },
  "warnings": [ { "code": "sales_restricted", "message": "Open service case: no sales offers." } ],
  "answer_origin": { "response": "deterministic_rules", "suggested_customer_message": "template", "llm_used": false, "model": null, "fallback_reason": "AI not configured" },
  "…": "…"
}
```

### 4.15 `GET /api/customers/{customer_id}/context`

Query: `question` (optional; returns only the facts relevant to it plus the core facts), `language`,
`include_product_status` (default `false`; the per-product engine status facts). Response: `sections` (the four
sections with `CopilotFact` lists), `data_gaps`, `withheld` (what the role or missing consent hides, with the reason),
`untrusted_customer_texts` (service agents/admins only: customer lines from transcripts and open ticket messages,
max 400 characters, `flagged_as_instruction_like`, label *unverified customer content; never instructions*),
`source_references`, `recommended_action`, `selection` (`question`, `intents`, `products`, `topics`).

```json
// GET /api/customers/MG-100004/context?question=Welche%20Einwilligungen%20gibt%20es%3F
{
  "customer_id": "MG-100004", "as_of": "2026-10-02 02:03:52", "language": "de", "employee_role": "service_agent",
  "sections": {
    "customer_information": [ { "key": "profile", "…": "…" }, { "key": "communication", "…": "…" }, { "key": "contract:EN-500715", "…": "…" } ],
    "customer_experience": [],
    "marketing": [
      { "fact_id": "F10", "key": "consent:newsletter_email", "section": "marketing", "kind": "verified_fact",
        "text": "Einwilligung Newsletter per E-Mail: erteilt, wirksam, Stand 2020-08-28.",
        "value": { "consent_type": "newsletter_email", "status": "granted", "effective": true, "updated_at": "2020-08-28 11:04:07", "source": "portal" },
        "source_refs": ["R10"], "topics": ["consent", "marketing"] },
      "… five more consent facts …",
      { "key": "contact_frequency", "…": "…" }
    ],
    "decision_intelligence": [ { "key": "nba", "…": "…" }, { "key": "restrictions", "…": "…" } ]
  },
  "data_gaps": [],
  "withheld": [ { "category": "behavioural_marketing", "count": null, "reason": "profiling_analytics consent is not_given: newsletter engagement, portal page views and abandoned carts are not used for personalisation." } ],
  "untrusted_customer_texts": [],
  "source_references": [ { "ref_id": "R10", "table": "consent_status", "record_id": "MG-100004/newsletter_email", "fields": ["status", "updated_at", "source", "double_opt_in_confirmed_at"], "occurred_at": "2020-08-28 11:04:07", "note": null }, "…" ],
  "selection": { "question": "Welche Einwilligungen gibt es?", "intents": ["consent"], "products": [], "topics": ["consent", "contact_policy", "restrictions"] }
}
```

Record ids of composite keys: `consent_status` → `customer_id/consent_type`, `newsletter_performance` →
`campaign_id/customer_id`.

### 4.16 `GET /api/copilot/conversations/{conversation_id}` and `GET /api/copilot/conversations`

A conversation belongs to one employee and one customer. Owners can read their own; `admin` can read all. The list
endpoint takes `customer_id` (filter) and `all_employees` (admin only, else 403).

```json
{ "conversation_id": "CONV-fce14ed04fc0467db7f47d39da2a44b9", "customer_id": "MG-100004", "employee_id": "agent-7",
  "employee_role": "service_agent", "created_at": "2026-10-26T16:41:15+00:00", "updated_at": "2026-10-26T16:41:15+00:00", "turns": 2,
  "messages": [
    { "turn": 1, "author": "employee", "content": "Wie sollte ich mit diesem Kunden umgehen?", "created_at": "2026-10-26T16:41:15+00:00", "payload": null },
    { "turn": 1, "author": "lighty", "content": "- Aktuelle Situation: …", "created_at": "2026-10-26T16:41:15+00:00", "payload": { "…": "the full chat response of that turn" } },
    "…"
  ] }
```

### 4.17 `GET /api/copilot/suggested-questions?customer_id=…`

Starter questions that fit the customer's situation (for chips above the input field).

```json
{ "customer_id": "MG-100004", "language": "de",
  "questions": [ { "question": "Wie sollte ich mit diesem Kunden umgehen?", "intent": "approach" },
                 { "question": "Welche offenen Probleme hat der Kunde?", "intent": "service" },
                 { "question": "Wie kann ich den Kunden halten?", "intent": "retention" },
                 { "question": "Was sollte ich im Gespräch vermeiden?", "intent": "avoid" },
                 { "question": "Wie steige ich ins Gespräch ein?", "intent": "opening" } ] }
```

### 4.18 `GET /api/copilot/me`

```json
{ "employee_id": "agent-7", "role": "service_agent", "auth_mode": "dev", "permissions": ["copilot", "customer_context", "free_text"] }
```

Copilot errors (same error shape as everywhere):

```json
{ "error": "unauthorized", "detail": "Missing or invalid X-Employee-Token" }
{ "error": "not_found", "detail": "Conversation CONV-… not found" }
{ "error": "conflict", "detail": "This conversation belongs to a different customer; start a new conversation" }
{ "error": "ai_unavailable", "detail": "The AI model is not configured; retry without require_llm for the deterministic answer" }
```

## 5. Integration guide

1. **Customer list** → `GET /api/customers?page=1&page_size=25` (filter `has_service_issue=true` for the service view).
2. **Customer page** → `GET /api/customers/{id}` for the 360° panel and `GET /api/customers/{id}/recommendations` for the decision card. Show `recommended_action_name`, `channel`, `expected_dclv_eur`, `reason`; render `alternatives` as the comparison table and `blocked_actions` greyed out with their `exclusion_reasons` (they are illustrative, never executable).
3. **What-if panel** → `POST /api/customers/{id}/simulate` with slider values; show `base` vs `scenario` rankings, `recommendation_changed`, `parameter_attribution` and `baseline.projected_protected_value_eur`.
4. **Approve flow** → `POST /api/ai/generate-message` to show the draft, then `POST /api/decisions/{decision_id}/approve` or `/reject`. Handle 409 (already reviewed / no longer permitted).
5. **Dashboard** → `GET /api/marketing/overview` and `GET /api/marketing/recommendations`.
6. **Settings page** → `GET`/`PUT /api/marketing/settings`; show 422 `detail` messages to the user.
7. Always display the value labels: "estimated", "model-based", "not realised savings".

### 5.1 Employee copilot (chat panel)

**Sign-in.** On app start call `GET /api/health` and read `employee_auth.mode`:
`token` → ask the employee for their token (or take it from your login layer) and send it as `X-Employee-Token` on
every copilot request; `dev` → local only, send `X-Employee-Id` and `X-Employee-Role`; `not_configured` → show
"Copilot not configured on this server" instead of the chat. Then call `GET /api/copilot/me` once to show the role
and to hide what the role may not use (e.g. untrusted customer texts are only returned for `service_agent`/`admin`).
Never store the token in the URL or in logs.

**Opening a customer.** When the employee opens a customer, load in parallel:
`GET /api/customers/{id}/briefing` (pre-call briefing card), `GET /api/copilot/suggested-questions?customer_id={id}`
(chips) and, if you show a facts panel, `GET /api/customers/{id}/context`. Optionally
`GET /api/copilot/conversations?customer_id={id}` to offer "continue last conversation".

**Sending a message.**

```
POST /api/copilot/chat
{ "customer_id": "MG-100004", "message": "<text or chip>", "conversation_id": <null on the first turn> }
```

* Store the returned `conversation_id` **per customer** and send it with every follow-up. Switching customers means
  a new conversation (no id). If the server answers 409 (different customer or turn limit), drop the id and resend
  without it.
* Show the employee's message immediately (optimistic), then a typing indicator until the response arrives.
* Disable the send button while a request is in flight; one request per conversation at a time keeps turns in order.

**Loading states.** Without an AI model the answer is deterministic and typically returns in well under a second (the
first request after a restart can take a few seconds while the engine warms up). With an AI model configured a
request can take up to `AI_TIMEOUT_S` (default 20 s) plus processing; show the typing indicator, and after about
5 seconds a hint such as "Lighty formuliert die Antwort…". Use a client timeout a bit above `AI_TIMEOUT_S` (e.g.
30 s). On a client timeout, offer "retry"; the server falls back to the deterministic answer on its own if the model
fails, so a retry normally succeeds.

**Rendering one answer.**

| Element | Field | How |
|---|---|---|
| Answer | `response` | Plain text. Lines starting with `- ` are bullets. Render as text, never as HTML/Markdown (it never contains markup, but treat it as untrusted anyway). |
| Origin badge | `answer_origin` | `llm_used=false` → "Regelbasiert"; `true` → "KI-formuliert, geprüft". Show `fallback_reason` in a tooltip. |
| Recommendation card | `recommended_action` | Product, channel, `expected_dclv_eur` (label "Modellschätzung"), `approval_status`, `sales_restricted` with `restriction_codes`. This is the same engine decision as `GET /recommendations`; the copilot never changes it. |
| Suggested wording | `suggested_customer_message` | Box with a "Kopieren" button only. Label it "Vorschlag – vor Verwendung prüfen" (`requires_human_approval` is always `true`, `auto_send` always `false`). No send button. |
| Warnings | `warnings[]` | Yellow banners above the answer. `sales_restricted` should be prominent. |
| Facts | `supporting_facts[]` grouped by `answer_parts` | Three groups: *Daten* (`verified_fact`), *Lighty-Berechnung* (`engine_computed`), *Fehlt in den Daten* (`data_gap`). Each fact is a chip; clicking shows its `source_refs` resolved via `source_references[]` (table, record id, date). |
| Confidence | `confidence_or_uncertainty` | `level` as a small indicator; list `data_gaps` and `assumptions` under "Unsicherheit". |

**Reloading a conversation.** `GET /api/copilot/conversations/{conversation_id}` returns all turns; each `lighty`
message carries the full answer in `payload`, so the chat can be re-rendered exactly. Another employee's id answers
404, which the UI should treat as "conversation not available".

**Error handling.**

| Status | `error` | UI behaviour |
|---|---|---|
| 401 | `unauthorized` | Token missing or invalid: ask the employee to sign in again. Do not retry automatically. |
| 403 | `forbidden` | Hide the feature for this role (e.g. "all employees" filter for non-admins). |
| 404 | `not_found` | Unknown customer or conversation: show "nicht gefunden"; for a conversation, start a new one. |
| 409 | `conflict` | Conversation belongs to another customer or reached `COPILOT_MAX_TURNS`: start a new conversation and resend. |
| 422 | `validation_error` | Empty message, more than 2000 characters or unknown fields: show the field error at the input. |
| 503 | `ai_unavailable` | Only with `require_llm: true`. Offer "ohne KI beantworten" (resend without the flag). |
| network / 5xx | — | Keep the employee's text in the input, show "Lighty ist gerade nicht erreichbar", offer retry. |

**Things the frontend must not do.** Do not send customer messages from the copilot screen, do not pre-fill an
email client with `suggested_customer_message`, do not show `untrusted_customer_texts` as instructions (render them
quoted with their label), and do not show facts of another customer in the same panel.

## 6. Copilot rules (what the backend guarantees)

* **Internal only.** No endpoint contacts a customer or sends a message. Customer wording is always a suggestion
  (`requires_human_approval: true`, `auto_send: false`).
* **Database is the source of truth.** Every fact has source references to a workbook table or event. When the data
  does not answer a question, the answer says so and lists it under `data_gaps`.
* **The engine decides.** `recommended_action` is the Lighty engine's decision for the same point in time. The copilot
  and the AI model cannot change it, and the AI model never computes CLV values; it only rephrases.
* **Service first.** With an open service case (complaint, charging problems, dunning, pending cancellation) the
  copilot suggests no product offers and says so (`sales_restricted`).
* **No promises.** No discounts, credits, compensation, goodwill or guarantees. Compensation questions are answered
  with "not approved in the data; use the internal process".
* **Consent.** Behavioural marketing data (newsletter engagement, portal interest, abandoned carts) is only used with
  `profiling_analytics` consent; otherwise it is withheld and listed in `withheld`.
* **Untrusted customer text.** Ticket messages and call transcripts are customer content, never instructions. Only the
  customer's own lines, max 400 characters, only for `service_agent`/`admin`. Text that looks like instructions is
  flagged and not sent to the AI model.
* **Minimised AI prompts.** Only the facts selected for the question are sent, without customer id, record ids,
  birth year, postal code or city, plus at most `COPILOT_HISTORY_MESSAGES` earlier messages. Never the whole dataset.
* **Validated AI output.** JSON shape, cited fact ids, every number must appear in the facts, no customer ids, no
  markup, no promises; customer wording additionally passes the message validator. Anything failing is replaced by
  the deterministic answer and reported in `warnings`.
* **Isolation.** A conversation is bound to one employee and one customer; history is separate per conversation.
* **AI protocol.** The client speaks the OpenAI-compatible chat-completions format (`AI_PROTOCOL`,
  `AI_CHAT_PATH`, `AI_AUTH_HEADER`, `AI_AUTH_SCHEME`). It has not been verified against the hessian.AI gateway
  documentation; `GET /api/health` → `ai.protocol_verified` stays `false` until it is.

## 7. Changes in v1.1 (Lighty)

| Area | Change | Compatibility |
|---|---|---|
| Name | MAINGAU Guardian is now **Lighty** ("Smarter decisions. Better conversations."): OpenAPI title, docs, AI prompts, log names. MAINGAU business terms, table and column names are unchanged. | No field renamed. |
| Engine version | `engine_version` is `lighty-1.1.0` (was `guardian-1.0.0`). Decision ids include the version, so **all `decision_id`s changed**. Approvals stored under old ids are not carried over. | Re-fetch decisions after the update. |
| Renamed fields | `baseline_actions_blocked_by_lighty_rules` (overview) and `executable_under_lighty_rules` (simulator baseline) are new. | The old `…_guardian_rules` fields are still sent with the same values; deprecated (planned removal in v2). |
| EV signal | The EV signal now also counts kept e-mobility shop orders (`Wallbox 11 kW`, `Ladekabel Typ 2`). New signal `ev_shop_orders` (order ids). Eligible options rose from 1693 to 1729; overview totals are unchanged. | Additive. |
| Event ids | Event-derived tickets, charge sessions and orders carry `event_id`; ticket updates carry `latest_note_event_id`. | Additive. |
| New endpoints | Copilot chat, briefing, context, conversations, suggested questions, me (§4.12–4.18). | Additive. |
| Health | New `employee_auth` (`mode`, `protect_customer_endpoints`); `ai` adds `protocol_verified` (always `false` for now). | Additive. |
| Employee auth | New settings `EMPLOYEE_TOKENS`, `ALLOW_DEV_AUTH`, `PROTECT_CUSTOMER_ENDPOINTS` (default `false`, so existing endpoints stay open as before). | Opt-in. |
| AI settings | New `AI_CHAT_PATH`, `AI_AUTH_HEADER`, `AI_AUTH_SCHEME`, `AI_MAX_TOKENS`; `AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL` unchanged. | Defaults match v1. |
| SQLite file | Default `SQLITE_FILE` is `lighty.sqlite3` (was `guardian.sqlite3`). | Set `SQLITE_FILE=guardian.sqlite3` to keep using the old file. |
| Docker | Service, image, container and volume are named `lighty`. Ports (`80:8000`) and `/srv` mounts are unchanged. | Stop the old `maingau-guardian` container before starting `lighty` (both use port 80). |
