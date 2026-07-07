-- Section 62: "triggers deal risk monitor notification" when a high-significance
-- market signal is routed to affected deals.
alter table notifications drop constraint if exists notifications_notification_type_check;
alter table notifications add constraint notifications_notification_type_check check (notification_type in (
    'deal_advancement_blocked', 'momentum_stalled', 'budget_variance',
    'daily_send_limit_reached', 'task_overdue', 'accuracy_flag_threshold', 'milestone_delay',
    'task_assigned', 'error_on_active_deal', 'refi_opportunity', 'disposition_opportunity',
    'performance_variance', 'market_signal_deal_impact'
));
