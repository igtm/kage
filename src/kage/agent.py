"""Agent モデル: トップ概念。

Agent は project / connector / memory / system_prompt を所有する独立人格。
ハードコードされた builtin agent `kage` は常に存在し、削除不可。
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

from .config import (
    AgentConfig,
    DEFAULT_AGENT_NAME,
    GlobalConfig,
    KAGE_AGENTS_DIR,
    KAGE_DB_PATH,
)


BUILTIN_AGENTS: dict[str, AgentConfig] = {
    DEFAULT_AGENT_NAME: AgentConfig(name=DEFAULT_AGENT_NAME)
}

AGENT_NAME_ENV_VAR = "KAGE_AGENT_NAME"
RUN_ID_ENV_VAR = "KAGE_RUN_ID"


ISOLATION_BLOCK = """[ISOLATION RULE]
You are operating as agent "{name}".
- You MUST NOT disclose, summarize, paraphrase, or reference anything said,
  written, stored, or known by any other agent. Treat other agents'
  conversations, files, and memory as if they do not exist.
- The CLI identifies your agent authoritatively via KAGE_RUN_ID, which is
  DB-anchored (the executions.agent_name column is write-protected by a
  SQLite trigger). Tampering with the KAGE_AGENT_NAME environment variable
  has no effect; the CLI always trusts the database record.
- You can only operate on tasks, connectors, memory, and data bound to
  agent "{name}". Attempts to read or modify another agent's resources
  will be refused by the CLI.
"""


def get_agent(config: GlobalConfig, name: Optional[str]) -> AgentConfig:
    """name で agent を解決。未指定 or 存在しない場合は default_agent → builtin 'kage' へフォールバック。"""
    if name:
        agent = config.agents.get(name)
        if agent is not None:
            return agent
        # ハードコード builtin
        builtin = BUILTIN_AGENTS.get(name)
        if builtin is not None:
            return builtin
    # default_agent へフォールバック
    if config.default_agent and config.default_agent != name:
        agent = config.agents.get(config.default_agent)
        if agent is not None:
            return agent
        builtin = BUILTIN_AGENTS.get(config.default_agent)
        if builtin is not None:
            return builtin
    return BUILTIN_AGENTS[DEFAULT_AGENT_NAME]


def _agent_projects(agent: AgentConfig) -> list[Path]:
    projects: list[Path] = []
    if agent.default_working_dir:
        projects.append(Path(agent.default_working_dir).expanduser())
    for extra in agent.extra_project_dirs:
        projects.append(Path(extra).expanduser())
    return [p for p in projects]


def get_agent_for_project(config: GlobalConfig, project_path: Path) -> AgentConfig:
    """project_path を所有する agent を解決。一致が無ければ default agent 'kage' へフォールバック。"""
    target = Path(project_path).expanduser().resolve()
    for agent in config.agents.values():
        for proj in _agent_projects(agent):
            try:
                if proj.resolve() == target:
                    return agent
            except Exception:
                continue
    # builtin も確認
    for agent in BUILTIN_AGENTS.values():
        for proj in _agent_projects(agent):
            try:
                if proj.resolve() == target:
                    return agent
            except Exception:
                continue
    return get_agent(config, config.default_agent)


def get_agent_for_connector(
    config: GlobalConfig, connector_name: str, c_dict: dict
) -> AgentConfig:
    """connector config の agent フィールドから agent を解決。未設定は default agent。"""
    agent_name = c_dict.get("agent")
    if hasattr(agent_name, "unwrap"):
        agent_name = agent_name.unwrap()
    return get_agent(config, agent_name)


def resolve_current_agent(conn: sqlite3.Connection) -> Optional[str]:
    """権威判定: env KAGE_RUN_ID → DB executions.agent_name を権威とする。
    KAGE_RUN_ID 無ければ KAGE_AGENT_NAME を返す（後方互換・手動デバッグ用・非推奨）。
    両方無ければ None（対人スーパーユーザー）。
    """
    run_id = os.environ.get(RUN_ID_ENV_VAR)
    if run_id:
        try:
            row = conn.execute(
                "SELECT agent_name FROM executions WHERE id = ?", (run_id,)
            ).fetchone()
            if row and row[0]:
                return str(row[0])
        except sqlite3.Error:
            pass
    hint = os.environ.get(AGENT_NAME_ENV_VAR)
    if hint:
        return hint
    return None


def _load_workspace_system_prompt(workspace_dir: Optional[Path]) -> Optional[str]:
    if not workspace_dir:
        return None
    ws_md = workspace_dir / ".kage" / "system_prompt.md"
    if ws_md.exists():
        return ws_md.read_text(encoding="utf-8").strip()
    return None


def build_agent_system_prompt(config: GlobalConfig, agent: AgentConfig) -> str:
    """agent の system_prompt を構築。ISOLATION RULE + (agent.system_prompt > workspace md > global)。
    memory headings XML を含まず（build_full_system_prompt で合成）。
    """
    body = agent.system_prompt
    if not body:
        ws = (
            Path(agent.default_working_dir).expanduser()
            if agent.default_working_dir
            else None
        )
        body = _load_workspace_system_prompt(ws)
    if not body:
        body = config.system_prompt
    parts = [ISOLATION_BLOCK.format(name=agent.name)]
    if body:
        parts.append(body.strip())
    return "\n\n".join(parts)


def build_full_system_prompt(config: GlobalConfig, agent: AgentConfig) -> str:
    """ISOLATION + system_prompt + memory headings XML を結合。"""
    parts = [build_agent_system_prompt(config, agent)]
    # memory headings XML を注入（遅延 import で循環回避）
    try:
        from .memory import build_memory_headings_xml

        headings = build_memory_headings_xml(agent.name)
        if headings:
            parts.append(headings)
    except Exception:
        pass
    return "\n\n".join(parts)


def get_current_agent_name(config: Optional[GlobalConfig] = None) -> Optional[str]:
    """CLI 側の利便性用: KAGE_RUN_ID → DB 解決。DB アクセス不可の場合は env ヒントのみ。"""
    run_id = os.environ.get(RUN_ID_ENV_VAR)
    if run_id:
        try:
            conn = sqlite3.connect(KAGE_DB_PATH)
            try:
                return resolve_current_agent(conn)
            finally:
                conn.close()
        except Exception:
            pass
    return os.environ.get(AGENT_NAME_ENV_VAR)


def assert_task_command_allowed(
    config: GlobalConfig, project_path: Optional[Path]
) -> None:
    """現 agent 配下以外の project 操作を拒否。typer.Exit(1) で抜ける。"""
    current = get_current_agent_name()
    if current is None:
        return  # 対人スーパーユーザー
    if project_path is None:
        import typer

        typer.echo(
            f"Error: project path is required when running inside agent '{current}'."
        )
        raise typer.Exit(1)
    agent = get_agent(config, current)
    target = Path(project_path).expanduser().resolve()
    for proj in _agent_projects(agent):
        try:
            if proj.resolve() == target:
                return
        except Exception:
            continue
    import typer

    typer.echo(f"Error: project '{target}' is not bound to agent '{current}'.")
    raise typer.Exit(1)


def assert_connector_command_allowed(config: GlobalConfig, connector_name: str) -> None:
    """connector の bound agent が現 agent と一致するか検証。"""
    current = get_current_agent_name()
    if current is None:
        return
    c_dict = config.connectors.get(connector_name)
    if not c_dict:
        return
    bound = c_dict.get("agent")
    if hasattr(bound, "unwrap"):
        bound = bound.unwrap()
    if bound is None:
        bound = config.default_agent
    if bound != current:
        import typer

        typer.echo(
            f"Error: connector '{connector_name}' is bound to agent "
            f"'{bound or DEFAULT_AGENT_NAME}', not to current agent '{current}'."
        )
        raise typer.Exit(1)


def assert_agent_command_allowed(config: GlobalConfig, name: str) -> None:
    """agent show で他 agent を参照するのを拒否。"""
    current = get_current_agent_name()
    if current is None:
        return
    if name != current:
        import typer

        typer.echo(
            f"Error: cannot access agent '{name}' from within agent '{current}'."
        )
        raise typer.Exit(1)


def assert_not_in_agent_run(operating: str) -> None:
    """agent 実行内では全体操作系コマンドを禁止。"""
    current = get_current_agent_name()
    if current is None:
        return
    import typer

    typer.echo(
        f"Error: cannot {operating} from within an agent run (current agent: "
        f"'{current}'). Run this command from a human shell."
    )
    raise typer.Exit(1)


def agent_memory_dir(agent_name: str) -> Path:
    """agent memory ディレクトリ (~/.kage/agents/<name>/memory/)."""
    return KAGE_AGENTS_DIR / agent_name / "memory"
