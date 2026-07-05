"""Repo 層: アプリ端 RLS 強制点。

KAGE_RUN_ID から executions.agent_name を権威として取得し、
agent_scope で SELECT フィルタ (RLS 相当) をかける。
agent_scope == None は人間スーパーユーザー・全件。
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from .agent import resolve_current_agent
from .config import KAGE_DB_PATH


class Repo:
    def __init__(self, conn: sqlite3.Connection, agent_scope: Optional[str]):
        self.conn = conn
        self.agent_scope = agent_scope  # None == superuser bypass RLS

    @classmethod
    def from_env(cls) -> "Repo":
        conn = sqlite3.connect(KAGE_DB_PATH)
        return cls(conn, agent_scope=resolve_current_agent(conn))

    def _scope_where(self, alias: str = "") -> tuple[str, list]:
        if self.agent_scope is None:
            return "", []
        prefix = f"{alias}." if alias else ""
        return f"WHERE COALESCE({prefix}agent_name, 'kage') = ?", [self.agent_scope]

    def list_executions(self, limit: int = 100) -> list[sqlite3.Row]:
        conn = sqlite3.connect(KAGE_DB_PATH)
        conn.row_factory = sqlite3.Row
        where, params = self._scope_where()
        rows = conn.execute(
            f"SELECT * FROM executions {where} ORDER BY run_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        conn.close()
        return rows

    def get_execution(self, run_id: str) -> Optional[sqlite3.Row]:
        conn = sqlite3.connect(KAGE_DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM executions WHERE id = ?", (run_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return None
        if self.agent_scope is None:
            return row
        agent = row["agent_name"] if "agent_name" in row.keys() else None
        effective = agent if agent else "kage"
        if effective != self.agent_scope:
            return None
        return row

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
