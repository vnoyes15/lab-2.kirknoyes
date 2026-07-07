-- Section 06/10/78 — error_log. Every unrecoverable error writes a complete record here:
-- full input payload, raw model output, failed validation checks. Resolution tracked
-- through to closure (EH4, EP2).
create table if not exists error_log (
    error_id uuid primary key default gen_random_uuid(),
    deal_id uuid references deals(deal_id) on delete set null,
    org_id uuid not null references orgs(org_id) on delete cascade,

    error_type text not null,
    agent_id text,
    step text,

    input_payload jsonb,
    raw_output text,
    failed_checks jsonb,

    resolution_status text not null default 'open' check (resolution_status in (
        'open', 'investigating', 'resolved'
    )),
    resolution_notes text,

    created_at timestamptz not null default now()
);

create index if not exists idx_error_log_org_status on error_log (org_id, resolution_status);
create index if not exists idx_error_log_deal_id on error_log (deal_id);

select arx_apply_org_rls('error_log');
