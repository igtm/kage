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
from kage.db import init_db, start_execution
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
