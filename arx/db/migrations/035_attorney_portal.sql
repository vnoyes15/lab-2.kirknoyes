-- Section 71 — Attorney Portal. Same deal-scoped access-grant shape as
-- deal_lp_access (021): "Access granted per deal by Admin." An attorney token can
-- only see deals where their user_id is in deal_attorney_access.
create table if not exists deal_attorney_access (
    access_id uuid primary key default gen_random_uuid(),
    deal_id uuid not null references deals(deal_id) on delete cascade,
    org_id uuid not null references orgs(org_id) on delete cascade,

    attorney_user_id uuid not null,
    granted_at timestamptz not null default now(),
    granted_by_user_id uuid,

    unique (deal_id, attorney_user_id)
);

create index if not exists idx_deal_attorney_access_attorney_user_id on deal_attorney_access (attorney_user_id);

select arx_apply_org_rls('deal_attorney_access');

-- Section 71: "flag issues back into the deal record as deal_comments." General
-- deal-scoped comment log — not attorney-exclusive by schema (author_role is stored,
-- not constrained), since nothing in the spec says only attorneys can ever comment,
-- just that this is *how* attorneys flag issues.
create table if not exists deal_comments (
    comment_id uuid primary key default gen_random_uuid(),
    deal_id uuid not null references deals(deal_id) on delete cascade,
    org_id uuid not null references orgs(org_id) on delete cascade,

    author_user_id uuid not null,
    author_role text not null,
    body text not null,

    created_at timestamptz not null default now()
);

create index if not exists idx_deal_comments_deal_id on deal_comments (deal_id, created_at);

select arx_apply_org_rls('deal_comments');
