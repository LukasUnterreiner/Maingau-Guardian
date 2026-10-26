# MAINGAU Guardian — Backend

**The AI that knows when NOT to sell.** Guardian is a Next Best Action engine that picks, for each
customer, the action with the highest expected change in Customer Lifetime Value — a product offer,
a retention offer, proactive service resolution, or no contact at all — after hard compliance rules
have been applied. Every decision comes with its counterfactuals: what the alternatives would be worth
and why blocked actions are blocked.

Futury Build Days hackathon with MAINGAU Energie and hessian.AI. Backend only; the frontend is separate.

* API reference for the frontend: [`API_CONTRACT.md`](API_CONTRACT.md)
* How every number is computed, assumptions and fallbacks: [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md)
* Swagger UI: `http://localhost:8000/docs`

## Quick start (macOS / Linux)

```bash
python3.12 -m venv .venv && source .venv/bin/activate     # Python 3.11+ ; 3.12 recommended
pip install -r requirements-dev.txt
cp .env.example .env                                     # optional, defaults work
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
```

The data files live in `data/` (`maingau_nba_mockdata.xlsx`, `event_stream_2026-10-01.jsonl`).
Startup loads and validates them (~6 s) and pre-computes decisions for all 750 customers (~2 s).

## Tests

```bash
pytest -q
```

43 tests, including the 12 mandatory scenarios of the brief, the MG‑100004 service case, a
dataset-wide check that the CLV formula and all churn drivers reproduce `customer_value`, API
contract/error tests, and an unreachable-AI test. Last run: **43 passed** on Python 3.13 (local) and
Python 3.12 (inside the Docker image).

## Docker

```bash
docker compose up -d --build          # VM port 80 -> container port 8000
curl localhost/api/health
```

* The app listens on `0.0.0.0:8000` inside the container; `compose.yaml` maps VM port 80 to it. On the
  hessian.AI server the external port 38080 is forwarded to VM port 80.
* `./data` is mounted read-only at `/srv/data`; the SQLite decision log, approvals and settings live
  in the named volume mounted at `/srv/runtime`.
* `restart: unless-stopped` and a health check on `/api/health`.
* Secrets (`AI_API_KEY`, `ADMIN_TOKEN`) only via `.env` / environment — never baked into the image.
* Behind a registry mirror use `docker build --build-arg BASE_IMAGE=<mirror>/python:3.12-slim .`.

Nothing in this repository deploys anything automatically.

## Configuration

See [`.env.example`](.env.example). Important variables:

| Variable | Default | Purpose |
|---|---|---|
| `DATA_DIR` | `./data` (`/srv/data` in Docker) | Workbook + event stream location |
| `EVALUATION_AS_OF` | `latest` | `latest` (replay all events), `snapshot`, or ISO timestamp |
| `RUNTIME_DIR` | `./runtime` (`/srv/runtime`) | SQLite file location |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Frontend origins |
| `ADMIN_TOKEN` | empty | If set, settings and approvals need header `X-Admin-Token` |
| `AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL` | empty | Optional LLM; without them deterministic texts are used |
| `AI_PROTOCOL` | `openai_chat_completions` | Only protocol implemented — verify against the provider docs first |

## Project structure

```
app/
  main.py                      FastAPI app, error handlers, CORS
  api/routes.py                Thin REST layer (/api/...)
  config/settings.py           Environment configuration
  data/loader.py               Workbook + event stream loading, validation, de-duplication
  models/schemas.py            Pydantic request/response models (the API contract)
  models/runtime_settings.py   Editable settings with hard-rule bounds
  services/
    customer_service.py        Customer 360° state at a point in time (snapshot + event replay)
    churn_model.py             Churn drivers reproduced from the value model
    clv_engine.py              clv_method: CLV, dCLV per action type
    acceptance_model.py        Smoothed p_accept from nba_action_history; service resolution proxy
    eligibility_engine.py      Consent, profiling, service-state, frequency, holdings, prerequisites
    recommendation_engine.py   Ranking, no-contact baseline, reasons, conventional baseline policy
    counterfactual_engine.py   Scenario simulation + one-at-a-time attribution
    analytics_service.py       Dashboard aggregates, Projected Protected Customer Value
    ai_service.py              Optional LLM, German templates, output validation, fallback
    decision_log.py            SQLite: decisions, approvals, drafts, settings
    guardian.py                Facade used by the routes
tests/                         pytest suite
data/                          Dataset (synthetic)
docs/METHODOLOGY.md            Method, assumptions, limitations
API_CONTRACT.md                Frontend contract
```

## What to show a jury

* **MG‑100004** — open complaint, dunning level 3 (event on 2026‑10‑01), callback requested. Guardian
  recommends proactive service resolution by phone (+66.50 EUR expected dCLV); all sales offers are
  blocked with machine-readable reasons; a conventional engine would have sent a shop offer worth
  −8.81 EUR.
* **MG‑100127** — healthy multi-line customer with consent: mobile cross-sell (+66.00 EUR).
* **MG‑100003** — profiling consent withdrawn at 10:14 on 2026‑10‑01: with `as_of=2026-10-01T10:00:00`
  Guardian proposes an internet offer, from 10:15 on it proposes nothing.
* **MG‑100006** — asked by phone for an offer because the price guarantee ends: StromGarant as a reply to
  the customer's own inquiry, not as unsolicited marketing.
* `/api/marketing/overview` — 337 of 750 customers get **no contact**; Projected Protected Customer
  Value vs. a sales-first baseline ≈ 7,959 EUR (model-based estimate).
