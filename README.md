# Arx — Phase 1 + Phase 2 + Phase 3 + Phase 4

AI-powered operating system for CRE operators (ZONIQ / Arx Build Brief v1.5). This repo
implements **Phase 1** (foundation), **Phase 2** (Section 07: "A-09 Document
Intelligence -> A-01 Deal Screener -> A-02 Underwriting -> A-07 Deal Memo Writer"),
**Phase 3** (Section 07: "A-03 Seller Profiler -> A-04 Offer Strategy -> A-05 LOI
Drafting -> A-12 Negotiation Support. Lender profiles. Capital raise intelligence
(A-13). Broker intelligence."), and **Phase 4** (Section 07: "A-10 Land Acquisition ->
A-11 Development Pro Forma -> A-06 Due Diligence -> A-08 Outreach. Notification
framework. Pipeline view. Momentum scoring.") of the six-phase build sequence. All 13
agents now exist.

## What's real vs. stubbed

| Area | Status |
|---|---|
| 27 DB migrations, RLS on every table | Real, verified against a live Postgres instance |
| Deal intake API, dedup, role auth | Real, tested end-to-end |
| Math validation suites (MV1-MV6, DV1-DV5) | Real, unit tested including an IRR solver |
| **A-09 Document Intelligence** | Real. Rent rolls via a deterministic parser (CSV/Excel/PDF); everything else via the model, schema- and source-cite-validated |
| **A-01 Deal Screener** | Real. Model-driven fast screen; schema-validated, never fabricates missing fields |
| **A-02 Underwriting Agent** | Real. Model produces the judgment fields; Python deterministically computes debt service/DSCR flags and re-validates everything via the Phase 1 math suite before it's usable |
| **A-07 Deal Memo Writer** | Real. Mechanically checks its own reported metrics against the active underwriting snapshot — a mismatch is an unrecoverable error, not a warning |
| **A-03 Motivated Seller Profiler** | Real. Logs every read to `seller_profile_access_log` (Section 25); acquisition + land archetypes |
| **A-04 Offer Strategy** | Real. Exactly 3 strategies (aggressive/middle/conventional), each with its own recomputed returns and risks |
| **A-05 LOI Drafting** | Real. WA-jurisdiction-aware; escrow reference and attorney warning are Python-enforced non-negotiables, not just prompted for |
| **A-12 Negotiation Support** | Real. Exactly one of 3 response options marked recommended, cross-field validated |
| **A-13 Capital Raise Intelligence** | Real. Matches against `lp_profiles`; never fabricates a track record when `deals_closed = 0` |
| **A-10 Land Acquisition** | Real. Screens raw land/entitlement risk; routes to A-03, straight to A-11, or ends, per its own `routing_recommendation` |
| **A-11 Development Pro Forma** | Real. Wires the full DV1-DV5 development math suite plus a second sensitivity axis (absorption delay) beyond what Section 15 names by ID |
| **A-06 Due Diligence Coordinator** | Real. Fixed, Python-determined checklist categories per track (never left to the model); `deal_advancement_blocked` is Python-computed from checklist statuses, not model-reported |
| **A-08 Outreach** | Real. Suppression list + daily send limit (Section 22) enforced in Python *before* the model is ever called — a suppressed contact never gets a drafted message at all |
| Relationship warmth scoring (Section 38) | Real, deterministic (hot/warm/cold from `last_contacted_at`) — DB helper exists; Celery Beat wiring still not scheduled (see Scope boundaries) |
| **Momentum scoring** (Section 06/23) | Real, deterministic — recency of deal_snapshot/outreach/deal_task activity plus time stuck in the current pipeline status; nightly Celery Beat job wired and scheduled |
| **Pipeline view** (`GET /api/v1/deals/pipeline`) | Real — every non-dead deal for the org, ordered by pipeline stage then momentum |
| **Notification framework** | Real skeleton — `notifications` table, deterministic trigger rules (A-06 blocked, A-08 daily limit, momentum stalled), `GET`/`POST .../read` API. `InAppChannel` is the only delivery channel implemented; `EmailChannel`/`SMSChannel` are explicit `NotImplementedError` stubs (no provider credentials in this environment) |
| Agent invocation API (all 13 agents + document upload + snapshot activation) | Real, tested end-to-end against a live Postgres + injected fake model client |
| LangGraph orchestration | Real topology *and* real nodes for 11 of 13 agents (`acquisition_flow`, `counterparty_offer_flow`, `document_flow`, `development_flow`: a01->a10->a03->a11 or a01->a11 directly); a06/a08 have no orchestration node (see Scope boundaries) |
| Celery Beat intelligence jobs | `recalculate_all_momentum` is real and scheduled; `warmth_scorer`/`daily_brief`/`market_signals`/`data_quality`/`feedback_loop` remain unbuilt |

Every agent module is designed the same way: pure functions over injectable
`ModelClient` (never called directly in tests — see `arx/tests/fakes.py`), schema
validation (Section 87), and a uniform `AgentValidationError` on failure so the API
layer has one error-handling path for all of them (Gate G-04).

## A cross-cutting bug found and fixed during Phase 4

While wiring the notification framework's daily-limit dedup check, testing surfaced
that `arx/db/connection.py::db_session()` wrapped an entire request in one outer
transaction — so **every** agent endpoint's "write `error_log`, then raise
`HTTPException`" error path (A-03 through A-13, every phase) was silently rolling back
its own `error_log` write. The response body's `error_id` was a real UUID (generated by
`INSERT ... RETURNING`), but the row never actually persisted, violating Section 10
EH4 ("All unrecoverable errors write to error_log"). Fixed by special-casing
`HTTPException` in `db_session()` so a controlled structured-error response commits
before re-raising, while any other exception still rolls back as before. Regression
test: `arx/tests/test_db_session_error_commit.py`.

## Scope boundaries — deferred, not silently skipped

- **Conversational interface** (SMS/voice via Twilio, per Section 07 Phase 4) — no
  Twilio credentials in this environment. `EmailChannel`/`SMSChannel` in
  `arx/notifications/channels.py` are explicit `NotImplementedError` stubs for the same
  reason, not silent no-ops.
- **Mobile quick-screen** — functionally redundant with A-01's existing screen; no
  separate mobile-specific endpoint was built.
- **Data visualization layer** (Section 85) — needs a frontend that doesn't exist in
  this API-only repo (Section 01: "API-first, no front end in Phase 1"). The backend
  data it would visualize is real and queryable today (`GET /api/v1/deals/pipeline`,
  momentum scores, `agent_quality_log`).
- **A-06/A-08 orchestration nodes** — no LangGraph node exists for either in
  `arx/orchestration/nodes.py`. A-06 (due diligence) and A-08 (outreach) are both
  long-lived/re-entrant rather than one-shot steps in a linear flow (DD tasks get
  worked over days; outreach recurs on its own cadence) — same reasoning already
  applied to A-12's standalone-node treatment in Phase 3. `arx/api/agents.py`'s
  `/agents/a06` and `/agents/a08` endpoints are the real, tested, production path for
  both.
- **`warmth_scorer`/`daily_brief`/`market_signals`/`data_quality`/`feedback_loop` Celery
  Beat jobs** (Section 86 repo structure, referenced in `arx/tasks/celery_app.py`'s
  docstring since Phase 1) — only `momentum_scorer.py` is built and scheduled this
  phase. `recalculate_org_warmth` (Section 38) has existed since Phase 3 but still has
  no Celery Beat job calling it.

## Setup (Section 86)

Requires Python 3.11+, Docker, and either a local Postgres 16 or a Supabase project.

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY, SUPABASE_*, SECRET_KEY at minimum
```

### Local Postgres (no Supabase project yet)

```bash
bash scripts/setup_local_db.sh          # creates arx_dev + the RLS-bound `arx` role, runs migrations
DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5432/arx_dev" python scripts/seed_org.py
# copy the printed DEFAULT_ORG_ID into .env
```

### Against a real Supabase project

```bash
python scripts/migrate.py                       # DATABASE_URL = Supabase connection string
python scripts/seed_org.py                       # DATABASE_URL = same
# set APP_DATABASE_URL to a connection using Supabase's `authenticated` role, not the
# service-role/superuser string — see the field docs in arx/api/config.py for why this
# matters (a bypass-privileged connection makes every RLS policy silently do nothing).
```

### Run it

```bash
uvicorn arx.api.main:app --reload --port 8000
curl http://127.0.0.1:8000/healthz
open http://127.0.0.1:8000/docs
```

Agent endpoints require a bearer JWT with `sub`/`org_id`/`role` claims signed with
`SECRET_KEY` (see `arx/api/auth.py`) — there's no login flow yet since Supabase Auth
owns that in production. Minting one for local testing:

```python
import jwt, time
jwt.encode({"sub": "...", "org_id": "...", "role": "analyst", "exp": int(time.time()) + 3600},
           "<SECRET_KEY from .env>", algorithm="HS256")
```

### Test it

```bash
pytest arx/tests/ -v                  # full suite (221 tests with a reachable DATABASE_URL)
python scripts/run_agent_tests.py     # Gate G-06: per-agent pass/fail (13/13 agents built)
```

Integration tests (`test_phase1_smoke.py`, `test_agents_api.py`,
`test_agents_api_phase3.py`, `test_agents_api_phase4.py`,
`test_snapshots_and_quality_log.py`, `test_relationship_warmth_db.py`,
`test_pipeline_and_momentum_db.py`, `test_notifications_db.py`,
`test_db_session_error_commit.py`) run live against Postgres and are skipped
automatically if no `DATABASE_URL` is reachable. None of them ever call the real
Anthropic API — `model_client_dependency` (FastAPI) or direct `model_client=` injection
swaps in `arx/tests/fakes.py::FakeModelClient` everywhere.

## Repo layout

```
arx/
  agents/         a01_deal_screener.py .. a13_capital_raise.py (all 13), plus
                  rent_roll_parser.py, loan_math.py, relationship_warmth.py,
                  momentum_scoring.py, notification_rules.py,
                  model_client.py (swappable AI provider), prompt_loader.py, errors.py
  api/            FastAPI app, config, auth/role enforcement, deals + agents +
                  notifications routers
  db/
    migrations/   27 numbered SQL migrations (tables + RLS, applied in order)
    local_dev/    auth.jwt() shim + notes — local/CI Postgres only, never Supabase
    queries/      snapshots.py, quality_log.py, cost_controls.py, relationship.py,
                  pipeline.py (momentum + pipeline view), notifications.py
    connection.py RLS-bound connection pool (sets request.jwt.claims per request);
                  special-cases HTTPException so a controlled error response commits
                  its error_log/notification write instead of rolling it back
  notifications/  channels.py — NotificationChannel protocol; InAppChannel (real),
                  EmailChannel/SMSChannel (explicit NotImplementedError stubs)
  validation/     Acquisition (MV1-MV6) / development (DV1-DV5) math suites + Pydantic
                  output schemas per agent (Section 87)
  orchestration/  LangGraph state, routing rules, and real nodes for 11 of 13 agents:
                  acquisition_flow.py (a01->a02->a07), counterparty_offer_flow.py
                  (a03->a04->a05), document_flow.py (a09), development_flow.py
                  (a01->a10->a03->a11 or a01->a11 directly); a12 is a standalone node
                  (Section 42); a06/a08 have no node (see Scope boundaries)
  prompts/        Versioned prompt YAML per agent (all 13 populated; current.txt +
                  CHANGELOG.md convention per Section 86)
  tasks/          Celery app + momentum_scorer.py (scheduled nightly)
  tests/
scripts/
  setup_local_db.sh   idempotent local Postgres bootstrap
  migrate.py          applies arx/db/migrations/*.sql
  seed_org.py         seeds ZONIQ org, uw_config (both tracks incl. target cap rate range),
                      org_jurisdictions (WA/CA/OR)
  run_agent_tests.py  Gate G-06 test runner (13/13 agents)
```

## Next: Phase 5

Section 07 Phase 5 — Quality & Compliance: the 8 quality gates (G-01 through G-08) at
full scope (this repo has only run G-06 and a G-08 subset so far), plus whatever
full-system polish items (LangGraph interrupt/resume for the human-checkpoint pattern
already noted in `arx/orchestration/nodes.py`, the deferred Celery Beat jobs and
notification channels above) Phase 5 designates as in-scope.
