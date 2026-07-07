-- Amends 007_deal_snapshots.sql's delete guard. The original trigger blocked every
-- delete unconditionally, including a cascade delete from `orgs`/`deals` — meaning an
-- org could never be purged (test cleanup, org offboarding, a future GDPR-style
-- deletion request) once it had any deal_snapshots at all. Section 13's actual intent
-- ("snapshots are never overwritten or deleted") is about protecting the audit trail
-- from routine mutation by the application/agents — not about making legitimate
-- administrative bulk deletion structurally impossible.
--
-- This keeps the guarantee that matters (no agent, no API route, no ordinary
-- application code path can delete a snapshot) while giving deliberate administrative
-- operations an explicit, auditable opt-in: they must SET a session GUC naming exactly
-- what they're doing before the delete succeeds. Nothing deletes a snapshot by accident.
create or replace function arx_block_snapshot_delete() returns trigger as $$
begin
    if current_setting('arx.allow_snapshot_delete', true) = 'true' then
        return old;
    end if;
    raise exception
        'deal_snapshots rows are never deleted through normal operation (snapshot_id=%). '
        'This looks like a cascade from deleting the parent org/deal. If this is a '
        'deliberate administrative purge (org offboarding, GDPR deletion, test '
        'teardown), run: SET LOCAL arx.allow_snapshot_delete = ''true''; first.',
        old.snapshot_id;
end;
$$ language plpgsql;
