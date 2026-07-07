-- Section 06 — orgs (multi-tenancy root)
create table if not exists orgs (
    org_id uuid primary key default gen_random_uuid(),
    org_name text not null,
    plan_tier text not null default 'standard' check (plan_tier in ('learning', 'standard', 'enterprise')),
    token_budget_monthly integer not null default 500000 check (token_budget_monthly > 0),
    token_used_this_month integer not null default 0 check (token_used_this_month >= 0),
    -- Pointer to the org's current uw_config version per track. The versioned configs
    -- themselves live in uw_config (Section 32) — this column is a fast-lookup convenience,
    -- not the source of truth for what a given deal was underwritten against
    -- (deals always resolve their config via financials.uw_config_version, Section 06).
    uw_config_version integer,
    -- Network intelligence opt-in (Section 59). Off by default — explicit opt-in required.
    network_participation boolean not null default false,
    status text not null default 'active' check (status in ('active', 'suspended', 'churned')),
    created_at timestamptz not null default now()
);

select arx_apply_org_rls('orgs');
