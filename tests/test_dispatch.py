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
from kage.db import (
    get_execution_agent,
    init_db,
    resume_execution,
    start_execution,
    update_execution,
)
from kage.dispatch import DispatchError, run_dispatch_worker
from kage.main import app
from kage.runs import get_run, load_run_metadata, write_run_metadata

runner = CliRunner()

AGY_TIMEOUT = (
    "[agy] print timeout after 15m0s with turn in progress; returning partial output\n"
    'AGY_ERROR: {"status":"DEADLINE_EXCEEDED","retryable":false,'
    '"reason":"print_timeout"}\n'
)


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
        output = "finished\n[KAGE_DISPATCH_STATUS: COMPLETE]"
        update_execution(child_run_id, "SUCCESS", output, "", exit_code=0)
        return {
            "stdout": output,
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
    assert "do not leave sub-agents" in generate.call_args.kwargs["system_prompt"]
    assert (
        "Do not return an interim progress report"
        in generate.call_args.kwargs["system_prompt"]
    )
    assert os.environ["KAGE_RUN_ID"] == child_run_id
    payload = connector.send_message.call_args.args[0]
    assert payload.text == "finished"
    assert payload.run_id == child_run_id
    assert (
        load_run_metadata(child_run_id)["dispatch_delivery"]["posted_message_id"]
        == "42"
    )


def test_dispatch_worker_rejects_success_with_abandoned_background_tasks(
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
                "request": "finish the long work",
            },
            "connector": {"name": "discord_public", "type": "discord"},
        },
    )
    monkeypatch.setenv("KAGE_RUN_ID", parent_run_id)
    mocker.patch("kage.config.get_global_config", return_value=_config(tmp_path))
    connector = mocker.Mock()
    connector.send_message.return_value = ConnectorDelivery(posted_message_id="43")
    mocker.patch("kage.connectors.runner.get_connector", return_value=connector)

    provider_stderr = (
        "root agent idle; waiting up to 5s for 2 background task(s)\n"
        "terminating 2 background task(s) on exit\n"
    )

    def incomplete_run(*args, **kwargs):
        update_execution(
            child_run_id,
            "SUCCESS",
            "still processing",
            provider_stderr,
            exit_code=0,
        )
        return {
            "stdout": "still processing",
            "stderr": provider_stderr,
            "returncode": 0,
            "attachments": [],
        }

    mocker.patch("kage.ai.chat.generate_logged_chat_reply", side_effect=incomplete_run)

    run_dispatch_worker(child_run_id)

    run = get_run(child_run_id)
    assert run.status == "ERROR"
    assert "remained incomplete after 3 provider turns" in run.stderr
    metadata = load_run_metadata(child_run_id)
    assert "remained incomplete after 3 provider turns" in metadata["dispatch_error"]
    assert len(metadata["dispatch_continuations"]) == 3
    payload = connector.send_message.call_args.args[0]
    assert "ended with ERROR" in payload.text
    assert "remained incomplete after 3 provider turns" in payload.text
    assert "still processing" in payload.text


def test_dispatch_worker_continues_pending_remote_work_in_same_run(
    isolated_dispatch_db, tmp_path, monkeypatch, mocker
):
    parent_run_id = _source_run(tmp_path)
    child_run_id = start_execution(
        str(tmp_path),
        "dispatch:remote",
        working_dir=str(tmp_path),
        execution_kind="dispatch",
        agent_name="public",
    )
    write_run_metadata(
        child_run_id,
        {
            "dispatch": {
                "parent_run_id": parent_run_id,
                "request": "wait for remote operation op-123",
            },
            "connector": {"name": "discord_public", "type": "discord"},
        },
    )
    monkeypatch.setenv("KAGE_RUN_ID", parent_run_id)
    mocker.patch("kage.config.get_global_config", return_value=_config(tmp_path))
    connector = mocker.Mock()
    connector.send_message.return_value = ConnectorDelivery(posted_message_id="44")
    mocker.patch("kage.connectors.runner.get_connector", return_value=connector)

    outputs = [
        "Operation op-123 is still running.\n[KAGE_DISPATCH_STATUS: CONTINUE]",
        (
            "Operation op-123 completed and all files were applied.\n"
            "[KAGE_DISPATCH_STATUS: COMPLETE]"
        ),
    ]

    def provider_turn(message, *args, **kwargs):
        output = outputs.pop(0)
        update_execution(child_run_id, "SUCCESS", output, "", exit_code=0)
        return {
            "stdout": output,
            "stderr": "",
            "returncode": 0,
            "attachments": [],
        }

    generate = mocker.patch(
        "kage.ai.chat.generate_logged_chat_reply", side_effect=provider_turn
    )

    run_dispatch_worker(child_run_id)

    assert generate.call_count == 2
    continuation_prompt = generate.call_args_list[1].args[0]
    assert "op-123" in continuation_prompt
    assert "reuse it instead of starting duplicate work" in continuation_prompt
    run = get_run(child_run_id)
    assert run.status == "SUCCESS"
    assert run.stdout == "Operation op-123 completed and all files were applied."
    metadata = load_run_metadata(child_run_id)
    assert metadata["dispatch_continuations"] == [
        {"turn": 1, "reason": "provider reported pending work"}
    ]
    payload = connector.send_message.call_args.args[0]
    assert payload.text == "Operation op-123 completed and all files were applied."


@pytest.mark.parametrize(
    "provider,code,error,initial_status,exhaust,expected_status,turns",
    [
        ("antigravity", 3, AGY_TIMEOUT, "FAILED", False, "SUCCESS", 2),
        ("antigravity", 3, AGY_TIMEOUT, "FAILED", True, "ERROR", 3),
        ("antigravity", 3, AGY_TIMEOUT, "STOPPED", False, "STOPPED", 1),
        ("codex", 3, AGY_TIMEOUT, "FAILED", False, "FAILED", 1),
        ("antigravity", 1, AGY_TIMEOUT, "FAILED", False, "FAILED", 1),
        ("antigravity", 3, "authentication failed", "FAILED", False, "FAILED", 1),
        ("antigravity", 3, "AGY_ERROR: {broken", "FAILED", False, "FAILED", 1),
        ("antigravity", 3, "AGY_ERROR: []", "FAILED", False, "FAILED", 1),
        (
            "antigravity",
            3,
            'AGY_ERROR: {"status":"DEADLINE_EXCEEDED","reason":"api_timeout"}',
            "FAILED",
            False,
            "FAILED",
            1,
        ),
    ],
)
def test_dispatch_handles_partial_print_timeout(
    isolated_dispatch_db,
    tmp_path,
    monkeypatch,
    mocker,
    provider,
    code,
    error,
    initial_status,
    exhaust,
    expected_status,
    turns,
):
    parent_run_id = _source_run(tmp_path)
    child_run_id = start_execution(
        str(tmp_path),
        "dispatch:timeout",
        working_dir=str(tmp_path),
        execution_kind="dispatch",
        provider_name=provider,
        agent_name="public",
    )
    write_run_metadata(
        child_run_id,
        {
            "dispatch": {"parent_run_id": parent_run_id, "request": "finish op-123"},
            "connector": {"name": "discord_public", "type": "discord"},
        },
    )
    monkeypatch.setenv("KAGE_RUN_ID", parent_run_id)
    mocker.patch("kage.config.get_global_config", return_value=_config(tmp_path))
    connector = mocker.Mock()
    connector.send_message.return_value = ConnectorDelivery(posted_message_id="42")
    mocker.patch("kage.connectors.runner.get_connector", return_value=connector)
    calls = []

    def provider_turn(message, **kwargs):
        assert get_run(child_run_id).status == "RUNNING"
        calls.append(message)
        if len(calls) == 1 or exhaust:
            # Even a COMPLETE marker cannot turn a timeout into success.
            output = "Polling op-123.\n[KAGE_DISPATCH_STATUS: COMPLETE]"
            status, returncode, stderr = initial_status, code, error
        else:
            output = "All files applied.\n[KAGE_DISPATCH_STATUS: COMPLETE]"
            status, returncode, stderr = "SUCCESS", 0, ""
        update_execution(child_run_id, status, output, stderr, exit_code=returncode)
        return {"stdout": output, "stderr": stderr, "returncode": returncode}

    generate = mocker.patch(
        "kage.ai.chat.generate_logged_chat_reply", side_effect=provider_turn
    )
    run_dispatch_worker(child_run_id)

    assert len(calls) == turns
    run = get_run(child_run_id)
    assert run.status == expected_status
    assert connector.send_message.call_count == 1
    if turns > 1:
        assert "op-123" in calls[1]
        assert "Read your saved checkpoint" in calls[1]
        instructions = generate.call_args.kwargs["system_prompt"]
        assert f".kage/tmp/dispatch-{child_run_id}.md" in instructions
        assert "at most 30 seconds" in instructions
        assert "before 10 minutes" in instructions
        assert (
            "print timeout"
            in load_run_metadata(child_run_id)["dispatch_continuations"][0]["reason"]
        )
    if exhaust:
        assert "incomplete after 3 provider turns" in run.stderr
        assert run.exit_code == 3
    if expected_status == "SUCCESS":
        assert run.exit_code == 0
        assert connector.send_message.call_args.args[0].text == "All files applied."


@pytest.mark.parametrize("status", ["RUNNING", "STOPPED", "ERROR", "FAILED"])
def test_resume_dispatch_requires_expected_status(
    isolated_dispatch_db, tmp_path, status
):
    run_id = start_execution(str(tmp_path), "dispatch:test", execution_kind="dispatch")
    update_execution(run_id, status, "", "")
    assert not resume_execution(run_id)
    assert resume_execution(run_id, expected_status="FAILED") == (status == "FAILED")
    assert get_run(run_id).status == ("RUNNING" if status == "FAILED" else status)


def test_dispatch_worker_rejects_complete_marker_with_unresolved_work(
    isolated_dispatch_db, tmp_path, monkeypatch, mocker
):
    parent_run_id = _source_run(tmp_path)
    child_run_id = start_execution(
        str(tmp_path),
        "dispatch:contradiction",
        working_dir=str(tmp_path),
        execution_kind="dispatch",
        agent_name="public",
    )
    write_run_metadata(
        child_run_id,
        {
            "dispatch": {
                "parent_run_id": parent_run_id,
                "request": "finish every chunk",
            },
            "connector": {"name": "discord_public", "type": "discord"},
        },
    )
    monkeypatch.setenv("KAGE_RUN_ID", parent_run_id)
    mocker.patch("kage.config.get_global_config", return_value=_config(tmp_path))
    connector = mocker.Mock()
    connector.send_message.return_value = ConnectorDelivery(posted_message_id="45")
    mocker.patch("kage.connectors.runner.get_connector", return_value=connector)

    outputs = [
        (
            "14件は完了しましたが、chunk_006はまだ処理中で、追記が必要です。\n"
            "[KAGE_DISPATCH_STATUS: COMPLETE]"
        ),
        (
            "chunk_006を含む全成果物の反映が完了しました。\n"
            "[KAGE_DISPATCH_STATUS: COMPLETE]"
        ),
    ]

    def provider_turn(*args, **kwargs):
        output = outputs.pop(0)
        update_execution(child_run_id, "SUCCESS", output, "", exit_code=0)
        return {
            "stdout": output,
            "stderr": "",
            "returncode": 0,
            "attachments": [],
        }

    generate = mocker.patch(
        "kage.ai.chat.generate_logged_chat_reply", side_effect=provider_turn
    )

    run_dispatch_worker(child_run_id)

    assert generate.call_count == 2
    metadata = load_run_metadata(child_run_id)
    assert (
        "described unresolved work" in metadata["dispatch_continuations"][0]["reason"]
    )
    assert get_run(child_run_id).status == "SUCCESS"
    assert (
        "全成果物の反映が完了しました" in connector.send_message.call_args.args[0].text
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
        output = "finished\n[KAGE_DISPATCH_STATUS: COMPLETE]"
        update_execution(child_run_id, "SUCCESS", output, "", exit_code=0)
        return {"stdout": output, "stderr": "", "attachments": []}

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
