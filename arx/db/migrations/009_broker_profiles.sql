-- Section 06/60 — broker_profiles (broker intelligence). Extends contacts for
-- contact_category = 'broker'.
create table if not exists broker_profiles (
    broker_id uuid primary key default gen_random_uuid(),
    contact_id uuid not null references contacts(contact_id) on delete cascade,
    org_id uuid not null references orgs(org_id) on delete cascade,

    active_markets text[],
    active_asset_types text[],
    avg_response_time_hrs numeric,
    deals_submitted integer not null default 0,
    deals_closed integer not null default 0,
    last_submission_at timestamptz,
    last_follow_up_from_us timestamptz,
    relationship_notes text,

    unique (contact_id)
);

select arx_apply_org_rls('broker_profiles');
