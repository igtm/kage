from datetime import datetime, timezone as dt_timezone
import zoneinfo
from croniter import croniter
from pathlib import Path
from .config import KAGE_PROJECTS_LIST, get_global_config
from .parser import load_project_tasks, TaskDef
from .executor import execute_task


def get_projects() -> list[Path]:
    if not KAGE_PROJECTS_LIST.exists():
        return []
    with open(KAGE_PROJECTS_LIST, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    return [Path(p) for p in set(lines) if Path(p).exists()]


def should_run(cron_expr: str, now: datetime, tz_name: str = "UTC") -> bool:
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except zoneinfo.ZoneInfoNotFoundError:
        print(f"Invalid timezone: {tz_name}, falling back to UTC")
        tz = dt_timezone.utc

    # `now` を指定タイムゾーンに変換（awareなdatetimeにする）
    if now.tzinfo is None:
        now_aware = now.astimezone(tz)
    else:
        now_aware = now.astimezone(tz)

    try:
        # croniterにawareなdatetimeを渡す
        itr = croniter(cron_expr, now_aware)
        # crontabは0秒起動が基本なので、nowの秒を切り捨てて判定する
        now_floored = now_aware.replace(second=0, microsecond=0)

        # get_prev で直前の実行予定時刻を取得（これも aware datetime になる）
        prev = itr.get_prev(datetime)

        # 前回の予定実行時刻とnow_flooredが一致すれば実行
        return prev == now_floored
    except Exception as e:
        print(f"Invalid cron expression: {cron_expr}, Error: {e}")
        return False


def parse_hour_string(s: str) -> set[int]:
    """
    "9-17,21" のような文字列を {9,10,11,12,13,14,15,16,17,21} のセットに変換する。
    """
    hours = set()
    if not s:
        return hours

    parts = s.split(",")
    for part in parts:
        part = part.strip()
        if "-" in part:
            try:
                start_s, end_s = part.split("-")
                start, end = int(start_s), int(end_s)
                # 逆転指定 (22-4) はサポートせず、順序通りとする
                for h in range(start, end + 1):
                    if 0 <= h <= 23:
                        hours.add(h)
            except ValueError:
                continue
        else:
            try:
                h = int(part)
                if 0 <= h <= 23:
                    hours.add(h)
            except ValueError:
                continue
    return hours


def is_within_time_window(task: TaskDef, now: datetime, tz_name: str) -> bool:
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        tz = dt_timezone.utc

    local_now = now.astimezone(tz)
    current_hour = local_now.hour

    # 禁止時間帯のチェック
    if task.denied_hours:
        denied = parse_hour_string(task.denied_hours)
        if current_hour in denied:
            return False

    # 許可時間帯のチェック
    if task.allowed_hours:
        allowed = parse_hour_string(task.allowed_hours)
        if current_hour not in allowed:
            return False

    return True


def run_all_scheduled_tasks():
    # utcnow を基準にしてタイムゾーン変換に備える
    now = datetime.now(dt_timezone.utc)
    projects = get_projects()
    cfg = get_global_config()
    tz_name = cfg.timezone

    for proj_dir in projects:
        tasks = load_project_tasks(proj_dir)
        for toml_file, local_task in tasks:
            t = local_task.task
            if not t.active:
                continue

            # タスク固有のタイムゾーン、なければグローバル
            task_tz = t.timezone or tz_name

            # 時間帯枠のチェック
            if not is_within_time_window(t, now, task_tz):
                continue

            if should_run(t.cron, now, task_tz):
                # 実行条件を満たした場合、非同期またはバックグラウンドで実行
                # 今回はPython内のサブプロセスとして呼び出す
                execute_task(proj_dir, local_task.task, task_file=toml_file)
