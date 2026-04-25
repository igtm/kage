from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from kage.parser import TaskDef
from kage.suspension import (
    get_suspension_status,
    parse_suspension_deadline,
    parse_suspension_duration,
    suspension_deadline_from_duration,
    update_markdown_front_matter_text,
)


def test_parse_suspension_deadline_date_uses_task_timezone_midnight():
    deadline = parse_suspension_deadline("2026-05-09", tz_name="Asia/Tokyo")

    assert deadline.isoformat(timespec="seconds") == "2026-05-09T00:00:00+09:00"


def test_parse_suspension_duration_accepts_single_token_units():
    assert parse_suspension_duration("30m").total_seconds() == 30 * 60
    assert parse_suspension_duration("3h").total_seconds() == 3 * 60 * 60
    assert parse_suspension_duration("14d").days == 14
    assert parse_suspension_duration("2w").days == 14


def test_parse_suspension_duration_rejects_invalid_tokens():
    with pytest.raises(ValueError):
        parse_suspension_duration("1d 2h")

    with pytest.raises(ValueError):
        parse_suspension_duration("0d")


def test_suspension_deadline_from_duration_uses_task_timezone():
    now = datetime(2026, 4, 25, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

    deadline = suspension_deadline_from_duration(
        "2w",
        now=now,
        tz_name="Asia/Tokyo",
    )

    assert deadline.isoformat(timespec="seconds") == "2026-05-09T12:00:00+09:00"


def test_suspension_deadline_from_duration_uses_elapsed_time_across_dst():
    now = datetime(2026, 3, 7, 12, 0, tzinfo=ZoneInfo("America/New_York"))

    deadline = suspension_deadline_from_duration(
        "1d",
        now=now,
        tz_name="America/New_York",
    )

    assert deadline.isoformat(timespec="seconds") == "2026-03-08T13:00:00-04:00"
    elapsed = deadline.astimezone(ZoneInfo("UTC")) - now.astimezone(ZoneInfo("UTC"))
    assert elapsed.total_seconds() == 24 * 60 * 60


def test_get_suspension_status_fails_closed_for_invalid_deadline():
    task = TaskDef(
        name="Nightly",
        cron="* * * * *",
        prompt="hello",
        suspended_until="not-a-date",
    )

    status = get_suspension_status(task, tz_name="UTC")

    assert status.is_suspended is True
    assert status.is_invalid is True


def test_get_suspension_status_fails_closed_for_blank_deadline():
    task = TaskDef(
        name="Nightly",
        cron="* * * * *",
        prompt="hello",
        suspended_until="",
    )

    status = get_suspension_status(task, tz_name="UTC")

    assert status.is_suspended is True
    assert status.is_invalid is True


def test_update_markdown_front_matter_preserves_prompt_body():
    source = """---
name: Nightly
cron: "* * * * *"
---

# Prompt

Keep this body exactly.
"""

    updated = update_markdown_front_matter_text(
        source,
        updates={
            "suspended_until": "2026-05-09T00:00:00+09:00",
            "suspended_reason": "Vacation",
        },
    )

    assert 'suspended_until: "2026-05-09T00:00:00+09:00"' in updated
    assert 'suspended_reason: "Vacation"' in updated
    assert updated.split("---\n", 2)[2] == source.split("---\n", 2)[2]


def test_update_markdown_front_matter_removes_suspension_keys():
    source = """---
name: Nightly
cron: "* * * * *"
suspended_until: "2026-05-09T00:00:00+09:00"
suspended_reason: "Vacation"
---

hello
"""

    updated = update_markdown_front_matter_text(
        source,
        remove_keys={"suspended_until", "suspended_reason"},
    )

    assert "suspended_until" not in updated
    assert "suspended_reason" not in updated
    assert updated.endswith("\nhello\n")
