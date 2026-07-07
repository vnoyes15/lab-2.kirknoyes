"""Agents as endpoints — Section 05. Phase 2 exposes A-01, A-02, A-07, and document
upload (A-09). MT3: every route requires admin|analyst — a Viewer token gets 403
regardless of front end, since Viewer is read-only (Section 09).

Every route follows the same shape: budget check (Section 11) -> run the agent ->
on AgentValidationError, write error_log and return 422 (Section 10 EH3/EH4, Section
78) -> on success, write an inactive deal_snapshot (Section 13 — never auto-active),
record agent_quality_log, and increment token usage in the same transaction (Section 11:
"Token count and database write in same transaction").
"""
import json
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from psycopg.rows import dict_row
from pydantic import BaseModel

from arx.agents.a01_deal_screener import A01ValidationError, run_a01
from arx.agents.a02_underwriting_agent import A02ValidationError, run_a02
from arx.agents.a03_seller_profiler import A03ValidationError, run_a03
from arx.agents.a04_offer_strategy import A04ValidationError, run_a04
from arx.agents.a05_loi_drafting import A05ValidationError, run_a05
from arx.agents.a07_deal_memo_writer import A07ValidationError, run_a07
from arx.agents.a09_document_intelligence import A09ValidationError, run_a09
from arx.agents.a12_negotiation_support import A12ValidationError, run_a12
from arx.agents.a13_capital_raise import A13ValidationError, run_a13
from arx.agents.errors import AgentValidationError
from arx.agents.model_client import ModelClient, model_client_dependency
from arx.api.auth import CurrentUser, require_role
from arx.api.deps import claims_for
from arx.db.connection import db_session
from arx.db.queries.cost_controls import check_budget, increment_token_usage
from arx.db.queries.quality_log import record_agent_run, record_error
from arx.db.queries.snapshots import activate_snapshot, get_active_snapshot, write_snapshot

router = APIRouter(prefix="/api/v1/deals", tags=["agents"])


def _get_deal(conn, deal_id: str) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select * from deals where deal_id = %s", (deal_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")
    return row


def _get_active_uw_config(conn, org_id: str, track: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "select config, version from uw_config where org_id = %s and track = %s and is_active",
            (org_id, track),
        )
        row = cur.fetchone()
    return row


def _enforce_budget_or_raise(conn, org_id: str) -> None:
    status_ = check_budget(conn, org_id)
    if status_.blocked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Org token budget exhausted ({status_.token_used_this_month}/{status_.token_budget_monthly}). "
                   "All agent calls are blocked until the budget resets (Section 11).",
        )


def _handle_agent_failure(
    conn, *, org_id: str, deal_id: str, agent_id: str, exc: AgentValidationError,
) -> HTTPException:
    error_id = record_error(
        conn, org_id=org_id, deal_id=deal_id, error_type="validation_failure",
        agent_id=agent_id, step="validation",
        input_payload=None, raw_output=str(exc.raw_output), failed_checks=exc.failed_checks,
    )
    record_agent_run(
        conn, org_id=org_id, deal_id=deal_id, agent_id=agent_id, prompt_version=None,
        confidence_score=None, validation_passed=False, failed_checks=exc.failed_checks, token_count=None,
    )
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"message": str(exc), "error_id": error_id, "failed_checks": exc.failed_checks},
    )


# --------------------------------------------------------------------------- A-01 ---

class A01Request(BaseModel):
    current_gross_rent: float | None = None
    intended_use: str | None = None


@router.post("/{deal_id}/agents/a01")
def invoke_a01(
    deal_id: str, payload: A01Request,
    user: CurrentUser = Depends(require_role("admin", "analyst")),
    model_client: ModelClient = Depends(model_client_dependency),
):
    with db_session(claims_for(user)) as conn:
        deal = _get_deal(conn, deal_id)
        _enforce_budget_or_raise(conn, user.org_id)

        acq_config = _get_active_uw_config(conn, user.org_id, "acquisition")
        dev_config = _get_active_uw_config(conn, user.org_id, "development")
        target_cap_rate_range = tuple(acq_config["config"]["target_cap_rate_range"]) if (
            acq_config and "target_cap_rate_range" in acq_config["config"]
        ) else None
        target_roc_range = tuple(dev_config["config"]["target_roc_range"]) if (
            dev_config and "target_roc_range" in dev_config["config"]
        ) else None

        try:
            result = run_a01(
                deal_id=deal_id,
                deal_type=deal["deal_type"],
                property_address=deal["property_address"],
                asking_price=deal["asking_price"],
                unit_count=deal["unit_count"],
                land_area_sf=deal["land_area_sf"],
                current_gross_rent=payload.current_gross_rent,
                intended_use=payload.intended_use,
                target_cap_rate_range=target_cap_rate_range,
                target_roc_range=target_roc_range,
                model_client=model_client,
            )
        except A01ValidationError as exc:
            with conn.transaction():
                http_exc = _handle_agent_failure(conn, org_id=user.org_id, deal_id=deal_id, agent_id="a01", exc=exc)
            raise http_exc

        with conn.transaction():
            snapshot_id = write_snapshot(
                conn, deal_id=deal_id, org_id=user.org_id, agent_id="a01",
                input_payload=payload.model_dump(), output_payload=result.output.model_dump(),
                confidence_score=result.output.confidence_score, created_by_user_id=user.user_id,
            )
            record_agent_run(
                conn, org_id=user.org_id, deal_id=deal_id, agent_id="a01", prompt_version=result.prompt_version,
                confidence_score=result.output.confidence_score, validation_passed=True, failed_checks=None,
                token_count=result.input_tokens + result.output_tokens,
            )
            increment_token_usage(conn, user.org_id, result.input_tokens + result.output_tokens)

    return {"snapshot_id": snapshot_id, "output": result.output.model_dump()}


# --------------------------------------------------------------------------- A-02 ---

class A02Request(BaseModel):
    gross_rent_hint: float | None = None
    purchase_price: float | None = None  # falls back to deal.asking_price
    loan_amount: float | None = None  # falls back to purchase_price * uw_config ltv
    ltv: float | None = None
    interest_rate: float | None = None
    amortization_years: int | None = None


@router.post("/{deal_id}/agents/a02")
def invoke_a02(
    deal_id: str, payload: A02Request,
    user: CurrentUser = Depends(require_role("admin", "analyst")),
    model_client: ModelClient = Depends(model_client_dependency),
):
    with db_session(claims_for(user)) as conn:
        deal = _get_deal(conn, deal_id)
        _enforce_budget_or_raise(conn, user.org_id)

        uw_config_row = _get_active_uw_config(conn, user.org_id, "acquisition")
        if uw_config_row is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No active acquisition uw_config for this org")
        defaults = uw_config_row["config"]

        purchase_price = payload.purchase_price or deal["asking_price"]
        if purchase_price is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="purchase_price is required (deal has no asking_price)")

        ltv = payload.ltv if payload.ltv is not None else defaults["ltv"]
        interest_rate = payload.interest_rate if payload.interest_rate is not None else defaults["interest_rate"]
        amortization_years = payload.amortization_years or defaults["amortization_years"]
        loan_amount = payload.loan_amount if payload.loan_amount is not None else purchase_price * ltv

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select cap_rate, price_per_unit, sale_date, source from market_comps "
                "where org_id = %s order by sale_date desc limit 10",
                (user.org_id,),
            )
            comps = cur.fetchall()

        try:
            result = run_a02(
                gross_rent_hint=payload.gross_rent_hint, purchase_price=purchase_price,
                asset_type=deal["asset_type"] or "multifamily", submarket=deal["property_address"],
                uw_defaults=defaults, loan_amount=loan_amount, ltv=ltv, interest_rate=interest_rate,
                amortization_years=amortization_years, comps=comps or None,
                model_client=model_client,
            )
        except A02ValidationError as exc:
            with conn.transaction():
                http_exc = _handle_agent_failure(conn, org_id=user.org_id, deal_id=deal_id, agent_id="a02", exc=exc)
            raise http_exc

        with conn.transaction():
            snapshot_id = write_snapshot(
                conn, deal_id=deal_id, org_id=user.org_id, agent_id="a02",
                input_payload=payload.model_dump(), output_payload=result.output.model_dump(),
                confidence_score=result.output.confidence_score, created_by_user_id=user.user_id,
            )
            record_agent_run(
                conn, org_id=user.org_id, deal_id=deal_id, agent_id="a02", prompt_version=result.prompt_version,
                confidence_score=result.output.confidence_score, validation_passed=True, failed_checks=None,
                token_count=result.input_tokens + result.output_tokens,
            )
            increment_token_usage(conn, user.org_id, result.input_tokens + result.output_tokens)

    return {"snapshot_id": snapshot_id, "output": result.output.model_dump(), "validation": result.validation.to_dict()}


# ------------------------------------------------------------------ snapshot activation ---

@router.post("/{deal_id}/agents/{agent_id}/snapshots/{snapshot_id}/activate")
def activate_agent_snapshot(
    deal_id: str, agent_id: str, snapshot_id: str,
    user: CurrentUser = Depends(require_role("admin", "analyst")),
):
    """R5: "Active snapshot only. Downstream agents pull user-designated active
    snapshot — never the most recent automatically." A new snapshot never
    auto-activates (Section 13) — this explicit call is how a human designates one."""
    with db_session(claims_for(user)) as conn:
        with conn.transaction():
            activate_snapshot(conn, deal_id=deal_id, agent_id=agent_id, snapshot_id=snapshot_id)
    return {"deal_id": deal_id, "agent_id": agent_id, "active_snapshot_id": snapshot_id}


# --------------------------------------------------------------------------- A-07 ---

class A07Request(BaseModel):
    audience_version: Literal["internal", "investor_facing"] = "internal"


@router.post("/{deal_id}/agents/a07")
def invoke_a07(
    deal_id: str, payload: A07Request,
    user: CurrentUser = Depends(require_role("admin", "analyst")),
    model_client: ModelClient = Depends(model_client_dependency),
):
    with db_session(claims_for(user)) as conn:
        deal = _get_deal(conn, deal_id)
        _enforce_budget_or_raise(conn, user.org_id)

        memo_track = "development" if deal["deal_type"] == "development" else "acquisition"
        underwriting_agent_id = "a11" if memo_track == "development" else "a02"

        active_snapshot = get_active_snapshot(conn, deal_id=deal_id, agent_id=underwriting_agent_id)
        if active_snapshot is None:
            # Section 13: "Missing active snapshot = recoverable error."
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"No active {underwriting_agent_id} snapshot for this deal — run and activate "
                       f"underwriting before writing a memo.",
            )

        try:
            result = run_a07(
                memo_track=memo_track,
                underwriting_snapshot=active_snapshot["output_payload"],
                confidence_score=active_snapshot["confidence_score"] or "low",
                property_context={
                    "address": deal["property_address"], "asset_type": deal["asset_type"],
                    "unit_count": deal["unit_count"], "land_area_sf": deal["land_area_sf"],
                },
                audience_version=payload.audience_version,
                model_client=model_client,
            )
        except A07ValidationError as exc:
            with conn.transaction():
                http_exc = _handle_agent_failure(conn, org_id=user.org_id, deal_id=deal_id, agent_id="a07", exc=exc)
            raise http_exc

        with conn.transaction():
            snapshot_id = write_snapshot(
                conn, deal_id=deal_id, org_id=user.org_id, agent_id="a07",
                input_payload=payload.model_dump(), output_payload=result.output.model_dump(),
                confidence_score=active_snapshot["confidence_score"], created_by_user_id=user.user_id,
            )
            record_agent_run(
                conn, org_id=user.org_id, deal_id=deal_id, agent_id="a07", prompt_version=result.prompt_version,
                confidence_score=active_snapshot["confidence_score"], validation_passed=True, failed_checks=None,
                token_count=result.input_tokens + result.output_tokens,
            )
            increment_token_usage(conn, user.org_id, result.input_tokens + result.output_tokens)

    return {"snapshot_id": snapshot_id, "output": result.output.model_dump()}


# ----------------------------------------------------------------- document upload / A-09 ---

@router.post("/{deal_id}/documents")
async def upload_document(
    deal_id: str,
    doc_type: str = Form(...),
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_role("admin", "analyst")),
    model_client: ModelClient = Depends(model_client_dependency),
):
    """R6/DI1: A-09 runs synchronously here at upload time — Phase 2 has no background
    job infrastructure yet (that's Phase 4, Section 07), so "runs before every other
    agent" is enforced by having no other route read from `documents`/`financials`
    until this one has written to them.
    """
    with db_session(claims_for(user)) as conn:
        deal = _get_deal(conn, deal_id)  # 404s if this deal isn't in the caller's org
        financial_track = "development" if deal["deal_type"] in ("land", "development") else "acquisition"
        _enforce_budget_or_raise(conn, user.org_id)

        file_bytes = await file.read()

        try:
            if doc_type == "rent_roll":
                result = run_a09(document_type="rent_roll", filename=file.filename, file_bytes=file_bytes, model_client=model_client)
            else:
                # Phase 2 text extraction: PDF via PyMuPDF; anything else, decode as
                # plain text. Word/Excel-specific extraction beyond rent rolls is not
                # yet wired (python-docx dependency is present for Phase 3+ use).
                document_text = _extract_text(file.filename, file_bytes)
                result = run_a09(document_type=doc_type, filename=file.filename, document_text=document_text, model_client=model_client)
        except A09ValidationError as exc:
            with conn.transaction():
                http_exc = _handle_agent_failure(conn, org_id=user.org_id, deal_id=deal_id, agent_id="a09", exc=exc)
            raise http_exc

        with conn.transaction():
            cur = conn.execute(
                """
                insert into documents (deal_id, org_id, doc_type, filename, storage_path, uploaded_by)
                values (%s, %s, %s, %s, %s, %s)
                returning doc_id
                """,
                (deal_id, user.org_id, doc_type, file.filename, f"pending-storage/{deal_id}/{file.filename}", user.user_id),
            )
            doc_id = cur.fetchone()[0]

            snapshot_id = write_snapshot(
                conn, deal_id=deal_id, org_id=user.org_id, agent_id="a09",
                input_payload={"doc_type": doc_type, "filename": file.filename},
                output_payload=result.output.model_dump(), confidence_score=None,
                created_by_user_id=user.user_id,
            )
            record_agent_run(
                conn, org_id=user.org_id, deal_id=deal_id, agent_id="a09", prompt_version=result.prompt_version,
                confidence_score=None, validation_passed=True, failed_checks=None,
                token_count=result.input_tokens + result.output_tokens,
            )
            increment_token_usage(conn, user.org_id, result.input_tokens + result.output_tokens)

            # Section 06: financials.extraction_source per field (DI3/Section 16).
            for mapping in result.output.financials_db_mapping:
                conn.execute(
                    """
                    insert into financials (deal_id, org_id, input_field, input_value, assumption_type,
                                             financial_track, extraction_source)
                    values (%s, %s, %s, %s, 'extracted', %s, %s)
                    """,
                    (deal_id, user.org_id, mapping.input_field, json.dumps(mapping.input_value),
                     financial_track, mapping.extraction_source),
                )

    return {"doc_id": str(doc_id), "snapshot_id": snapshot_id, "output": result.output.model_dump()}


# --------------------------------------------------------------------------- A-03 ---

class A03Request(BaseModel):
    contact_id: str
    owner_name: str | None = None
    ownership_duration_years: float | None = None
    public_record_data: dict | None = None
    prior_contact_history: dict | None = None


@router.post("/{deal_id}/agents/a03")
def invoke_a03(
    deal_id: str, payload: A03Request,
    user: CurrentUser = Depends(require_role("admin", "analyst")),
    model_client: ModelClient = Depends(model_client_dependency),
):
    with db_session(claims_for(user)) as conn:
        deal = _get_deal(conn, deal_id)
        _enforce_budget_or_raise(conn, user.org_id)

        # The contact must belong to this org (RLS-scoped select, not just the FK) —
        # otherwise a caller could log an access entry against another org's seller
        # contact_id without ever being denied by RLS itself (FK checks in Postgres
        # bypass RLS, so this check has to happen explicitly).
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("select contact_id from contacts where contact_id = %s", (payload.contact_id,))
            if cur.fetchone() is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")

        try:
            result = run_a03(
                deal_type=deal["deal_type"], property_address=deal["property_address"],
                owner_name=payload.owner_name, ownership_duration_years=payload.ownership_duration_years,
                public_record_data=payload.public_record_data, prior_contact_history=payload.prior_contact_history,
                model_client=model_client,
            )
        except A03ValidationError as exc:
            with conn.transaction():
                http_exc = _handle_agent_failure(conn, org_id=user.org_id, deal_id=deal_id, agent_id="a03", exc=exc)
            raise http_exc

        with conn.transaction():
            # Section 03/25: every read of a seller profile writes to
            # seller_profile_access_log — this is that write, in the same
            # transaction as the snapshot so the two can never drift apart.
            conn.execute(
                "insert into seller_profile_access_log (contact_id, org_id, accessed_by_user_id, access_context) "
                "values (%s, %s, %s, %s)",
                (payload.contact_id, user.org_id, user.user_id, f"a03_profile_generated_for_deal_{deal_id}"),
            )
            snapshot_id = write_snapshot(
                conn, deal_id=deal_id, org_id=user.org_id, agent_id="a03",
                input_payload=payload.model_dump(), output_payload=result.output.model_dump(),
                confidence_score=result.output.confidence_score, created_by_user_id=user.user_id,
            )
            record_agent_run(
                conn, org_id=user.org_id, deal_id=deal_id, agent_id="a03", prompt_version=result.prompt_version,
                confidence_score=result.output.confidence_score, validation_passed=True, failed_checks=None,
                token_count=result.input_tokens + result.output_tokens,
            )
            increment_token_usage(conn, user.org_id, result.input_tokens + result.output_tokens)

    return {"snapshot_id": snapshot_id, "output": result.output.model_dump()}


# --------------------------------------------------------------------------- A-04 ---

class A04Request(BaseModel):
    seller_profile: dict
    comps: list[dict] | None = None


@router.post("/{deal_id}/agents/a04")
def invoke_a04(
    deal_id: str, payload: A04Request,
    user: CurrentUser = Depends(require_role("admin", "analyst")),
    model_client: ModelClient = Depends(model_client_dependency),
):
    """Phase 3 supports acquisition deals (reads the active A-02 snapshot). Land/
    development deals will use A-11's snapshot once that agent lands in Phase 4 —
    calling this for a land/development deal today 409s for the same reason A-07 does."""
    with db_session(claims_for(user)) as conn:
        deal = _get_deal(conn, deal_id)
        _enforce_budget_or_raise(conn, user.org_id)

        active_snapshot = get_active_snapshot(conn, deal_id=deal_id, agent_id="a02")
        if active_snapshot is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No active a02 snapshot for this deal — run and activate underwriting before requesting offer strategies.",
            )

        acq_config = _get_active_uw_config(conn, user.org_id, "acquisition")
        feasibility_default = None
        if deal["deal_type"] in ("land", "development"):
            dev_config = _get_active_uw_config(conn, user.org_id, "development")
            feasibility_default = (dev_config["config"].get("land_feasibility_days") if dev_config else None)

        try:
            result = run_a04(
                deal_type=deal["deal_type"], underwriting_snapshot=active_snapshot["output_payload"],
                seller_profile=payload.seller_profile, comps=payload.comps,
                feasibility_contingency_days_default=feasibility_default, model_client=model_client,
            )
        except A04ValidationError as exc:
            with conn.transaction():
                http_exc = _handle_agent_failure(conn, org_id=user.org_id, deal_id=deal_id, agent_id="a04", exc=exc)
            raise http_exc

        with conn.transaction():
            snapshot_id = write_snapshot(
                conn, deal_id=deal_id, org_id=user.org_id, agent_id="a04",
                input_payload=payload.model_dump(), output_payload=result.output.model_dump(),
                confidence_score=None, created_by_user_id=user.user_id,
            )
            record_agent_run(
                conn, org_id=user.org_id, deal_id=deal_id, agent_id="a04", prompt_version=result.prompt_version,
                confidence_score=None, validation_passed=True, failed_checks=None,
                token_count=result.input_tokens + result.output_tokens,
            )
            increment_token_usage(conn, user.org_id, result.input_tokens + result.output_tokens)

    return {"snapshot_id": snapshot_id, "output": result.output.model_dump()}


# --------------------------------------------------------------------------- A-05 ---

class A05Request(BaseModel):
    state_code: str
    selected_offer_strategy: dict
    non_standard_structure: Literal["subject_to", "seller_financing", "complex_jv"] | None = None


@router.post("/{deal_id}/agents/a05")
def invoke_a05(
    deal_id: str, payload: A05Request,
    user: CurrentUser = Depends(require_role("admin", "analyst")),
    model_client: ModelClient = Depends(model_client_dependency),
):
    with db_session(claims_for(user)) as conn:
        deal = _get_deal(conn, deal_id)
        _enforce_budget_or_raise(conn, user.org_id)

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select * from org_jurisdictions where org_id = %s and state_code = %s",
                (user.org_id, payload.state_code),
            )
            jurisdiction = cur.fetchone()
        if jurisdiction is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"No org_jurisdictions row configured for state '{payload.state_code}' — an Admin must "
                       f"configure jurisdiction defaults before drafting an LOI there (Section 56).",
            )

        try:
            result = run_a05(
                deal_type=deal["deal_type"], state_code=payload.state_code,
                selected_offer_strategy=payload.selected_offer_strategy, org_jurisdiction=jurisdiction,
                non_standard_structure=payload.non_standard_structure, model_client=model_client,
            )
        except A05ValidationError as exc:
            with conn.transaction():
                http_exc = _handle_agent_failure(conn, org_id=user.org_id, deal_id=deal_id, agent_id="a05", exc=exc)
            raise http_exc

        with conn.transaction():
            snapshot_id = write_snapshot(
                conn, deal_id=deal_id, org_id=user.org_id, agent_id="a05",
                input_payload=payload.model_dump(), output_payload=result.output.model_dump(),
                confidence_score=None, created_by_user_id=user.user_id,
            )
            record_agent_run(
                conn, org_id=user.org_id, deal_id=deal_id, agent_id="a05", prompt_version=result.prompt_version,
                confidence_score=None, validation_passed=True, failed_checks=None,
                token_count=result.input_tokens + result.output_tokens,
            )
            increment_token_usage(conn, user.org_id, result.input_tokens + result.output_tokens)

    return {"snapshot_id": snapshot_id, "output": result.output.model_dump()}


# --------------------------------------------------------------------------- A-12 ---

class A12Request(BaseModel):
    original_offer_strategy: dict
    seller_counter_terms: dict
    seller_profile: dict | None = None
    comparable_precedents: list[dict] | None = None
    org_return_thresholds: dict | None = None


@router.post("/{deal_id}/agents/a12")
def invoke_a12(
    deal_id: str, payload: A12Request,
    user: CurrentUser = Depends(require_role("admin", "analyst")),
    model_client: ModelClient = Depends(model_client_dependency),
):
    with db_session(claims_for(user)) as conn:
        _get_deal(conn, deal_id)
        _enforce_budget_or_raise(conn, user.org_id)

        active_snapshot = get_active_snapshot(conn, deal_id=deal_id, agent_id="a02")
        if active_snapshot is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No active a02 snapshot for this deal — negotiation support requires the deal's underwriting.",
            )

        try:
            result = run_a12(
                original_offer_strategy=payload.original_offer_strategy,
                seller_counter_terms=payload.seller_counter_terms,
                underwriting_snapshot=active_snapshot["output_payload"],
                seller_profile=payload.seller_profile, comparable_precedents=payload.comparable_precedents,
                org_return_thresholds=payload.org_return_thresholds, model_client=model_client,
            )
        except A12ValidationError as exc:
            with conn.transaction():
                http_exc = _handle_agent_failure(conn, org_id=user.org_id, deal_id=deal_id, agent_id="a12", exc=exc)
            raise http_exc

        with conn.transaction():
            snapshot_id = write_snapshot(
                conn, deal_id=deal_id, org_id=user.org_id, agent_id="a12",
                input_payload=payload.model_dump(), output_payload=result.output.model_dump(),
                confidence_score=None, created_by_user_id=user.user_id,
            )
            record_agent_run(
                conn, org_id=user.org_id, deal_id=deal_id, agent_id="a12", prompt_version=result.prompt_version,
                confidence_score=None, validation_passed=True, failed_checks=None,
                token_count=result.input_tokens + result.output_tokens,
            )
            increment_token_usage(conn, user.org_id, result.input_tokens + result.output_tokens)

    return {"snapshot_id": snapshot_id, "output": result.output.model_dump()}


# --------------------------------------------------------------------------- A-13 ---

class A13Request(BaseModel):
    equity_needed: float | None = None


@router.post("/{deal_id}/agents/a13")
def invoke_a13(
    deal_id: str, payload: A13Request,
    user: CurrentUser = Depends(require_role("admin", "analyst")),
    model_client: ModelClient = Depends(model_client_dependency),
):
    with db_session(claims_for(user)) as conn:
        deal = _get_deal(conn, deal_id)
        _enforce_budget_or_raise(conn, user.org_id)

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("select * from lp_profiles where org_id = %s", (user.org_id,))
            lp_profiles = cur.fetchall()

            # Section 26 (Feedback Loop Engine) and Section 58 (Comp & Precedent
            # Library) — which would populate real total_equity_deployed /
            # avg_return_vs_projection / strongest_precedent from closed-deal
            # performance — are Phase 5 work. deals_closed is real; the rest is left
            # unknown rather than estimated (N3: never fabricate).
            cur.execute(
                "select count(*) as n from deals where org_id = %s and status = 'closed'", (user.org_id,)
            )
            deals_closed = cur.fetchone()["n"]

        org_deal_history = {
            "deals_closed": deals_closed,
            "total_equity_deployed": 0.0,
            "avg_return_vs_projection": None,
            "strongest_precedent": None,
        }
        deal_context = {
            "deal_id": deal_id, "asset_type": deal["asset_type"], "deal_type": deal["deal_type"],
            "equity_needed": payload.equity_needed,
        }

        try:
            result = run_a13(
                deal_context=deal_context, lp_profiles=lp_profiles, org_deal_history=org_deal_history,
                model_client=model_client,
            )
        except A13ValidationError as exc:
            with conn.transaction():
                http_exc = _handle_agent_failure(conn, org_id=user.org_id, deal_id=deal_id, agent_id="a13", exc=exc)
            raise http_exc

        with conn.transaction():
            snapshot_id = write_snapshot(
                conn, deal_id=deal_id, org_id=user.org_id, agent_id="a13",
                input_payload=payload.model_dump(), output_payload=result.output.model_dump(),
                confidence_score=None, created_by_user_id=user.user_id,
            )
            record_agent_run(
                conn, org_id=user.org_id, deal_id=deal_id, agent_id="a13", prompt_version=result.prompt_version,
                confidence_score=None, validation_passed=True, failed_checks=None,
                token_count=result.input_tokens + result.output_tokens,
            )
            increment_token_usage(conn, user.org_id, result.input_tokens + result.output_tokens)

    return {"snapshot_id": snapshot_id, "output": result.output.model_dump()}


def _extract_text(filename: str, file_bytes: bytes) -> str:
    if filename.lower().endswith(".pdf"):
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        try:
            return "\n".join(page.get_text() for page in doc)
        finally:
            doc.close()
    return file_bytes.decode("utf-8", errors="replace")
