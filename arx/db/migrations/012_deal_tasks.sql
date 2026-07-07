-- Section 06/73 — deal_tasks. Created automatically by agents (A-06 DD checklist items,
-- starting Phase 2/4) and manually by users. Section 73: a deal cannot advance from
-- due_diligence to closed while any high-priority task is not_started or in_progress —
-- enforced at the API layer (arx/api/deals.py), not here.
create table if not exists deal_tasks (
    task_id uuid primary key default gen_random_uuid(),
    deal_id uuid not null references deals(deal_id) on delete cascade,
    org_id uuid not null references orgs(org_id) on delete cascade,

    assigned_to_user_id uuid,
    title text not null,
    description text,
    due_date date,
    status text not null default 'not_started' check (status in (
        'not_started', 'in_progress', 'complete', 'blocked'
    )),
    priority text not null default 'medium' check (priority in ('low', 'medium', 'high')),
    -- Which agent created this task, e.g. 'a06'. Null for user-created tasks.
    source_agent text,

    created_at timestamptz not null default now(),
    completed_at timestamptz,

    constraint chk_completed_at_when_complete
        check (status <> 'complete' or completed_at is not null)
);

create index if not exists idx_deal_tasks_deal_id on deal_tasks (deal_id);
create index if not exists idx_deal_tasks_status_priority on deal_tasks (deal_id, status, priority);

select arx_apply_org_rls('deal_tasks');
