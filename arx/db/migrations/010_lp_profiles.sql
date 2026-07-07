-- Section 06/64 — lp_profiles (capital raise intelligence, A-13).
create table if not exists lp_profiles (
    lp_id uuid primary key default gen_random_uuid(),
    org_id uuid not null references orgs(org_id) on delete cascade,

    name text not null,
    contact_info jsonb,
    investor_type text check (investor_type in (
        'hnw_individual', 'family_office', 'small_institution', 'other'
    )),

    check_size_min numeric,
    check_size_max numeric check (check_size_max is null or check_size_min is null or check_size_max >= check_size_min),
    target_returns jsonb,
    preferred_structures text[],
    asset_types text[],
    geographic_focus text[],

    last_investment_date date,
    total_invested_with_us numeric not null default 0,
    notes text,

    created_at timestamptz not null default now()
);

select arx_apply_org_rls('lp_profiles');
