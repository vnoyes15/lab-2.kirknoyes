-- Section 23 — "Each stage transition requires timestamp and user." This has never
-- been recorded anywhere: deals.status_changed_at (026) only tracks the *current*
-- stage's start, overwritten on the next transition. This table is the actual history,
-- and is what Section 20's pipeline analytics ("average days per stage") needs — that
-- endpoint cannot be real without it.
create table if not exists deal_status_history (
    history_id uuid primary key default gen_random_uuid(),
    deal_id uuid not null references deals(deal_id) on delete cascade,
    org_id uuid not null references orgs(org_id) on delete cascade,

    status text not null,
    entered_at timestamptz not null default now(),
    exited_at timestamptz,
    changed_by_user_id uuid
);

create index if not exists idx_deal_status_history_deal_id on deal_status_history (deal_id, entered_at);
create index if not exists idx_deal_status_history_org_status on deal_status_history (org_id, status);

select arx_apply_org_rls('deal_status_history');
