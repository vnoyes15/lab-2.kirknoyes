-- Section 03 (A-03 "All access logged to seller_profile_access_log"), Section 25 Privacy
-- & Retention: "Every read of a seller profile writes to seller_profile_access_log."
create table if not exists seller_profile_access_log (
    access_log_id uuid primary key default gen_random_uuid(),
    contact_id uuid not null references contacts(contact_id) on delete cascade,
    org_id uuid not null references orgs(org_id) on delete cascade,

    accessed_by_user_id uuid not null,
    accessed_at timestamptz not null default now(),
    access_context text
);

create index if not exists idx_seller_profile_access_log_contact_id on seller_profile_access_log (contact_id);

select arx_apply_org_rls('seller_profile_access_log');
