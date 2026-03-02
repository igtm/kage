import pytest
import time
import subprocess
from pathlib import Path
from kage.executor import execute_task, stop_execution
from kage.parser import TaskDef
from kage.db import init_db, KAGE_DB_PATH
import sqlite3

@pytest.fixture
def clean_db(mocker, tmp_path):
    db_path = tmp_path / "kage.db"
    mocker.patch("kage.db.KAGE_DB_PATH", db_path)
    mocker.patch("kage.config.KAGE_DB_PATH", db_path)
    init_db()
    yield db_path

def test_stop_execution_flow(tmp_path: Path, clean_db):
    # 長時間実行されるコマンドを定義 (10秒間sleep)
    # 既存のタスクと衝突しないようにユニークな名前を使用
    task_name = f"test_task_{int(time.time())}"
    task = TaskDef(name=task_name, cron="* * * * *", command="sleep 10")
    
    # 実行を別スレッドで開始
    import threading
    thread = threading.Thread(target=execute_task, args=(tmp_path, task))
    thread.start()
    
    # PIDがDBに書き込まれるまで少し待つ
    exec_id = None
    db_path = clean_db
    for i in range(20):
        time.sleep(0.5)
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, task_name, status, pid FROM executions")
        all_rows = cursor.fetchall()
        print(f"Polling {i}: {all_rows}")
        
        for r_id, r_name, r_status, r_pid in all_rows:
            if r_name == task_name and r_status == 'RUNNING' and r_pid:
                exec_id = r_id
                break
        conn.close()
        if exec_id:
            break
    
    assert exec_id is not None, "Execution should be started and PID stored"
    
    # 停止実行
    stop_execution(exec_id)
    
    # 終了を待つ
    thread.join(timeout=5)
    
    # ステータス確認
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT status, stderr FROM executions WHERE id = ?", (exec_id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row[0] == "STOPPED"
    assert "Terminated by user" in row[1]
