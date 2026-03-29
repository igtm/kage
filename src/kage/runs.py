from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from .config import KAGE_DB_PATH, KAGE_LOGS_DIR

LogStream = Literal["stdout", "stderr", "merged"]
CONNECTOR_POLL_SOURCE = "connector_poll"


@dataclass
class RunRecord:
    id: str
    project_path: str
    task_name: str
    run_at: str
    status: str
    stdout: str = ""
    stderr: str = ""
    pid: int | None = None
    finished_at: str | None = None
    log_dir: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    events_path: str | None = None
    exit_code: int | None = None
    output_summary: str | None = None
    stdout_bytes: int | None = 0
    stderr_bytes: int | None = 0
    last_output_at: str | None = None
    working_dir: str | None = None
    execution_kind: str | None = None
    provider_name: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["project_short"] = project_short_name(self.project_path)
        data["run_at_local"] = format_local_timestamp(self.run_at)
        data["duration_seconds"] = get_duration_seconds(self)
        data["duration_display"] = format_duration(get_duration_seconds(self))
        data["has_raw_logs"] = has_raw_logs(self)
        data["meta_path"] = str(get_run_log_paths(self.id)["meta_path"])
        data["source"] = get_run_source(self)
        return data


def _connect() -> sqlite3.Connection:
    from .db import init_db

    init_db()
    conn = sqlite3.connect(KAGE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_logs_root() -> Path:
    KAGE_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return KAGE_LOGS_DIR


def get_run_log_dir(exec_id: str) -> Path:
    return ensure_logs_root() / exec_id


def get_run_log_paths(exec_id: str) -> dict[str, Path]:
    log_dir = get_run_log_dir(exec_id)
    return {
        "log_dir": log_dir,
        "stdout_path": log_dir / "stdout.log",
        "stderr_path": log_dir / "stderr.log",
        "events_path": log_dir / "events.jsonl",
        "meta_path": log_dir / "meta.json",
        "artifact_dir": log_dir / "artifacts",
    }


def ensure_run_log_files(exec_id: str) -> dict[str, Path]:
    paths = get_run_log_paths(exec_id)
    paths["log_dir"].mkdir(parents=True, exist_ok=True)
    for key in ("stdout_path", "stderr_path", "events_path"):
        paths[key].touch(exist_ok=True)
    return paths


def get_run_artifact_dir(exec_id: str) -> Path:
    return get_run_log_paths(exec_id)["artifact_dir"]


def load_run_metadata(run_or_id: RunRecord | str) -> dict:
    exec_id = run_or_id.id if isinstance(run_or_id, RunRecord) else run_or_id
    meta_path = get_run_log_paths(exec_id)["meta_path"]
    if not meta_path.exists():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def write_run_metadata(exec_id: str, metadata: dict, merge: bool = True) -> Path:
    paths = get_run_log_paths(exec_id)
    paths["log_dir"].mkdir(parents=True, exist_ok=True)
    meta_path = paths["meta_path"]

    payload: dict = {}
    if merge:
        payload.update(load_run_metadata(exec_id))
    payload.update(metadata)
    meta_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return meta_path


def get_run_source(run: RunRecord) -> str:
    return (
        CONNECTOR_POLL_SOURCE if run.execution_kind == CONNECTOR_POLL_SOURCE else "task"
    )


def project_short_name(project_path: str) -> str:
    parts = Path(project_path).parts
    if len(parts) >= 1:
        return parts[-1]
    return project_path


def format_local_timestamp(value: str | None) -> str:
    if not value:
        return "-"
    try:
        return (
            datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        )
    except ValueError:
        return value


def format_relative_timestamp(
    value: str | None,
    *,
    now: datetime | None = None,
    is_ja: bool = False,
) -> str:
    if not value:
        return "-"

    try:
        target = datetime.fromisoformat(value).astimezone()
    except ValueError:
        return value

    current = (
        now.astimezone(target.tzinfo)
        if now
        else datetime.now().astimezone(target.tzinfo)
    )
    delta_seconds = int((current - target).total_seconds())
    future = delta_seconds < 0
    delta_seconds = abs(delta_seconds)

    if delta_seconds < 10:
        return "たった今" if is_ja else "just now"

    units = [
        (365 * 24 * 60 * 60, "年", "y"),
        (30 * 24 * 60 * 60, "か月", "mo"),
        (24 * 60 * 60, "日", "d"),
        (60 * 60, "時間", "h"),
        (60, "分", "m"),
        (1, "秒", "s"),
    ]
    amount = 0
    ja_unit = "秒"
    en_unit = "s"
    for unit_seconds, ja_label, en_label in units:
        if delta_seconds >= unit_seconds:
            amount = delta_seconds // unit_seconds
            ja_unit = ja_label
            en_unit = en_label
            break

    if is_ja:
        suffix = "後" if future else "前"
        return f"{amount}{ja_unit}{suffix}"

    return f"in {amount}{en_unit}" if future else f"{amount}{en_unit} ago"


def get_duration_seconds(run: RunRecord) -> float | None:
    try:
        start = datetime.fromisoformat(run.run_at)
    except ValueError:
        return None

    if run.finished_at:
        try:
            end = datetime.fromisoformat(run.finished_at)
        except ValueError:
            return None
    elif run.status == "RUNNING":
        end = (
            datetime.now().astimezone(start.tzinfo) if start.tzinfo else datetime.now()
        )
    else:
        return None

    return max((end - start).total_seconds(), 0.0)


def format_duration(duration_seconds: float | None) -> str:
    if duration_seconds is None:
        return "-"
    total = int(duration_seconds)
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _row_to_run(row: sqlite3.Row) -> RunRecord:
    return RunRecord(**dict(row))


def get_run(exec_id: str) -> RunRecord | None:
    if not KAGE_DB_PATH.exists():
        return None
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT
                id, project_path, task_name, run_at, status, stdout, stderr, pid,
                finished_at, log_dir, stdout_path, stderr_path, events_path,
                exit_code, output_summary, stdout_bytes, stderr_bytes,
                last_output_at, working_dir, execution_kind, provider_name
            FROM executions
            WHERE id = ?
            """,
            (exec_id,),
        ).fetchone()
        return _row_to_run(row) if row else None
    finally:
        conn.close()


def list_runs(
    limit: int | None = 20,
    task_name: str | None = None,
    project_filter: str | None = None,
    status: str | None = None,
    source: str | None = None,
) -> list[RunRecord]:
    if not KAGE_DB_PATH.exists():
        return []

    conditions: list[str] = []
    params: list[object] = []
    if task_name:
        conditions.append("task_name = ?")
        params.append(task_name)
    if project_filter:
        conditions.append("project_path LIKE ?")
        params.append(f"%{project_filter}%")
    if status:
        conditions.append("status = ?")
        params.append(status)
    if source == CONNECTOR_POLL_SOURCE:
        conditions.append("execution_kind = ?")
        params.append(CONNECTOR_POLL_SOURCE)
    elif source == "task":
        conditions.append("(execution_kind IS NULL OR execution_kind != ?)")
        params.append(CONNECTOR_POLL_SOURCE)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    conn = _connect()
    try:
        limit_clause = ""
        if limit is not None:
            params.append(limit)
            limit_clause = "LIMIT ?"
        rows = conn.execute(
            f"""
            SELECT
                id, project_path, task_name, run_at, status, stdout, stderr, pid,
                finished_at, log_dir, stdout_path, stderr_path, events_path,
                exit_code, output_summary, stdout_bytes, stderr_bytes,
                last_output_at, working_dir, execution_kind, provider_name
            FROM executions
            {where}
            ORDER BY run_at DESC
            {limit_clause}
            """,
            params,
        ).fetchall()
        return [_row_to_run(row) for row in rows]
    finally:
        conn.close()


def resolve_latest_run_for_task(
    task_name: str, project_filter: str | None = None
) -> tuple[RunRecord | None, list[str]]:
    if not KAGE_DB_PATH.exists():
        return None, []

    conn = _connect()
    try:
        params: list[object] = [task_name]
        project_where = ""
        if project_filter:
            project_where = " AND project_path LIKE ?"
            params.append(f"%{project_filter}%")

        rows = conn.execute(
            f"""
            SELECT DISTINCT project_path
            FROM executions
            WHERE task_name = ? {project_where}
            ORDER BY project_path ASC
            """,
            params,
        ).fetchall()
        projects = [row["project_path"] for row in rows]
        if not projects:
            return None, []
        if len(projects) > 1 and not project_filter:
            return None, projects

        selected_project = projects[0]
        row = conn.execute(
            """
            SELECT
                id, project_path, task_name, run_at, status, stdout, stderr, pid,
                finished_at, log_dir, stdout_path, stderr_path, events_path,
                exit_code, output_summary, stdout_bytes, stderr_bytes,
                last_output_at, working_dir, execution_kind, provider_name
            FROM executions
            WHERE task_name = ? AND project_path = ?
            ORDER BY run_at DESC
            LIMIT 1
            """,
            (task_name, selected_project),
        ).fetchone()
        return (_row_to_run(row) if row else None), projects
    finally:
        conn.close()


def infer_output_summary(stdout: str, stderr: str, max_len: int = 120) -> str:
    for source in (stdout, stderr):
        if not source:
            continue
        for raw_line in source.splitlines():
            line = " ".join(raw_line.strip().split())
            if line:
                return line[:max_len]
    return ""


def has_raw_logs(run: RunRecord) -> bool:
    for path_str in (run.stdout_path, run.stderr_path, run.events_path):
        if path_str and Path(path_str).exists():
            return True
    return False


def log_path_for_stream(run: RunRecord, stream: LogStream) -> Path | None:
    if stream == "merged":
        return Path(run.events_path) if run.events_path else None
    if stream == "stdout":
        return Path(run.stdout_path) if run.stdout_path else None
    if stream == "stderr":
        return Path(run.stderr_path) if run.stderr_path else None
    raise ValueError(f"Unknown stream: {stream}")


def parse_since(value: str | None) -> datetime | None:
    if not value:
        return None

    rel_match = re.fullmatch(r"(\d+)([smhd])", value.strip())
    if rel_match:
        amount = int(rel_match.group(1))
        unit = rel_match.group(2)
        delta = {
            "s": timedelta(seconds=amount),
            "m": timedelta(minutes=amount),
            "h": timedelta(hours=amount),
            "d": timedelta(days=amount),
        }[unit]
        return datetime.now().astimezone() - delta

    try:
        return datetime.fromisoformat(value).astimezone()
    except ValueError as exc:
        raise ValueError(
            "Invalid --since value. Use ISO timestamp or relative values like 10m, 2h, 1d."
        ) from exc


def _read_text(path: Path | None) -> str:
    if not path or not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _read_events(run: RunRecord) -> list[dict]:
    path = Path(run.events_path) if run.events_path else None
    if not path or not path.exists():
        return []
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if "ts" not in payload or "stream" not in payload or "text" not in payload:
            continue
        events.append(payload)
    return events


def _legacy_events(run: RunRecord, stream: LogStream = "merged") -> list[dict]:
    timestamp = run.last_output_at or run.finished_at or run.run_at
    events: list[dict] = []
    if stream in {"merged", "stdout"} and run.stdout:
        events.append({"ts": timestamp, "stream": "stdout", "text": run.stdout})
    if stream in {"merged", "stderr"} and run.stderr:
        events.append({"ts": timestamp, "stream": "stderr", "text": run.stderr})
    return events


def collect_run_events(
    run: RunRecord,
    stream: LogStream = "merged",
    since: str | None = None,
) -> list[dict]:
    cutoff = parse_since(since)
    raw_events = _read_events(run) or _legacy_events(run, stream=stream)
    events: list[dict] = []
    for payload in raw_events:
        event_stream = str(payload.get("stream", ""))
        if stream != "merged" and event_stream != stream:
            continue
        if not _event_after_cutoff(payload, cutoff):
            continue
        events.append(
            {
                "ts": payload.get("ts", ""),
                "stream": event_stream,
                "text": str(payload.get("text", "")),
                "run_id": run.id,
                "task_name": run.task_name,
                "project_path": run.project_path,
                "project_short": project_short_name(run.project_path),
            }
        )
    return events


def _event_sort_key(payload: dict) -> tuple[datetime, str, str]:
    try:
        ts = datetime.fromisoformat(str(payload.get("ts", ""))).astimezone()
    except ValueError:
        ts = datetime.fromtimestamp(0).astimezone()
    return ts, str(payload.get("project_path", "")), str(payload.get("task_name", ""))


def render_combined_events(
    events: list[dict],
    *,
    stream: LogStream = "merged",
    lines: int | None = None,
) -> str:
    rendered: list[str] = []
    for payload in sorted(events, key=_event_sort_key):
        formatted_ts = format_local_timestamp(str(payload.get("ts", "")))
        ts_parts = formatted_ts.split(" ", 1)
        ts = ts_parts[1] if len(ts_parts) > 1 else formatted_ts
        task_label = (
            f"{payload.get('project_short', '-')}/{payload.get('task_name', '-')}"
        )
        stream_name = str(payload.get("stream", "")).upper().ljust(6)
        text = str(payload.get("text", ""))
        logical_lines = text.splitlines() or [text]
        for line in logical_lines:
            if stream == "merged":
                rendered.append(f"{ts} {task_label} {stream_name} {line}\n")
            else:
                rendered.append(f"{ts} {task_label} {line}\n")
    return _tail_text("".join(rendered), lines)


def load_all_log_text(
    *,
    stream: LogStream = "merged",
    lines: int | None = None,
    since: str | None = None,
    project_filter: str | None = None,
    task_name: str | None = None,
) -> str:
    events: list[dict] = []
    for run in list_runs(
        limit=None,
        project_filter=project_filter,
        task_name=task_name,
    ):
        events.extend(collect_run_events(run, stream=stream, since=since))
    return render_combined_events(events, stream=stream, lines=lines)


def _tail_text(text: str, lines: int | None) -> str:
    if lines is None:
        return text
    return "".join(text.splitlines(keepends=True)[-lines:])


def _event_after_cutoff(payload: dict, cutoff: datetime | None) -> bool:
    if cutoff is None:
        return True
    try:
        return datetime.fromisoformat(payload["ts"]).astimezone() >= cutoff
    except ValueError:
        return True


def _render_merged_events(
    events: list[dict], lines: int | None = None, since: datetime | None = None
) -> str:
    rendered: list[str] = []
    for payload in events:
        if not _event_after_cutoff(payload, since):
            continue
        formatted_ts = format_local_timestamp(payload["ts"])
        ts_parts = formatted_ts.split(" ", 1)
        ts = ts_parts[1] if len(ts_parts) > 1 else formatted_ts
        stream = payload["stream"].upper().ljust(6)
        text = str(payload["text"])
        logical_lines = text.splitlines() or [text]
        for line in logical_lines:
            rendered.append(f"{ts} {stream} {line}\n")
    return _tail_text("".join(rendered), lines)


def load_log_text(
    run: RunRecord,
    stream: LogStream = "merged",
    lines: int | None = None,
    since: str | None = None,
) -> str:
    cutoff = parse_since(since)
    if stream == "merged":
        events = _read_events(run)
        if events:
            return _render_merged_events(events, lines=lines, since=cutoff)
        legacy_parts = []
        if run.stdout:
            legacy_parts.append(run.stdout)
        if run.stderr:
            legacy_parts.append(f"[STDERR]\n{run.stderr}")
        return _tail_text("\n".join(legacy_parts), lines)

    raw_path = log_path_for_stream(run, stream)
    if cutoff is None and raw_path and raw_path.exists():
        raw_text = _read_text(raw_path)
        if raw_text:
            return _tail_text(raw_text, lines)

    events = _read_events(run)
    if events:
        filtered = [
            str(payload["text"])
            for payload in events
            if payload["stream"] == stream and _event_after_cutoff(payload, cutoff)
        ]
        if filtered:
            return _tail_text("".join(filtered), lines)

    legacy = run.stdout if stream == "stdout" else run.stderr
    return _tail_text(legacy or "", lines)
