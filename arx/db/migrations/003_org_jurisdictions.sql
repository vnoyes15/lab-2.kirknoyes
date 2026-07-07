-- Section 18 (WA law), Section 56 (white-label schema), Section 07 Phase 1 scope.
-- One row per state per org. WA, CA, OR pre-populated with rent control parameters
-- (Section 56). All other states default to federal minimums + attorney_review_required.
create table if not exists org_jurisdictions (
    jurisdiction_id uuid primary key default gen_random_uuid(),
    org_id uuid not null references orgs(org_id) on delete cascade,
    state_code text not null check (state_code ~ '^[A-Z]{2}$'),

    -- LOI defaults (Section 05, 19, 56) — all org-configurable per jurisdiction.
    earnest_money_pct numeric not null default 0.01 check (earnest_money_pct > 0),
    earnest_money_holder text not null default 'licensed_escrow',
    acquisition_dd_days integer not null default 30 check (acquisition_dd_days > 0),
    land_feasibility_days_min integer not null default 60,
    land_feasibility_days_max integer not null default 90
        check (land_feasibility_days_max >= land_feasibility_days_min),
    closing_timeline_days_min integer not null default 45,
    closing_timeline_days_max integer not null default 60
        check (closing_timeline_days_max >= closing_timeline_days_min),

    -- Rent control (Section 18 — WA RCW 59.18, effective May 2025).
    rent_control_active boolean not null default false,
    rent_control_cap_formula text,
    rent_control_notice_days integer,

    -- WA1/WA2/WA3: non-WA states default true; reviewed per-jurisdiction by Admin.
    attorney_review_required boolean not null default true,

    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    unique (org_id, state_code)
);

create trigger trg_org_jurisdictions_updated_at
    before update on org_jurisdictions
    for each row execute function arx_set_updated_at();

select arx_apply_org_rls('org_jurisdictions');
