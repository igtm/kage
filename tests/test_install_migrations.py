import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kage import db
from kage.main import app
from kage.migrations.runner import (
    get_install_migration_state_path,
    run_install_migrations,
)
from kage.runs import get_run, load_run_metadata

runner = CliRunner()


@pytest.fixture
def migration_env(tmp_path: Path, mocker):
    db_path = tmp_path / "kage.db"
    logs_dir = tmp_path / "logs"
    global_dir = tmp_path / ".kage"
    mocker.patch("kage.db.KAGE_DB_PATH", db_path)
    mocker.patch("kage.config.KAGE_DB_PATH", db_path)
    mocker.patch("kage.runs.KAGE_DB_PATH", db_path)
    mocker.patch("kage.config.KAGE_LOGS_DIR", logs_dir)
    mocker.patch("kage.runs.KAGE_LOGS_DIR", logs_dir)
    mocker.patch("kage.migrations.runner.KAGE_DB_PATH", db_path)
    mocker.patch("kage.migrations.runner.KAGE_LOGS_DIR", logs_dir)
    mocker.patch("kage.migrations.runner.KAGE_GLOBAL_DIR", global_dir)
    db.init_db()
    return {"db_path": db_path, "logs_dir": logs_dir, "global_dir": global_dir}


def _make_legacy_run(db_path: Path) -> str:
    exec_id = db.start_execution("/tmp/demo", "Legacy Task")
    db.update_execution(
        exec_id,
        "SUCCESS",
        "legacy stdout\n",
        "legacy stderr\n",
        exit_code=0,
        output_summary="legacy stdout",
    )
    run = get_run(exec_id)
    assert run is not None
    shutil.rmtree(Path(run.log_dir))

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        UPDATE executions
        SET log_dir = NULL, stdout_path = NULL, stderr_path = NULL, events_path = NULL,
            stdout_bytes = NULL, stderr_bytes = NULL, last_output_at = NULL
        WHERE id = ?
        """,
        (exec_id,),
    )
    conn.commit()
    conn.close()
    return exec_id


def test_run_install_migrations_backfills_legacy_run_logs(migration_env):
    exec_id = _make_legacy_run(migration_env["db_path"])

    results = run_install_migrations(from_version="0.4.1", to_version="0.4.3")

    assert [result.migration_id for result in results] == [
        "0001_backfill_legacy_run_logs"
    ]
    run = get_run(exec_id)
    assert run is not None
    assert Path(run.stdout_path).read_text(encoding="utf-8") == "legacy stdout\n"
    assert Path(run.stderr_path).read_text(encoding="utf-8") == "legacy stderr\n"
    events = Path(run.events_path).read_text(encoding="utf-8")
    assert '"stream": "stdout"' in events
    assert '"stream": "stderr"' in events
    metadata = load_run_metadata(exec_id)
    assert (
        metadata["legacy_backfill"]["migration_id"] == "0001_backfill_legacy_run_logs"
    )
    assert get_install_migration_state_path().exists()

    second_run = run_install_migrations(from_version="0.4.1", to_version="0.4.3")
    assert second_run == []


def test_migrate_install_cli_reports_applied_migrations(migration_env):
    _make_legacy_run(migration_env["db_path"])

    result = runner.invoke(
        app,
        [
            "migrate",
            "install",
            "--from-version",
            "0.4.1",
            "--to-version",
            "0.4.3",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload[0]["migration_id"] == "0001_backfill_legacy_run_logs"
    assert payload[0]["details"]["backfilled_runs"] == 1
