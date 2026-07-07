# Arx — Phase 1 through Phase 6

AI-powered operating system for CRE operators (ZONIQ / Arx Build Brief v1.5). This repo
implements all six phases of the build sequence (Section 07): **Phase 1** (foundation),
**Phase 2** (A-09 -> A-01 -> A-02 -> A-07), **Phase 3** (A-03 -> A-04 -> A-05 -> A-12,
lender profiles, capital raise intelligence), **Phase 4** (A-10 -> A-11 -> A-06 -> A-08,
notifications, pipeline view, momentum scoring), **Phase 5** (full state management,
daily intelligence brief, portfolio layer, LP trust layer, output accuracy flagging,
audit report, scenario modeling, all Phase 5 quality gates), and **Phase 6** (External
Data + Ecosystem: portfolio stress test, deal risk monitor, asset performance tracking,
refi & disposition engine, portfolio context for A-02/A-11, JV & complex equity
modeling, attorney & lender portals, data portability, deal team task management
enforcement, error response protocol completion, market signal processing, network
intelligence, data quality engine, feedback loop health reporting). All 13 agents
exist and all 8 Phase 5 quality gates (Section 14, G-01 through G-08) pass.

## What's real vs. stubbed

| Area | Status |
|---|---|
| 36 DB migrations, RLS on every table | Real, verified against a live Postgres instance |
| Deal intake API, dedup, role auth (5 roles: admin/analyst/viewer/lp/attorney) | Real, tested end-to-end |
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
| **Pipeline view** (`GET /api/v1/pipeline`) | Real — filters (status/deal_type/assigned_user_id/submarket/date range), `GET /api/v1/pipeline/analytics` (death reasons, deal-type breakdown, average days per stage via `deal_status_history`) |
| **Notification framework** | Real — `notifications` table, deterministic trigger rules (A-06 blocked, A-08 daily limit, momentum stalled, accuracy-flag threshold, milestone delay, task assigned, error on active deal, refi/disposition opportunity, performance variance, market signal deal impact), `GET`/`POST .../read` API. `InAppChannel` is the only delivery channel implemented; `EmailChannel`/`SMSChannel` are explicit `NotImplementedError` stubs (no provider credentials in this environment) |
| **Orchestration interrupt/resume** (Section 07 Phase 5) | Real — `acquisition_flow_with_checkpoint` genuinely pauses at the A-02->A-07 boundary (LangGraph `interrupt_before` + `MemorySaver`) and only proceeds on an explicit resume. `MemorySaver` is in-process/non-persistent (see Scope boundaries) |
| **Output Accuracy Flagging** (Section 35) | Real — `PATCH .../snapshots/{id}/accuracy` sets `accuracy_flag`/`accuracy_note`; 3 `inaccurate` flags on the same agent within 30 days triggers an Admin notification |
| **LP Trust Layer** (Section 49) | Real — `lp` role scoped via `deal_lp_access`; `GET /api/v1/lp/deals`, `GET /api/v1/lp/deals/{id}` (curated allow-list view), `GET /api/v1/lp/report/{id}?period=Q1-2026` |
| **Deal Scenario Modeling** (Section 63) | Real — `POST /api/v1/deals/{id}/scenarios` recomputes NOI/cap rate/DSCR (acquisition) or total cost/ROC/spread (development) under combined assumption overrides against the deal's active A-02/A-11 snapshot |
| **Portfolio Layer** (Section 29) | Real — `deal_performance`, `GET /api/v1/portfolio`, `GET /api/v1/portfolio/development` |
| **Audit & Compliance Report** (Section 57) | Real — `GET /api/v1/deals/{id}/audit-report` (every agent output, assumption/override, status change, document, counter-offer, human decision, **and every `error_log` entry**, Section 78 EP3). `?format=pdf` returns an explicit 501 |
| **Daily Intelligence Brief** (Section 40) | Real — `GET /api/v1/brief`: stalled deals, DD countdowns, milestone status, top new leads, market pulse, warmth alerts, blocked tasks, budget variance, next-action recommendations, **data-quality action items (Section 51), monthly-actuals prompt on the 5th (Section 76 FL2)** — personalized per role. 6am scheduled multi-channel delivery deferred (no email/SMS provider) |
| **Deal Team Task Management** (Section 73) | Real — `POST`/`GET /api/v1/deals/{id}/tasks` (fires `task_assigned` notification); `PATCH .../status` blocks `due_diligence` -> `closed` while any high-priority task is `not_started`/`in_progress`, enforced at the API layer |
| **Error Response Protocol** (Section 78) | Real — EP1: agent failures fire `error_on_active_deal` for deals not closed/dead. EP2: `GET`/`PATCH /api/v1/errors` tracks `resolution_status`/`resolution_notes` through to closure (Admin-only). EP3: every error is in the audit report |
| **Portfolio Stress Test** (Section 47) | Real — `POST /api/v1/portfolio/stress-test` (rate/vacancy/cap-rate-expansion shocks, per-asset DSCR for acquisition assets via active A-02, value-only impact for construction-phase development assets via active A-11 — no DSCR fabricated where there's no loan data) |
| **Asset Performance Tracking + Deal Risk Monitor** (Sections 45, 44) | Real — actual-vs-projected NOI variance notification (10%) / Admin escalation (20%) on `POST .../performance`; `GET /api/v1/deals/{id}/risk` and `/portfolio/risk-monitor` compute 7 of 8 spec'd risk checks live (absorption-vs-pro-forma has no data source anywhere — documented gap) |
| **Refi & Disposition Engine** (Section 46) | Real — `POST .../refi-analysis` (debt-constant-improvement trigger, MOIC/CoC projection) and `.../disposition-analysis` (cap-rate-compression trigger + 45-day ID / 180-day close 1031 windows), on-demand since both need a proposed rate/market cap rate this environment has no live feed for |
| **Portfolio Context for A-02/A-11** (Section 69) | Real — every A-02/A-11 invocation returns a `portfolio_context` key: current portfolio aggregates (weighted-avg DSCR, geographic/asset-type concentration, total equity deployed) and the post-acquisition impact of this specific deal |
| **JV & Complex Equity Structure Modeling** (Section 70) | Real — `POST`/`GET /api/v1/deals/{id}/waterfall`: simple LP/GP with promote (MOIC-hurdle-gated — a documented simplification of a true IRR hurdle), preferred equity with compounding pref + GP catch-up, JV co-GP profit split, mezzanine debt layer, ground lease with residual ownership. Nothing before Phase 6 had *any* waterfall math despite Section 70 assigning the simple case to Phase 1 |
| **Attorney Portal** (Section 71) | Real — new `attorney` role scoped via `deal_attorney_access`; curated deal view (documents + legal-review DD items only, never financials/seller profile/outreach), `deal_comments`, confirms legal-review A-06 checklist items |
| **Lender Package Generation** (Section 71) | Real — `GET /api/v1/deals/{id}/lender-package` assembles the deal memo, underwriting output, rent roll/inspection/title/environmental summaries (latest A-09 extraction of each type), and capital stack in one call. "ZONIQ operating track record" has no data source anywhere in this platform — returned `null` with an explicit note |
| **Data Portability & Migration** (Section 74) | Real — `POST /api/v1/import/{resource_type}` (deals/contacts/market_comps/lender_profiles/deal_performance CSV, per-row validation + dedup, failed rows never block valid ones); `GET /api/v1/export` (Admin-only, full org data as JSON or a ZIP of CSVs) |
| **Market Signal Processing** (Section 62) | Real — `POST /api/v1/market-signals`; a `high`-significance signal routes to every active deal in the same submarket, recomputes momentum, and fires a notification per affected deal. Signal *sourcing* (fed funds/BLS/permit feeds) stays manual entry — the external feeds are out of reach in this environment |
| **Network Intelligence Layer** (Section 59) | Real — `POST /api/v1/deals/{id}/network-contribution` (org opt-in + per-contribution consent + 30-day post-close delay, acquisition deals only); `GET /api/v1/network-intelligence/{status,comps}` aggregate across every org's contributions via a bypass-RLS connection, never surfacing which org contributed what |
| **Data Quality Engine** (Section 51) | Real — `GET /api/v1/data-quality/report` (Admin-only): stale market comps/lender profiles/active snapshots, A-09 high-correction-rate detection (via the existing accuracy-flag system), missing-required-fields-for-next-stage. No `market_intelligence` table exists anywhere in this schema — documented gap, not fabricated. Scheduled nightly via Celery Beat alongside the on-demand endpoint |
| **Feedback Loop health** (Section 76 FL4) | Real — `GET /api/v1/feedback-loop/health` (Admin-only): how many owned assets have current/stale/no performance data |
| Agent invocation API (all 13 agents + document upload + snapshot activation) | Real, tested end-to-end against a live Postgres + injected fake model client |
| LangGraph orchestration | Real topology *and* real nodes for 11 of 13 agents; a06/a08 have no orchestration node (see Scope boundaries) |
| Celery Beat intelligence jobs | `recalculate_all_momentum` and `run_data_quality_checks_all_orgs` are real and scheduled; `warmth_scorer`/`market_signals`(ingestion)/`feedback_loop` remain unbuilt as scheduled jobs — their underlying computations are real and callable on demand |
| **All 8 Phase 5 quality gates** (Section 14) | Real, all passing — `scripts/run_quality_gates.py`. G-01/G-08 use synthetic-but-realistic stand-ins (no real ZONIQ production data/documents in this environment), documented the same way as each other |

Every agent module is designed the same way: pure functions over injectable
`ModelClient` (never called directly in tests — see `arx/tests/fakes.py`), schema
validation (Section 87), and a uniform `AgentValidationError` on failure so the API
layer has one error-handling path for all of them (Gate G-04). Every Phase 6
deterministic-math module (`portfolio_stress.py`, `refi_disposition.py`,
`portfolio_context.py`, `equity_waterfall.py`, `deal_risk_monitor.py`,
`data_quality.py`) follows the same "not a 14th agent" contract established by
`scenario_modeling.py` in Phase 5: pure functions, no AI, no DB.

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

## Gaps found and fixed during Phase 6

Several Phase 6 tasks turned out to be fixing real gaps in already-"completed" earlier
phases, discovered by re-reading the actual build brief rather than trusting prior
summaries:
- **Section 73 enforcement** ("A deal cannot advance from due_diligence to closed
  while any high-priority task is open") was never implemented despite `deal_tasks`
  existing since Phase 2/4 — added directly to `PATCH .../deals/{id}/status`.
- **Section 78 EP1/EP2** (Admin notification on active-deal errors; resolution
  tracking through to closure) — `error_log` existed since Phase 1 with
  `resolution_status`/`resolution_notes` columns, but nothing ever wrote to them or
  notified anyone. Both are now real.
- **Section 70's equity waterfall** — the spec states "Phase 1 covers simple LP/GP
  waterfall and preferred equity," but no waterfall math existed anywhere before this
  phase. Built as the foundation alongside the JV/mezzanine/ground-lease structures
  Phase 6 explicitly adds.
- **`market_signals`/`network_contributions` tables** existed since early migrations
  (013/019) as unused scaffolding with docstrings describing Phase 6 logic that was
  never written — that logic is now real.

## Scope boundaries — deferred, not silently skipped

- **Conversational interface** (SMS/voice via Twilio, per Section 07 Phase 4) — no
  Twilio credentials in this environment. `EmailChannel`/`SMSChannel` in
  `arx/notifications/channels.py` are explicit `NotImplementedError` stubs for the same
  reason, not silent no-ops.
- **Mobile quick-screen** — functionally redundant with A-01's existing screen; no
  separate mobile-specific endpoint was built.
- **Data visualization layer** (Section 85) — needs a frontend that doesn't exist in
  this API-only repo (Section 01: "API-first, no front end in Phase 1"). The backend
  data it would visualize is real and queryable today.
- **A-06/A-08 orchestration nodes** — no LangGraph node exists for either; both are
  long-lived/re-entrant rather than one-shot steps in a linear flow. `arx/api/agents.py`'s
  `/agents/a06` and `/agents/a08` endpoints are the real, tested, production path for
  both.
- **`warmth_scorer`/`market_signals` (ingestion)/`feedback_loop` Celery Beat jobs** —
  only `momentum_scorer.py` and `data_quality_checker.py` are built and scheduled.
  `recalculate_org_warmth` (Section 38) has existed since Phase 3 but still has no
  Celery Beat job calling it. Market signal *routing* is real and runs synchronously
  on `POST /api/v1/market-signals`; automated signal *sourcing* (fed funds/BLS/permit
  feeds) has no external credentials in this environment.
- **Persistent LangGraph checkpointer** — `acquisition_flow_with_checkpoint`'s
  interrupt/resume is real but uses `MemorySaver` (in-process only). A real deployment
  needs `langgraph-checkpoint-postgres`, which conflicts with this project's pinned
  `langgraph==0.2.62` version — tracked in `arx/orchestration/acquisition_flow.py`'s
  comments rather than silently forced in.
- **PDF exports** (audit report `?format=pdf`, LP quarterly report) — no PDF rendering
  library configured; returns an explicit 501 rather than silently falling back.
- **LP capital account / upcoming events** (Section 49 quarterly report) — no capital-
  contributions/distributions ledger or scheduled-events model exists anywhere in the
  platform; returned as explicit `None`/`[]`, not a fabricated number.
- **Development milestone stage-sequence enforcement** — `PATCH
  .../deals/{id}/milestones/{type}` doesn't enforce Section 23's described milestone
  ordering.
- **"Absorption slower than pro forma in lease-up phase"** (Section 44) — no
  actual-absorption/leasing data is tracked anywhere in the schema (that's Section 72
  PM2's leasing feed, no credentials); the other 7 of 8 Deal Risk Monitor checks are real.
- **`market_intelligence` staleness check** (Section 51) — no `market_intelligence`
  table exists anywhere in this schema, and nothing else in the build brief defines
  what it would contain distinct from `market_comps`/`market_signals`; documented as
  a gap in the data quality report rather than invented.
- **"ZONIQ operating track record"** (Section 71 lender package) — no fund-level
  historical performance data source exists; returned `null` with an explicit note.
- **True IRR-hurdle equity waterfall** (Section 70) — the simple LP/GP promote
  structure gates on a target multiple-on-invested-capital (MOIC) instead of a
  time-weighted IRR, since a real IRR hurdle needs a goal-seek across a full
  multi-period cash flow timeline (interim distributions *and* the final sale both
  feed it) — materially more scope than this module takes on. Documented in
  `arx/agents/equity_waterfall.py`'s module docstring.
- **Development-deal network contributions** (Section 59) — `network_contributions`
  has no ROC/IRR columns, so only acquisition deals can contribute; a documented
  schema boundary, not a bug.
- **`financing_type` on network contributions** — no field anywhere tracks a deal's
  actual financing type (lender_profiles has *lender* loan-type capabilities, not the
  *deal's* actual financing) — left as an optional caller-supplied field, never
  fabricated.

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
pytest arx/tests/ -v                  # full suite (462 tests with a reachable DATABASE_URL)
python scripts/run_agent_tests.py     # Gate G-06: per-agent pass/fail (13/13 agents built)
python scripts/run_quality_gates.py   # All 8 Phase 5 quality gates (G-01 through G-08)
```

Most integration tests (anything ending `_db.py`, plus `test_phase1_smoke.py`,
`test_agents_api*.py`, `test_snapshots_and_quality_log.py`, `test_gate_g0*.py`,
`test_db_session_error_commit.py`, `test_orchestration_interrupt_resume.py`) run live
against Postgres and are skipped automatically if no `DATABASE_URL` is reachable. None
of them ever call the real Anthropic API — `model_client_dependency` (FastAPI) or
direct `model_client=` injection swaps in `arx/tests/fakes.py::FakeModelClient`
everywhere.

## Repo layout

```
arx/
  agents/         a01_deal_screener.py .. a13_capital_raise.py (all 13), plus
                  rent_roll_parser.py, loan_math.py, relationship_warmth.py,
                  momentum_scoring.py, notification_rules.py, scenario_modeling.py,
                  portfolio_stress.py, refi_disposition.py, portfolio_context.py,
                  equity_waterfall.py, deal_risk_monitor.py, data_portability.py,
                  data_quality.py, model_client.py (swappable AI provider),
                  prompt_loader.py, errors.py
  api/            FastAPI app, config, auth/role enforcement (5 roles: admin/analyst/
                  viewer/lp/attorney); deals + agents + notifications + pipeline +
                  portfolio + lp + scenarios + audit + daily_brief + errors + risk +
                  refi_disposition + equity_waterfall + attorney + lender_package +
                  data_portability + market_signals + network_intelligence +
                  data_quality routers
  db/
    migrations/   36 numbered SQL migrations (tables + RLS, applied in order)
    local_dev/    auth.jwt() shim + notes — local/CI Postgres only, never Supabase
    queries/      snapshots.py (incl. accuracy flagging), quality_log.py (incl.
                  error resolution), cost_controls.py, relationship.py, pipeline.py,
                  notifications.py, portfolio.py (incl. stress test + portfolio
                  aggregates), lp.py, audit_report.py, daily_brief.py, deal_risk.py,
                  equity_waterfalls.py, attorney.py, lender_package.py,
                  data_portability.py, market_signals.py, network_intelligence.py,
                  data_quality.py
    connection.py RLS-bound connection pool (sets request.jwt.claims per request);
                  special-cases HTTPException so a controlled error response commits
                  its error_log/notification write instead of rolling it back
  notifications/  channels.py — NotificationChannel protocol; InAppChannel (real),
                  EmailChannel/SMSChannel (explicit NotImplementedError stubs)
  validation/     Acquisition (MV1-MV6) / development (DV1-DV5) math suites + Pydantic
                  output schemas per agent (Section 87)
  orchestration/  LangGraph state, routing rules, and real nodes for 11 of 13 agents:
                  acquisition_flow.py (a01->a02->a07, plus
                  acquisition_flow_with_checkpoint's real interrupt/resume at the
                  a02->a07 boundary), counterparty_offer_flow.py (a03->a04->a05),
                  document_flow.py (a09), development_flow.py (a01->a10->a03->a11 or
                  a01->a11 directly); a12 is a standalone node; a06/a08 have no node
  prompts/        Versioned prompt YAML per agent (all 13 populated; current.txt +
                  CHANGELOG.md convention per Section 86)
  tasks/          Celery app + momentum_scorer.py + data_quality_checker.py (both
                  scheduled nightly)
  tests/          incl. test_gate_g01_end_to_end.py .. test_gate_g08_document_intelligence.py
scripts/
  setup_local_db.sh    idempotent local Postgres bootstrap
  migrate.py           applies arx/db/migrations/*.sql
  seed_org.py          seeds ZONIQ org, uw_config (both tracks incl. target cap rate range),
                       org_jurisdictions (WA/CA/OR)
  run_agent_tests.py   Gate G-06 test runner (13/13 agents)
  run_quality_gates.py All 8 Phase 5 quality gate test suites (G-01 through G-08)
```
