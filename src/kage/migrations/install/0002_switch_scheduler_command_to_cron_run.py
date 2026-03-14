from __future__ import annotations

from ... import daemon
from ..runner import InstallMigrationContext

MIGRATION_ID = "0002_switch_scheduler_command_to_cron_run"
SUMMARY = "Migrate installed scheduler entries from 'kage run' to 'kage cron run'"


def should_run(_: InstallMigrationContext) -> bool:
    platform = daemon.get_platform()
    if platform.startswith("linux"):
        return daemon._linux_scheduler_needs_migration()
    if platform == "darwin" and daemon.LAUNCHD_PLIST_PATH.exists():
        try:
            content = daemon.LAUNCHD_PLIST_PATH.read_text(encoding="utf-8")
        except Exception:
            return False
        return (
            "<string>cron</string>" not in content and "<string>run</string>" in content
        )
    return False


def run(_: InstallMigrationContext) -> dict:
    return daemon.migrate_scheduler_command_if_needed()
