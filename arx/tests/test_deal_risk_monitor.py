from arx.agents.deal_risk_monitor import (
    cap_rate_repricing_risk,
    construction_budget_variance_risk,
    construction_draw_approaching_limit_risk,
    dd_deadline_with_open_flags_risk,
    dscr_breach_risk,
    schedule_delay_risk,
    seller_distress_escalation_risk,
)


def test_dscr_breach_risk_hard_fail_is_critical():
    flag = dscr_breach_risk(dscr_hard_fail=True, dscr_warning=True, dscr=0.9)
    assert flag.risk_type == "dscr_breach"
    assert flag.severity == "critical"


def test_dscr_breach_risk_warning_only():
    flag = dscr_breach_risk(dscr_hard_fail=False, dscr_warning=True, dscr=1.10)
    assert flag.severity == "warning"


def test_dscr_breach_risk_healthy_returns_none():
    assert dscr_breach_risk(dscr_hard_fail=False, dscr_warning=False, dscr=1.4) is None


def test_cap_rate_repricing_flags_when_market_widens():
    flag = cap_rate_repricing_risk(acquisition_cap_rate=0.055, current_market_cap_rate=0.065)
    assert flag is not None
    assert flag.risk_type == "cap_rate_repricing"


def test_cap_rate_repricing_no_flag_below_threshold():
    assert cap_rate_repricing_risk(acquisition_cap_rate=0.055, current_market_cap_rate=0.057) is None


def test_dd_deadline_requires_both_open_flags_and_elapsed_time():
    assert dd_deadline_with_open_flags_risk(days_in_due_diligence=45, open_flagged_task_count=0) is None
    assert dd_deadline_with_open_flags_risk(days_in_due_diligence=5, open_flagged_task_count=2) is None
    flag = dd_deadline_with_open_flags_risk(days_in_due_diligence=45, open_flagged_task_count=2)
    assert flag is not None and flag.severity == "critical"


def test_seller_distress_escalation_requires_score_and_indicators():
    assert seller_distress_escalation_risk(motivated_seller_score=90, distress_indicators=[]) is None
    assert seller_distress_escalation_risk(motivated_seller_score=40, distress_indicators=["divorce"]) is None
    flag = seller_distress_escalation_risk(motivated_seller_score=80, distress_indicators=["divorce"])
    assert flag is not None


def test_construction_budget_variance_flags_over_threshold():
    assert construction_budget_variance_risk(total_budget=1_000_000, total_variance=50_000) is None
    flag = construction_budget_variance_risk(total_budget=1_000_000, total_variance=150_000)
    assert flag is not None and flag.risk_type == "budget_variance"


def test_schedule_delay_flags_delayed_milestones():
    assert schedule_delay_risk(delayed_milestones=[]) is None
    flag = schedule_delay_risk(delayed_milestones=[{"milestone_type": "construction_start"}])
    assert flag is not None
    assert "construction_start" in flag.detail


def test_construction_draw_approaching_limit():
    assert construction_draw_approaching_limit_risk(total_committed=1_000_000, total_drawn=500_000) is None
    flag = construction_draw_approaching_limit_risk(total_committed=1_000_000, total_drawn=950_000)
    assert flag is not None
