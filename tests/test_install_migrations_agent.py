import pytest
import tomlkit

import kage.migrations.runner as runner_mod
from kage import db as db_mod


def _import_m0003():
    import importlib

    return importlib.import_module(
        "kage.migrations.install.0003_agent_isolation_baseline"
    )


def _import_m0004():
    import importlib

    return importlib.import_module(
        "kage.migrations.install.0004_migrate_config_to_agent_model"
    )


@pytest.fixture
def migration_env(tmp_path, mocker):
    db_path = tmp_path / "kage.db"
    logs_dir = tmp_path / "logs"
    global_dir = tmp_path / ".kage"
    config_path = global_dir / "config.toml"
    projects_list = global_dir / "projects.list"
    mocker.patch("kage.db.KAGE_DB_PATH", db_path)
    mocker.patch("kage.config.KAGE_DB_PATH", db_path)
    mocker.patch("kage.runs.KAGE_DB_PATH", db_path)
    mocker.patch("kage.config.KAGE_LOGS_DIR", logs_dir)
    mocker.patch("kage.runs.KAGE_LOGS_DIR", logs_dir)
    mocker.patch("kage.migrations.runner.KAGE_DB_PATH", db_path)
    mocker.patch("kage.migrations.runner.KAGE_LOGS_DIR", logs_dir)
    mocker.patch("kage.migrations.runner.KAGE_GLOBAL_DIR", global_dir)
    mocker.patch("kage.config.KAGE_CONFIG_PATH", config_path)
    mocker.patch("kage.config.KAGE_PROJECTS_LIST", projects_list)
    mocker.patch("kage.daemon.get_platform", return_value="linux")
    mocker.patch("kage.daemon.subprocess.check_output", return_value="")
    db_mod.init_db()
    return {
        "db_path": db_path,
        "logs_dir": logs_dir,
        "global_dir": global_dir,
        "config_path": config_path,
        "projects_list": projects_list,
    }


def test_m0003_creates_triggers(migration_env):
    import sqlite3

    m3 = _import_m0003()
    ctx = runner_mod.InstallMigrationContext(
        from_version=None,
        to_version=None,
        global_dir=migration_env["global_dir"],
        db_path=migration_env["db_path"],
        logs_dir=migration_env["logs_dir"],
        state_path=migration_env["global_dir"] / "migrations" / "install_state.json",
    )
    # init_db が既に trigger を作成しているため should_run は False を返し得る
    # その場合でも run() は安全に呼べて現状を返す
    result = m3.run(ctx)
    assert result["executions.agent_name_column"] is True
    # 実際に trigger が存在する
    conn = sqlite3.connect(migration_env["db_path"])
    triggers = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND name IN ('trg_exec_agent_no_update','trg_exec_agent_no_delete')"
        )
    }
    conn.close()
    assert "trg_exec_agent_no_update" in triggers
    assert "trg_exec_agent_no_delete" in triggers


def test_m0004_strips_memory_max_entries_and_replaces_system_prompt(
    migration_env, tmp_path
):
    m4 = _import_m0004()
    # setup: global config with memory_max_entries + a project with system_prompt.md / .kage/memory/
    config_path = migration_env["config_path"]
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        'memory_max_entries = 5\nsystem_prompt = "old"\n', encoding="utf-8"
    )

    proj = tmp_path / "proj"
    proj.mkdir()
    kage_dir = proj / ".kage"
    kage_dir.mkdir()
    tasks_dir = kage_dir / "tasks"
    tasks_dir.mkdir()
    sp = kage_dir / "system_prompt.md"
    sp.write_text(
        "## 1. Task Decomposition\nlegacy task.json\n## 2. Memory System\nlegacy",
        encoding="utf-8",
    )
    mem_dir = kage_dir / "memory"
    mem_dir.mkdir()
    (mem_dir / "2025-01-01.json").write_text("{}", encoding="utf-8")

    migration_env["projects_list"].write_text(str(proj) + "\n", encoding="utf-8")

    ctx = runner_mod.InstallMigrationContext(
        from_version=None,
        to_version=None,
        global_dir=migration_env["global_dir"],
        db_path=migration_env["db_path"],
        logs_dir=migration_env["logs_dir"],
        state_path=migration_env["global_dir"] / "migrations" / "install_state.json",
    )
    assert m4.should_run(ctx)

    result = m4.run(ctx)
    assert str(config_path) in result["configs_cleaned"]
    # memory_max_entries が消えている
    with open(config_path, "r", encoding="utf-8") as f:
        doc = tomlkit.load(f)
    assert "memory_max_entries" not in doc
    # system_prompt.md が新版に置き換えられ backup 作成済み
    assert sp.exists()
    backups = list(sp.parent.glob("system_prompt.md.bak.*"))
    assert backups
    # 旧 memory dir が archive 退避
    archived = list(kage_dir.glob("memory.legacy.*"))
    assert archived
    assert not mem_dir.exists()


def test_m0004_skips_when_already_clean(migration_env, tmp_path):
    m4 = _import_m0004()
    # クリーンな環境
    ctx = runner_mod.InstallMigrationContext(
        from_version=None,
        to_version=None,
        global_dir=migration_env["global_dir"],
        db_path=migration_env["db_path"],
        logs_dir=migration_env["logs_dir"],
        state_path=migration_env["global_dir"] / "migrations" / "install_state.json",
    )
    assert not m4.should_run(ctx)
