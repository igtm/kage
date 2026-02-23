from datetime import datetime
from croniter import croniter
from pathlib import Path
from .config import KAGE_PROJECTS_LIST
from .parser import load_project_tasks
from .executor import execute_task

def get_projects() -> list[Path]:
    if not KAGE_PROJECTS_LIST.exists():
        return []
    with open(KAGE_PROJECTS_LIST, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    return [Path(p) for p in set(lines) if Path(p).exists()]

def should_run(cron_expr: str, now: datetime) -> bool:
    try:
        # croniter with down to minutes precision
        itr = croniter(cron_expr, now)
        # 1分前を取得し、次の実行時刻が現在時刻と一致(または1分前以内)するかで簡易判定
        # crontabは0秒起動が基本なので、nowの秒を切り捨てて判定する
        now_floored = now.replace(second=0, microsecond=0)
        prev = itr.get_prev(datetime)
        # 前回の予定実行時刻とnow_flooredが一致すれば実行
        return prev == now_floored
    except Exception as e:
        print(f"Invalid cron expression: {cron_expr}, Error: {e}")
        return False

def run_all_scheduled_tasks():
    now = datetime.now()
    projects = get_projects()
    
    for proj_dir in projects:
        tasks = load_project_tasks(proj_dir)
        for toml_file, local_task in tasks:
            if should_run(local_task.task.cron, now):
                # 実行条件を満たした場合、非同期またはバックグラウンドで実行
                # 今回はPython内のサブプロセスとして呼び出す
                execute_task(proj_dir, local_task.task)

