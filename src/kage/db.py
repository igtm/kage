import sqlite3
import uuid
from datetime import datetime
from .config import KAGE_DB_PATH


def init_db():
    KAGE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(KAGE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS executions (
            id TEXT PRIMARY KEY,
            project_path TEXT,
            task_name TEXT,
            run_at TEXT,
            status TEXT,
            stdout TEXT,
            stderr TEXT
        )
    """)
    # Migration: finished_at カラムを追加（既存DB対応）
    try:
        cursor.execute("ALTER TABLE executions ADD COLUMN finished_at TEXT")
    except sqlite3.OperationalError:
        pass  # 既に存在する場合

    conn.commit()
    conn.close()


def start_execution(project_path: str, task_name: str) -> str:
    """実行開始を記録し、実行IDを返す。"""
    conn = sqlite3.connect(KAGE_DB_PATH)
    cursor = conn.cursor()
    run_at = datetime.now().isoformat()
    exec_id = str(uuid.uuid4())
    cursor.execute(
        """
        INSERT INTO executions (id, project_path, task_name, run_at, status, stdout, stderr, finished_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (exec_id, project_path, task_name, run_at, "RUNNING", "", "", None),
    )
    conn.commit()
    conn.close()
    return exec_id


def update_execution(
    exec_id: str, status: str, stdout: str, stderr: str, finished_at: str = None
):
    """実行結果を更新する。"""
    conn = sqlite3.connect(KAGE_DB_PATH)
    cursor = conn.cursor()
    if finished_at is None:
        finished_at = datetime.now().isoformat()

    cursor.execute(
        """
        UPDATE executions 
        SET status = ?, stdout = ?, stderr = ?, finished_at = ?
        WHERE id = ?
    """,
        (status, stdout, stderr, finished_at, exec_id),
    )

    # ログを最大100件に制限
    cursor.execute("""
        DELETE FROM executions 
        WHERE id NOT IN (
            SELECT id FROM executions 
            ORDER BY run_at DESC 
            LIMIT 100
        )
    """)

    conn.commit()
    conn.close()


def log_execution(
    project_path: str, task_name: str, status: str, stdout: str, stderr: str
):
    """(互換性のために残す) 即時に完了した実行を記録する。"""
    exec_id = start_execution(project_path, task_name)
    update_execution(exec_id, status, stdout, stderr)
