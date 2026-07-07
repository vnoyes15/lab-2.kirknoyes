-- Phase 6 adds three new notification triggers:
--   task_assigned (Section 73: "Assigned users receive notification on task creation")
--   error_on_active_deal (Section 78 EP1: "Admin notified immediately for errors on
--   deals in active stages")
--   refi_opportunity / disposition_opportunity (Section 46)
alter table notifications drop constraint if exists notifications_notification_type_check;
alter table notifications add constraint notifications_notification_type_check check (notification_type in (
    'deal_advancement_blocked', 'momentum_stalled', 'budget_variance',
    'daily_send_limit_reached', 'task_overdue', 'accuracy_flag_threshold', 'milestone_delay',
    'task_assigned', 'error_on_active_deal', 'refi_opportunity', 'disposition_opportunity',
    'performance_variance'
));
