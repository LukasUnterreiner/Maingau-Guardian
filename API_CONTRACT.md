# MAINGAU Guardian — API Contract v1

This is the contract for the frontend team. Response structures in this document are
stable for `engine_version = guardian-1.0.0`. New fields may be **added**; existing fields
will not be renamed, removed or change type without a version bump.

Interactive docs: `GET /docs` (Swagger UI) and `GET /openapi.json`.
All JSON examples below are real responses from the dataset (arrays shortened with `…`).

## 1. Conventions

| Topic | Rule |
|---|---|
| Base URL | Local: `http://localhost:8000`. Server: `http://<host>:38080` (→ VM port 80 → container 8000). |
| Prefix | Every endpoint lives under `/api`. |
| Content type | `application/json; charset=utf-8`. German text is UTF‑8. |
| Money | `*_eur` fields are floats in EUR, rounded to 2 decimals. |
| Probabilities | Floats in `[0, 1]` (`0.1099` = 10.99 %). `churn_*` are 12‑month probabilities. |
| Timestamps | Strings `YYYY-MM-DD HH:MM:SS` (dataset local time, no time zone). Review timestamps are ISO‑8601 UTC. |
| Unknown values | `null` means *unknown*, never *no*. E.g. `product_holdings["P-IN-01"] = null` = holding not in data. |
| Value labels | Every money/probability figure is **observed** (from the dataset), **estimated** (model) or **simulated** (scenario). See `value_labels` / `value_label`. Guardian values are model-based estimates, not realised savings or causal uplift. |
| Point in time | Optional `as_of` query/body parameter: `latest` (default, snapshot + full event stream), `snapshot` (2026‑09‑30 23:59:59, no events) or an ISO timestamp such as `2026-10-01T10:15:00`. |
| Pagination | `page` (≥1) and `page_size`; responses carry `items`, `page`, `page_size`, `total`, `total_pages`. |
| CORS | Allowed origins come from `CORS_ORIGINS` (default `http://localhost:3000,http://localhost:5173`). |
| Auth | `PUT /api/marketing/settings` and the approve/reject endpoints require header `X-Admin-Token` **when** the server sets `ADMIN_TOKEN`. In local dev (no token set) they are open. |

### Errors

All errors share one shape:

```json
{ "error": "not_found", "detail": "Customer MG-000000 not found" }
```

| HTTP | `error` | When |
|---|---|---|
| 401 | `http_error` | Missing/invalid `X-Admin-Token` (only if `ADMIN_TOKEN` is configured). |
| 404 | `not_found` | Unknown customer id or decision id. |
| 409 | `conflict` | Approving an already reviewed decision, approving/messaging a no‑contact decision, or approving an action that is no longer permitted (e.g. consent was withdrawn meanwhile). |
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
| GET | `/api/customers/{customer_id}/recommendations` | Guardian decision (Next Best Action) |
| POST | `/api/customers/{customer_id}/simulate` | Counterfactual simulation |
| GET | `/api/marketing/overview` | Dashboard aggregates incl. Projected Protected Customer Value |
| GET | `/api/marketing/recommendations` | Paginated list of decisions across all customers |
| GET | `/api/marketing/settings` | Current runtime settings |
| PUT | `/api/marketing/settings` | Update runtime settings (validated, cannot loosen hard rules) |
| POST | `/api/decisions/{decision_id}/approve` | Human approval |
| POST | `/api/decisions/{decision_id}/reject` | Human rejection |
| POST | `/api/ai/explain` | Natural-language explanation (LLM or deterministic fallback) |
| POST | `/api/ai/generate-message` | German customer draft (always pending approval) |

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
  "ai": { "configured": false, "protocol": "openai_chat_completions", "enabled": false, "model": null },
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

### 4.4 `GET /api/customers/{customer_id}/recommendations` — Guardian decision

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
  "decision_id": "DEC-9584ea6ab3bda89a",
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
  "engine_version": "guardian-1.0.0"
}
```

Example — healthy cross-sell (MG‑100127, abbreviated):

```json
{ "customer_id": "MG-100127", "decision_id": "DEC-c5ee7ad5f7406971", "recommended_action": "P-MO-01", "recommended_action_name": "Mobil S / M / L",
  "action_type": "sales", "product_id": "P-MO-01", "channel": "app_push", "process": "marketing", "tonality": "sie", "tonality_source": "default_formal",
  "current_clv_eur": 3263.46, "expected_dclv_eur": 66.0, "estimated_clv_after_eur": 3329.46, "acceptance_probability": 0.1099,
  "required_service_workflow": false, "requires_human_approval": true, "approval_status": "pending_approval",
  "reason": "Offer Mobil S / M / L via app_push: expected dCLV +66.00 EUR versus no contact (estimated acceptance 11.0%). Adds 54 EUR annual margin if accepted. Next best permitted alternative: P-IN-01 (+40.47 EUR).",
  "alternatives": [ { "product_id": "P-IN-01", "channel": "portal_popup", "expected_dclv_eur": 40.47, "…": "…" }, "…", { "product_id": "NO_CONTACT", "expected_dclv_eur": 0.0, "…": "…" } ],
  "blocked_actions": [ { "product_id": "P-EN-03", "exclusion_reasons": ["PREREQUISITE_MISSING"], "…": "…" } ],
  "eligibility_checks": ["…"], "value_labels": {"…": "…"}, "engine_version": "guardian-1.0.0" }
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
  "decision_id": "DEC-a63ff8ce0afed84f",
  "base_decision_id": "DEC-9584ea6ab3bda89a",
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
                "executable_under_guardian_rules": false, "expected_dclv_eur": -8.81, "projected_protected_value_eur": 46.33 },
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
| `total_projected_incremental_clv_eur` | Sum of Guardian expected dCLV. |
| `baseline` | Baseline policy, its total expected dCLV, action mix and how many of its actions Guardian's rules would block. |
| `projected_protected_customer_value_eur` | Guardian total − baseline total. **Model-based estimate.** |
| `value_by_segment`, `value_by_clv_tier` | Customers, expected dCLV (and current CLV) per business-line mix / CLV tier. |
| `settings_version` | Version of the settings used. |

```json
{
  "total_customers_evaluated": 750,
  "as_of": "2026-10-02 02:03:52",
  "marketing_actions": { "eligible_product_options": 1693, "blocked_product_options": 11057,
                         "blocked_by_reason": { "PREREQUISITE_MISSING": 7646, "CHANNEL_NOT_AVAILABLE": 3964, "PROFILING_CONSENT_NOT_GIVEN": 3349, "…": 0 } },
  "recommended_action_distribution": { "NO_CONTACT": 337, "P-MO-01": 127, "P-SV-01": 118, "P-EN-01": 69, "P-IN-01": 66, "P-EN-02": 24, "P-EN-04": 7, "P-EN-03": 2 },
  "recommended_by_action_type": { "no_contact": 337, "sales": 271, "service": 118, "retention": 24 },
  "recommended_by_business_line": { "none": 337, "mobile": 127, "service": 118, "energy": 102, "internet": 66 },
  "recommended_by_channel": { "none": 337, "newsletter_email": 119, "service_email": 110, "app_push": 85, "portal_popup": 71, "outbound_call": 17, "service_call": 10, "sms": 1 },
  "customers_with_active_service_issues": 227,
  "pending_approvals": 413,
  "total_current_clv_eur": 412035.44,
  "total_projected_incremental_clv_eur": 15982.06,
  "baseline": { "policy": "conventional_sales_first", "total_expected_dclv_eur": 8022.89,
                "action_distribution": { "P-SH-01": 374, "P-MO-01": 181, "NO_CONTACT": 63, "…": 0 }, "baseline_actions_blocked_by_guardian_rules": 360 },
  "projected_protected_customer_value_eur": 7959.17,
  "projected_protected_customer_value_label": "Model-based estimate: expected CLV under Guardian minus expected CLV under the baseline policy. Not realised savings and not proven causal uplift.",
  "value_by_segment": { "energy": { "customers": 393, "expected_dclv_eur": 8290.8, "current_clv_eur": 200964.09 }, "…": {} },
  "value_by_clv_tier": { "clv_0_500": { "customers": 343, "expected_dclv_eur": 6631.57 }, "…": {} },
  "settings_version": 0
}
```

### 4.7 `GET /api/marketing/recommendations`

Query: `page`, `page_size` (1–500, default 50), `action_type`, `channel`, `business_line`, `approval_status`, `include_no_contact` (default `false`). Sorted by `expected_dclv_eur` desc.

```json
{
  "items": [
    { "customer_id": "MG-100315", "decision_id": "DEC-b205eb767385c725", "recommended_action": "P-SV-01",
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
{ "decision_id": "DEC-9584ea6ab3bda89a", "customer_id": "MG-100004", "approval_status": "approved",
  "reviewer": "marketing.lead", "review_note": "ok", "reviewed_at": "2026-10-26T14:57:42+00:00" }
```

### 4.10 `POST /api/ai/explain`

Body: `{ "decision_id": "DEC-…" }` or `{ "customer_id": "MG-…" }` (computes the current decision).

```json
{ "customer_id": "MG-100004", "decision_id": "DEC-9584ea6ab3bda89a", "recommended_action": "P-SV-01",
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
{ "customer_id": "MG-100127", "decision_id": "DEC-c5ee7ad5f7406971", "message_id": 1, "channel": "app_push", "tonality": "sie",
  "language": "de", "preferred_contact_language": "de", "subject": null,
  "body": "MAINGAU: Passend zu Ihrem Vertrag stellen wir Ihnen unsere Mobilfunktarife vor. Details im Kundenportal. Abmeldung jederzeit im Portal möglich.",
  "source": "template_fallback", "fallback_reason": "AI not configured",
  "validation": { "passed": true, "problems": [], "length": 143 },
  "approval_status": "pending_approval", "requires_human_approval": true }
```

For `service_call` / `outbound_call` the body is a call guide for the agent, not a message. Validation rejects numbers, prices, percentages, urgency phrases, wrong Du/Sie and over-long texts.

## 5. Integration guide

1. **Customer list** → `GET /api/customers?page=1&page_size=25` (filter `has_service_issue=true` for the service view).
2. **Customer page** → `GET /api/customers/{id}` for the 360° panel and `GET /api/customers/{id}/recommendations` for the decision card. Show `recommended_action_name`, `channel`, `expected_dclv_eur`, `reason`; render `alternatives` as the comparison table and `blocked_actions` greyed out with their `exclusion_reasons` (they are illustrative, never executable).
3. **What-if panel** → `POST /api/customers/{id}/simulate` with slider values; show `base` vs `scenario` rankings, `recommendation_changed`, `parameter_attribution` and `baseline.projected_protected_value_eur`.
4. **Approve flow** → `POST /api/ai/generate-message` to show the draft, then `POST /api/decisions/{decision_id}/approve` or `/reject`. Handle 409 (already reviewed / no longer permitted).
5. **Dashboard** → `GET /api/marketing/overview` and `GET /api/marketing/recommendations`.
6. **Settings page** → `GET`/`PUT /api/marketing/settings`; show 422 `detail` messages to the user.
7. Always display the value labels: "estimated", "model-based", "not realised savings".
