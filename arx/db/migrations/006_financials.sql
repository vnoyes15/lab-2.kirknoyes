-- Section 06 — financials (underwriting inputs). Key/value shape (input_field/input_value)
-- rather than fixed columns: the field set differs by financial_track and grows as new
-- agents (A-09, A-11) land in later phases without requiring a schema migration per field.
create table if not exists financials (
    financial_id uuid primary key default gen_random_uuid(),
    deal_id uuid not null references deals(deal_id) on delete cascade,
    org_id uuid not null references orgs(org_id) on delete cascade,

    input_field text not null,
    input_value jsonb not null,

    assumption_type text not null check (assumption_type in ('system_default', 'user_provided', 'extracted')),
    financial_track text not null check (financial_track in ('acquisition', 'development')),
    uw_config_version integer,

    extraction_source text check (extraction_source in ('manual', 'a09_extracted', 'rent_roll_parsed')),

    -- Section 21 — Assumption Override Logging. Required whenever assumption_type =
    -- 'user_provided' and the value deviates from the org's uw_config default.
    -- API enforces min 10 chars / not-blank (Section 21); DB check is defense in depth.
    override_by_user_id uuid,
    override_note text check (override_note is null or length(trim(override_note)) >= 10),

    created_at timestamptz not null default now(),

    constraint chk_override_note_when_overridden
        check (override_by_user_id is null or override_note is not null)
);

create index if not exists idx_financials_deal_id on financials (deal_id);
create index if not exists idx_financials_org_id on financials (org_id);

select arx_apply_org_rls('financials');
