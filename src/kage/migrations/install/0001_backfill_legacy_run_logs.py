from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sqlite3

from ..runner import InstallMigrationContext
from ...db import init_db
from ...runs import ensure_run_log_files, write_run_metadata

MIGRATION_ID = "0001_backfill_legacy_run_logs"
SUMMARY = "Backfill per-run log files for legacy executions stored only in SQLite"


def _row_needs_backfill(row: sqlite3.Row) -> bool:
    log_dir = row["log_dir"]
    stdout_path = row["stdout_path"]
    stderr_path = row["stderr_path"]
    events_path = row["events_path"]
    expected = [log_dir, stdout_path, stderr_path, events_path]
    if not all(expected):
        return True
    return not all(str(path) and Path(path).exists() for path in expected)


def should_run(ctx: InstallMigrationContext) -> bool:
    if not ctx.db_path.exists():
        return False

    init_db()
    conn = sqlite3.connect(ctx.db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, log_dir, stdout_path, stderr_path, events_path
            FROM executions
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()

    return any(_row_needs_backfill(row) for row in rows)


def _write_events(events_path, event_ts: str, stdout: str, stderr: str) -> None:
    with events_path.open("w", encoding="utf-8", errors="replace") as handle:
        for stream_name, text in (("stdout", stdout), ("stderr", stderr)):
            chunks = text.splitlines(keepends=True)
            if not chunks and text:
                chunks = [text]
            for chunk in chunks:
                handle.write(
                    json.dumps(
                        {"ts": event_ts, "stream": stream_name, "text": chunk},
                        ensure_ascii=False,
                    )
                    + "\n"
                )


def run(ctx: InstallMigrationContext) -> dict:
    if not ctx.db_path.exists():
        return {"backfilled_runs": 0}

    init_db()
    conn = sqlite3.connect(ctx.db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    rows = cursor.execute(
        """
        SELECT
            id, run_at, finished_at, status, stdout, stderr, log_dir, stdout_path,
            stderr_path, events_path, stdout_bytes, stderr_bytes, last_output_at
        FROM executions
        ORDER BY run_at ASC
        """
    ).fetchall()

    backfilled_runs = 0
    now_ts = datetime.now().astimezone().isoformat()
    for row in rows:
        if not _row_needs_backfill(row):
            continue

        stdout = row["stdout"] or ""
        stderr = row["stderr"] or ""
        event_ts = (
            row["last_output_at"] or row["finished_at"] or row["run_at"] or now_ts
        )
        log_paths = ensure_run_log_files(row["id"])
        log_paths["stdout_path"].write_text(stdout, encoding="utf-8")
        log_paths["stderr_path"].write_text(stderr, encoding="utf-8")
        _write_events(log_paths["events_path"], event_ts, stdout, stderr)

        stdout_bytes = len(stdout.encode("utf-8"))
        stderr_bytes = len(stderr.encode("utf-8"))
        cursor.execute(
            """
            UPDATE executions
            SET log_dir = ?, stdout_path = ?, stderr_path = ?, events_path = ?,
                stdout_bytes = ?, stderr_bytes = ?, last_output_at = ?
            WHERE id = ?
            """,
            (
                str(log_paths["log_dir"]),
                str(log_paths["stdout_path"]),
                str(log_paths["stderr_path"]),
                str(log_paths["events_path"]),
                stdout_bytes,
                stderr_bytes,
                event_ts,
                row["id"],
            ),
        )
        write_run_metadata(
            row["id"],
            {
                "legacy_backfill": {
                    "migration_id": MIGRATION_ID,
                    "summary": SUMMARY,
                    "reconstructed_from_db_columns": True,
                }
            },
        )
        backfilled_runs += 1

    conn.commit()
    conn.close()
    return {"backfilled_runs": backfilled_runs}
