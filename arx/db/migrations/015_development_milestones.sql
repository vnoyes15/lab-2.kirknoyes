-- Section 06 — development_milestones (development tracking).
create table if not exists development_milestones (
    milestone_id uuid primary key default gen_random_uuid(),
    deal_id uuid not null references deals(deal_id) on delete cascade,
    org_id uuid not null references orgs(org_id) on delete cascade,

    milestone_type text not null check (milestone_type in (
        'entitlement_submitted', 'entitlement_approved', 'permits_issued',
        'construction_start', 'construction_complete', 'first_unit_leased',
        'stabilization', 'refi_or_sale'
    )),
    projected_date date,
    actual_date date,
    status text not null default 'projected' check (status in (
        'projected', 'in_progress', 'complete', 'delayed'
    )),
    variance_days integer,
    notes text,

    unique (deal_id, milestone_type)
);

create index if not exists idx_development_milestones_deal_id on development_milestones (deal_id);

select arx_apply_org_rls('development_milestones');
