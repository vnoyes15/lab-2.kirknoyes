-- Section 06/59 — network_contributions. Anonymized deal data for the (Phase 6+)
-- network intelligence layer. Zero PII, zero deal identifiers in the row itself.
--
-- org_id is retained per Section 06's schema so a contributing org can audit and manage
-- its own contribution history and honor opt-out — but MT5/Section 59 double
-- anonymization means no cross-org query path may ever join this table back to org
-- identity for another org's benefit. Enforced two ways: RLS restricts org_id visibility
-- to the contributing org itself (same as every other table), and network-layer
-- aggregation queries (built in Phase 6) must select only the non-identifying columns
-- when computing cross-org market intelligence — org_id is never surfaced in that output.
create table if not exists network_contributions (
    contribution_id uuid primary key default gen_random_uuid(),
    org_id uuid not null references orgs(org_id) on delete cascade,

    submarket text not null,
    asset_type text,
    deal_type text check (deal_type in ('acquisition', 'land', 'development')),

    close_cap_rate numeric,
    price_per_unit numeric,
    financing_type text,
    dd_days integer,

    contributed_at timestamptz not null default now()
);

create index if not exists idx_network_contributions_submarket on network_contributions (submarket, asset_type);

select arx_apply_org_rls('network_contributions');
