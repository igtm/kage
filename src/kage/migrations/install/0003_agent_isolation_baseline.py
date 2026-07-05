from __future__ import annotations

import sqlite3

from ..runner import InstallMigrationContext
from ...db import init_db

MIGRATION_ID = "0003_agent_isolation_baseline"
SUMMARY = "Add agent_name column and immutability triggers for multi-tenant isolation"


def _has_agent_column(cursor: sqlite3.Cursor, table: str) -> bool:
    cols = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}
    return "agent_name" in cols


def _has_trigger(cursor: sqlite3.Cursor, name: str) -> bool:
    row = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def should_run(ctx: InstallMigrationContext) -> bool:
    if not ctx.db_path.exists():
        return False
    init_db()  # idempotent ALTER + trigger CREATE IF NOT EXISTS
    conn = sqlite3.connect(ctx.db_path)
    try:
        cursor = conn.cursor()
        has_col = _has_agent_column(cursor, "executions")
        has_update = _has_trigger(cursor, "trg_exec_agent_no_update")
        has_delete = _has_trigger(cursor, "trg_exec_agent_no_delete")
        return not (has_col and has_update and has_delete)
    finally:
        conn.close()


def run(ctx: InstallMigrationContext) -> dict:
    init_db()
    conn = sqlite3.connect(ctx.db_path)
    try:
        cursor = conn.cursor()
        return {
            "executions.agent_name_column": _has_agent_column(cursor, "executions"),
            "trg_exec_agent_no_update": _has_trigger(
                cursor, "trg_exec_agent_no_update"
            ),
            "trg_exec_agent_no_delete": _has_trigger(
                cursor, "trg_exec_agent_no_delete"
            ),
            "legacy_rows_kept_null": True,
        }
    finally:
        conn.close()
