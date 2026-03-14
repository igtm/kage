import subprocess
import shutil
import typer
import sys
import os
import re
from pathlib import Path


def get_platform():
    return sys.platform


def get_kage_path():
    return shutil.which("kage") or "kage"


SCHEDULER_COMMAND = ("cron", "run")
LEGACY_SCHEDULER_COMMAND = ("run",)
LEGACY_SCHEDULER_PATTERN = re.compile(
    r"(?P<exe>(?:\"[^\"]*kage\"|'[^']*kage'|\S*kage))\s+run\b"
)


def _scheduler_command_for_path(kage_path: str) -> str:
    return f"{kage_path} {' '.join(SCHEDULER_COMMAND)}"


def _line_has_scheduler_entry(line: str) -> bool:
    return "kage run" in line or "kage cron run" in line


def _line_has_legacy_scheduler_entry(line: str) -> bool:
    return "kage cron run" not in line and "kage run" in line


def _read_linux_crontab() -> str:
    try:
        return subprocess.check_output(
            ["crontab", "-l"], text=True, stderr=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError:
        return ""


def _write_linux_crontab(content: str) -> bool:
    proc = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
    proc.communicate(content)
    return proc.returncode == 0


def _rewrite_scheduler_line(line: str) -> str:
    if not _line_has_legacy_scheduler_entry(line):
        return line
    return LEGACY_SCHEDULER_PATTERN.sub(r"\g<exe> cron run", line, count=1)


def _linux_scheduler_needs_migration() -> bool:
    return any(
        _line_has_legacy_scheduler_entry(line)
        for line in _read_linux_crontab().splitlines()
    )


def migrate_scheduler_command_if_needed() -> dict:
    platform = get_platform()
    if platform.startswith("linux"):
        current_cron = _read_linux_crontab()
        if not current_cron:
            return {"updated": False, "platform": "linux"}
        lines = current_cron.splitlines()
        if not any(_line_has_legacy_scheduler_entry(line) for line in lines):
            return {"updated": False, "platform": "linux"}
        new_cron = "\n".join(_rewrite_scheduler_line(line) for line in lines) + "\n"
        if not _write_linux_crontab(new_cron):
            raise RuntimeError("Failed to update crontab")
        return {"updated": True, "platform": "linux"}

    if platform == "darwin":
        if not LAUNCHD_PLIST_PATH.exists():
            return {"updated": False, "platform": "darwin"}
        plist_content = LAUNCHD_PLIST_PATH.read_text(encoding="utf-8")
        if "<string>cron</string>" in plist_content:
            return {"updated": False, "platform": "darwin"}
        _setup_macos_launchd()
        return {"updated": True, "platform": "darwin"}

    return {"updated": False, "platform": platform}


# --- Linux (cron) Implementation ---


def _setup_linux_cron():
    """Add kage cron run to crontab with configurable interval."""
    from .config import get_global_config

    cfg = get_global_config()
    interval = max(1, cfg.cron_interval_minutes)

    # cron式を間隔から生成
    if interval == 1:
        cron_expr = "* * * * *"
    else:
        cron_expr = f"*/{interval} * * * *"

    current_cron = _read_linux_crontab()
    if current_cron and any(
        _line_has_legacy_scheduler_entry(line) for line in current_cron.splitlines()
    ):
        new_cron = (
            "\n".join(
                _rewrite_scheduler_line(line) for line in current_cron.splitlines()
            )
            + "\n"
        )
        if _write_linux_crontab(new_cron):
            typer.echo("Updated existing kage crontab entry to use 'kage cron run'.")
        else:
            typer.echo("Failed to update crontab.")
        return

    if current_cron and any(
        _line_has_scheduler_entry(line) for line in current_cron.splitlines()
    ):
        typer.echo("Crontab already has a kage entry.")
        return

    kage_path = get_kage_path()
    log_file = Path.home() / ".kage" / "cron.log"
    new_job = (
        f"{cron_expr} {_scheduler_command_for_path(kage_path)} >> {log_file} 2>&1\n"
    )

    new_cron = current_cron
    if current_cron and not current_cron.endswith("\n"):
        new_cron += "\n"
    new_cron += new_job

    try:
        if _write_linux_crontab(new_cron):
            typer.echo(f"Successfully added kage to crontab (every {interval} min).")
        else:
            typer.echo("Failed to update crontab.")
    except Exception as e:
        typer.echo(f"Failed to update crontab: {e}")


def _remove_linux_cron():
    current_cron = _read_linux_crontab()
    if not current_cron:
        typer.echo("No crontab found.")
        return

    lines = current_cron.splitlines()
    new_lines = [line for line in lines if not _line_has_scheduler_entry(line)]

    if len(lines) == len(new_lines):
        typer.echo("No kage entry found in crontab.")
        return

    new_cron = "\n".join(new_lines) + ("\n" if new_lines else "")

    try:
        if not new_lines:
            subprocess.run(["crontab", "-r"])
        else:
            _write_linux_crontab(new_cron)
        typer.echo("Successfully removed kage from crontab.")
    except Exception as e:
        typer.echo(f"Failed to update crontab: {e}")


def _stop_linux_cron():
    """Disable kage entry by commenting it out."""
    current_cron = _read_linux_crontab()
    if not current_cron:
        typer.echo("No crontab found.")
        return

    lines = current_cron.splitlines()
    new_lines = []
    found = False
    for line in lines:
        if _line_has_scheduler_entry(line) and not line.strip().startswith("#"):
            new_lines.append(f"# {line}")
            found = True
        else:
            new_lines.append(line)

    if not found:
        typer.echo("kage is already stopped or not installed.")
        return

    new_cron = "\n".join(new_lines) + "\n"
    _write_linux_crontab(new_cron)
    typer.echo("kage background tasks stopped (commented out in crontab).")


def _start_linux_cron():
    """Enable kage entry by uncommenting it."""
    current_cron = _read_linux_crontab()
    if not current_cron:
        typer.echo("No crontab found.")
        return

    lines = current_cron.splitlines()
    new_lines = []
    found = False
    for line in lines:
        if _line_has_scheduler_entry(line) and line.strip().startswith("#"):
            new_lines.append(line.replace("#", "", 1).strip())
            found = True
        else:
            new_lines.append(line)

    if not found:
        if any(_line_has_scheduler_entry(line) for line in lines):
            typer.echo("kage is already started.")
        else:
            typer.echo("kage is not installed in crontab. Use install first.")
        return

    new_cron = "\n".join(new_lines) + "\n"
    _write_linux_crontab(new_cron)
    typer.echo("kage background tasks started (uncommented in crontab).")


# --- macOS (launchd) Implementation ---

LAUNCHD_PLIST_ID = "com.user.kage"
LAUNCHD_PLIST_PATH = (
    Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_PLIST_ID}.plist"
)


def _launchd_domain() -> str:
    return f"gui/{os.getuid()}"


def _launchd_label() -> str:
    return f"{_launchd_domain()}/{LAUNCHD_PLIST_ID}"


def _bootout_macos_launchd():
    """Unload launchd agent if loaded. Ignore errors."""
    subprocess.run(
        ["launchctl", "bootout", _launchd_label()],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["launchctl", "bootout", _launchd_domain(), str(LAUNCHD_PLIST_PATH)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Fallback for older launchctl behavior.
    subprocess.run(
        ["launchctl", "unload", str(LAUNCHD_PLIST_PATH)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _setup_macos_launchd():
    """Create a launchd plist to run kage at a configurable interval."""
    from .config import get_global_config

    cfg = get_global_config()

    # Use macOS specific interval (seconds) if provided, otherwise fallback to minutes-based conversion
    if cfg.darwin_launchd_interval_seconds is not None:
        # Safety: Must be at least 15 seconds
        interval_seconds = max(15, cfg.darwin_launchd_interval_seconds)
    else:
        interval_seconds = max(60, cfg.cron_interval_minutes * 60)

    keep_alive = cfg.darwin_launchd_keep_alive

    kage_path = get_kage_path()
    log_file = Path.home() / ".kage" / "launchd.log"

    env_block = ""
    if cfg.env_path:
        env_block = f"""
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{cfg.env_path}</string>
    </dict>"""

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHD_PLIST_ID}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{kage_path}</string>
        <string>cron</string>
        <string>run</string>
    </array>
    <key>StartInterval</key>
    <integer>{interval_seconds}</integer>
    <key>KeepAlive</key>
    <{"true" if keep_alive else "false"}/>
    <key>StandardOutPath</key>
    <string>{log_file}</string>
    <key>StandardErrorPath</key>
    <string>{log_file}</string>{env_block}
</dict>
</plist>
"""

    LAUNCHD_PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAUNCHD_PLIST_PATH.write_text(plist_content)

    try:
        _bootout_macos_launchd()
        subprocess.run(
            ["launchctl", "bootstrap", _launchd_domain(), str(LAUNCHD_PLIST_PATH)],
            check=True,
        )
        subprocess.run(["launchctl", "kickstart", "-k", _launchd_label()], check=True)
        typer.echo(
            f"Successfully registered kage to launchd (every {cfg.cron_interval_minutes} min). Agent ID: {LAUNCHD_PLIST_ID}"
        )
    except Exception as e:
        typer.echo(f"Failed to register launchd agent: {e}")


def _remove_macos_launchd():
    if not LAUNCHD_PLIST_PATH.exists():
        typer.echo("No launchd agent found for kage.")
        return

    try:
        _bootout_macos_launchd()
        LAUNCHD_PLIST_PATH.unlink()
        typer.echo("Successfully removed kage from launchd.")
    except Exception as e:
        typer.echo(f"Failed to remove launchctl agent: {e}")


def _start_macos_launchd():
    if not LAUNCHD_PLIST_PATH.exists():
        typer.echo("kage launchd agent is not installed. Use install first.")
        return
    try:
        # bootstrap may fail when already loaded, so ignore and always kickstart.
        subprocess.run(
            ["launchctl", "bootstrap", _launchd_domain(), str(LAUNCHD_PLIST_PATH)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(["launchctl", "kickstart", "-k", _launchd_label()], check=True)
        typer.echo("kage background tasks started (launchctl loaded).")
    except Exception as e:
        typer.echo(f"Failed to start launchctl agent: {e}")


def _stop_macos_launchd():
    if not LAUNCHD_PLIST_PATH.exists():
        typer.echo("kage launchd agent is not installed.")
        return
    try:
        result = subprocess.run(
            ["launchctl", "bootout", _launchd_label()],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            subprocess.run(
                ["launchctl", "bootout", _launchd_domain(), str(LAUNCHD_PLIST_PATH)],
                check=True,
            )
        typer.echo("kage background tasks stopped (launchctl unloaded).")
    except Exception as e:
        typer.echo(f"Failed to stop launchctl agent: {e}")


# --- Public API ---


def install():
    typer.echo("Installing kage cron (system scheduler)...")

    # PATHを保存して、cron実行時に復元できるようにする
    from .config import set_config_value

    current_path = os.environ.get("PATH", "")
    if current_path:
        set_config_value("env_path", current_path, is_global=True)
        typer.echo("Saved current PATH to global config (env_path).")

    plat = get_platform()
    if plat.startswith("linux"):
        _setup_linux_cron()
    elif plat == "darwin":
        _setup_macos_launchd()


def remove():
    plat = get_platform()
    if plat == "linux":
        _remove_linux_cron()
    elif plat == "darwin":
        _remove_macos_launchd()


def start():
    platform = get_platform()
    if platform == "darwin":
        _start_macos_launchd()
    else:
        _start_linux_cron()


def stop():
    platform = get_platform()
    if platform == "darwin":
        _stop_macos_launchd()
    else:
        _stop_linux_cron()


def restart():
    stop()
    start()


def status():
    platform = get_platform()
    if platform == "darwin":
        if LAUNCHD_PLIST_PATH.exists():
            try:
                result = subprocess.run(
                    ["launchctl", "print", _launchd_label()],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if result.returncode == 0:
                    typer.echo(
                        f"[ACTIVE] launchd agent '{LAUNCHD_PLIST_ID}' is loaded."
                    )
                else:
                    typer.echo(
                        f"[STOPPED] launchd agent exists at {LAUNCHD_PLIST_PATH} but is not loaded."
                    )
            except Exception:
                typer.echo(f"[ACTIVE] launchd agent present at {LAUNCHD_PLIST_PATH}")
        else:
            typer.echo("[NOT INSTALLED] No launchd agent found.")
    else:
        try:
            current_cron = _read_linux_crontab()
            if any(
                _line_has_scheduler_entry(line) for line in current_cron.splitlines()
            ):
                if any(
                    line.strip().startswith("#") and _line_has_scheduler_entry(line)
                    for line in current_cron.splitlines()
                ):
                    typer.echo(
                        "[STOPPED] kage entry exists but is commented out in crontab."
                    )
                else:
                    typer.echo("[ACTIVE] kage entry found in crontab.")
            else:
                typer.echo("[NOT INSTALLED] No kage entry in crontab.")
        except subprocess.CalledProcessError:
            typer.echo("[NOT INSTALLED] No crontab found.")
