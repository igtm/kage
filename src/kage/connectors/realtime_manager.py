"""Lifecycle management for long-lived realtime connector listeners.

Realtime connectors are started as detached background processes by
`kage cron run` and by the `kage connector realtime start` command.  This
module tracks them with PID files and keeps one process per connector.
"""

from __future__ import annotations

import os
import re
import signal
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from ..config import KAGE_GLOBAL_DIR, get_global_config
from .runner import _build_connector

RUN_DIR = KAGE_GLOBAL_DIR / "run"
LOG_DIR = KAGE_GLOBAL_DIR / "logs"

# Lock files prevent multiple simultaneous `kage cron run` instances from
# starting the same realtime connector twice.
LOCK_DIR = KAGE_GLOBAL_DIR / "run" / "locks"


def _ensure_dirs() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    LOCK_DIR.mkdir(parents=True, exist_ok=True)


def _pid_file(name: str) -> Path:
    _ensure_dirs()
    return RUN_DIR / f"connector-realtime-{name}.pid"


def _log_file(name: str) -> Path:
    _ensure_dirs()
    return LOG_DIR / f"connector-realtime-{name}.log"


def _lock_file(name: str) -> Path:
    _ensure_dirs()
    return LOCK_DIR / f"connector-realtime-{name}.lock"


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_pid(name: str) -> int | None:
    pid_path = _pid_file(name)
    if not pid_path.exists():
        return None
    try:
        return int(pid_path.read_text().strip())
    except Exception:
        return None


def _write_pid(name: str, pid: int) -> None:
    _pid_file(name).write_text(str(pid))


def _remove_pid(name: str) -> None:
    try:
        _pid_file(name).unlink()
    except FileNotFoundError:
        pass


class _RealtimeLock:
    """Cross-platform best-effort lock around realtime process operations."""

    def __init__(self, name: str):
        self._lock_path = _lock_file(name)
        self._fd: int | None = None

    def __enter__(self) -> _RealtimeLock:
        try:
            import fcntl

            self._fd = os.open(str(self._lock_path), os.O_CREAT | os.O_RDWR)
            fcntl.flock(self._fd, fcntl.LOCK_EX)
        except Exception:
            # Locking is best-effort; if fcntl is unavailable we still proceed.
            pass
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._fd is not None:
            try:
                import fcntl

                fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None


def _kage_command() -> list[str]:
    """Return the command prefix to invoke kage in a subprocess.

    When kage is run from cron the subprocess inherits a minimal PATH, so we
    prefer the executable that started the current process (``sys.argv[0]``)
    and only fall back to PATH lookup or ``python -m kage``.
    """
    invoked = sys.argv[0]
    if os.path.basename(invoked) == "kage" and os.path.isfile(invoked):
        return [invoked]

    kage_bin = shutil.which("kage")
    if kage_bin:
        return [kage_bin]

    return [sys.executable, "-m", "kage"]


def get_realtime_connector_names() -> list[str]:
    """Return names of connectors configured with realtime=True."""
    config = get_global_config()
    names: list[str] = []
    for name, c_dict in config.connectors.items():
        connector = _build_connector(name, c_dict)
        if connector and connector.config.realtime:
            names.append(name)
    return names


def is_realtime_running(name: str) -> bool:
    """Return True if a realtime listener appears to be running for ``name``."""
    pid = _read_pid(name)
    if pid is None:
        return False
    return _is_process_alive(pid)


def _rotate_log(name: str) -> None:
    """Rotate the existing log file and clean up stale rotated logs."""
    log_path = _log_file(name)
    if not log_path.exists() or log_path.stat().st_size == 0:
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    rotated = log_path.with_suffix(f".log.{timestamp}")
    try:
        log_path.rename(rotated)
    except OSError:
        # If rotation fails, truncate the existing log to avoid unbounded growth.
        try:
            log_path.write_text("")
        except OSError:
            pass
        return

    _cleanup_old_logs(name)


def _cleanup_old_logs(name: str) -> None:
    """Keep at most 5 rotated logs and remove any older than 7 days."""
    base = _log_file(name)
    rotated = sorted(
        base.parent.glob(f"{base.name}.*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    now = time.time()
    max_age_seconds = 7 * 24 * 60 * 60

    for index, path in enumerate(rotated):
        try:
            if index >= 5 or (now - path.stat().st_mtime) > max_age_seconds:
                path.unlink()
        except OSError:
            pass


def start_realtime_connector(name: str) -> tuple[bool, str]:
    """Start a detached realtime listener for ``name``.

    Returns (started, message).  If already running, ``started`` is False and
    ``message`` explains why.
    """
    with _RealtimeLock(name):
        pid = _read_pid(name)
        if pid is not None and _is_process_alive(pid):
            return (
                False,
                f"Realtime listener for '{name}' is already running (pid {pid}).",
            )

        if pid is not None:
            _remove_pid(name)

        log_path = _log_file(name)
        _rotate_log(name)
        cmd = _kage_command() + ["connector", "realtime", "run", name]
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}

        try:
            log_f = log_path.open("a", encoding="utf-8", buffering=1)
            log_f.write(
                f"\n--- kage realtime start at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n"
            )
            log_f.flush()

            proc = subprocess.Popen(
                cmd,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
                env=env,
            )
            _write_pid(name, proc.pid)

            # Give the process a moment to fail; if it died immediately,
            # report the failure rather than claiming success.
            time.sleep(0.3)
            if proc.poll() is not None:
                _remove_pid(name)
                return False, f"Realtime listener for '{name}' exited immediately."

            return True, f"Started realtime listener for '{name}' (pid {proc.pid})."
        except Exception as exc:
            _remove_pid(name)
            return False, f"Failed to start realtime listener for '{name}': {exc}"


def stop_realtime_connector(name: str) -> tuple[bool, str]:
    """Stop the realtime listener for ``name``.

    Returns (stopped, message).
    """
    with _RealtimeLock(name):
        pid = _read_pid(name)
        if pid is None:
            return False, f"No realtime listener is recorded for '{name}'."

        if not _is_process_alive(pid):
            _remove_pid(name)
            return False, f"Realtime listener for '{name}' was not running."

        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            _remove_pid(name)
            return False, f"Realtime listener for '{name}' was not running."
        except Exception as exc:
            return False, f"Failed to stop realtime listener for '{name}': {exc}"

        # Wait briefly for graceful shutdown.
        for _ in range(15):
            if not _is_process_alive(pid):
                _remove_pid(name)
                return True, f"Stopped realtime listener for '{name}' (pid {pid})."
            time.sleep(0.2)

        # Force kill if still alive.
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except Exception:
            pass

        _remove_pid(name)
        return True, f"Stopped realtime listener for '{name}' (pid {pid})."


def restart_realtime_connector(name: str) -> tuple[bool, str]:
    """Restart the realtime listener for ``name``."""
    stop_realtime_connector(name)
    return start_realtime_connector(name)


def get_realtime_status() -> list[dict]:
    """Return status information for all known realtime connectors."""
    _ensure_dirs()
    status: list[dict] = []
    desired = set(get_realtime_connector_names())

    # Known PID files (running or stale)
    pid_pattern = re.compile(r"connector-realtime-(.+)\.pid")
    for pid_path in RUN_DIR.glob("connector-realtime-*.pid"):
        match = pid_pattern.match(pid_path.name)
        if not match:
            continue
        name = match.group(1)
        pid = _read_pid(name)
        alive = pid is not None and _is_process_alive(pid)
        status.append(
            {
                "name": name,
                "pid": pid,
                "running": alive,
                "configured": name in desired,
                "log_file": str(_log_file(name)),
            }
        )

    # Configured but no PID file yet
    for name in sorted(desired):
        if not any(s["name"] == name for s in status):
            status.append(
                {
                    "name": name,
                    "pid": None,
                    "running": False,
                    "configured": True,
                    "log_file": str(_log_file(name)),
                }
            )

    status.sort(key=lambda x: x["name"])
    return status


def manage_realtime_processes() -> None:
    """Ensure configured realtime connectors are running.

    This function is called by ``kage cron run`` every minute.  It starts any
    missing realtime listeners and stops any that are no longer configured.
    """
    desired = get_realtime_connector_names()
    current_status = get_realtime_status()
    current_names = {s["name"] for s in current_status}

    for name in desired:
        if not is_realtime_running(name):
            started, msg = start_realtime_connector(name)
            print(f"[kage] {msg}")

    for name in current_names - set(desired):
        stopped, msg = stop_realtime_connector(name)
        if stopped:
            print(f"[kage] {msg}")
