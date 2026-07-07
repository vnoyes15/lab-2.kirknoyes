# Arx — Phase 1 + Phase 2 + Phase 3

AI-powered operating system for CRE operators (ZONIQ / Arx Build Brief v1.5). This repo
implements **Phase 1** (foundation), **Phase 2** (Section 07: "A-09 Document
Intelligence -> A-01 Deal Screener -> A-02 Underwriting -> A-07 Deal Memo Writer"), and
**Phase 3** (Section 07: "A-03 Seller Profiler -> A-04 Offer Strategy -> A-05 LOI
Drafting -> A-12 Negotiation Support. Lender profiles. Capital raise intelligence
(A-13). Broker intelligence.") of the six-phase build sequence.

## What's real vs. stubbed

| Area | Status |
|---|---|
| 24 DB migrations, RLS on every table | Real, verified against a live Postgres instance |
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
| Relationship warmth scoring (Section 38) | Real, deterministic (hot/warm/cold from `last_contacted_at`); nightly Celery job wiring is Phase 4 |
| Agent invocation API (9 agents + document upload + snapshot activation) | Real, tested end-to-end against a live Postgres + injected fake model client |
| LangGraph orchestration | Real topology *and* real nodes for all 9 built agents (`acquisition_flow`, `counterparty_offer_flow`, `document_flow`); a06/a08/a10/a11 remain named placeholders |
| 4 remaining agents (A-06, A-08, A-10, A-11) | Not built — Phase 4 per Section 07 |
| Celery Beat intelligence jobs | Not built — Phase 4 onward (celery app itself is wired) |

Every agent module is designed the same way: pure functions over injectable
`ModelClient` (never called directly in tests — see `arx/tests/fakes.py`), schema
validation (Section 87), and a uniform `AgentValidationError` on failure so the API
layer has one error-handling path for all of them (Gate G-04).

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
pytest arx/tests/ -v                  # full suite (153 tests)
python scripts/run_agent_tests.py     # Gate G-06: per-agent pass/fail (9/13 agents built)
```

Integration tests (`test_phase1_smoke.py`, `test_agents_api.py`,
`test_agents_api_phase3.py`, `test_snapshots_and_quality_log.py`,
`test_relationship_warmth_db.py`) run live against Postgres and are skipped
automatically if no `DATABASE_URL` is reachable. None of them ever call the real
Anthropic API — `model_client_dependency` (FastAPI) or direct `model_client=` injection
swaps in `arx/tests/fakes.py::FakeModelClient` everywhere.

## Repo layout

```
arx/
  agents/         a01_deal_screener.py, a02_underwriting_agent.py, a03_seller_profiler.py,
                  a04_offer_strategy.py, a05_loi_drafting.py, a07_deal_memo_writer.py,
                  a09_document_intelligence.py, a12_negotiation_support.py, a13_capital_raise.py,
                  rent_roll_parser.py, loan_math.py, relationship_warmth.py,
                  model_client.py (swappable AI provider), prompt_loader.py, errors.py
  api/            FastAPI app, config, auth/role enforcement, deals + agents routers
  db/
    migrations/   24 numbered SQL migrations (tables + RLS, applied in order)
    local_dev/    auth.jwt() shim + notes — local/CI Postgres only, never Supabase
    queries/      snapshots.py, quality_log.py, cost_controls.py, relationship.py
    connection.py RLS-bound connection pool (sets request.jwt.claims per request)
  validation/     Acquisition (MV1-MV6) / development (DV1-DV5) math suites + Pydantic
                  output schemas per agent (Section 87)
  orchestration/  LangGraph state, routing rules, and real nodes for all 9 built agents:
                  acquisition_flow.py (a01->a02->a07), counterparty_offer_flow.py
                  (a03->a04->a05), document_flow.py (a09); a12 is a standalone node
                  (Section 42 — only activates when a counter-offer arrives)
  prompts/        Versioned prompt YAML per agent (9 populated; current.txt + CHANGELOG.md
                  convention per Section 86)
  tasks/          Celery app (jobs land Phase 4)
  tests/
scripts/
  setup_local_db.sh   idempotent local Postgres bootstrap
  migrate.py          applies arx/db/migrations/*.sql
  seed_org.py         seeds ZONIQ org, uw_config (both tracks incl. target cap rate range),
                      org_jurisdictions (WA/CA/OR)
  run_agent_tests.py  Gate G-06 test runner (9/13 agents)
```

## Next: Phase 4

Section 07 Phase 4 — Development + Execution: A-10 Land Acquisition -> A-11
Development Pro Forma -> A-06 Due Diligence (both DD tracks) -> A-08 Outreach, plus
the notification framework, pipeline view, momentum scoring, conversational interface,
and the data visualization layer's build sequence (Section 85).
