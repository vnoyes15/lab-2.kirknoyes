-- Section 06 — deals (core table). Status machine per Section 23:
--   acquisition:  lead -> screened -> underwriting -> loi -> under_contract -> due_diligence -> closed | dead
--   land:         lead -> screened -> feasibility_study -> loi -> under_contract -> due_diligence -> entitlement -> (construction_start | disposition)
--   development:  ... -> entitlement -> construction -> lease_up -> stabilized
create table if not exists deals (
    deal_id uuid primary key default gen_random_uuid(),
    org_id uuid not null references orgs(org_id) on delete cascade,

    property_address text not null,
    asset_type text,
    deal_type text not null check (deal_type in ('acquisition', 'land', 'development')),

    unit_count integer check (unit_count is null or unit_count > 0),
    land_area_sf numeric check (land_area_sf is null or land_area_sf > 0),
    asking_price numeric check (asking_price is null or asking_price >= 0),

    status text not null default 'lead' check (status in (
        'lead', 'screened', 'feasibility_study', 'underwriting', 'loi', 'under_contract',
        'due_diligence', 'entitlement', 'construction', 'lease_up', 'stabilized',
        'closed', 'dead'
    )),

    source text,

    is_acquired boolean not null default false,
    acquisition_date date,
    close_reason_code text check (close_reason_code in (
        'seller_declined_offer', 'deal_failed_underwriting', 'financing_unavailable',
        'due_diligence_failed', 'entitlement_failed', 'construction_cost_infeasible', 'other'
    )),
    -- Required whenever status = 'dead' (Section 23). Enforced below via check.
    final_economics jsonb,

    momentum_score integer check (momentum_score is null or momentum_score between 0 and 100),
    days_in_current_status integer not null default 0 check (days_in_current_status >= 0),

    latitude numeric check (latitude is null or latitude between -90 and 90),
    longitude numeric check (longitude is null or longitude between -180 and 180),

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    constraint chk_dead_requires_reason
        check (status <> 'dead' or close_reason_code is not null)
);

-- Deal intake dedup (Section 19): same address + org_id + non-dead status returns the
-- existing deal_id rather than creating a duplicate.
create unique index if not exists uq_deals_org_address_active
    on deals (org_id, property_address)
    where status <> 'dead';

create index if not exists idx_deals_org_status on deals (org_id, status);
create index if not exists idx_deals_org_deal_type on deals (org_id, deal_type);

create trigger trg_deals_updated_at
    before update on deals
    for each row execute function arx_set_updated_at();

select arx_apply_org_rls('deals');
