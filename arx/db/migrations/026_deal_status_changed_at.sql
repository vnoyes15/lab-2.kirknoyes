-- Section 06/23 — momentum scoring needs a per-status clock. deals.days_in_current_status
-- (added in 005_deals.sql) has had nothing populating it since Phase 1: there was no
-- column recording *when* the current status started, so "days in current status"
-- could never be computed. status_changed_at fills that gap; a trigger resets it (and
-- zeroes days_in_current_status immediately, ahead of the next nightly recompute)
-- whenever status actually changes, so a deal that just moved stage always reads 0
-- rather than a stale nonzero from before the move.
alter table deals add column if not exists status_changed_at timestamptz not null default now();

update deals set status_changed_at = created_at where status_changed_at is null;

create or replace function arx_deals_reset_status_clock() returns trigger as $$
begin
    if new.status is distinct from old.status then
        new.status_changed_at := now();
        new.days_in_current_status := 0;
    end if;
    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_deals_status_clock on deals;
create trigger trg_deals_status_clock
    before update on deals
    for each row execute function arx_deals_reset_status_clock();
