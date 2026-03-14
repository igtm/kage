import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from kage import db
from kage.compiler import get_task_source_fingerprints
from kage.config import CommandDef, GlobalConfig, ProviderConfig
from kage.main import app
from kage.parser import TaskDef
from kage.runs import format_local_timestamp, format_relative_timestamp, get_run

runner = CliRunner()


@pytest.fixture
def cli_env(tmp_path: Path, mocker):
    db_path = tmp_path / "kage.db"
    logs_dir = tmp_path / "logs"
    mocker.patch("kage.db.KAGE_DB_PATH", db_path)
    mocker.patch("kage.config.KAGE_DB_PATH", db_path)
    mocker.patch("kage.runs.KAGE_DB_PATH", db_path)
    mocker.patch("kage.config.KAGE_LOGS_DIR", logs_dir)
    mocker.patch("kage.runs.KAGE_LOGS_DIR", logs_dir)
    db.init_db()
    return {"db_path": db_path, "logs_dir": logs_dir}


def _append_event(path: Path, stream: str, text: str, ts: str | None = None):
    payload = {
        "ts": ts or datetime.now().astimezone().isoformat(),
        "stream": stream,
        "text": text,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def test_format_relative_timestamp_supports_english_and_japanese():
    now = datetime.now().astimezone()
    four_hours_ago = (now - timedelta(hours=4)).isoformat()
    two_days_future = (now + timedelta(days=2)).isoformat()

    assert format_relative_timestamp(four_hours_ago, now=now) == "4h ago"
    assert format_relative_timestamp(four_hours_ago, now=now, is_ja=True) == "4時間前"
    assert format_relative_timestamp(two_days_future, now=now) == "in 2d"
    assert format_relative_timestamp(two_days_future, now=now, is_ja=True) == "2日後"


def test_runs_cli_lists_table_with_relative_time(cli_env):
    exec_id = db.start_execution("/tmp/demo", "Nightly Research")
    start_at = datetime.now().astimezone() - timedelta(hours=4)
    finished_at = start_at + timedelta(minutes=30)
    with sqlite3.connect(cli_env["db_path"]) as conn:
        conn.execute(
            "UPDATE executions SET run_at = ?, finished_at = ? WHERE id = ?",
            (start_at.isoformat(), finished_at.isoformat(), exec_id),
        )
        conn.commit()
    db.update_execution(
        exec_id,
        "SUCCESS",
        "visible output\n",
        "",
        finished_at=finished_at.isoformat(),
        exit_code=0,
        output_summary="visible output",
    )

    result = runner.invoke(app, ["runs"], env={"COLUMNS": "160"})

    assert result.exit_code == 0
    assert "When" in result.stdout
    assert "Status" in result.stdout
    assert "Nightly Research" in result.stdout
    assert "SUCCESS" in result.stdout
    assert "4h ago" in result.stdout
    assert "30m 0s" in result.stdout
    assert exec_id[:8] not in result.stdout


def test_runs_cli_can_show_absolute_time(cli_env):
    exec_id = db.start_execution("/tmp/demo", "Nightly Research")
    start_at = datetime.now().astimezone() - timedelta(hours=4)
    finished_at = start_at + timedelta(minutes=15)
    with sqlite3.connect(cli_env["db_path"]) as conn:
        conn.execute(
            "UPDATE executions SET run_at = ?, finished_at = ? WHERE id = ?",
            (start_at.isoformat(), finished_at.isoformat(), exec_id),
        )
        conn.commit()
    db.update_execution(
        exec_id,
        "FAILED",
        "",
        "boom\n",
        finished_at=finished_at.isoformat(),
        exit_code=1,
        output_summary="boom",
    )

    result = runner.invoke(app, ["runs", "--absolute-time"], env={"COLUMNS": "160"})

    assert result.exit_code == 0
    assert format_local_timestamp(start_at.isoformat()) in result.stdout
    assert "FAILED" in result.stdout


def test_runs_cli_uses_japanese_relative_time_when_lang_is_japanese(cli_env):
    exec_id = db.start_execution("/tmp/demo", "Nightly Research")
    start_at = datetime.now().astimezone() - timedelta(hours=4)
    finished_at = start_at + timedelta(minutes=10)
    with sqlite3.connect(cli_env["db_path"]) as conn:
        conn.execute(
            "UPDATE executions SET run_at = ?, finished_at = ? WHERE id = ?",
            (start_at.isoformat(), finished_at.isoformat(), exec_id),
        )
        conn.commit()
    db.update_execution(
        exec_id,
        "SUCCESS",
        "ok\n",
        "",
        finished_at=finished_at.isoformat(),
        exit_code=0,
        output_summary="ok",
    )

    result = runner.invoke(
        app,
        ["runs"],
        env={"COLUMNS": "160", "LANG": "ja_JP.UTF-8"},
    )

    assert result.exit_code == 0
    assert "日時" in result.stdout
    assert "4時間前" in result.stdout


def test_logs_cli_reads_raw_stdout_without_cleaning(cli_env):
    exec_id = db.start_execution("/tmp/demo", "Nightly Research")
    run = get_run(exec_id)
    assert run is not None

    stdout_path = Path(run.stdout_path)
    events_path = Path(run.events_path)
    stdout_path.write_text("<thinking>secret</thinking>\nvisible\n", encoding="utf-8")
    _append_event(events_path, "stdout", "<thinking>secret</thinking>\nvisible\n")

    db.update_execution(
        exec_id,
        "SUCCESS",
        "visible\n",
        "",
        exit_code=0,
        output_summary="visible",
        stdout_bytes=len(stdout_path.read_bytes()),
    )

    result = runner.invoke(app, ["logs", "Nightly Research", "--stream", "stdout"])

    assert result.exit_code == 0
    assert "<thinking>secret</thinking>" in result.stdout
    assert "visible" in result.stdout


def test_logs_cli_without_task_merges_all_tasks_in_time_order(cli_env):
    first_id = db.start_execution("/tmp/project-a", "Nightly Research")
    first_run = get_run(first_id)
    assert first_run is not None

    second_id = db.start_execution("/tmp/project-b", "Morning Sweep")
    second_run = get_run(second_id)
    assert second_run is not None

    older_ts = (datetime.now().astimezone() - timedelta(minutes=2)).isoformat()
    newer_ts = (datetime.now().astimezone() - timedelta(minutes=1)).isoformat()
    _append_event(Path(first_run.events_path), "stdout", "alpha\n", ts=older_ts)
    _append_event(Path(second_run.events_path), "stderr", "beta\n", ts=newer_ts)

    db.update_execution(first_id, "SUCCESS", "alpha\n", "", output_summary="alpha")
    db.update_execution(second_id, "FAILED", "", "beta\n", output_summary="beta")

    result = runner.invoke(app, ["logs"], env={"COLUMNS": "160"})

    assert result.exit_code == 0
    assert "project-a/Nightly Research" in result.stdout
    assert "project-b/Morning Sweep" in result.stdout
    assert "alpha" in result.stdout
    assert "beta" in result.stdout
    assert result.stdout.index("alpha") < result.stdout.index("beta")


def test_logs_cli_requires_project_for_duplicate_task_names(cli_env):
    first = db.start_execution("/tmp/project-a", "Shared Task")
    db.update_execution(first, "SUCCESS", "a\n", "", output_summary="a")

    second = db.start_execution("/tmp/project-b", "Shared Task")
    db.update_execution(second, "SUCCESS", "b\n", "", output_summary="b")

    result = runner.invoke(app, ["logs", "Shared Task"])

    assert result.exit_code == 1
    assert "Use --project" in result.stdout


def test_logs_cli_path_requires_single_target(cli_env):
    result = runner.invoke(app, ["logs", "--path"])

    assert result.exit_code == 2
    assert "--path requires a task name or --run <exec_id>" in result.output


def test_logs_cli_accepts_follow_short_option(cli_env, mocker):
    exec_id = db.start_execution("/tmp/demo", "Nightly Research")
    db.update_execution(exec_id, "SUCCESS", "done\n", "", output_summary="done")
    follow_logs = mocker.patch("kage.main._follow_logs")

    result = runner.invoke(app, ["logs", "Nightly Research", "-f"])

    assert result.exit_code == 0
    follow_logs.assert_called_once()


def test_runs_cli_filters_connector_poll_source(cli_env):
    connector_run = db.start_execution(
        "/tmp/demo", "connector:test_discord", execution_kind="connector_poll"
    )
    db.update_execution(
        connector_run,
        "SUCCESS",
        "reply\n",
        "",
        output_summary="reply",
    )

    task_run = db.start_execution(
        "/tmp/demo", "Nightly Research", execution_kind="prompt"
    )
    db.update_execution(task_run, "SUCCESS", "done\n", "", output_summary="done")

    result = runner.invoke(app, ["runs", "--source", "connector_poll"])

    assert result.exit_code == 0
    assert "connector:test_discord" in result.stdout
    assert "Nightly Research" not in result.stdout


def test_top_level_run_requires_task_name():
    result = runner.invoke(app, ["run"])

    assert result.exit_code == 2


def test_cron_run_executes_scheduler(mocker):
    run_all = mocker.patch("kage.scheduler.run_all_scheduled_tasks")

    result = runner.invoke(app, ["cron", "run"])

    assert result.exit_code == 0
    run_all.assert_called_once_with()


def test_task_list_shows_compiled_statuses(mocker, tmp_path: Path):
    project_dir = tmp_path / "workspace" / "proj"
    task_file = project_dir / ".kage" / "tasks" / "nightly.md"
    shell_file = project_dir / ".kage" / "tasks" / "shell.md"
    task_file.parent.mkdir(parents=True)

    prompt_task = TaskDef(name="Nightly", cron="* * * * *", prompt="hello")
    shell_task = TaskDef(name="Shell", cron="* * * * *", command="echo hi")
    cfg = GlobalConfig(
        default_ai_engine="gemini",
        commands={"gemini": CommandDef(template=["gemini", "--prompt", "{prompt}"])},
        providers={"gemini": ProviderConfig(command="gemini")},
    )

    mocker.patch("kage.scheduler.get_projects", return_value=[project_dir])
    mocker.patch(
        "kage.config.get_global_config",
        side_effect=lambda workspace_dir=None: cfg,
    )
    mocker.patch(
        "kage.parser.load_project_tasks",
        return_value=[
            (task_file, SimpleNamespace(task=prompt_task)),
            (shell_file, SimpleNamespace(task=shell_task)),
        ],
    )
    mocker.patch(
        "kage.compiler.compiled_task_indicator",
        side_effect=[
            {"state": "stale", "label": "stale"},
            {"state": "n/a", "label": "-"},
        ],
    )

    result = runner.invoke(app, ["task", "list"], env={"COLUMNS": "160"})

    assert result.exit_code == 0
    assert "Nightly" in result.stdout
    assert "Shell" in result.stdout
    assert "Prompt (Compiled)" in result.stdout
    assert "gemini (Inherited)" in result.stdout
    assert "proj" in result.stdout
    assert str(project_dir) not in result.stdout


def test_doctor_reports_stale_compiled_locks(mocker, tmp_path: Path):
    global_dir = tmp_path / ".kage"
    config_path = global_dir / "config.toml"
    projects_list = global_dir / "projects.list"
    db_path = global_dir / "kage.db"
    logs_dir = global_dir / "logs"
    state_path = global_dir / "migrations" / "install_state.json"
    project_dir = tmp_path / "proj"
    task_file = project_dir / ".kage" / "tasks" / "nightly.md"

    global_dir.mkdir(parents=True)
    logs_dir.mkdir(parents=True)
    config_path.write_text("", encoding="utf-8")
    projects_list.write_text(str(project_dir) + "\n", encoding="utf-8")
    db_path.write_text("", encoding="utf-8")
    task_file.parent.mkdir(parents=True)
    task_file.write_text(
        """---
name: Nightly
cron: "* * * * *"
provider: codex
---

hello
""",
        encoding="utf-8",
    )

    cfg = GlobalConfig(
        default_ai_engine="codex",
        commands={"codex": CommandDef(template=["codex", "exec", "{prompt}"])},
        providers={"codex": ProviderConfig(command="codex")},
    )

    mocker.patch("kage.config.KAGE_GLOBAL_DIR", global_dir)
    mocker.patch("kage.config.KAGE_CONFIG_PATH", config_path)
    mocker.patch("kage.config.KAGE_PROJECTS_LIST", projects_list)
    mocker.patch("kage.config.KAGE_DB_PATH", db_path)
    mocker.patch("kage.config.KAGE_LOGS_DIR", logs_dir)
    mocker.patch(
        "kage.config.get_global_config",
        side_effect=lambda workspace_dir=None: cfg,
    )
    mocker.patch("kage.scheduler.get_projects", return_value=[project_dir])
    mocker.patch(
        "kage.migrations.runner.get_install_migration_state_path",
        return_value=state_path,
    )
    mocker.patch("kage.migrations.runner.discover_install_migrations", return_value=[])
    mocker.patch(
        "kage.compiler.compiled_task_indicator",
        return_value={
            "state": "stale",
            "label": "stale",
            "path": str(task_file.with_suffix(".lock.sh")),
            "exists": True,
            "is_fresh": False,
            "needs_compile": True,
        },
    )

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "compiled locks" in result.stdout
    assert "Nightly@proj" in result.stdout


def test_task_show_includes_prompt_hash(mocker, tmp_path: Path):
    project_dir = tmp_path / "proj"
    task_file = project_dir / ".kage" / "tasks" / "nightly.md"
    task_file.parent.mkdir(parents=True)
    task_file.write_text(
        """---
name: Nightly
cron: "* * * * *"
---

Create a report
""",
        encoding="utf-8",
    )
    task = TaskDef(name="Nightly", cron="* * * * *", prompt="Create a report")
    prompt_hash = get_task_source_fingerprints(task_file)["prompt_hash"]
    cfg = GlobalConfig(
        default_ai_engine="gemini",
        commands={"gemini": CommandDef(template=["gemini", "--prompt", "{prompt}"])},
        providers={"gemini": ProviderConfig(command="gemini")},
    )

    mocker.patch(
        "kage.main._resolve_named_task",
        return_value=(project_dir, task_file, task),
    )
    mocker.patch(
        "kage.config.get_global_config",
        side_effect=lambda workspace_dir=None: cfg,
    )

    result = runner.invoke(app, ["task", "show", "Nightly"])

    assert result.exit_code == 0
    assert "Prompt Hash" in result.stdout
    assert prompt_hash in result.stdout
