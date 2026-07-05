from pathlib import Path

import pytest

from kage.agent import (
    BUILTIN_AGENTS,
    build_full_system_prompt,
    build_agent_system_prompt,
    get_agent,
    get_agent_for_connector,
    get_agent_for_project,
    RUN_ID_ENV_VAR,
    AGENT_NAME_ENV_VAR,
)
from kage.config import AgentConfig, GlobalConfig


def test_builtin_kage_is_immutable():
    assert "kage" in BUILTIN_AGENTS
    assert isinstance(BUILTIN_AGENTS["kage"], AgentConfig)


def test_get_agent_fallback_chain():
    config = GlobalConfig(default_agent="kage")
    # 未指定 name -> default agent 'kage'
    assert get_agent(config, None).name == "kage"
    # 存在しない name -> builtin 'kage'
    assert get_agent(config, "nonexistent").name == "kage"
    # 存在 name -> それ
    cfg = GlobalConfig(
        agents={"public": AgentConfig(name="public", system_prompt="x")},
        default_agent="kage",
    )
    assert get_agent(cfg, "public").name == "public"


def test_get_agent_for_project_matches_working_dir():
    proj = "/tmp/agent-test-proj"
    cfg = GlobalConfig(
        agents={
            "public": AgentConfig(name="public", default_working_dir=proj),
        },
        default_agent="kage",
    )
    assert get_agent_for_project(cfg, Path(proj)).name == "public"


def test_get_agent_for_project_falls_back_to_kage():
    cfg = GlobalConfig(default_agent="kage")
    # 一致する agent が無ければ kage
    a = get_agent_for_project(cfg, Path("/nonexistent-project-path"))
    assert a.name == "kage"


def test_get_agent_for_connector_uses_agent_field():
    cfg = GlobalConfig(
        agents={
            "private": AgentConfig(name="private"),
        },
        default_agent="kage",
    )
    assert get_agent_for_connector(cfg, "dm", {"agent": "private"}).name == "private"
    assert get_agent_for_connector(cfg, "publicch", {"agent": None}).name == "kage"


def test_build_agent_system_prompt_includes_isolation_block():
    cfg = GlobalConfig(default_agent="kage", system_prompt="custom body")
    agent = AgentConfig(name="public", system_prompt="persona body")
    sp = build_agent_system_prompt(cfg, agent)
    assert "[ISOLATION RULE]" in sp
    assert 'agent "public"' in sp
    assert "KAGE_RUN_ID" in sp
    assert "persona body" in sp
    # global system_prompt は agent.body があるため使われない
    assert "custom body" not in sp


def test_build_agent_system_prompt_falls_back_to_global():
    cfg = GlobalConfig(default_agent="kage", system_prompt="global body")
    agent = AgentConfig(name="public")  # system_prompt 未設定
    sp = build_agent_system_prompt(cfg, agent)
    assert "global body" in sp


def test_build_full_system_prompt_contains_memory_headings_if_present(
    tmp_path, monkeypatch
):
    # agent memory dir をモックしないと実際の ~/.kage に書き込む
    from kage import memory as mem_mod
    from kage import agent as agent_mod

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(agent_mod, "KAGE_AGENTS_DIR", fake_home / ".kage" / "agents")
    monkeypatch.setattr(
        mem_mod,
        "agent_memory_dir",
        lambda n: fake_home / ".kage" / "agents" / n / "memory",
    )
    fake_home = tmp_path

    mem_mod.write_memory("public", "prefs", "user lang", "日本語で返答せよ")
    cfg = GlobalConfig(default_agent="kage")
    agent = AgentConfig(name="public")
    sp = build_full_system_prompt(cfg, agent)
    assert "<available_memories>" in sp
    assert "<name>prefs</name>" in sp
    assert "<description>user lang</description>" in sp
    # location は隠蔽されている
    assert "<location>" not in sp


def test_resolve_current_agent_prefers_db_over_env(monkeypatch, tmp_path):
    import sqlite3
    from kage import agent as agent_mod
    from kage.db import init_db, start_execution

    db_path = tmp_path / "kage.db"
    monkeypatch.setattr(agent_mod, "KAGE_DB_PATH", db_path)
    # init_db 内で KAGE_DB_PATH を直接 import しているのでそちらもパッチ
    import kage.db as db_mod

    monkeypatch.setattr(db_mod, "KAGE_DB_PATH", db_path)

    init_db()
    exec_id = start_execution(
        "/proj",
        "task",
        agent_name="public",
    )
    monkeypatch.setenv(RUN_ID_ENV_VAR, exec_id)
    monkeypatch.setenv(AGENT_NAME_ENV_VAR, "private")  # 偽装

    conn = sqlite3.connect(db_path)
    from kage.agent import resolve_current_agent

    assert resolve_current_agent(conn) == "public"  # DB 優先
    conn.close()


def test_resolve_current_agent_none_when_no_env(monkeypatch):
    monkeypatch.delenv(RUN_ID_ENV_VAR, raising=False)
    monkeypatch.delenv(AGENT_NAME_ENV_VAR, raising=False)
    import sqlite3
    from kage.agent import resolve_current_agent

    conn = sqlite3.connect(":memory:")
    assert resolve_current_agent(conn) is None


def test_trigger_blocks_agent_name_update(monkeypatch, tmp_path):
    import sqlite3
    from kage.db import init_db, start_execution
    import kage.db as db_mod

    db_path = tmp_path / "kage.db"
    monkeypatch.setattr(db_mod, "KAGE_DB_PATH", db_path)

    init_db()
    exec_id = start_execution("/proj", "task", agent_name="public")

    conn = sqlite3.connect(db_path)
    with pytest.raises(sqlite3.Error):
        conn.execute(
            "UPDATE executions SET agent_name = ? WHERE id = ?",
            ("evil", exec_id),
        )
    # legacy NULL 行は UPDATE 可能（trigger は NULL 変更のみ ABORT?）
    # NOTE: trigger は `BEFORE UPDATE OF agent_name` で任意の UPDATE を ABORT する。
    # これは仕様通り。legacy 行の UPDATE も含めて agent_name 列上の UPDATE 全部を ABORT する。
    row = conn.execute(
        "SELECT agent_name FROM executions WHERE id = ?", (exec_id,)
    ).fetchone()
    assert row[0] == "public"  # 変更されていない
    conn.close()


def test_trigger_blocks_delete_of_agent_rows(monkeypatch, tmp_path):
    import sqlite3
    from kage.db import init_db, start_execution
    import kage.db as db_mod

    db_path = tmp_path / "kage.db"
    monkeypatch.setattr(db_mod, "KAGE_DB_PATH", db_path)

    init_db()
    exec_id = start_execution("/proj", "task", agent_name="public")

    conn = sqlite3.connect(db_path)
    with pytest.raises(sqlite3.Error):
        conn.execute("DELETE FROM executions WHERE id = ?", (exec_id,))
    conn.close()


def test_trigger_allows_delete_of_legacy_null_rows(monkeypatch, tmp_path):
    import sqlite3
    from kage.db import init_db
    import kage.db as db_mod

    db_path = tmp_path / "kage.db"
    monkeypatch.setattr(db_mod, "KAGE_DB_PATH", db_path)

    init_db()
    conn = sqlite3.connect(db_path)
    # legacy 行 (agent_name NULL)
    conn.execute(
        "INSERT INTO executions (id, project_path, task_name, run_at, status, stdout, stderr) "
        "VALUES ('legacy-1', '/p', 't', '2020', 'SUCCESS', '', '')"
    )
    conn.commit()
    conn.execute("DELETE FROM executions WHERE id = 'legacy-1'")
    conn.commit()
    conn.close()
