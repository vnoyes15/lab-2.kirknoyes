"""Arx API entry point — Section 05: FastAPI, agents as endpoints, role enforcement
middleware, API versioning. Section 01: API-first, no front end in Phase 1.
"""
from fastapi import FastAPI

from arx.api import agents, deals
from arx.api.config import get_settings

# Fail fast at import time if required env vars are missing (Section 86) — this must
# happen before the app object is even constructed, not on first request.
get_settings()

app = FastAPI(
    title="Arx API",
    description="AI-powered operating system for commercial real estate operators.",
    version="0.1.0",
)

app.include_router(deals.router)
app.include_router(agents.router)


@app.get("/healthz", tags=["ops"])
def healthz() -> dict:
    return {"status": "ok"}
