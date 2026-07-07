-- Section 06/13 — deal_snapshots (versioning). Every validated agent output creates an
-- immutable snapshot. New snapshot never auto-activates — user designates explicitly.
-- Downstream agents always pull the active snapshot (R5), never "most recent."
create table if not exists deal_snapshots (
    snapshot_id uuid primary key default gen_random_uuid(),
    deal_id uuid not null references deals(deal_id) on delete cascade,
    org_id uuid not null references orgs(org_id) on delete cascade,
    agent_id text not null,
    version_number integer not null check (version_number > 0),

    is_active boolean not null default false,
    confidence_score text check (confidence_score in ('high', 'medium', 'low')),

    input_payload jsonb not null,
    output_payload jsonb not null,

    -- Section 35 — Output Accuracy Flagging. Mutable post-hoc; everything else on this
    -- row is immutable once written (enforced by trg_deal_snapshots_immutable below).
    accuracy_flag text check (accuracy_flag in ('accurate', 'partial', 'inaccurate')),
    accuracy_note text,

    created_by_user_id uuid,
    notes text,
    created_at timestamptz not null default now(),

    unique (deal_id, agent_id, version_number)
);

-- G-05: re-run creates a new snapshot, never overwrites; exactly one active per deal+agent.
create unique index if not exists uq_deal_snapshots_active
    on deal_snapshots (deal_id, agent_id)
    where is_active;

create index if not exists idx_deal_snapshots_deal_id on deal_snapshots (deal_id);

-- Immutability (Section 13: "Immutable once written"). Only accuracy_flag, accuracy_note,
-- notes, and is_active (snapshot activation, R5) may change after insert. Deletes are
-- blocked outright — snapshots are "never overwritten or deleted."
create or replace function arx_enforce_snapshot_immutability() returns trigger as $$
begin
    if old.deal_id is distinct from new.deal_id
        or old.org_id is distinct from new.org_id
        or old.agent_id is distinct from new.agent_id
        or old.version_number is distinct from new.version_number
        or old.input_payload is distinct from new.input_payload
        or old.output_payload is distinct from new.output_payload
        or old.confidence_score is distinct from new.confidence_score
        or old.created_by_user_id is distinct from new.created_by_user_id
        or old.created_at is distinct from new.created_at
    then
        raise exception 'deal_snapshots rows are immutable except is_active, accuracy_flag, accuracy_note, notes (snapshot_id=%)', old.snapshot_id;
    end if;
    return new;
end;
$$ language plpgsql;

create trigger trg_deal_snapshots_immutable
    before update on deal_snapshots
    for each row execute function arx_enforce_snapshot_immutability();

-- Amended by 023_amend_snapshot_delete_guard.sql to allow an explicit, session-scoped
-- opt-in for deliberate administrative purges (org offboarding, GDPR deletion, test
-- teardown) — the unconditional version below blocked even a cascade delete from the
-- parent org/deal, making it impossible to ever remove an org that had any snapshots.
create or replace function arx_block_snapshot_delete() returns trigger as $$
begin
    raise exception 'deal_snapshots rows are never deleted (snapshot_id=%)', old.snapshot_id;
end;
$$ language plpgsql;

create trigger trg_deal_snapshots_no_delete
    before delete on deal_snapshots
    for each row execute function arx_block_snapshot_delete();

select arx_apply_org_rls('deal_snapshots');
