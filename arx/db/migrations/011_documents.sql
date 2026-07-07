-- Section 06/54 — documents (document vault). Every deal document has a deal-linked,
-- version-tracked, permission-controlled home in Supabase Storage; this table is the
-- metadata index over that storage. Agent-generated documents (A-05 LOI, A-07 memo,
-- A-06 checklist) auto-populate this table on generation starting Phase 2.
create table if not exists documents (
    doc_id uuid primary key default gen_random_uuid(),
    deal_id uuid not null references deals(deal_id) on delete cascade,
    org_id uuid not null references orgs(org_id) on delete cascade,

    doc_type text not null check (doc_type in (
        'rent_roll', 'om', 'lease', 'title_commitment', 'environmental', 'appraisal',
        'inspection', 'loan_term_sheet', 'loi', 'purchase_agreement', 'dd_item',
        'deal_memo', 'lp_report', 'audit_report', 'other'
    )),
    filename text not null,
    storage_path text not null,
    version integer not null default 1 check (version > 0),

    -- Set once A-09 Document Intelligence processes this file (Phase 2+). Null in Phase 1.
    a09_extraction_id uuid,

    uploaded_by uuid,
    visibility text not null default 'all_roles' check (visibility in ('all_roles', 'admin_analyst_only')),

    created_at timestamptz not null default now()
);

create index if not exists idx_documents_deal_id on documents (deal_id);

select arx_apply_org_rls('documents');
