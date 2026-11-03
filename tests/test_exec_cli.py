import signal
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kage import db
from kage.config import AgentConfig, CommandDef, GlobalConfig, ProviderConfig
from kage.executor import run_logged_command
from kage.main import app
from kage.runs import get_run, list_runs, load_run_metadata

runner = CliRunner()


@pytest.fixture
def exec_env(tmp_path, monkeypatch, mocker):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("KAGE_RUN_ID", raising=False)
    monkeypatch.delenv("KAGE_AGENT_NAME", raising=False)
    for module in ("db", "config", "runs", "agent"):
        mocker.patch(f"kage.{module}.KAGE_DB_PATH", tmp_path / "kage.db")
    mocker.patch("kage.runs.KAGE_LOGS_DIR", tmp_path / "logs")
    mocker.patch("kage.executor.KAGE_GLOBAL_DIR", tmp_path / "global")
    mocker.patch("kage.rate_limit.RATE_LIMIT_STATE_PATH", tmp_path / "limits.json")
    mocker.patch("kage.memory.build_memory_headings_xml", return_value="")
    script = (
        "import os, sys; "
        "assert '指示内容' in sys.argv[1]; "
        "assert os.environ['KAGE_RUN_ID']; "
        "print('<final>回答本文</final>'); "
        "print('provider diagnostic', file=sys.stderr)"
    )
    cfg = GlobalConfig(
        default_ai_engine="fake",
        commands={
            "fake": CommandDef(template=[sys.executable, "-c", script, "{prompt}"])
        },
        providers={"fake": ProviderConfig(command="fake")},
    )
    mocker.patch("kage.executor.get_global_config", return_value=cfg)
    db.init_db()
    return cfg


def test_exec_runs_without_task_file_and_keeps_logs(exec_env, tmp_path):
    result = runner.invoke(app, ["exec", "-p", "指示内容"])

    assert result.exit_code == 0, result.output
    assert result.stdout == "回答本文\n"
    assert "Run: " in result.stderr
    assert "provider diagnostic" in result.stderr
    assert not (tmp_path / ".kage").exists()
    runs = list_runs()
    assert len(runs) == 1
    record = runs[0]
    assert record.status == "SUCCESS"
    assert record.execution_kind == "prompt"
    assert record.project_path == str(tmp_path)
    assert record.working_dir == str(tmp_path)
    assert record.provider_name == "fake"
    assert load_run_metadata(record)["prompt"] == "指示内容"
    assert db.get_execution_agent(record.id) == "kage"
    assert record.pid is None
    assert "<final>回答本文</final>" in Path(record.stdout_path).read_text()
    assert not list((tmp_path / "global" / "locks").glob("*.lock"))
    shown = runner.invoke(app, ["runs", "show", record.id])
    assert shown.exit_code == 0
    assert record.id in shown.output


def test_exec_uses_project_agent_and_its_provider(exec_env, tmp_path):
    exec_env.agents["dev"] = AgentConfig(
        name="dev", default_working_dir=str(tmp_path), provider="fake"
    )
    exec_env.default_ai_engine = None

    result = runner.invoke(app, ["exec", "--prompt", "指示内容"])

    assert result.exit_code == 0, result.output
    assert db.get_execution_agent(list_runs()[0].id) == "dev"


def test_exec_uses_configured_default_agent(exec_env):
    exec_env.agents["default"] = AgentConfig(name="default")
    exec_env.default_agent = "default"

    result = runner.invoke(app, ["exec", "-p", "指示内容"])

    assert result.exit_code == 0, result.output
    assert db.get_execution_agent(list_runs()[0].id) == "default"


def test_exec_provider_failure_is_nonzero(exec_env):
    exec_env.commands["fake"].template = [
        sys.executable,
        "-c",
        "import sys; print('provider failed', file=sys.stderr); sys.exit(7)",
    ]

    result = runner.invoke(app, ["exec", "-p", "指示内容"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "provider failed" in result.stderr
    record = list_runs()[0]
    assert record.status == "FAILED"
    assert record.exit_code == 7


def test_exec_missing_engine_is_nonzero(exec_env):
    exec_env.default_ai_engine = None

    result = runner.invoke(app, ["exec", "-p", "指示内容"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "did not start" in result.stderr


def test_exec_missing_executable_is_recorded(exec_env):
    exec_env.commands["fake"].template = ["/nonexistent/kage-test-provider", "{prompt}"]

    result = runner.invoke(app, ["exec", "-p", "指示内容"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "nonexistent" in result.stderr
    assert list_runs()[0].status == "ERROR"


@pytest.mark.parametrize("args", [["exec"], ["exec", "-p", "  "]])
def test_exec_requires_nonempty_prompt(exec_env, args):
    result = runner.invoke(app, args)

    assert result.exit_code == 2
    assert list_runs() == []


def test_exec_rejects_agent_run(exec_env, monkeypatch):
    parent = db.start_execution("/parent", "parent", agent_name="dev")
    monkeypatch.setenv("KAGE_RUN_ID", parent)

    result = runner.invoke(app, ["exec", "-p", "指示内容"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "human shell" in result.stderr
    assert len(list_runs()) == 1


def test_exec_interrupt_stops_run(exec_env, mocker):
    mocker.patch("kage.executor.run_logged_command", side_effect=KeyboardInterrupt)

    result = runner.invoke(app, ["exec", "-p", "指示内容"])

    assert result.exit_code == 130
    assert result.stdout == ""
    record = list_runs()[0]
    assert record.status == "STOPPED"
    assert record.exit_code == 130
    assert record.pid is None


@pytest.mark.parametrize("needs_kill", [False, True])
def test_logged_command_interrupt_terminates_process_group(
    exec_env, tmp_path, mocker, needs_kill
):
    run_id = db.start_execution(str(tmp_path), "interrupt", agent_name="kage")
    proc = mocker.Mock(pid=12345)
    proc.wait.side_effect = (
        [KeyboardInterrupt(), subprocess.TimeoutExpired("fake", 1), -9]
        if needs_kill
        else [KeyboardInterrupt(), -15]
    )
    mocker.patch("kage.executor.subprocess.Popen", return_value=proc)
    mocker.patch("kage.executor._stream_process_output", return_value={"threads": []})
    mocker.patch("kage.executor.os.getpgid", return_value=12345)
    killpg = mocker.patch("kage.executor.os.killpg")

    with pytest.raises(KeyboardInterrupt):
        run_logged_command(["fake"], tmp_path, {}, run_id)

    assert killpg.call_args_list[0] == mocker.call(12345, signal.SIGTERM)
    if needs_kill:
        assert killpg.call_args_list[1] == mocker.call(12345, signal.SIGKILL)
    assert get_run(run_id).pid == 12345
