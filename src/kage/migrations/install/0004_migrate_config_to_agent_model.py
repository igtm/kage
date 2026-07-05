from __future__ import annotations

from datetime import datetime
from pathlib import Path

import tomlkit

from ..runner import InstallMigrationContext
from ... import config as kage_config

MIGRATION_ID = "0004_migrate_config_to_agent_model"
SUMMARY = (
    "Remove memory_max_entries from config files, back up and replace legacy "
    "task-memory system_prompt, archive legacy .kage/memory/ directories"
)


def _config_path() -> Path:
    return kage_config.KAGE_CONFIG_PATH


def _projects_list() -> Path:
    return kage_config.KAGE_PROJECTS_LIST


def _iter_project_config_paths() -> list[Path]:
    paths: list[Path] = []
    if _projects_list().exists():
        try:
            with open(_projects_list(), "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
        except Exception:
            lines = []
        for line in lines:
            p = Path(line) / ".kage" / "config.toml"
            if p.exists():
                paths.append(p)
    return paths


def _config_has_memory_max_entries(path: Path) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = tomlkit.load(f)
    except Exception:
        return False
    return "memory_max_entries" in doc


def _strip_memory_max_entries(path: Path) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = tomlkit.load(f)
    except Exception:
        return False
    changed = False
    if "memory_max_entries" in doc:
        del doc["memory_max_entries"]
        changed = True
    if not changed:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        tomlkit.dump(doc, f)
    return True


def _iter_system_prompt_paths() -> list[Path]:
    paths: list[Path] = []
    global_md = Path.home() / ".kage" / "system_prompt.md"
    if global_md.exists():
        paths.append(global_md)
    if _projects_list().exists():
        try:
            with open(_projects_list(), "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
        except Exception:
            lines = []
        for line in lines:
            p = Path(line) / ".kage" / "system_prompt.md"
            if p.exists():
                paths.append(p)
    return paths


def _is_legacy_system_prompt(content: str) -> bool:
    markers = ["## 1. Task Decomposition", "## 2. Memory System", "task.json"]
    return any(marker in content for marker in markers)


def _backup_and_replace_system_prompt(path: Path, ts: str) -> bool:
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return False
    backup = path.with_suffix(f".md.bak.{ts}")
    if not backup.exists():
        backup.write_text(content, encoding="utf-8")
    new_content = _build_new_default_system_prompt()
    path.write_text(new_content, encoding="utf-8")
    return True


def _iter_project_memory_dirs() -> list[Path]:
    dirs: list[Path] = []
    if _projects_list().exists():
        try:
            with open(_projects_list(), "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
        except Exception:
            lines = []
        for line in lines:
            mem = Path(line) / ".kage" / "memory"
            if mem.exists() and mem.is_dir():
                dirs.append(mem)
    return dirs


def _archive_memory_dir(mem_dir: Path, ts: str) -> Path | None:
    parent = mem_dir.parent
    archive = parent / f"memory.legacy.{ts}"
    if archive.exists():
        return None
    try:
        mem_dir.rename(archive)
        return archive
    except Exception:
        return None


def _build_new_default_system_prompt() -> str:
    """新版 system_prompt を返す。default_config.toml のシステムプロンプトと同一内容。
    循環 import を避けるため default_config.toml から直接読み込む。"""
    try:
        from importlib import resources

        pkg_files = resources.files("kage")
        toml_path = pkg_files.joinpath("default_config.toml")
        with toml_path.open("r", encoding="utf-8") as f:
            doc = tomlkit.load(f)
        sp = doc.get("system_prompt")
        if sp is not None:
            return str(sp).strip() + "\n"
    except Exception:
        pass
    # fallback: 組込みの最小新版
    return _MINIMAL_NEW_SYSTEM_PROMPT.strip() + "\n"


_MINIMAL_NEW_SYSTEM_PROMPT = """
# Role: kage (影) - Autonomous Project Agent

You are 'kage', an autonomous AI agent that executes scheduled tasks within a
software project. The Agent-aware system prompt is provided by your Agent
configuration. See `kage memory list / show` for durable state.

## Execution Modes
- `continuous`: runs on every matching cron tick.
- `once`: runs once; finish everything in this run.
- `autostop`: same as continuous for execution.

## Guidelines
- Finish what you can NOW.
- Use `kage memory write/show/list/delete/search` for persistent state.
- DO NOT modify `.kage/tasks/*.md`. Use `kage task suspend/resume` for control.
"""


def should_run(ctx: InstallMigrationContext) -> bool:
    # 1. memory_max_entries がどこかに存在
    if _config_path().exists() and _config_has_memory_max_entries(_config_path()):
        return True
    for p in _iter_project_config_paths():
        if _config_has_memory_max_entries(p):
            return True
    # 2. legacy system_prompt.md が存在
    for p in _iter_system_prompt_paths():
        try:
            if _is_legacy_system_prompt(p.read_text(encoding="utf-8")):
                return True
        except Exception:
            continue
    # 3. legacy .kage/memory/ が存在
    if _iter_project_memory_dirs():
        return True
    return False


def run(ctx: InstallMigrationContext) -> dict:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    result: dict = {
        "configs_cleaned": [],
        "system_prompts_backed_up_and_replaced": [],
        "memory_dirs_archived": [],
    }
    # 1. config.toml の memory_max_entries 削除
    for path in [_config_path(), *_iter_project_config_paths()]:
        if not path.exists():
            continue
        if _config_has_memory_max_entries(path):
            if _strip_memory_max_entries(path):
                result["configs_cleaned"].append(str(path))
    # 2. system_prompt.md のバックアップ + 完全置き換え
    for path in _iter_system_prompt_paths():
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if _is_legacy_system_prompt(content):
            if _backup_and_replace_system_prompt(path, ts):
                result["system_prompts_backed_up_and_replaced"].append(str(path))
    # 3. legacy .kage/memory/ を退避
    for mem in _iter_project_memory_dirs():
        archive = _archive_memory_dir(mem, ts)
        if archive is not None:
            result["memory_dirs_archived"].append(str(archive))
    return result
