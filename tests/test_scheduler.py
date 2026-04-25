from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone as dt_timezone

from kage.parser import TaskDef
from kage.scheduler import run_all_scheduled_tasks


def test_scheduler_skips_current_and_invalid_suspensions(mocker, tmp_path: Path):
    project_dir = tmp_path / "proj"
    future_file = project_dir / ".kage" / "tasks" / "future.md"
    invalid_file = project_dir / ".kage" / "tasks" / "invalid.md"
    expired_file = project_dir / ".kage" / "tasks" / "expired.md"

    future_task = TaskDef(
        name="Future",
        cron="* * * * *",
        command="echo future",
        suspended_until="2999-01-01T00:00:00+00:00",
    )
    invalid_task = TaskDef(
        name="Invalid",
        cron="* * * * *",
        command="echo invalid",
        suspended_until="not-a-date",
    )
    expired_task = TaskDef(
        name="Expired",
        cron="* * * * *",
        command="echo expired",
        suspended_until="2000-01-01T00:00:00+00:00",
    )

    mocker.patch("kage.scheduler.get_projects", return_value=[project_dir])
    mocker.patch(
        "kage.scheduler.get_global_config",
        return_value=SimpleNamespace(timezone="UTC"),
    )
    mocker.patch(
        "kage.scheduler.load_project_tasks",
        return_value=[
            (future_file, SimpleNamespace(task=future_task)),
            (invalid_file, SimpleNamespace(task=invalid_task)),
            (expired_file, SimpleNamespace(task=expired_task)),
        ],
    )
    execute_task = mocker.patch("kage.scheduler.execute_task")
    mocker.patch("kage.connectors.runner.run_connectors")

    run_all_scheduled_tasks()

    execute_task.assert_called_once_with(
        project_dir,
        expired_task,
        task_file=expired_file,
    )


def test_scheduler_uses_project_timezone_for_date_only_suspension(
    mocker, tmp_path: Path
):
    project_dir = tmp_path / "proj"
    task_file = project_dir / ".kage" / "tasks" / "nightly.md"
    task = TaskDef(
        name="Nightly",
        cron="* * * * *",
        command="echo hi",
        suspended_until="2026-05-09",
    )

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            current = datetime(2026, 5, 8, 16, 0, 30, tzinfo=dt_timezone.utc)
            return current if tz is None else current.astimezone(tz)

    mocker.patch("kage.scheduler.datetime", FrozenDateTime)
    mocker.patch("kage.scheduler.get_projects", return_value=[project_dir])
    mocker.patch(
        "kage.scheduler.get_global_config",
        side_effect=lambda workspace_dir=None: SimpleNamespace(
            timezone="Asia/Tokyo" if workspace_dir else "UTC"
        ),
    )
    mocker.patch(
        "kage.scheduler.load_project_tasks",
        return_value=[(task_file, SimpleNamespace(task=task))],
    )
    execute_task = mocker.patch("kage.scheduler.execute_task")
    mocker.patch("kage.connectors.runner.run_connectors")

    run_all_scheduled_tasks()

    execute_task.assert_called_once_with(project_dir, task, task_file=task_file)
