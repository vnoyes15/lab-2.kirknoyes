-- Section 43 — Lender Matching Engine. Referenced there ("identifies matching lenders
-- from lender_profiles... Ranked by last_deal_date recency") but not one of Section
-- 06's explicitly listed tables — this schema is derived from Section 43's own field
-- list, following the same contact-extension pattern as broker_profiles (009) and
-- lp_profiles (010): a lender is a contacts row with contact_category = 'lender',
-- extended with lending-specific criteria.
create table if not exists lender_profiles (
    lender_id uuid primary key default gen_random_uuid(),
    contact_id uuid not null references contacts(contact_id) on delete cascade,
    org_id uuid not null references orgs(org_id) on delete cascade,

    asset_types text[],
    -- Section 43: "loan_types (acquisition | construction | bridge | permanent)".
    -- Stored as text[] (an org may lend across multiple types) rather than a single
    -- enum column, same convention as broker_profiles.active_asset_types.
    loan_types text[],
    target_markets text[],

    ltv_max numeric check (ltv_max is null or (ltv_max > 0 and ltv_max <= 1)),
    ltc_max numeric check (ltc_max is null or (ltc_max > 0 and ltc_max <= 1)),
    dscr_threshold numeric check (dscr_threshold is null or dscr_threshold > 0),

    last_deal_date date,
    relationship_notes text,
    created_at timestamptz not null default now(),

    unique (contact_id)
);

create index if not exists idx_lender_profiles_org_id on lender_profiles (org_id);

select arx_apply_org_rls('lender_profiles');
