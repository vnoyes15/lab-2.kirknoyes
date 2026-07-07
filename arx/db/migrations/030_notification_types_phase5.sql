-- Phase 5 adds two new notification triggers:
--   accuracy_flag_threshold (Section 35: 3 'inaccurate' flags on the same agent within
--   30 days -> Admin notification recommending prompt review)
--   milestone_delay (Section 49: LP Trust Layer development track - milestone delay
--   notifications fire to LP users when schedule slips beyond defined thresholds)
alter table notifications drop constraint if exists notifications_notification_type_check;
alter table notifications add constraint notifications_notification_type_check check (notification_type in (
    'deal_advancement_blocked', 'momentum_stalled', 'budget_variance',
    'daily_send_limit_reached', 'task_overdue', 'accuracy_flag_threshold', 'milestone_delay'
));
