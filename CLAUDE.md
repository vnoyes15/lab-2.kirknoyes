# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Stride — a personal workout accountability app. Every morning the goal is a
2-3 mile walk/run plus strength training 4-5x/week; the app logs entries and
tracks a run streak and weekly strength count against that goal.

Two independent Node projects, each with its own `package.json` and `node_modules`:

- `server/` — Express API (ESM, Node 22+)
- `client/` — Vite + React frontend

There is no root-level `package.json` or workspace config — always `cd` into
`server/` or `client/` before running npm commands.

## Commands

```bash
# Backend (from server/)
npm install
npm run dev     # node --watch src/index.js, http://localhost:3001
npm test        # vitest run
npx vitest run test/stats.test.js -t "resets to zero"   # single test

# Frontend (from client/)
npm install
npm run dev     # vite dev server, http://localhost:5173 (proxies /api -> :3001)
npm run build   # production build to client/dist
```

Run the backend before the frontend — the Vite dev server proxies `/api/*`
requests to `http://localhost:3001` (see `client/vite.config.js`), and the
UI's `fetch` calls will fail without it.

## Architecture

**Storage**: `server/src/store.js` persists entries as a flat JSON array in
`server/data/entries.json` (created on first write, gitignored). No database.
This is deliberate for a single-user personal project — if this ever needs
concurrent users or larger data, swap `store.js` for a real DB, but the
`readEntries()`/`addEntry()`/`deleteEntry()` interface is what `index.js` and
`stats.js` depend on, so keep that shape.

**Stats logic is pure and isolated**: `server/src/stats.js` has no I/O — it
takes an `entries` array and a `todayStr` and returns streak/weekly-count
data. This is intentional so the interesting logic (streak math, week
boundaries) is unit-testable without spinning up the server or touching the
filesystem. When changing streak/goal behavior, edit here first and add a
test in `server/test/stats.test.js`; don't reimplement date math in
`index.js` or in the React components.

Two computed pieces, both keyed off a Monday-start week:
- **Run streak**: consecutive days (walking backward from today) with a
  qualifying run, where "qualifying" = `distanceMiles >= MIN_RUN_MILES` (2).
  Multiple runs on the same day dedupe to one. If today has no run yet, the
  streak still reflects "through yesterday" rather than resetting to 0 —
  the day isn't over yet.
- **Weekly strength count**: unique *days* (not sessions) with a strength
  entry in the Mon-Sun week containing `todayStr`, compared against
  `STRENGTH_GOAL_MIN`/`MAX` (4-5).

**API** (`server/src/index.js`): `GET/POST /api/entries`, `DELETE
/api/entries/:id`, `GET /api/stats` (accepts an optional `?today=YYYY-MM-DD`
query param, used for testing/backdating — the frontend never sets it).
Validation (date format, type enum, positive distance for runs) happens
inline in the route handlers, not in a middleware layer — there's only one
resource, so it isn't worth abstracting yet.

**Frontend** (`client/src/App.jsx`): one component tree, no router, no state
library. `App` owns `entries`/`stats` state and a single `refresh()` that
re-fetches both after any mutation (simpler than patching local state
in each form's submit handler). `api.js` is a thin fetch wrapper — routes
and error shape must stay in sync with `server/src/index.js`.

## Conventions

- Dates are always `YYYY-MM-DD` strings end-to-end (API, storage, frontend
  inputs) — never `Date` objects across a boundary. Parsing/formatting is
  centralized in `stats.js` (`parseDateOnly`/`formatDateOnly`/`addDays`),
  reuse those rather than adding new date math.
- Both server and client are ESM (`"type": "module"` in both
  `package.json`s) — no `require()`.
