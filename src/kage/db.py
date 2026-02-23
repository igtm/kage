import sqlite3
import uuid
from datetime import datetime
from .config import KAGE_DB_PATH

def init_db():
    conn = sqlite3.connect(KAGE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS executions (
            id TEXT PRIMARY KEY,
            project_path TEXT,
            task_name TEXT,
            run_at TEXT,
            status TEXT,
            stdout TEXT,
            stderr TEXT
        )
    ''')
    conn.commit()
    conn.close()

def log_execution(project_path: str, task_name: str, status: str, stdout: str, stderr: str):
    conn = sqlite3.connect(KAGE_DB_PATH)
    cursor = conn.cursor()
    run_at = datetime.now().isoformat()
    exec_id = str(uuid.uuid4())
    cursor.execute('''
        INSERT INTO executions (id, project_path, task_name, run_at, status, stdout, stderr)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (exec_id, project_path, task_name, run_at, status, stdout, stderr))
    conn.commit()
    conn.close()
