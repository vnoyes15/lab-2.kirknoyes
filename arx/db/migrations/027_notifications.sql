-- Section 06 — notifications. Referenced since Phase 1's construction_budget comment
-- ("Variance triggers LP notification when above threshold") as Phase 4+ intelligence
-- job output; this is the skeleton those jobs write into. in_app is the only delivery
-- channel implemented for real right now (arx/notifications/channels.py) — email/SMS
-- delivery is deferred (no Twilio/SendGrid credentials in this environment), so every
-- notification lands here regardless of channel and is at minimum visible via the
-- /api/v1/notifications API.
create table if not exists notifications (
    notification_id uuid primary key default gen_random_uuid(),
    org_id uuid not null references orgs(org_id) on delete cascade,
    deal_id uuid references deals(deal_id) on delete cascade,
    -- Null recipient_user_id means "org-wide" (visible to any user in the org via RLS,
    -- same as an unassigned deal_task) rather than a specific person's inbox.
    recipient_user_id uuid,

    notification_type text not null check (notification_type in (
        'deal_advancement_blocked', 'momentum_stalled', 'budget_variance',
        'daily_send_limit_reached', 'task_overdue'
    )),
    severity text not null check (severity in ('info', 'warning', 'critical')),
    title text not null,
    body text not null,
    source_agent text,

    is_read boolean not null default false,
    read_at timestamptz,

    created_at timestamptz not null default now(),

    constraint chk_read_at_when_read
        check (is_read = false or read_at is not null)
);

create index if not exists idx_notifications_org_created_at on notifications (org_id, created_at desc);
create index if not exists idx_notifications_org_unread on notifications (org_id, is_read) where not is_read;

select arx_apply_org_rls('notifications');
