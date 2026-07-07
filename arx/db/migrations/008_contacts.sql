-- Section 06 — contacts (CRM + counterparty). Section 38: warmth_score is the
-- hot/warm/cold categorical state (recalculated nightly from outreach recency in
-- Phase 4's Celery Beat job), not a numeric score.
create table if not exists contacts (
    contact_id uuid primary key default gen_random_uuid(),
    org_id uuid not null references orgs(org_id) on delete cascade,

    name text not null,
    role_type text,
    contact_info jsonb,

    last_contacted_at timestamptz,
    warmth_score text check (warmth_score in ('hot', 'warm', 'cold')),

    total_deals_submitted integer not null default 0,
    total_deals_closed integer not null default 0,

    contact_category text not null check (contact_category in (
        'seller', 'broker', 'lender', 'lp', 'attorney', 'property_manager', 'other'
    )),

    -- Section 22 Outreach Compliance — checked before every A-08 draft.
    suppressed boolean not null default false,
    suppressed_at timestamptz,

    notes text,
    created_at timestamptz not null default now(),

    constraint chk_suppressed_at_when_suppressed
        check (suppressed = false or suppressed_at is not null)
);

create index if not exists idx_contacts_org_category on contacts (org_id, contact_category);

select arx_apply_org_rls('contacts');
