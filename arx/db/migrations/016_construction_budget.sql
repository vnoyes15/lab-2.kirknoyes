-- Section 06 — construction_budget. One row per budget line item per deal.
-- Variance triggers LP notification when above threshold (Phase 4+ intelligence job).
create table if not exists construction_budget (
    budget_id uuid primary key default gen_random_uuid(),
    deal_id uuid not null references deals(deal_id) on delete cascade,
    org_id uuid not null references orgs(org_id) on delete cascade,

    line_item text not null,
    budget_amount numeric not null,
    committed_amount numeric not null default 0,
    drawn_to_date numeric not null default 0,
    variance_amount numeric,

    updated_at timestamptz not null default now()
);

create index if not exists idx_construction_budget_deal_id on construction_budget (deal_id);

create trigger trg_construction_budget_updated_at
    before update on construction_budget
    for each row execute function arx_set_updated_at();

select arx_apply_org_rls('construction_budget');
