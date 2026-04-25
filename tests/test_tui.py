import asyncio

from textual.widgets import DataTable, Log
from typer.testing import CliRunner

from kage.main import app
from kage.runs import RunRecord
from kage.tui import (
    KageTuiApp,
    _format_connector_history,
    _format_task_details,
    _task_key,
)

runner = CliRunner()


def test_tui_command_invokes_start_tui(mocker):
    start_tui = mocker.patch("kage.tui.start_tui")

    result = runner.invoke(app, ["tui"])

    assert result.exit_code == 0
    start_tui.assert_called_once_with()


def test_format_task_details_includes_prompt_and_compiled_state():
    rendered = _format_task_details(
        {
            "name": "Nightly",
            "project_path": "/tmp/demo",
            "file": "/tmp/demo/.kage/tasks/nightly.md",
            "type_display": "Prompt (Compiled)",
            "provider_display": "gemini (Inherited)",
            "cron": "* * * * *",
            "active": True,
            "mode": "continuous",
            "concurrency_policy": "allow",
            "task_timezone": "UTC",
            "allowed_hours": None,
            "denied_hours": None,
            "timeout_minutes": 15,
            "compiled_state": "fresh",
            "compiled_path": "/tmp/demo/.kage/tasks/nightly.lock.sh",
            "suspension_summary": "until: 2999-01-01T00:00:00+00:00",
            "suspended_reason": "Vacation",
            "command": None,
            "prompt": "write a summary",
        },
        is_ja=False,
    )

    assert "Prompt (Compiled)" in rendered
    assert "gemini (Inherited)" in rendered
    assert "Compiled Path" in rendered
    assert "until: 2999-01-01T00:00:00+00:00" in rendered
    assert "Vacation" in rendered
    assert "write a summary" in rendered


def test_format_connector_history_includes_run_id_and_content():
    rendered = _format_connector_history(
        {"name": "discord_main", "config": {"type": "discord", "poll": True}},
        [
            {
                "timestamp": 1_700_000_000,
                "role": "assistant",
                "content": "done",
                "run_id": "12345678-0000-0000-0000-000000000000",
            }
        ],
        is_ja=False,
    )

    assert "discord_main" in rendered
    assert "assistant" in rendered
    assert "done" in rendered
    assert "[run: 12345678]" in rendered


def test_tui_left_tables_update_selection_on_cursor_move(mocker):
    tasks = [
        {
            "name": "alpha",
            "project_name": "proj-a",
            "project_path": "/tmp/proj-a",
            "file": "/tmp/proj-a/.kage/tasks/alpha.md",
            "type_display": "Prompt",
            "provider_display": "gemini (Inherited)",
            "cron": "* * * * *",
            "active": True,
            "mode": "oneshot",
            "concurrency_policy": "allow",
            "task_timezone": "UTC",
            "allowed_hours": None,
            "denied_hours": None,
            "timeout_minutes": 15,
            "compiled_state": "none",
            "compiled_path": None,
            "command": None,
            "prompt": "alpha prompt",
        },
        {
            "name": "beta",
            "project_name": "proj-b",
            "project_path": "/tmp/proj-b",
            "file": "/tmp/proj-b/.kage/tasks/beta.md",
            "type_display": "Prompt (Compiled)",
            "provider_display": "codex (Inherited)",
            "cron": "*/5 * * * *",
            "active": True,
            "mode": "oneshot",
            "concurrency_policy": "allow",
            "task_timezone": "UTC",
            "allowed_hours": None,
            "denied_hours": None,
            "timeout_minutes": 15,
            "compiled_state": "fresh",
            "compiled_path": "/tmp/proj-b/.kage/tasks/beta.lock.sh",
            "command": None,
            "prompt": "beta prompt",
        },
    ]
    runs = [
        RunRecord(
            id="run-alpha",
            project_path="/tmp/proj-a",
            task_name="alpha",
            run_at="2026-03-15T10:00:00+09:00",
            status="SUCCESS",
        ),
        RunRecord(
            id="run-beta",
            project_path="/tmp/proj-b",
            task_name="beta",
            run_at="2026-03-15T11:00:00+09:00",
            status="FAILED",
        ),
    ]
    connectors = [
        {"name": "alpha-bot", "config": {"type": "discord", "poll": True}},
        {"name": "beta-bot", "config": {"type": "slack", "poll": True}},
    ]

    mocker.patch("kage.tui.get_config_api", return_value={"tasks": tasks})
    mocker.patch("kage.tui.list_runs", return_value=runs)
    mocker.patch("kage.tui.get_connectors", return_value=connectors)
    mocker.patch("kage.tui.get_connector_history", side_effect=lambda _name: [])
    mocker.patch("kage.tui.load_all_log_text", return_value="merged logs")
    mocker.patch("kage.tui.load_log_text", return_value="run logs")

    async def exercise() -> None:
        app = KageTuiApp()
        async with app.run_test() as pilot:
            await pilot.pause()

            logs_task_table = app.query_one("#logs-task-table", DataTable)
            logs_task_table.focus()
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            assert app.selected_logs_task_key == _task_key(tasks[0])
            assert app.selected_run_id == "run-alpha"

            app.action_show_tab("tasks")
            await pilot.pause()
            tasks_table = app.query_one("#tasks-table", DataTable)
            tasks_table.focus()
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            assert app.selected_task_detail_key == _task_key(tasks[1])

            app.action_show_tab("connectors")
            await pilot.pause()
            connectors_table = app.query_one("#connectors-table", DataTable)
            connectors_table.focus()
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            assert app.selected_connector_name == "beta-bot"

    asyncio.run(exercise())


def test_tui_logs_panel_scrolls_when_focused(mocker):
    tasks = [
        {
            "name": "alpha",
            "project_name": "proj-a",
            "project_path": "/tmp/proj-a",
            "file": "/tmp/proj-a/.kage/tasks/alpha.md",
            "type_display": "Prompt",
            "provider_display": "gemini (Inherited)",
            "cron": "* * * * *",
            "active": True,
            "mode": "oneshot",
            "concurrency_policy": "allow",
            "task_timezone": "UTC",
            "allowed_hours": None,
            "denied_hours": None,
            "timeout_minutes": 15,
            "compiled_state": "none",
            "compiled_path": None,
            "command": None,
            "prompt": "alpha prompt",
        }
    ]
    runs = [
        RunRecord(
            id="run-alpha",
            project_path="/tmp/proj-a",
            task_name="alpha",
            run_at="2026-03-15T10:00:00+09:00",
            status="SUCCESS",
        )
    ]
    long_log = "\n".join(f"line {index}" for index in range(1, 200))

    mocker.patch("kage.tui.get_config_api", return_value={"tasks": tasks})
    mocker.patch("kage.tui.list_runs", return_value=runs)
    mocker.patch("kage.tui.get_connectors", return_value=[])
    mocker.patch("kage.tui.get_connector_history", side_effect=lambda _name: [])
    mocker.patch("kage.tui.load_all_log_text", return_value=long_log)
    mocker.patch("kage.tui.load_log_text", return_value=long_log)

    async def exercise() -> None:
        app = KageTuiApp()
        async with app.run_test(size=(80, 16)) as pilot:
            await pilot.pause()

            logs_widget = app.query_one("#logs-content", Log)
            logs_widget.focus()
            await pilot.pause()
            assert logs_widget.scroll_y == 0

            await pilot.press("pagedown")
            await pilot.pause()

            assert logs_widget.scroll_y > 0

    asyncio.run(exercise())
