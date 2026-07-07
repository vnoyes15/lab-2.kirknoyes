-- Section 32 — Versioned Underwriting Configuration.
-- Defaults live here, versioned per org, per track (acquisition | development).
-- Prior deals retain the config version active when underwritten (financials.uw_config_version
-- points back to uw_config.version). Config changes never mutate a prior version in place —
-- they insert a new version and flip is_active.
create table if not exists uw_config (
    config_id uuid primary key default gen_random_uuid(),
    org_id uuid not null references orgs(org_id) on delete cascade,
    track text not null check (track in ('acquisition', 'development')),
    version integer not null check (version > 0),
    is_active boolean not null default true,

    -- Section 02/03 ZONIQ defaults. Both tracks' full parameter sets live in one jsonb
    -- column rather than dozens of nullable typed columns — the shape differs by track
    -- and orgs may add fields (Section 56: fully org-configurable).
    config jsonb not null,

    created_at timestamptz not null default now(),
    created_by_user_id uuid,

    unique (org_id, track, version)
);

-- Only one active config per org+track at a time (Section 32 versioning semantics).
create unique index if not exists uq_uw_config_active
    on uw_config (org_id, track)
    where is_active;

select arx_apply_org_rls('uw_config');

-- ZONIQ acquisition-track defaults (Section 03 A-02, Section 04 ZONIQ DEFAULTS):
--   vacancy 0.07, property_management 0.08, maintenance 0.05, capex_reserves 0.05,
--   insurance_pct_of_price 0.005, ltv 0.75, interest_rate 0.065, amortization_years 30
--
-- ZONIQ development-track defaults (Section 10 A-11 KEY DEFAULTS):
--   soft_costs_pct_of_hard {min: 0.15, max: 0.20}, construction_contingency_pct {min: 0.05, max: 0.10},
--   construction_loan_ltc 0.65, stabilized_occupancy 0.93
--
-- Seeded by scripts/seed_org.py — never hardcoded in application code (config values are
-- data, not logic; Admin can change them per Section 32 without a deploy).
