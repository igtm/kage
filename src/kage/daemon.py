import subprocess
import shutil
import typer
import sys
import os
from pathlib import Path

def get_platform():
    return sys.platform

def get_kage_path():
    return shutil.which("kage") or "kage"

# --- Linux (cron) Implementation ---

def _setup_linux_cron():
    """Add kage run to crontab with configurable interval."""
    from .config import get_global_config
    cfg = get_global_config()
    interval = max(1, cfg.daemon_interval_minutes)
    
    # cron式を間隔から生成
    if interval == 1:
        cron_expr = "* * * * *"
    else:
        cron_expr = f"*/{interval} * * * *"

    try:
        current_cron = subprocess.check_output(["crontab", "-l"], text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        current_cron = ""

    if "kage run" in current_cron:
        typer.echo("Crontab already has a kage entry.")
        return

    kage_path = get_kage_path()
    log_file = Path.home() / ".kage" / "cron.log"
    new_job = f"{cron_expr} {kage_path} run >> {log_file} 2>&1\n"
    
    new_cron = current_cron
    if current_cron and not current_cron.endswith("\n"):
        new_cron += "\n"
    new_cron += new_job

    try:
        proc = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
        proc.communicate(new_cron)
        if proc.returncode == 0:
            typer.echo(f"Successfully added kage to crontab (every {interval} min).")
        else:
            typer.echo("Failed to update crontab.")
    except Exception as e:
        typer.echo(f"Failed to update crontab: {e}")

def _remove_linux_cron():
    try:
        current_cron = subprocess.check_output(["crontab", "-l"], text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        typer.echo("No crontab found.")
        return

    lines = current_cron.splitlines()
    new_lines = [line for line in lines if "kage run" not in line]
    
    if len(lines) == len(new_lines):
        typer.echo("No kage entry found in crontab.")
        return

    new_cron = "\n".join(new_lines) + ("\n" if new_lines else "")
    
    try:
        if not new_lines:
            subprocess.run(["crontab", "-r"])
        else:
            proc = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
            proc.communicate(new_cron)
        typer.echo("Successfully removed kage from crontab.")
    except Exception as e:
        typer.echo(f"Failed to update crontab: {e}")

def _stop_linux_cron():
    """Disable kage entry by commenting it out."""
    try:
        current_cron = subprocess.check_output(["crontab", "-l"], text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        typer.echo("No crontab found.")
        return

    lines = current_cron.splitlines()
    new_lines = []
    found = False
    for line in lines:
        if "kage run" in line and not line.strip().startswith("#"):
            new_lines.append(f"# {line}")
            found = True
        else:
            new_lines.append(line)
    
    if not found:
        typer.echo("kage is already stopped or not installed.")
        return

    new_cron = "\n".join(new_lines) + "\n"
    proc = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
    proc.communicate(new_cron)
    typer.echo("kage background tasks stopped (commented out in crontab).")

def _start_linux_cron():
    """Enable kage entry by uncommenting it."""
    try:
        current_cron = subprocess.check_output(["crontab", "-l"], text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        typer.echo("No crontab found.")
        return

    lines = current_cron.splitlines()
    new_lines = []
    found = False
    for line in lines:
        if "kage run" in line and line.strip().startswith("#"):
            new_lines.append(line.replace("#", "", 1).strip())
            found = True
        else:
            new_lines.append(line)
    
    if not found:
        if any("kage run" in l for l in lines):
            typer.echo("kage is already started.")
        else:
            typer.echo("kage is not installed in crontab. Use install first.")
        return

    new_cron = "\n".join(new_lines) + "\n"
    proc = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
    proc.communicate(new_cron)
    typer.echo("kage background tasks started (uncommented in crontab).")

# --- macOS (launchd) Implementation ---

LAUNCHD_PLIST_ID = "com.user.kage"
LAUNCHD_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_PLIST_ID}.plist"

def _setup_macos_launchd():
    """Create a launchd plist to run kage at a configurable interval."""
    from .config import get_global_config
    cfg = get_global_config()
    interval_seconds = max(60, cfg.daemon_interval_minutes * 60)

    kage_path = get_kage_path()
    log_file = Path.home() / ".kage" / "launchd.log"
    
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHD_PLIST_ID}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{kage_path}</string>
        <string>run</string>
    </array>
    <key>StartInterval</key>
    <integer>{interval_seconds}</integer>
    <key>StandardOutPath</key>
    <string>{log_file}</string>
    <key>StandardErrorPath</key>
    <string>{log_file}</string>
</dict>
</plist>
"""
    
    LAUNCHD_PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAUNCHD_PLIST_PATH.write_text(plist_content)
    
    try:
        # Unload if already loaded (ignore error)
        subprocess.run(["launchctl", "unload", str(LAUNCHD_PLIST_PATH)], stderr=subprocess.DEVNULL)
        # Load and start
        subprocess.run(["launchctl", "load", str(LAUNCHD_PLIST_PATH)], check=True)
        typer.echo(f"Successfully registered kage to launchd (every {cfg.daemon_interval_minutes} min). Agent ID: {LAUNCHD_PLIST_ID}")
    except Exception as e:
        typer.echo(f"Failed to register launchd agent: {e}")

def _remove_macos_launchd():
    if not LAUNCHD_PLIST_PATH.exists():
        typer.echo("No launchd agent found for kage.")
        return
        
    try:
        subprocess.run(["launchctl", "unload", str(LAUNCHD_PLIST_PATH)], stderr=subprocess.DEVNULL)
        LAUNCHD_PLIST_PATH.unlink()
        typer.echo("Successfully removed kage from launchd.")
    except Exception as e:
        typer.echo(f"Failed to remove launchctl agent: {e}")

def _start_macos_launchd():
    if not LAUNCHD_PLIST_PATH.exists():
        typer.echo("kage launchd agent is not installed. Use install first.")
        return
    try:
        subprocess.run(["launchctl", "load", str(LAUNCHD_PLIST_PATH)], check=True)
        typer.echo("kage background tasks started (launchctl loaded).")
    except Exception as e:
        typer.echo(f"Failed to start launchctl agent: {e}")

def _stop_macos_launchd():
    if not LAUNCHD_PLIST_PATH.exists():
        typer.echo("kage launchd agent is not installed.")
        return
    try:
        subprocess.run(["launchctl", "unload", str(LAUNCHD_PLIST_PATH)], check=True)
        typer.echo("kage background tasks stopped (launchctl unloaded).")
    except Exception as e:
        typer.echo(f"Failed to stop launchctl agent: {e}")

# --- Public API ---

def install():
    typer.echo("Installing kage daemon...")

    # PATHを保存して、cron実行時に復元できるようにする
    from .config import set_config_value
    current_path = os.environ.get("PATH", "")
    if current_path:
        set_config_value("env_path", current_path, is_global=True)
        typer.echo("Saved current PATH to global config (env_path).")

    plat = get_platform()
    if plat.startswith("linux"):
        _setup_linux_cron()
    elif plat == "macos":
        _setup_macos_launchd()

def remove():
    plat = get_platform()
    if plat == "linux":
        _remove_linux_cron()
    elif plat == "macos":
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
            # Check if actually loaded
            try:
                out = subprocess.check_output(["launchctl", "list"], text=True)
                if LAUNCHD_PLIST_ID in out:
                    typer.echo(f"[ACTIVE] launchd agent '{LAUNCHD_PLIST_ID}' is loaded.")
                else:
                    typer.echo(f"[STOPPED] launchd agent exists at {LAUNCHD_PLIST_PATH} but is not loaded.")
            except:
                typer.echo(f"[ACTIVE] launchd agent present at {LAUNCHD_PLIST_PATH}")
        else:
            typer.echo("[NOT INSTALLED] No launchd agent found.")
    else:
        try:
            current_cron = subprocess.check_output(["crontab", "-l"], text=True, stderr=subprocess.DEVNULL)
            if "kage run" in current_cron:
                if any(line.strip().startswith("#") and "kage run" in line for line in current_cron.splitlines()):
                    typer.echo("[STOPPED] kage entry exists but is commented out in crontab.")
                else:
                    typer.echo("[ACTIVE] kage entry found in crontab.")
            else:
                typer.echo("[NOT INSTALLED] No kage entry in crontab.")
        except subprocess.CalledProcessError:
            typer.echo("[NOT INSTALLED] No crontab found.")
