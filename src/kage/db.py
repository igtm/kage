import shutil
import sqlite3
import uuid
from datetime import datetime

from .config import KAGE_DB_PATH, get_global_config
from .runs import ensure_run_log_files, get_run_log_dir


def init_db():
    KAGE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(KAGE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS executions (
            id TEXT PRIMARY KEY,
            project_path TEXT,
            task_name TEXT,
            run_at TEXT,
            status TEXT,
            stdout TEXT,
            stderr TEXT,
            pid INTEGER,
            finished_at TEXT,
            log_dir TEXT,
            stdout_path TEXT,
            stderr_path TEXT,
            events_path TEXT,
            exit_code INTEGER,
            output_summary TEXT,
            stdout_bytes INTEGER,
            stderr_bytes INTEGER,
            last_output_at TEXT,
            working_dir TEXT,
            execution_kind TEXT,
            provider_name TEXT
        )
    """
    )

    migrations = {
        "finished_at": "TEXT",
        "pid": "INTEGER",
        "log_dir": "TEXT",
        "stdout_path": "TEXT",
        "stderr_path": "TEXT",
        "events_path": "TEXT",
        "exit_code": "INTEGER",
        "output_summary": "TEXT",
        "stdout_bytes": "INTEGER",
        "stderr_bytes": "INTEGER",
        "last_output_at": "TEXT",
        "working_dir": "TEXT",
        "execution_kind": "TEXT",
        "provider_name": "TEXT",
        "agent_name": "TEXT",
    }
    for column_name, column_type in migrations.items():
        try:
            cursor.execute(
                f"ALTER TABLE executions ADD COLUMN {column_name} {column_type}"
            )
        except sqlite3.OperationalError:
            pass

    _ensure_quest_tables(cursor)
    _ensure_agent_immutable_triggers(cursor)

    conn.commit()
    conn.close()


def _ensure_agent_immutable_triggers(cursor: sqlite3.Cursor) -> None:
    """executions.agent_name の改竄・削除を禁止する trigger。
    legacy 行（agent_name IS NULL）は DELETE を許可し互換維持。
    """
    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_exec_agent_no_update
        BEFORE UPDATE OF agent_name ON executions
        BEGIN
            SELECT RAISE(ABORT, 'agent_name is immutable');
        END
        """
    )
    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_exec_agent_no_delete
        BEFORE DELETE ON executions
        WHEN OLD.agent_name IS NOT NULL
        BEGIN
            SELECT RAISE(ABORT, 'agent_name rows are immutable');
        END
        """
    )


def _ensure_quest_tables(cursor: sqlite3.Cursor) -> None:
    """Create the quest lifecycle tables if they do not exist.

    The quest lifecycle is an event-driven, team-based alternative to the cron
    lifecycle. Tables store quests, their mind-map nodes, and directed edges.
    """
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS quests (
            id TEXT PRIMARY KEY,
            project_path TEXT NOT NULL,
            name TEXT NOT NULL,
            direction TEXT NOT NULL,
            status TEXT NOT NULL,
            max_agent_runs INTEGER NOT NULL DEFAULT 50,
            agent_runs INTEGER NOT NULL DEFAULT 0,
            roles_json TEXT,
            provider TEXT,
            mode TEXT NOT NULL DEFAULT 'team',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    # Add the `mode` column to quests created before v2.
    try:
        cursor.execute(
            "ALTER TABLE quests ADD COLUMN mode TEXT NOT NULL DEFAULT 'team'"
        )
    except sqlite3.OperationalError:
        pass
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS quest_nodes (
            id TEXT PRIMARY KEY,
            quest_id TEXT NOT NULL,
            parent_id TEXT,
            role TEXT NOT NULL,
            hypothesis TEXT NOT NULL,
            status TEXT NOT NULL,
            verdict TEXT,
            evidence TEXT,
            proposed_by TEXT,
            run_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    # Add the `proposed_by` column to legacy quest_nodes tables (v1 — missing column).
    try:
        cursor.execute("ALTER TABLE quest_nodes ADD COLUMN proposed_by TEXT")
    except sqlite3.OperationalError:
        pass
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS quest_edges (
            id TEXT PRIMARY KEY,
            quest_id TEXT NOT NULL,
            from_node TEXT,
            to_node TEXT,
            relation TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )


def start_execution(
    project_path: str,
    task_name: str,
    pid: int = None,
    working_dir: str | None = None,
    execution_kind: str | None = None,
    provider_name: str | None = None,
    agent_name: str | None = None,
) -> str:
    """実行開始を記録し、実行IDを返す。agent_name は INSERT 時に固定され trigger で保護される。"""
    init_db()
    conn = sqlite3.connect(KAGE_DB_PATH)
    cursor = conn.cursor()
    run_at = datetime.now().astimezone().isoformat()
    exec_id = str(uuid.uuid4())
    log_paths = ensure_run_log_files(exec_id)
    cursor.execute(
        """
        INSERT INTO executions (
            id, project_path, task_name, run_at, status, stdout, stderr, finished_at,
            pid, log_dir, stdout_path, stderr_path, events_path, exit_code,
            output_summary, stdout_bytes, stderr_bytes, last_output_at, working_dir,
            execution_kind, provider_name, agent_name
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            exec_id,
            project_path,
            task_name,
            run_at,
            "RUNNING",
            "",
            "",
            None,
            pid,
            str(log_paths["log_dir"]),
            str(log_paths["stdout_path"]),
            str(log_paths["stderr_path"]),
            str(log_paths["events_path"]),
            None,
            "",
            0,
            0,
            None,
            working_dir,
            execution_kind,
            provider_name,
            agent_name,
        ),
    )
    conn.commit()
    conn.close()
    return exec_id


def get_execution_agent(run_id: str) -> str | None:
    """run_id から agent_name を権威的に取得。"""
    if not KAGE_DB_PATH.exists():
        return None
    conn = sqlite3.connect(KAGE_DB_PATH)
    try:
        row = conn.execute(
            "SELECT agent_name FROM executions WHERE id = ?", (run_id,)
        ).fetchone()
        return str(row[0]) if row and row[0] else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def get_execution_pid(exec_id: str) -> int | None:
    """実行IDからPIDを取得する。"""
    conn = sqlite3.connect(KAGE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT pid FROM executions WHERE id = ?", (exec_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def get_execution_status(exec_id: str) -> str | None:
    """実行IDから現在のステータスを取得する。"""
    conn = sqlite3.connect(KAGE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM executions WHERE id = ?", (exec_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def _prune_runs(cursor: sqlite3.Cursor):
    retention = get_global_config().run_retention_count
    if retention <= 0:
        return

    cursor.execute(
        """
        SELECT id, log_dir
        FROM executions
        WHERE id NOT IN (
            SELECT id FROM executions
            ORDER BY run_at DESC
            LIMIT ?
        )
    """,
        (retention,),
    )
    rows = cursor.fetchall()
    for exec_id, log_dir in rows:
        target = log_dir or str(get_run_log_dir(exec_id))
        try:
            shutil.rmtree(target)
        except FileNotFoundError:
            pass
        except OSError:
            pass

    cursor.execute(
        """
        DELETE FROM executions
        WHERE id NOT IN (
            SELECT id FROM executions
            ORDER BY run_at DESC
            LIMIT ?
        )
    """,
        (retention,),
    )


def update_execution(
    exec_id: str,
    status: str,
    stdout: str,
    stderr: str,
    finished_at: str = None,
    exit_code: int | None = None,
    output_summary: str | None = None,
    stdout_bytes: int | None = None,
    stderr_bytes: int | None = None,
    last_output_at: str | None = None,
):
    """実行結果を更新する。"""
    conn = sqlite3.connect(KAGE_DB_PATH)
    cursor = conn.cursor()
    if finished_at is None:
        finished_at = datetime.now().astimezone().isoformat()

    where = "WHERE id = ?"
    if status != "STOPPED":
        where += " AND status != 'STOPPED'"

    cursor.execute(
        f"""
        UPDATE executions
        SET status = ?, stdout = ?, stderr = ?, finished_at = ?, exit_code = ?,
            output_summary = ?, stdout_bytes = ?, stderr_bytes = ?,
            last_output_at = ?
        {where}
    """,
        (
            status,
            stdout,
            stderr,
            finished_at,
            exit_code,
            output_summary,
            stdout_bytes,
            stderr_bytes,
            last_output_at,
            exec_id,
        ),
    )
    updated = cursor.rowcount > 0
    _prune_runs(cursor)

    conn.commit()
    conn.close()
    return updated


def set_execution_pid(exec_id: str, pid: int | None):
    """実行中レコードの PID を更新する。"""
    conn = sqlite3.connect(KAGE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE executions SET pid = ? WHERE id = ?", (pid, exec_id))
    conn.commit()
    conn.close()


def log_execution(
    project_path: str, task_name: str, status: str, stdout: str, stderr: str
):
    """(互換性のために残す) 即時に完了した実行を記録する。"""
    exec_id = start_execution(project_path, task_name)
    update_execution(exec_id, status, stdout, stderr)
