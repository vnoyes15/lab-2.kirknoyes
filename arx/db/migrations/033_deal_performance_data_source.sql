-- Section 45 Asset Performance Tracking: "data_source field tracks whether data was
-- entered manually or received via PM integration (Section 72)." PM2 (the actual
-- AppFolio/Buildium/Yardi/RealPage API integration) is Phase 6 scope but has no
-- credentials in this environment (see README scope boundaries) — the column exists
-- now so the schema is ready and every write path is explicit about its source,
-- rather than the PM integration retrofitting this later.
alter table deal_performance add column if not exists data_source text not null default 'manual'
    check (data_source in ('manual', 'pm_integration'));
