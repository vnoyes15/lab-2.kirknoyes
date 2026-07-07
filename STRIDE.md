# Stride

A personal workout accountability app: log your daily morning walk/run and
strength sessions, and track your run streak and weekly strength count
against a 4-5x/week goal.

## Structure

- `server/` — Express API, stores entries in a local JSON file (`server/data/entries.json`, gitignored)
- `client/` — Vite + React frontend

## Running locally

Two terminals:

```bash
cd server && npm install && npm run dev   # http://localhost:3001
cd client && npm install && npm run dev   # http://localhost:5173
```

Open http://localhost:5173 — the Vite dev server proxies `/api` to the backend.

See `CLAUDE.md` for architecture notes and all available commands.
