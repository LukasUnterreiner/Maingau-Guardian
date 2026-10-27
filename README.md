# Lighty — Backend

**Smarter decisions. Better conversations.**

Lighty (formerly *MAINGAU Guardian*) has two parts:

1. **Decision engine.** A Next Best Action engine that picks, for each customer, the action with the highest
   expected change in Customer Lifetime Value — a product offer, a retention offer, proactive service resolution,
   or no contact at all — after hard compliance rules have been applied. Every decision comes with its
   counterfactuals: what the alternatives would be worth and why blocked actions are blocked.
2. **Employee copilot.** An internal assistant for MAINGAU service and sales employees. It builds a sourced
   customer context from all tables, writes a pre-call briefing, and answers questions such as *"Wie sollte ich mit
   diesem Kunden umgehen?"* in a multi-turn chat. It uses only database facts and the engine's decision, never
   contacts customers, and every suggested customer wording needs human approval.

Futury Build Days hackathon with MAINGAU Energie and hessian.AI. The backend is in `app/`; a web app in the team's
"Daylight" design that runs on top of it is in `frontend/` (see [Web app](#web-app-frontend)).

* API reference for the frontend: [`API_CONTRACT.md`](API_CONTRACT.md) (copilot: §4.12–4.18, chat UI guide: §5.1,
  changes from Guardian: §7)
* How every number is computed, assumptions and fallbacks: [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md)
* Swagger UI: `http://localhost:8000/docs`

## Quick start (macOS / Linux)

```bash
python3.12 -m venv .venv && source .venv/bin/activate     # Python 3.11+ ; 3.12 recommended
pip install -r requirements-dev.txt
cp .env.example .env                                     # then set ALLOW_DEV_AUTH=true for local copilot tests
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then open <http://localhost:8000/docs> or try:

```bash
curl localhost:8000/api/health
curl localhost:8000/api/customers/MG-100004/recommendations        # service case
curl localhost:8000/api/customers/MG-100127/recommendations        # healthy cross-sell
curl -X POST localhost:8000/api/customers/MG-100004/simulate \
     -H 'Content-Type: application/json' \
     -d '{"acceptance_probability_overrides":{"P-SV-01":0.5},"service_resolution_cost_eur":30}'
curl localhost:8000/api/marketing/overview

# Copilot (local dev mode: ALLOW_DEV_AUTH=true; on a server use X-Employee-Token instead)
H='-H X-Employee-Id:agent-7 -H X-Employee-Role:service_agent'
curl $H localhost:8000/api/customers/MG-100004/briefing
curl $H -X POST localhost:8000/api/copilot/chat -H 'Content-Type: application/json' \
     -d '{"customer_id":"MG-100004","message":"Wie sollte ich mit diesem Kunden umgehen?"}'
```

The data files live in `data/` (`maingau_nba_mockdata.xlsx`, `event_stream_2026-10-01.jsonl`).
Startup loads and validates them and pre-computes decisions for all 750 customers (about 7–8 s in total).
A deterministic copilot answer then takes a few milliseconds.

## Employee copilot

| Endpoint | Purpose |
|---|---|
| `POST /api/copilot/chat` | Grounded answer about one customer; send `conversation_id` for follow-ups |
| `GET /api/customers/{id}/briefing` | Pre-call briefing: overview, situation, approach, German opening, what to avoid, NBA, economic rationale |
| `GET /api/customers/{id}/context` | Customer context as typed facts with source references (optionally only those relevant to a question) |
| `GET /api/copilot/conversations[/{id}]` | Own conversations (admins: all) |
| `GET /api/copilot/suggested-questions` | Starter questions for the chat |
| `GET /api/copilot/me` | Current employee and permissions |

How an answer is made: authenticate the employee and check the role → build the customer context from all tables
(`customer_context_service.py`) → take the engine's decision for the same point in time → apply consent and role
filters → select only the facts relevant to the question → compose a deterministic answer → optionally let the LLM
rephrase it from a minimised prompt (no customer id, no address data, untrusted customer text delimited and
filtered) → validate the output (cited facts, numbers, promises, markup, Du/Sie) → return answer, recommended
action, suggested wording, facts, source references, warnings and uncertainty.

Without an AI model, or when the model fails or its output does not pass validation, the copilot answers with the
deterministic rules. The request format was checked against the hessian.AI Inference API handout
(`https://hip-gw.hessian.ai/v1`, `/chat/completions`, Bearer key, model `vllm/Kolibri-1`); `.env.example` is
prefilled with these values, only `AI_API_KEY` has to be set on the server. A live call has not been made from the
development environment (the gateway was not reachable from there), so test it once on the server.

## Web app (`frontend/`)

A Streamlit app in the team's Lighty "Daylight" design (`frontend/theme/`, unchanged from the design team) that shows
live data from the backend:

* **Cockpit** (soft-card layout): KPI tiles with small bar charts of real distributions (pending decisions by type,
  customers by churn band, ΔCLV by CLV tier, Lighty vs. sales-first), customer cards for the most valuable customers
  likely to cancel and for the top decisions waiting for review (churn risk, value at stake, Lighty's next step,
  Details / Reject / Approve), an activity feed of the latest approvals and rejections (`reviewed_by`,
  `reviewed_at`), today's decision mix and contacts by channel.
* **Churn risk**: the customers most likely to cancel (top quarter by 12-month churn risk), why (the churn
  drivers), the customer value at stake if they leave (their CLV) and the CLV already lost to service problems
  (`clv_service_impact_eur` from the data). Each customer page starts with the same churn card, including what
  Lighty's recommended action does to the risk.
* **Regions**: a map of Germany (16 state outlines from Natural Earth, served by the app itself, no map tiles and no
  request to outside servers), on the night blue of the sidebar. States are coloured by a rate (a lighter blue is a
  higher rate), each city gets a spark-yellow pillar as tall as an amount; four views (Churn, Service, Opportunity,
  Workload). Under the map: the colour range (High / Medium / Low) and the highest and lowest state or city. Click a state to zoom in, click a city to narrow the customer cards to it;
  the selection is in the page address (`?region=DE-HE&city=Darmstadt`). Data from `GET /api/marketing/regions`.
  Reporting only: the region is never used for a recommendation.
* **Approval queue**: all decisions by status (pending, approved, rejected) with filters; select a row to see the
  full decision and approve or reject it. **Export to Excel** downloads the filtered list as an .xlsx file (numbers
  with € and % formats, header row frozen, filters on).
* **Customers**: Lighty's decision for one customer, the options it compared (blocked ones greyed out with their
  rule codes) and **Ask Lighty**, the employee copilot chat with suggested questions, warnings, fact chips,
  confidence and the German wording box (copy only, never send). Lighty answers in the app language; the wording
  for the customer is always German.
* **English / Deutsch**: the switch in the sidebar (and on the sign-in card) changes the whole app, including
  Lighty's chat answers, the decision reason, number and date formats and the Excel export. The choice is kept in
  the page address (`?lang=Deutsch`), so a reload keeps it. English has no Sie/Du, so the English app shows the form
  of address as Formal/Informal. Texts live next to their use as `tr("English", "Deutsch")` (`frontend/i18n.py`).

Employees sign in with a token from `EMPLOYEE_TOKENS`. The app calls the backend from the server side, so CORS does
not apply. Everything the API returns is HTML-escaped before it is shown.

```bash
cd frontend && pip install -r requirements.txt
LIGHTY_API_URL=http://localhost:8000 streamlit run app.py      # http://localhost:8501
```

| Variable | Default | Purpose |
|---|---|---|
| `LIGHTY_API_URL` | `http://localhost:8000` (`http://lighty:8000` in Docker) | Backend address |
| `LIGHTY_TOKEN` | empty | Local use only: sign in automatically with this employee token |
| `LIGHTY_ADMIN_TOKEN` | empty | Needed only when the backend sets `ADMIN_TOKEN` (approve/reject); compose passes `ADMIN_TOKEN` from `.env` |

`docker compose up -d --build` starts it as service `lighty-ui` next to the backend, on VM port 443 (`UI_PORT`).
On wsvm38 that is **`http://130.83.85.181:38443`** (plain HTTP on that port, type `http://`).

Tested by hand in Chromium against the local backend: sign-in (wrong and right token), cockpit, approving a
decision (flash message, pending count goes down), approving and rejecting from the cockpit cards (activity feed
updates), queue filters, row selection, churn-risk page and card, customer page, two chat turns, the Regions map
(click on Hessen, click on Darmstadt, the four views, a shared link, phone width) and a phone-width view. There are no automated tests for the web app.

## Tests

```bash
pytest -q
```

106 tests:

* Engine (45): the 12 mandatory scenarios of the brief, the MG‑100004 service case, a dataset-wide check that the
  CLV formula and all churn drivers reproduce `customer_value`, API contract/error tests, the German decision reason
  and an unreachable-AI test.
* Copilot (46, `tests/test_copilot.py`): context building, personalised answers, unresolved issues, use of the
  engine decision, consent restrictions, cross-sell and retention, no fabricated values, missing information,
  invalid ids, unavailable or misbehaving LLM, conversation isolation, authorisation, no cross-customer leakage,
  prompt injection in customer text, safe output formatting and rule names in words instead of codes. Test
  customers are picked from the dataset by their situation, not hard-coded.
* Regions (6, `tests/test_regions.py`): every dataset city is in the city table, state totals equal the cockpit
  (750 customers, 204 likely to cancel, €64,426 at stake), cities carry their map position, invalid parameters,
  unknown cities counted as unassigned, missing city table.
* LLM client (9, `tests/test_llm_client.py`): request format of the hessian.AI gateway, removal of reasoning
  blocks, failures without leaking the key, pause after network errors.

Last run: **106 passed** (Python 3.13 local).

## Docker

```bash
docker compose up -d --build          # VM port 80 -> container port 8000
curl localhost/api/health
```

* The app listens on `0.0.0.0:8000` inside the container; `compose.yaml` maps VM port 80 to it. On the
  team server on the hessian.AI workshop infrastructure (wsvm38) the external port 38080 is forwarded to VM port 80, so the API is at
  `http://130.83.85.181:38080`. Per the server handout, clone the repo under `/srv` (e.g. `/srv/lighty`), the data disk.
  On wsvm38 the admin user needs `sudo` for Docker commands.
* Service, image, container and volume are named `lighty`. If the older `maingau-guardian` container runs on the
  same host, run `docker compose down` before updating the checkout (or `docker compose up -d --build
  --remove-orphans` afterwards), because both use port 80. The new volume starts with an empty decision log.
* `lighty-ui` (the web app, `frontend/`) is built from `frontend/Dockerfile` and maps VM port 443 to Streamlit's
  8501; it reaches the backend inside the compose network at `http://lighty:8000`.
* `./data` is mounted read-only at `/srv/data`; the SQLite decision log, approvals, settings and copilot
  conversations live in the named volume mounted at `/srv/runtime`.
* `restart: unless-stopped` and a health check on `/api/health`.
* Secrets (`AI_API_KEY`, `ADMIN_TOKEN`, `EMPLOYEE_TOKENS`) only via `.env` / environment — never baked into the image.
* Behind a registry mirror use `docker build --build-arg BASE_IMAGE=<mirror>/python:3.12-slim .`.

Nothing in this repository deploys anything automatically.

## Configuration

See [`.env.example`](.env.example). Important variables:

| Variable | Default | Purpose |
|---|---|---|
| `DATA_DIR` | `./data` (`/srv/data` in Docker) | Workbook + event stream location |
| `EVALUATION_AS_OF` | `latest` | `latest` (replay all events), `snapshot`, or ISO timestamp |
| `RUNTIME_DIR` | `./runtime` (`/srv/runtime`) | SQLite file location |
| `SQLITE_FILE` | `lighty.sqlite3` | Set `guardian.sqlite3` to keep the pre-rename file |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Frontend origins |
| `ADMIN_TOKEN` | empty | If set, settings and approvals need header `X-Admin-Token` |
| `EMPLOYEE_TOKENS` | empty | `token:employee_id:role,...` (roles `service_agent`, `sales_agent`, `marketing`, `admin`; tokens ≥ 12 characters). Required for the copilot on a server |
| `ALLOW_DEV_AUTH` | `false` | Local only: accept `X-Employee-Id`/`X-Employee-Role` without token when no tokens are set |
| `PROTECT_CUSTOMER_ENDPOINTS` | `false` | Also require an employee on the customer, marketing-list and AI endpoints |
| `COPILOT_HISTORY_MESSAGES` | `6` | Earlier messages of a conversation sent to the LLM |
| `COPILOT_MAX_TURNS` | `40` | Turns per conversation |
| `AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL` | empty | Optional LLM; without them deterministic texts are used |
| `AI_PROTOCOL` | `openai_chat_completions` | Only protocol implemented — verify against the provider docs first |
| `AI_CHAT_PATH`, `AI_AUTH_HEADER`, `AI_AUTH_SCHEME` | `/chat/completions`, `Authorization`, `Bearer` | Request format details, adjustable once the provider docs are checked |
| `AI_TIMEOUT_S`, `AI_MAX_TOKENS` | `20`, `700` | LLM call limits |
| `AI_CONNECT_TIMEOUT_S`, `AI_COOLDOWN_S` | `5`, `120` | If the gateway cannot be reached, stop trying after 5 s and answer deterministically for the next 2 minutes |
| `WARM_PORTFOLIO_ON_STARTUP` | `true` | Pre-compute all decisions at startup |

## Project structure

```
app/
  main.py                        FastAPI app, error handlers, CORS
  api/routes.py                  Engine, marketing and AI endpoints (/api/...)
  api/copilot_routes.py          Copilot, briefing and context endpoints (employee auth)
  config/settings.py             Environment configuration
  data/loader.py                 Workbook + event stream loading, validation, de-duplication
  models/schemas.py              Pydantic request/response models (engine contract)
  models/copilot_schemas.py      Pydantic models of the copilot contract
  models/runtime_settings.py     Editable settings with hard-rule bounds
  services/
    customer_service.py          Customer 360° state at a point in time (snapshot + event replay)
    churn_model.py               Churn drivers reproduced from the value model
    clv_engine.py                clv_method: CLV, dCLV per action type
    acceptance_model.py          Smoothed p_accept from nba_action_history; service resolution proxy
    eligibility_engine.py        Consent, profiling, service-state, frequency, holdings, prerequisites
    recommendation_engine.py     Ranking, no-contact baseline, reasons, conventional baseline policy
    counterfactual_engine.py     Scenario simulation + one-at-a-time attribution
    analytics_service.py         Dashboard aggregates, Projected Protected Customer Value
    ai_service.py                Explanations and German message templates, message validation, fallback
    llm_client.py                Configurable LLM client (OpenAI-compatible format), no key in logs
    access_control.py            Employee tokens, roles and permissions
    customer_context_service.py  Typed, sourced customer facts in four sections; untrusted-text handling
    ai_prompt_service.py         Minimised prompts and validation of model output
    employee_copilot_service.py  Chat, briefing, context selection, deterministic composition
    conversation_service.py      SQLite: copilot conversations and messages
    decision_log.py              SQLite: decisions, approvals, drafts, settings
    region_service.py            Totals per state and city for the Regions map (reporting only)
    lighty.py                    Facade used by the routes
frontend/
  app.py                         Streamlit entry: theme, sign-in, navigation
  lighty_api.py                  Client for the backend API
  i18n.py                        English / Deutsch switch and tr("English", "Deutsch")
  ui.py                          Design pieces filled with API data, cached data access, approve/reject
  views/                         Cockpit, churn risk, regions map, approval queue, customer page with Ask Lighty
  static/                        Logo, map outlines (geo/, Natural Earth) and Plotly's base map file (topojson/)
  theme/                         Lighty "Daylight" design from the design team (CSS, helpers, preview)
tests/                           pytest suite
data/                            Dataset (synthetic); reference/city_regions.csv maps cities to states
docs/METHODOLOGY.md              Method, assumptions, limitations
API_CONTRACT.md                  Frontend contract
```

## What to show a jury

* **MG‑100004** — open complaint, dunning level 3 (event on 2026‑10‑01), callback requested. Lighty recommends
  proactive service resolution by phone (+66.50 EUR expected dCLV); all sales offers are blocked with
  machine-readable reasons; a conventional engine would have sent a shop offer worth −8.81 EUR. The briefing tells
  the agent to start with the complaint and the callback, not to sell, and suggests a German opening.
* **MG‑100009** — four failed charging sessions in 30 days: the copilot opens with the charging problem and keeps
  offers out of the call.
* **MG‑100023** — wallbox at home, no Autostrom contract: asked *"Lohnt sich Autostrom?"*, the copilot answers from
  the engine's eligibility (permitted via portal pop-up, small expected dCLV, not the top action) and cites the
  absence check in `autostrom_contracts`.
* **MG‑100127** — healthy multi-line customer with consent: mobile cross-sell (+66.00 EUR).
* **MG‑100003** — profiling consent withdrawn at 10:14 on 2026‑10‑01: with `as_of=2026-10-01T10:00:00`
  Lighty proposes an internet offer, from 10:15 on it proposes nothing.
* **MG‑100006** — asked by phone for an offer because the price guarantee ends: StromGarant as a reply to
  the customer's own inquiry, not as unsolicited marketing.
* `/api/marketing/overview` — 337 of 750 customers get **no contact**; Projected Protected Customer
  Value vs. a sales-first baseline ≈ 7,959 EUR (model-based estimate).
