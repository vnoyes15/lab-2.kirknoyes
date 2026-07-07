"""Arx API entry point — Section 05: FastAPI, agents as endpoints, role enforcement
middleware, API versioning. Section 01: API-first, no front end in Phase 1.
"""
from fastapi import FastAPI

from arx.api import (
    agents,
    attorney,
    audit,
    daily_brief,
    deals,
    equity_waterfall,
    errors,
    lender_package,
    lp,
    notifications,
    pipeline,
    portfolio,
    refi_disposition,
    risk,
    scenarios,
)
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
app.include_router(notifications.router)
app.include_router(pipeline.router)
app.include_router(portfolio.router)
app.include_router(lp.router)
app.include_router(scenarios.router)
app.include_router(audit.router)
app.include_router(daily_brief.router)
app.include_router(errors.router)
app.include_router(risk.router)
app.include_router(refi_disposition.router)
app.include_router(equity_waterfall.router)
app.include_router(attorney.router)
app.include_router(attorney.deals_router)
app.include_router(lender_package.router)


@app.get("/healthz", tags=["ops"])
def healthz() -> dict:
    return {"status": "ok"}
