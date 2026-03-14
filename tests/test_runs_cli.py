import json
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kage import db
from kage.main import app
from kage.runs import get_run

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


def _append_event(path: Path, stream: str, text: str):
    payload = {
        "ts": datetime.now().astimezone().isoformat(),
        "stream": stream,
        "text": text,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def test_runs_cli_lists_tsv(cli_env):
    exec_id = db.start_execution("/tmp/demo", "Nightly Research")
    db.update_execution(
        exec_id,
        "SUCCESS",
        "visible output\n",
        "",
        exit_code=0,
        output_summary="visible output",
    )

    result = runner.invoke(app, ["runs"])

    assert result.exit_code == 0
    assert "Nightly Research" in result.stdout
    assert exec_id[:8] in result.stdout
    assert "\tSUCCESS\t" in result.stdout


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


def test_logs_cli_requires_project_for_duplicate_task_names(cli_env):
    first = db.start_execution("/tmp/project-a", "Shared Task")
    db.update_execution(first, "SUCCESS", "a\n", "", output_summary="a")

    second = db.start_execution("/tmp/project-b", "Shared Task")
    db.update_execution(second, "SUCCESS", "b\n", "", output_summary="b")

    result = runner.invoke(app, ["logs", "Shared Task"])

    assert result.exit_code == 1
    assert "Use --project" in result.stdout


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
