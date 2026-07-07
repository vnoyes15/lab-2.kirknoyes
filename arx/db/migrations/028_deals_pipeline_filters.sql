-- Section 20 — Pipeline View filters need two deals columns that were never added:
-- assigned_user_id (who owns this deal — GET /api/v1/pipeline?assigned_user_id=...)
-- and submarket (GET /api/v1/pipeline?submarket=...). A-01/A-02 previously derived a
-- submarket string ad hoc from property_address for prompt context only; this is the
-- first place it's actually stored and queryable on the deal itself.
alter table deals add column if not exists assigned_user_id uuid;
alter table deals add column if not exists submarket text;

create index if not exists idx_deals_org_assigned_user on deals (org_id, assigned_user_id);
create index if not exists idx_deals_org_submarket on deals (org_id, submarket);
