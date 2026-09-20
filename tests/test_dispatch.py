import os
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kage import agent as agent_mod
from kage import db as db_mod
from kage import runs as runs_mod
from kage.config import AgentConfig, GlobalConfig
from kage.connector_payload import ConnectorDelivery
from kage.db import get_execution_agent, init_db, start_execution, update_execution
from kage.dispatch import DispatchError, run_dispatch_worker
from kage.main import app
from kage.runs import get_run, load_run_metadata, write_run_metadata

runner = CliRunner()


@pytest.fixture
def isolated_dispatch_db(tmp_path, monkeypatch):
    db_path = tmp_path / "kage.db"
    logs_path = tmp_path / "logs"
    monkeypatch.setattr(db_mod, "KAGE_DB_PATH", db_path)
    monkeypatch.setattr(agent_mod, "KAGE_DB_PATH", db_path)
    monkeypatch.setattr(runs_mod, "KAGE_DB_PATH", db_path)
    monkeypatch.setattr(runs_mod, "KAGE_LOGS_DIR", logs_path)
    init_db()
    return db_path


def _source_run(tmp_path: Path, *, agent: str = "public") -> str:
    run_id = start_execution(
        str(tmp_path),
        "connector:discord_public",
        working_dir=str(tmp_path),
        execution_kind="connector_realtime",
        agent_name=agent,
    )
    write_run_metadata(
        run_id,
        {"connector": {"name": "discord_public", "type": "discord"}},
    )
    return run_id


def _config(tmp_path: Path, *, connector_agent: str = "public") -> GlobalConfig:
    return GlobalConfig(
        default_agent="kage",
        agents={
            "public": AgentConfig(name="public", default_working_dir=str(tmp_path))
        },
        connectors={
            "discord_public": {
                "type": "discord",
                "agent": connector_agent,
                "bot_token": "token",
                "channel_id": "123",
            }
        },
    )


def test_dispatch_creates_same_agent_child_without_prompt_in_process_args(
    isolated_dispatch_db, tmp_path, monkeypatch, mocker
):
    source_run_id = _source_run(tmp_path)
    monkeypatch.setenv("KAGE_RUN_ID", source_run_id)
    monkeypatch.setenv("KAGE_AGENT_NAME", "tampered")
    mocker.patch("kage.config.get_global_config", return_value=_config(tmp_path))
    mocker.patch(
        "kage.connectors.realtime_manager._kage_command", return_value=["kage"]
    )
    popen = mocker.patch("kage.dispatch.subprocess.Popen")
    popen.return_value.pid = 4321

    result = runner.invoke(
        app,
        ["dispatch", "--name", "chapters", "--prompt", "long private request"],
    )

    assert result.exit_code == 0, result.output
    child_run_id = result.output.split("run ", 1)[1].split(",", 1)[0]
    assert get_execution_agent(child_run_id) == "public"
    metadata = load_run_metadata(child_run_id)
    assert metadata["dispatch"]["parent_run_id"] == source_run_id
    assert metadata["dispatch"]["request"] == "long private request"
    assert metadata["connector"]["name"] == "discord_public"
    command = popen.call_args.args[0]
    assert command == ["kage", "_dispatch-worker", child_run_id]
    assert "long private request" not in command
    assert popen.call_args.kwargs["env"]["KAGE_RUN_ID"] == source_run_id
    assert popen.call_args.kwargs["start_new_session"] is True


def test_dispatch_rejects_cross_agent_connector_binding(
    isolated_dispatch_db, tmp_path, monkeypatch, mocker
):
    source_run_id = _source_run(tmp_path)
    monkeypatch.setenv("KAGE_RUN_ID", source_run_id)
    mocker.patch(
        "kage.config.get_global_config",
        return_value=_config(tmp_path, connector_agent="private"),
    )
    popen = mocker.patch("kage.dispatch.subprocess.Popen")

    result = runner.invoke(app, ["dispatch", "--prompt", "secret"])

    assert result.exit_code == 1
    assert "not bound to source agent 'public'" in result.output
    popen.assert_not_called()


def test_dispatch_spawn_failure_marks_child_error(
    isolated_dispatch_db, tmp_path, monkeypatch, mocker
):
    source_run_id = _source_run(tmp_path)
    monkeypatch.setenv("KAGE_RUN_ID", source_run_id)
    mocker.patch("kage.config.get_global_config", return_value=_config(tmp_path))
    mocker.patch(
        "kage.connectors.realtime_manager._kage_command", return_value=["kage"]
    )
    mocker.patch(
        "kage.dispatch.subprocess.Popen", side_effect=OSError("spawn unavailable")
    )

    result = runner.invoke(app, ["dispatch", "--prompt", "work"])

    assert result.exit_code == 1
    assert "Failed to start dispatch worker" in result.output
    conn = sqlite3.connect(isolated_dispatch_db)
    try:
        row = conn.execute(
            "SELECT status, agent_name FROM executions "
            "WHERE execution_kind = 'dispatch'"
        ).fetchone()
    finally:
        conn.close()
    assert row == ("ERROR", "public")


def test_dispatch_requires_connector_scoped_source(
    isolated_dispatch_db, tmp_path, monkeypatch, mocker
):
    source_run_id = start_execution(
        str(tmp_path), "ordinary", working_dir=str(tmp_path), agent_name="public"
    )
    monkeypatch.setenv("KAGE_RUN_ID", source_run_id)
    mocker.patch("kage.config.get_global_config", return_value=_config(tmp_path))

    result = runner.invoke(app, ["dispatch", "--prompt", "secret"])

    assert result.exit_code == 1
    assert "only from an active connector run" in result.output


def test_dispatch_worker_rejects_wrong_parent_bearer(
    isolated_dispatch_db, tmp_path, monkeypatch
):
    parent_run_id = _source_run(tmp_path)
    child_run_id = start_execution(
        str(tmp_path),
        "dispatch:test",
        working_dir=str(tmp_path),
        execution_kind="dispatch",
        agent_name="public",
    )
    write_run_metadata(
        child_run_id,
        {
            "dispatch": {"parent_run_id": parent_run_id, "request": "work"},
            "connector": {"name": "discord_public", "type": "discord"},
        },
    )
    monkeypatch.setenv("KAGE_RUN_ID", "wrong-parent")

    with pytest.raises(DispatchError, match="parent-run authentication failed"):
        run_dispatch_worker(child_run_id)

    assert get_run(child_run_id).status == "RUNNING"
    assert "dispatch_error" not in load_run_metadata(child_run_id)


def test_dispatch_worker_executes_as_child_and_replies_to_source_connector(
    isolated_dispatch_db, tmp_path, monkeypatch, mocker
):
    parent_run_id = _source_run(tmp_path)
    child_run_id = start_execution(
        str(tmp_path),
        "dispatch:chapters",
        working_dir=str(tmp_path),
        execution_kind="dispatch",
        agent_name="public",
    )
    write_run_metadata(
        child_run_id,
        {
            "dispatch": {
                "parent_run_id": parent_run_id,
                "name": "chapters",
                "request": "do the long work",
            },
            "connector": {"name": "discord_public", "type": "discord"},
        },
    )
    monkeypatch.setenv("KAGE_RUN_ID", parent_run_id)
    mocker.patch("kage.config.get_global_config", return_value=_config(tmp_path))
    connector = mocker.Mock()
    connector.send_message.return_value = ConnectorDelivery(posted_message_id="42")
    mocker.patch("kage.connectors.runner.get_connector", return_value=connector)

    def complete_run(*args, **kwargs):
        update_execution(child_run_id, "SUCCESS", "finished", "", exit_code=0)
        return {
            "stdout": "finished",
            "stderr": "",
            "returncode": 0,
            "attachments": [],
        }

    generate = mocker.patch(
        "kage.ai.chat.generate_logged_chat_reply", side_effect=complete_run
    )

    run_dispatch_worker(child_run_id)

    assert generate.call_args.kwargs["existing_run_id"] == child_run_id
    assert generate.call_args.kwargs["agent_name"] == "public"
    assert "already running as a detached" in generate.call_args.kwargs["system_prompt"]
    assert os.environ["KAGE_RUN_ID"] == child_run_id
    payload = connector.send_message.call_args.args[0]
    assert payload.text == "finished"
    assert payload.run_id == child_run_id
    assert (
        load_run_metadata(child_run_id)["dispatch_delivery"]["posted_message_id"]
        == "42"
    )


def test_dispatch_child_agent_is_immutable(isolated_dispatch_db, tmp_path):
    child_run_id = start_execution(
        str(tmp_path), "dispatch:test", execution_kind="dispatch", agent_name="public"
    )
    conn = sqlite3.connect(isolated_dispatch_db)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="agent_name is immutable"):
            conn.execute(
                "UPDATE executions SET agent_name = 'private' WHERE id = ?",
                (child_run_id,),
            )
    finally:
        conn.close()


def test_dispatch_delivery_failure_marks_run_error(
    isolated_dispatch_db, tmp_path, monkeypatch, mocker
):
    parent_run_id = _source_run(tmp_path)
    child_run_id = start_execution(
        str(tmp_path),
        "dispatch:delivery",
        working_dir=str(tmp_path),
        execution_kind="dispatch",
        agent_name="public",
    )
    write_run_metadata(
        child_run_id,
        {
            "dispatch": {"parent_run_id": parent_run_id, "request": "work"},
            "connector": {"name": "discord_public", "type": "discord"},
        },
    )
    monkeypatch.setenv("KAGE_RUN_ID", parent_run_id)
    mocker.patch("kage.config.get_global_config", return_value=_config(tmp_path))

    def complete_run(*args, **kwargs):
        update_execution(child_run_id, "SUCCESS", "finished", "", exit_code=0)
        return {"stdout": "finished", "stderr": "", "attachments": []}

    mocker.patch("kage.ai.chat.generate_logged_chat_reply", side_effect=complete_run)
    connector = mocker.Mock()
    connector.send_message.side_effect = RuntimeError("delivery unavailable")
    mocker.patch("kage.connectors.runner.get_connector", return_value=connector)

    with pytest.raises(RuntimeError, match="delivery unavailable"):
        run_dispatch_worker(child_run_id)

    run = get_run(child_run_id)
    assert run.status == "ERROR"
    assert "delivery unavailable" in run.stderr
    assert load_run_metadata(child_run_id)["dispatch_error"] == "delivery unavailable"
