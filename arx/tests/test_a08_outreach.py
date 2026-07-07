import pytest

from arx.agents.a08_outreach import A08DailyLimitError, A08SuppressedError, A08ValidationError, run_a08
from arx.tests.fakes import FakeModelClient


def _response(**overrides):
    base = {
        "message_text": "Hi, I'm reaching out about a potential acquisition in your area. " * 2,
        "channel": "email",
        "can_spam_placeholder": "[SENDER PHYSICAL ADDRESS]",
    }
    base.update(overrides)
    return base


def test_run_a08_suppressed_contact_never_calls_model():
    fake = FakeModelClient(_response())
    with pytest.raises(A08SuppressedError):
        run_a08(
            recipient_type="seller", recipient_context={}, channel="email", deal_context=None,
            is_suppressed=True, daily_send_count_so_far=0, model_client=fake,
        )
    assert len(fake.calls) == 0


def test_run_a08_daily_limit_reached_never_calls_model():
    fake = FakeModelClient(_response())
    with pytest.raises(A08DailyLimitError):
        run_a08(
            recipient_type="broker", recipient_context={}, channel="email", deal_context=None,
            is_suppressed=False, daily_send_count_so_far=50, daily_send_limit=50, model_client=fake,
        )
    assert len(fake.calls) == 0


def test_run_a08_email_requires_can_spam_placeholder():
    bad = _response(can_spam_placeholder=None)
    fake = FakeModelClient(bad)
    with pytest.raises(A08ValidationError, match="schema validation"):
        run_a08(
            recipient_type="seller", recipient_context={}, channel="email", deal_context=None,
            is_suppressed=False, daily_send_count_so_far=0, model_client=fake,
        )


def test_run_a08_email_success_sets_checks_true():
    fake = FakeModelClient(_response())
    result = run_a08(
        recipient_type="seller", recipient_context={"seller_archetype": "distressed"}, channel="email",
        deal_context={"deal_id": "d1"}, is_suppressed=False, daily_send_count_so_far=10, model_client=fake,
    )
    assert result.output.suppression_checked is True
    assert result.output.daily_limit_checked is True
    assert len(fake.calls) == 1


def test_run_a08_sms_channel_length_limit_enforced():
    bad = _response(channel="sms", can_spam_placeholder=None, message_text="x" * 600)
    fake = FakeModelClient(bad)
    with pytest.raises(A08ValidationError, match="schema validation"):
        run_a08(
            recipient_type="broker", recipient_context={}, channel="sms", deal_context=None,
            is_suppressed=False, daily_send_count_so_far=0, model_client=fake,
        )


def test_run_a08_sms_does_not_require_can_spam():
    response = _response(channel="sms", can_spam_placeholder=None, message_text="x" * 150)
    fake = FakeModelClient(response)
    result = run_a08(
        recipient_type="broker", recipient_context={}, channel="sms", deal_context=None,
        is_suppressed=False, daily_send_count_so_far=0, model_client=fake,
    )
    assert result.output.channel == "sms"


def test_run_a08_lp_recipient_type():
    response = _response(channel="linkedin", can_spam_placeholder=None, message_text="x" * 150)
    fake = FakeModelClient(response)
    result = run_a08(
        recipient_type="lp", recipient_context={"investor_type": "family_office"}, channel="linkedin",
        deal_context={"deal_id": "d1"}, is_suppressed=False, daily_send_count_so_far=0, model_client=fake,
    )
    assert result.output.channel == "linkedin"
