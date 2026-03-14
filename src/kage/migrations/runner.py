from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import importlib
import json
import pkgutil
from pathlib import Path
from types import ModuleType
from typing import Callable

from ..config import KAGE_DB_PATH, KAGE_GLOBAL_DIR, KAGE_LOGS_DIR

INSTALL_MIGRATION_PACKAGE = "kage.migrations.install"


@dataclass(frozen=True)
class InstallMigrationContext:
    from_version: str | None
    to_version: str | None
    global_dir: Path
    db_path: Path
    logs_dir: Path
    state_path: Path


@dataclass(frozen=True)
class InstallMigrationSpec:
    migration_id: str
    summary: str
    module_name: str
    should_run: Callable[[InstallMigrationContext], bool]
    run: Callable[[InstallMigrationContext], dict | None]


@dataclass(frozen=True)
class InstallMigrationResult:
    migration_id: str
    summary: str
    details: dict


def _default_should_run(_: InstallMigrationContext) -> bool:
    return True


def _normalize_version(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    if not candidate or candidate.lower() in {"unknown", "not installed", "none"}:
        return None
    return candidate


def get_install_migration_state_path() -> Path:
    return KAGE_GLOBAL_DIR / "migrations" / "install_state.json"


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {"applied": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"applied": {}}
    if not isinstance(payload, dict):
        return {"applied": {}}
    applied = payload.get("applied")
    if not isinstance(applied, dict):
        payload["applied"] = {}
    return payload


def _save_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _module_to_spec(module: ModuleType) -> InstallMigrationSpec:
    migration_id = getattr(module, "MIGRATION_ID", module.__name__.rsplit(".", 1)[-1])
    summary = getattr(module, "SUMMARY", migration_id)
    should_run = getattr(module, "should_run", None)
    run = getattr(module, "run", None)

    if not callable(run):
        raise ValueError(f"{module.__name__} must define callable run(ctx)")
    if should_run is None:
        should_run = _default_should_run
    if not callable(should_run):
        raise ValueError(f"{module.__name__} should_run must be callable")

    return InstallMigrationSpec(
        migration_id=migration_id,
        summary=summary,
        module_name=module.__name__,
        should_run=should_run,
        run=run,
    )


def discover_install_migrations() -> list[InstallMigrationSpec]:
    package = importlib.import_module(INSTALL_MIGRATION_PACKAGE)
    specs: list[InstallMigrationSpec] = []
    for module_info in pkgutil.iter_modules(package.__path__):
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(
            f"{INSTALL_MIGRATION_PACKAGE}.{module_info.name}"
        )
        specs.append(_module_to_spec(module))
    specs.sort(key=lambda spec: spec.module_name)
    return specs


def run_install_migrations(
    from_version: str | None = None,
    to_version: str | None = None,
) -> list[InstallMigrationResult]:
    state_path = get_install_migration_state_path()
    state = _load_state(state_path)
    applied = state.setdefault("applied", {})
    ctx = InstallMigrationContext(
        from_version=_normalize_version(from_version),
        to_version=_normalize_version(to_version),
        global_dir=KAGE_GLOBAL_DIR,
        db_path=KAGE_DB_PATH,
        logs_dir=KAGE_LOGS_DIR,
        state_path=state_path,
    )

    results: list[InstallMigrationResult] = []
    for migration in discover_install_migrations():
        if migration.migration_id in applied:
            continue
        if not migration.should_run(ctx):
            continue

        details = migration.run(ctx) or {}
        result = InstallMigrationResult(
            migration_id=migration.migration_id,
            summary=migration.summary,
            details=details,
        )
        results.append(result)
        applied[migration.migration_id] = {
            "applied_at": datetime.now().astimezone().isoformat(),
            "from_version": ctx.from_version,
            "to_version": ctx.to_version,
            "details": result.details,
        }
        _save_state(state_path, state)

    return results


def install_migration_results_to_json(results: list[InstallMigrationResult]) -> str:
    return json.dumps(
        [asdict(result) for result in results], ensure_ascii=False, indent=2
    )
