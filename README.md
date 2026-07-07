# Arx — Phase 1: Foundation

AI-powered operating system for CRE operators (ZONIQ / Arx Build Brief v1.5). This repo
currently implements **Phase 1** of the six-phase build sequence (Build Brief Section 07):
repo scaffold, Docker, FastAPI, Supabase-compatible Postgres + RLS, a LangGraph
orchestration scaffold, auth, versioned underwriting config for both tracks, the deal
intake API, `org_jurisdictions`, and the math validation suites. **No agent logic yet**
— that starts in Phase 2.

## What's real vs. stubbed

| Area | Status |
|---|---|
| 22 DB migrations, RLS on every table | Real, verified against a live Postgres instance |
| Deal intake API (`POST /api/v1/deals/intake`), dedup, role auth | Real, tested end-to-end |
| Math validation suites (MV1-MV6, DV1-DV5) | Real, unit tested including an IRR solver |
| LangGraph orchestration topology (routing, state, flows) | Real topology; every agent node is a placeholder that raises `NotImplementedError` naming the phase it lands in |
| 13 agents (A-01 .. A-13) | Not built — Phase 2 onward |
| Celery Beat intelligence jobs | Not built — Phase 4 onward (celery app itself is wired) |

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

### Test it

```bash
pytest arx/tests/ -v
```

`test_phase1_smoke.py` is a live integration test (Section 86 S9) — it creates two real
orgs, posts a deal through the running API, and asserts org B cannot see org A's deal
(Gate G-02, verified structurally in Phase 1 rather than waiting for Phase 5). It's
skipped automatically if no `DATABASE_URL` is reachable.

## Repo layout

See Build Brief Section 86 for the full convention (prompt versioning, agent module
naming, etc. — those start applying in Phase 2). Phase 1's tree:

```
arx/
  api/            FastAPI app, config, auth/role enforcement, deal intake router
  db/
    migrations/   22 numbered SQL migrations (tables + RLS, applied in order)
    local_dev/    auth.jwt() shim + notes — local/CI Postgres only, never Supabase
    connection.py RLS-bound connection pool (sets request.jwt.claims per request)
  validation/     Acquisition (MV1-MV6) and development (DV1-DV5) math suites
  orchestration/  LangGraph state, routing rules, and flow topology (placeholder nodes)
  tasks/          Celery app (jobs land Phase 4)
  agents/         empty — Phase 2+
  prompts/        empty — Phase 2+
  tests/
scripts/
  setup_local_db.sh   idempotent local Postgres bootstrap
  migrate.py          applies arx/db/migrations/*.sql
  seed_org.py         seeds ZONIQ org, uw_config (both tracks), org_jurisdictions (WA/CA/OR)
```
