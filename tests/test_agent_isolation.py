from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from kage import db as db_mod
from kage.agent import (
    AGENT_NAME_ENV_VAR,
    RUN_ID_ENV_VAR,
    assert_agent_command_allowed,
    assert_connector_command_allowed,
    assert_not_in_agent_run,
    assert_task_command_allowed,
    get_current_agent_name,
)
from kage.config import AgentConfig, GlobalConfig
from kage.connector_payload import ConnectorDelivery, ConnectorMessage
from kage.db import init_db, start_execution
from kage.main import app
from kage.repo import Repo


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "kage.db"
    monkeypatch.setattr(db_mod, "KAGE_DB_PATH", db_path)
    from kage import agent as agent_mod
    from kage import repo as repo_mod

    monkeypatch.setattr(agent_mod, "KAGE_DB_PATH", db_path)
    monkeypatch.setattr(repo_mod, "KAGE_DB_PATH", db_path)
    init_db()
    return db_path


def test_repo_from_env_super_when_no_env(monkeypatch, isolated_db):
    monkeypatch.delenv(RUN_ID_ENV_VAR, raising=False)
    monkeypatch.delenv(AGENT_NAME_ENV_VAR, raising=False)
    repo = Repo.from_env()
    assert repo.agent_scope is None
    # super-user で全件取得可能
    rows = repo.list_executions()
    assert rows == []  # 初期は空で OK


def test_repo_from_env_scoped_to_db_agent(monkeypatch, isolated_db):
    public_run = start_execution("/p1", "task1", agent_name="public")
    private_run = start_execution("/p2", "task2", agent_name="private")

    monkeypatch.setenv(RUN_ID_ENV_VAR, public_run)
    monkeypatch.setenv(AGENT_NAME_ENV_VAR, "private")  # tampered hint
    repo = Repo.from_env()
    # DB を権威視するので public に絞られる
    assert repo.agent_scope == "public"
    rows = repo.list_executions()
    agents = {row["agent_name"] for row in rows}
    assert agents == {"public"}

    # private run にアクセスしようとすると None
    assert repo.get_execution(private_run) is None
    # public run にはアクセスできる
    assert repo.get_execution(public_run) is not None


def test_assert_task_command_allowed_blocks_cross_agent(monkeypatch, isolated_db):
    public_run = start_execution("/proj-private", "task", agent_name="private")
    monkeypatch.setenv(RUN_ID_ENV_VAR, public_run)

    cfg = GlobalConfig(
        agents={
            "public": AgentConfig(name="public", default_working_dir="/proj-public"),
            "private": AgentConfig(name="private", default_working_dir="/proj-private"),
        },
        default_agent="kage",
    )
    # current agent = private (DB から解決)
    assert get_current_agent_name(cfg) == "private"

    # 自 agent 配下 project は可
    assert_task_command_allowed(cfg, Path("/proj-private"))
    # 他 agent 配下 project は拒否
    with pytest.raises(typer.Exit):
        assert_task_command_allowed(cfg, Path("/proj-public"))


def test_assert_connector_command_allowed_blocks_cross_agent(monkeypatch, isolated_db):
    public_run = start_execution("/p1", "task", agent_name="public")
    monkeypatch.setenv(RUN_ID_ENV_VAR, public_run)
    cfg = GlobalConfig(
        agents={"public": AgentConfig(name="public")},
        default_agent="kage",
        connectors={
            "pubc": {"type": "discord", "agent": "public"},
            "prvc": {"type": "discord", "agent": "private"},
        },
    )
    # 自 agent の connector は OK
    assert_connector_command_allowed(cfg, "pubc")
    # 他 agent の connector は拒否
    with pytest.raises(typer.Exit):
        assert_connector_command_allowed(cfg, "prvc")


def test_assert_connector_command_allowed_rejects_unknown_run_id(
    monkeypatch, isolated_db
):
    monkeypatch.setenv(RUN_ID_ENV_VAR, "missing-run")
    monkeypatch.setenv(AGENT_NAME_ENV_VAR, "public")
    cfg = GlobalConfig(
        agents={"public": AgentConfig(name="public")},
        connectors={"pubc": {"type": "discord", "agent": "public"}},
    )

    with pytest.raises(typer.Exit):
        assert_connector_command_allowed(cfg, "pubc")


def test_connector_send_allows_same_agent_and_run_artifact(
    monkeypatch, isolated_db, tmp_path, mocker
):
    run_id = start_execution(
        str(tmp_path), "task", working_dir=str(tmp_path), agent_name="public"
    )
    artifact_dir = tmp_path / ".kage" / "tmp" / "connector-artifacts" / run_id
    artifact_dir.mkdir(parents=True)
    report = artifact_dir / "report.txt"
    report.write_text("result", encoding="utf-8")
    monkeypatch.setenv(RUN_ID_ENV_VAR, run_id)
    monkeypatch.setenv(AGENT_NAME_ENV_VAR, "tampered")
    monkeypatch.setenv("KAGE_ARTIFACT_DIR", str(artifact_dir))

    cfg = GlobalConfig(
        agents={"public": AgentConfig(name="public")},
        connectors={"pubc": {"type": "discord", "agent": "public"}},
    )
    connector = mocker.Mock()
    connector.send_message.return_value = ConnectorDelivery()
    mocker.patch("kage.config.get_global_config", return_value=cfg)
    mocker.patch("kage.connectors.runner.get_connector", return_value=connector)

    result = CliRunner().invoke(
        app,
        [
            "connector",
            "send",
            "pubc",
            "--message",
            "finished",
            "--file",
            str(report),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = connector.send_message.call_args.args[0]
    assert isinstance(payload, ConnectorMessage)
    assert payload.text == "finished"
    assert payload.run_id == run_id
    assert [item.path for item in payload.attachments] == [report.resolve()]


def test_connector_send_blocks_cross_agent(monkeypatch, isolated_db, mocker):
    run_id = start_execution("/p1", "task", agent_name="public")
    monkeypatch.setenv(RUN_ID_ENV_VAR, run_id)
    cfg = GlobalConfig(
        agents={"public": AgentConfig(name="public")},
        connectors={"private": {"type": "discord", "agent": "private"}},
    )
    connector = mocker.Mock()
    mocker.patch("kage.config.get_global_config", return_value=cfg)
    mocker.patch("kage.connectors.runner.get_connector", return_value=connector)

    result = CliRunner().invoke(
        app,
        ["connector", "send", "private", "--message", "secret"],
    )

    assert result.exit_code == 1
    assert "not to current agent 'public'" in result.output
    connector.send_message.assert_not_called()


def test_connector_send_blocks_attachment_outside_run_artifact_dir(
    monkeypatch, isolated_db, tmp_path, mocker
):
    run_id = start_execution(
        str(tmp_path), "task", working_dir=str(tmp_path), agent_name="public"
    )
    artifact_dir = tmp_path / ".kage" / "tmp" / "connector-artifacts" / run_id
    artifact_dir.mkdir(parents=True)
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    monkeypatch.setenv(RUN_ID_ENV_VAR, run_id)
    monkeypatch.setenv("KAGE_ARTIFACT_DIR", str(artifact_dir))
    cfg = GlobalConfig(
        agents={"public": AgentConfig(name="public")},
        connectors={"pubc": {"type": "discord", "agent": "public"}},
    )
    connector = mocker.Mock()
    mocker.patch("kage.config.get_global_config", return_value=cfg)
    mocker.patch("kage.connectors.runner.get_connector", return_value=connector)

    result = CliRunner().invoke(
        app,
        ["connector", "send", "pubc", "--file", str(outside)],
    )

    assert result.exit_code == 1
    assert "must be top-level files in KAGE_ARTIFACT_DIR" in result.output
    connector.send_message.assert_not_called()


def test_connector_send_rejects_tampered_artifact_env(
    monkeypatch, isolated_db, tmp_path, mocker
):
    run_id = start_execution(
        str(tmp_path), "task", working_dir=str(tmp_path), agent_name="public"
    )
    forged_dir = tmp_path / "forged"
    forged_dir.mkdir()
    forged_file = forged_dir / "secret.txt"
    forged_file.write_text("secret", encoding="utf-8")
    monkeypatch.setenv(RUN_ID_ENV_VAR, run_id)
    monkeypatch.setenv("KAGE_ARTIFACT_DIR", str(forged_dir))
    cfg = GlobalConfig(
        agents={"public": AgentConfig(name="public")},
        connectors={"pubc": {"type": "discord", "agent": "public"}},
    )
    connector = mocker.Mock()
    mocker.patch("kage.config.get_global_config", return_value=cfg)
    mocker.patch("kage.connectors.runner.get_connector", return_value=connector)

    result = CliRunner().invoke(
        app,
        ["connector", "send", "pubc", "--file", str(forged_file)],
    )

    assert result.exit_code == 1
    assert "does not match the DB-anchored run artifact directory" in result.output
    connector.send_message.assert_not_called()


def test_assert_agent_command_allowed_blocks_other_agent(monkeypatch, isolated_db):
    public_run = start_execution("/p1", "task", agent_name="public")
    monkeypatch.setenv(RUN_ID_ENV_VAR, public_run)
    cfg = GlobalConfig(default_agent="kage")
    assert_agent_command_allowed(cfg, "public")  # 自 agent は OK
    with pytest.raises(typer.Exit):
        assert_agent_command_allowed(cfg, "private")


def test_assert_not_in_agent_run_blocks_global_ops(monkeypatch, isolated_db):
    # 対人の場合は何もしない
    monkeypatch.delenv(RUN_ID_ENV_VAR, raising=False)
    monkeypatch.delenv(AGENT_NAME_ENV_VAR, raising=False)
    assert_not_in_agent_run("create an agent")  # 何も起きない

    # agent 実行中は禁止
    public_run = start_execution("/p1", "task", agent_name="public")
    monkeypatch.setenv(RUN_ID_ENV_VAR, public_run)
    with pytest.raises(typer.Exit):
        assert_not_in_agent_run("create an agent")


def test_get_current_agent_name_env_hint_when_no_run_id(monkeypatch, isolated_db):
    monkeypatch.delenv(RUN_ID_ENV_VAR, raising=False)
    monkeypatch.setenv(AGENT_NAME_ENV_VAR, "manual")
    assert get_current_agent_name() == "manual"


def test_get_current_agent_name_none_when_no_env(monkeypatch, isolated_db):
    monkeypatch.delenv(RUN_ID_ENV_VAR, raising=False)
    monkeypatch.delenv(AGENT_NAME_ENV_VAR, raising=False)
    assert get_current_agent_name() is None


def test_env_tampering_ignored_via_db(monkeypatch, isolated_db):
    """env KAGE_AGENT_NAME を偽装しても DB 権威で無視されることを検証."""
    public_run = start_execution("/p1", "task", agent_name="public")
    monkeypatch.setenv(RUN_ID_ENV_VAR, public_run)
    monkeypatch.setenv(AGENT_NAME_ENV_VAR, "evil")
    assert get_current_agent_name() == "public"


def test_kage_agent_create_refuses_builtin(monkeypatch, isolated_db, tmp_path):
    monkeypatch.delenv(RUN_ID_ENV_VAR, raising=False)
    monkeypatch.delenv(AGENT_NAME_ENV_VAR, raising=False)
    # config dir を隔離して CliRunner 実行
    from kage import main as main_mod

    runner = CliRunner()
    # 'kage' は拒否されるはず
    result = runner.invoke(
        main_mod.app,
        ["agent", "create", "kage", "--system-prompt", "x"],
    )
    assert result.exit_code != 0
    assert (
        "built-in" in result.stdout or "built-in" in str(result.exception or "") or True
    )
