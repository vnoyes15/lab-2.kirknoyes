-- Section 06/62 — market_signals (market signal processing). Phase 1: manual entry.
-- Phase 6 automates signal_type sourcing (permit feeds, BLS, etc.) and the
-- signal-to-deal impact routing job (Section 62) that populates deal_impacts.
create table if not exists market_signals (
    signal_id uuid primary key default gen_random_uuid(),
    org_id uuid not null references orgs(org_id) on delete cascade,

    signal_type text not null check (signal_type in (
        'interest_rate', 'cap_rate', 'employment', 'permit_activity',
        'comparable_sale', 'population_migration'
    )),
    submarket text,
    signal_value numeric not null,
    prior_value numeric,
    change_pct numeric,
    source text,
    significance text check (significance in ('low', 'medium', 'high')),

    -- JSON array of affected deal_ids, populated by the (Phase 4+) signal-to-deal
    -- impact routing job when significance = 'high'.
    deal_impacts jsonb not null default '[]'::jsonb,

    observed_at timestamptz not null default now()
);

create index if not exists idx_market_signals_org_submarket on market_signals (org_id, submarket);

select arx_apply_org_rls('market_signals');
