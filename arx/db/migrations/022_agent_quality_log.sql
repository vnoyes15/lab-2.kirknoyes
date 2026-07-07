-- Section 12 Observability & Output Quality: "agent_quality_log records every run."
-- Section 87 schema versioning: "Schema version is stored in
-- agent_quality_log.prompt_version for every agent run — enabling retroactive quality
-- analysis across prompt versions." No agent logic exists yet in Phase 1 (Section 07),
-- but the log table is foundational per N7 and is written to starting Phase 2.
create table if not exists agent_quality_log (
    log_id uuid primary key default gen_random_uuid(),
    org_id uuid not null references orgs(org_id) on delete cascade,
    deal_id uuid references deals(deal_id) on delete set null,

    agent_id text not null,
    prompt_version text,

    confidence_score text check (confidence_score in ('high', 'medium', 'low')),
    validation_passed boolean not null,
    failed_checks jsonb,
    token_count integer,

    created_at timestamptz not null default now()
);

create index if not exists idx_agent_quality_log_org_agent on agent_quality_log (org_id, agent_id, created_at desc);

-- Section 12: "Validation failure rate above 5% over 7 days triggers Admin alert."
-- (Alerting job lands with Celery Beat in Phase 4 — this index supports that query.)
create index if not exists idx_agent_quality_log_validation_passed on agent_quality_log (org_id, validation_passed, created_at);

select arx_apply_org_rls('agent_quality_log');
