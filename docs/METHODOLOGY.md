# Guardian methodology, assumptions and fallbacks

This document explains how every number is produced, which inputs are observed,
estimated or simulated, and every place where the data does not specify something.

## 1. Data inspection (done before coding)

* 23 sheets (the 18 listed in the brief plus `README`, `columns`, `sources`, `clv_method`
  and `newsletter_campaigns`). 750 customers, snapshot 2026‑09‑30 23:59.
* The `clv_method` formula reproduces `customer_value.clv_eur` for all 750 customers within
  ±3.5 EUR (the inputs in `customer_value` are rounded). Test: `test_clv_formula_reproduces_dataset_at_snapshot`.
* The churn model behind `churn_prob_12m` was reverse-engineered and verified:

  ```
  churn = mean(base churn of active contracts) × max(0.8^(lines−1), 0.5) + Σ driver increments
  churn = 0.95 if a cancellation was received
  ```
  base: electricity 0.14, gas 0.12, mobile 0.18, Autostrom 0.20. Energy counts as one
  business line, HEMS counts as a line but has no base churn. The driver set Guardian derives
  from the raw tables matches the documented `churn_drivers` text for **all 750** customers.
  Test: `test_churn_drivers_match_documented_drivers_for_all_customers`.
* 24 customers without an active line have churn 0.25 — a base that is **not documented**
  in `value_assumptions`. Guardian therefore never recomputes the base; it uses
  `structural_churn = churn_prob_12m − Σ snapshot driver increments` (see §3).
* Event stream: 647 lines, 12 duplicate `event_id`s (dropped), late events (ingested the next day).

## 2. Customer 360° and time

* State at `as_of` = workbook snapshot + events with `occurred_at ≤ as_of`. Default `as_of` is the
  last event (full replay). The effective time of an event is `occurred_at`: a consent withdrawal is
  binding from the moment it happened.
* Charging sessions only count once their CDR arrived (`cdr_received_at ≤ as_of`) — late roaming CDRs.
* Windows: tickets 12 calendar months, failed charging 30 days, price guarantee end within 90 days.
* Newsletter engagement ignores `apple_mpp_prefetch` machine opens. Guest shop orders (no
  `customer_id`) are not attributed.
* Unknown stays unknown: missing CSAT is not "low CSAT", a missing consent row is `unknown`
  (= not granted, but reported as unknown), unknown holdings are `null`.
* `payment_method` columns are dropped at load time (hard rule 8).
* Tonality: counted Du/Sie markers in the customer's own ticket messages and the "Kunde:" lines of
  call transcripts. No signal → `sie` with `tonality_source = default_formal`.

| Event | Effect |
|---|---|
| `consent_changed` | Overrides the consent type from `occurred_at`. |
| `dunning_level_changed` | Updates the matching energy contract. |
| `contract_cancellation_received` | Contract → `cancellation_pending` (churn 0.95, marketing blocked). |
| `gas_meter_deregistration_received` | Marks deregistration (signal for heat pump, blocks gas offers). |
| `ticket_created` / `ticket_updated` | New open ticket / status + note (e.g. "Kunde fordert Rückruf" → service call). |
| `charge_session_failed` | Adds a failed session. |
| `call_transcript_ready` | Customer lines feed tonality. |
| `order_placed` | Counts as a shop holding. |
| others | Recorded in `applied_events`, no decision effect. |

## 3. CLV engine (clv_method, literally)

```
CLV  = Σ_{t=1..H} (annual_margin − cost_to_serve) · (1 − churn)^(t−1) / (1 + r)^t
dCLV = p · (CLV_accept − CLV_now) + (1 − p) · (CLV_reject − CLV_now) − contact_cost
```

* `r` and `H` from `value_assumptions` (6 %, 10 years). Margin and cost to serve from `customer_value` (observed).
* `churn_now = structural_churn + Σ live driver increments` (0.95 if cancellation pending). At the
  snapshot this equals the dataset value exactly; events can add or remove drivers.
* **sales / upsell**: margin + `annual_margin_if_bought_eur`, churn + `churn_effect_if_bought` (annuity).
* **one_off (shop)**: margin added **once**, undiscounted (purchase happens now), plus churn effect.
* **retention P‑EN‑02**: the `price_guarantee_ends_90d` driver is removed. The catalogue churn effect
  (−0.10) describes the same effect and is **not** added again.
* **service P‑SV‑01**: service churn drivers removed (open complaint, last CSAT ≤ 2, dunning ≥ 2,
  ≥ 3 failed charges in 30 d — the list in `clv_method`), minus `service_resolution_cost_eur` (15 EUR).
  `tickets_12m_ge2` is history and is not undone. Cost to serve and `clv_service_impact_eur` are **not**
  adjusted in addition (no double counting).
* **reject**: `CLV_now`, except a marketing contact during an open complaint or dunning:
  churn + `contact_during_service_case` (0.05).
* **no contact**: explicit baseline, dCLV = 0.
* Contact costs by channel: email/newsletter 0.01, SMS 0.08, portal pop-up 0.00, call 6.00.
  `app_push` uses the pop-up cost (the parameter is described as "Portal/app pop-up").

## 4. Acceptance probabilities (estimated, observational)

* Source: `nba_action_history`, delivered non-control actions, 14-day conversion.
* Legacy actions sent without a consent check (297) are excluded by default — we do not learn from
  contacts that should not have happened (setting `exclude_unconsented_history`).
* Beta smoothing with pseudo-count k = 20: global → offer → offer×channel → offer×channel×tonality.
* Offers without history (P‑EN‑01, P‑EN‑03, P‑EN‑04, P‑MO‑03, P‑SL‑02, P‑SL‑03, P‑SH‑04) fall back to the
  global rate (3.42 %) and are labelled `fallback_global_rate_no_offer_history`.
* Control group: smoothed control conversion per offer is reported next to every p. Mode
  `net_of_control` uses max(0, treated − control) as a conservative alternative.
* **P‑SV‑01** has no history. Proxy: share of closed tickets of the relevant category (complaint,
  autostrom for charging, billing for dunning) resolved without escalation and without a repeat
  contact, smoothed toward the all-ticket rate. Labelled `service_resolution_proxy_<category>`.
* None of these are causal effects. Every response carries value labels saying so.

## 5. Eligibility and compliance

| Rule | Implementation |
|---|---|
| 1 Channel consent | newsletter_email → `newsletter_email` (+ double opt-in); portal_popup/app_push → `portal_app_personalisation` (+ portal account / app); sms → `marketing_sms`; outbound_call → `marketing_phone`. |
| 2 Withdrawal | Event replay by `occurred_at`; unsubscribes via newsletter after the last consent update count as withdrawn. |
| 3 Profiling | Every marketing NBA is personalised → `profiling_analytics` must be granted. |
| 4 Service state | Open complaint, dunning ≥ 1, pending cancellation block all marketing incl. retention. |
| 5 Frequency | Delivered marketing actions: ≤ 2 in 30 days, ≥ 7 days gap (policy defaults — the data defines none; hard cap 4). |
| 6 Holdings | Held products and missing prerequisites block (`PRODUCT_ALREADY_HELD`, `PREREQUISITE_MISSING`). |
| 7 Prices / urgency | The engine never outputs prices. Message templates contain none; the validator rejects numbers, €, %, urgency phrases. |
| 8 Payment data | `payment_method` dropped at load. Dunning is used only as the documented exclusion signal and churn driver. |
| 9 Human approval | Every executable action starts `pending_approval`; approval re-checks eligibility on the latest data. |
| 10 Service ≠ marketing | Service channels (`service_email`, `service_call`) carry only P‑SV‑01 content and need no marketing consent; marketing needs consent + profiling. |

Prerequisites per product follow `product_catalog.typical_target_signal`. Where the catalogue says
the signal is unknown in the data (gas heating, balcony, internet holdings) the product is **not**
blocked for that reason.

**Customer-initiated tariff inquiry (interpretation to confirm with MAINGAU).** If the customer has an
open `tariff` ticket (e.g. MG‑100006 called on 2026‑10‑01 asking for an offer because the price
guarantee ends), the retention offer P‑EN‑02 may be sent as the **reply to that request** through the
service channel (`process = customer_inquiry_reply`). Marketing consent, profiling and frequency limits
do not apply to answering the customer's own request; complaint/dunning/cancellation blocks and human
approval still apply. p uses the offer-level history (conservative: history is unsolicited contacts).

## 6. Decision rule

1. Evaluate all (product × channel) candidates; best channel per product.
2. Rank executable products by expected dCLV (priority setting only breaks ties).
3. Recommend the top action if dCLV > `min_expected_dclv_eur` (default 0), else no contact —
   unless the customer has an open complaint and P‑SV‑01 is permitted (required service workflow,
   flagged `required_service_workflow = true`).
4. Decision ids are SHA-256 of customer, `as_of`, settings, scenario and engine version → deterministic.

## 7. Counterfactual simulator and baseline

* Scenario parameters only reach the CLV engine and p; eligibility is computed without them, and the
  simulator raises an error if the set of blocked candidates ever differs from the base run.
* `parameter_attribution` re-runs every changed parameter on its own.
* **Baseline `conventional_sales_first`**: per customer the sales/upsell/one-off offer with the highest
  `p × margin_if_bought`, among products not held and whose prerequisite fits, on any channel with
  channel consent. It ignores service state, profiling consent and contact frequency (like a
  campaign engine) and is then valued with the same CLV method.
* **Projected Protected Customer Value** = Σ Guardian expected dCLV − Σ baseline expected dCLV.
  Model-based estimate; not realised savings and not proven causal uplift.

## 8. AI

* Optional; disabled unless `AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL` are set. Only an OpenAI-compatible
  `/chat/completions` protocol is implemented and it is **not verified** against hessian.AI docs.
* The model gets a minimal fact sheet (no name, birth year, address, contract ids) and only rephrases.
  Explanations may contain no numbers that are not in the facts; drafts may contain no numbers,
  prices, %, urgency, wrong Du/Sie. Failures → deterministic fallback. Drafts are stored as pending approval.

## 9. Known limitations

* `customer_value` margins are monthly snapshots; events do not change margin or cost to serve.
* The customer-initiated inquiry path is a legal interpretation, not a challenge rule.
* Products with no history share the global acceptance rate.
* Contact-frequency defaults are a policy choice, not data.
* German drafts for the 7 customers with `preferred_contact_language = en` are still German (the brief
  asks for German); the response reports the preferred language so the reviewer can decide.

## 10. Priority 4 (concept, not implemented)

* **Uplift evaluation**: log approved/rejected decisions and outcomes; keep a random 10 % hold-out per
  action (as the legacy engine did) and estimate uplift as treated − control per action with
  confidence intervals before calling anything causal.
* **Feedback**: `service_nba_feedback` (agent dismiss reasons, "customer_upset") could down-weight
  offers during service contacts.
* **Event replay** is implemented via `as_of`; streaming ingestion would apply the same handlers.
