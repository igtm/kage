from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


from kage.rate_limit import (
    RateLimitInfo,
    is_model_rate_limited,
    parse_rate_limit_info,
    set_model_rate_limit_reset,
    clear_model_rate_limit_reset,
)


def _make_now(**kwargs):
    return datetime(2026, 7, 9, tzinfo=ZoneInfo("Asia/Tokyo"), **kwargs)


def test_detects_codex_usage_limit_with_relative_reset():
    now = _make_now()
    stdout = ""
    stderr = (
        "You've hit your usage limit. "
        "Upgrade to Pro or try again in 2 days 17 hours 14 minutes."
    )
    info = parse_rate_limit_info(stdout, stderr, now=now)
    assert info.is_limited is True
    assert info.reset_at is not None
    expected = now + timedelta(days=2, hours=17, minutes=14)
    assert abs(info.reset_at - expected) < timedelta(seconds=1)
    assert info.retry_after_seconds == int(
        timedelta(days=2, hours=17, minutes=14).total_seconds()
    )


def test_detects_opencode_monthly_limit():
    now = _make_now()
    stderr = (
        "monthly usage limit reached. It will reset in 7 days 10 hours. "
        "To continue using... [retrying in ~1 week attempt #1]"
    )
    info = parse_rate_limit_info("", stderr, now=now)
    assert info.is_limited is True
    expected = now + timedelta(days=7, hours=10)
    assert abs(info.reset_at - expected) < timedelta(seconds=1)


def test_detects_claude_absolute_reset():
    now = _make_now()
    stderr = "You've hit your limit. It resets Jan 29 at 1pm (Asia/Tokyo)."
    info = parse_rate_limit_info("", stderr, now=now)
    assert info.is_limited is True
    expected = datetime(2027, 1, 29, 13, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert info.reset_at == expected


def test_detects_refreshes_in_relative():
    now = _make_now()
    stderr = "Refreshes in 2 hours, 3 minutes."
    info = parse_rate_limit_info("", stderr, now=now)
    assert info.is_limited is True
    expected = now + timedelta(hours=2, minutes=3)
    assert abs(info.reset_at - expected) < timedelta(seconds=1)


def test_detects_retry_after_header():
    now = _make_now()
    stderr = "HTTP 429\nRetry-After: 123\nRate limit exceeded"
    info = parse_rate_limit_info("", stderr, now=now)
    assert info.is_limited is True
    expected = now + timedelta(seconds=123)
    assert abs(info.reset_at - expected) < timedelta(seconds=1)


def test_detects_try_again_at_time():
    now = _make_now(hour=15, minute=0)
    stderr = "You've hit your usage limit. To get more access, try again at 3:51 PM."
    info = parse_rate_limit_info("", stderr, now=now)
    assert info.is_limited is True
    expected = now.replace(hour=15, minute=51)
    assert info.reset_at == expected


def test_does_not_detect_regular_error():
    stderr = "Some random failure happened"
    info = parse_rate_limit_info("", stderr)
    assert info.is_limited is False
    assert info.reset_at is None


def test_rate_limit_state_skip_and_clear(tmp_path, monkeypatch):
    state_path = tmp_path / "rate_limit_state.json"
    monkeypatch.setattr("kage.rate_limit.RATE_LIMIT_STATE_PATH", state_path)
    now = _make_now()
    future = now + timedelta(hours=2)

    assert is_model_rate_limited("codex", "gpt-5", now=now) is False

    set_model_rate_limit_reset("codex", "gpt-5", future)
    assert is_model_rate_limited("codex", "gpt-5", now=now) is True
    assert (
        is_model_rate_limited("codex", "gpt-5", now=future + timedelta(seconds=1))
        is False
    )

    clear_model_rate_limit_reset("codex", "gpt-5")
    assert is_model_rate_limited("codex", "gpt-5", now=now) is False


def test_rate_limit_info_defaults():
    info = RateLimitInfo()
    assert info.is_limited is False
    assert info.reset_at is None
