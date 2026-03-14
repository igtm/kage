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
    }
    for column_name, column_type in migrations.items():
        try:
            cursor.execute(
                f"ALTER TABLE executions ADD COLUMN {column_name} {column_type}"
            )
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()


def start_execution(
    project_path: str,
    task_name: str,
    pid: int = None,
    working_dir: str | None = None,
    execution_kind: str | None = None,
    provider_name: str | None = None,
) -> str:
    """実行開始を記録し、実行IDを返す。"""
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
            execution_kind, provider_name
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        ),
    )
    conn.commit()
    conn.close()
    return exec_id


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
