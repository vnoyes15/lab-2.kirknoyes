-- Section 29 — Portfolio Layer. "Once a deal closes (is_acquired = true), it enters
-- the portfolio layer. deal_performance records monthly actuals." One row per
-- deal per calendar month. Feeds both the portfolio aggregation view here and the
-- Section 26 feedback loop's "projection vs. actual" comparison against A-02/A-11.
create table if not exists deal_performance (
    performance_id uuid primary key default gen_random_uuid(),
    deal_id uuid not null references deals(deal_id) on delete cascade,
    org_id uuid not null references orgs(org_id) on delete cascade,

    period date not null, -- first-of-month; e.g. 2026-07-01 for July 2026
    actual_gross_rent numeric,
    actual_vacancy_rate numeric,
    actual_noi numeric,
    actual_operating_expenses numeric,
    notes text,

    created_by_user_id uuid,
    created_at timestamptz not null default now(),

    unique (deal_id, period)
);

create index if not exists idx_deal_performance_deal_id on deal_performance (deal_id, period);

select arx_apply_org_rls('deal_performance');
