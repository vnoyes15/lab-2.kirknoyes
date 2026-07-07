-- Section 03/08/22 — outreach_log. Referenced ("Logs to outreach_log and updates
-- relationship warmth score", "Default daily send limit: 50 per org across all
-- channels") but not in Section 06's explicit table list — same situation as
-- lender_profiles (024): schema derived from these sections' own field references.
create table if not exists outreach_log (
    outreach_id uuid primary key default gen_random_uuid(),
    org_id uuid not null references orgs(org_id) on delete cascade,
    contact_id uuid not null references contacts(contact_id) on delete cascade,
    deal_id uuid references deals(deal_id) on delete set null,

    recipient_type text not null check (recipient_type in ('seller', 'broker', 'lender', 'lp')),
    channel text not null check (channel in ('email', 'sms', 'linkedin', 'phone_script')),
    message_text text not null,

    sent_by_user_id uuid,
    sent_at timestamptz not null default now()
);

create index if not exists idx_outreach_log_org_sent_at on outreach_log (org_id, sent_at);
create index if not exists idx_outreach_log_contact_id on outreach_log (contact_id);

select arx_apply_org_rls('outreach_log');
