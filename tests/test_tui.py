from typer.testing import CliRunner

from kage.main import app
from kage.tui import _format_connector_history, _format_task_details

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
            "command": None,
            "prompt": "write a summary",
        },
        is_ja=False,
    )

    assert "Prompt (Compiled)" in rendered
    assert "gemini (Inherited)" in rendered
    assert "Compiled Path" in rendered
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
