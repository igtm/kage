from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel
import tomlkit


class AIEngineConfig(BaseModel):
    engine: Optional[str] = None
    args: Optional[List[str]] = None


class TaskDef(BaseModel):
    name: str
    cron: str
    command: Optional[str] = None
    shell: Optional[str] = None
    prompt: Optional[str] = None
    provider: Optional[str] = None
    command_template: Optional[List[str]] = None
    parser: Optional[str] = None
    parser_args: Optional[str] = None
    ai: Optional[AIEngineConfig] = None


class LocalTask(BaseModel):
    task: TaskDef


def _parse_task_dict(data: dict) -> Optional[TaskDef]:
    """dict から TaskDef を生成する。ai フィールドは入れ子 dict を許容。"""
    try:
        if "ai" in data and isinstance(data["ai"], dict):
            data = dict(data)
            data["ai"] = AIEngineConfig(**data["ai"])
        return TaskDef(**data)
    except Exception:
        return None


def _parse_front_matter(text: str) -> Optional[dict]:
    """
    Markdown front matter (--- ... ---) を簡易パースする。
    形式は `key: value` のみ対応（ネストは非対応）。
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return None

    data: dict = {}
    for raw in lines[1:end_idx]:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        key = k.strip()
        val = v.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        data[key] = val
    return data


def parse_task_file(filepath: Path) -> List[tuple[str, TaskDef]]:
    """
    タスクファイルから TaskDef のリストを返す。

    対応フォーマット:
      1. TOML: 単一タスク [task]
      2. TOML: 複数タスク [task_xxx] 群
      3. Markdown: front matter 1ファイル1タスク（promptタスクのみ）
    """
    suffix = filepath.suffix.lower()

    # Markdown front matter (1 task / file, prompt-only)
    if suffix == ".md":
        try:
            text = filepath.read_text(encoding="utf-8")
        except Exception as e:
            print(f"Error reading {filepath}: {e}")
            return []

        fm = _parse_front_matter(text)
        if not fm:
            print(f"No valid front matter found in {filepath}")
            return []

        # md は prompt タスクのみ許可
        if "command" in fm:
            print(f"Markdown task must be prompt-only (command is not allowed): {filepath}")
            return []

        required = ["name", "cron", "prompt"]
        if not all(k in fm and str(fm[k]).strip() for k in required):
            print(f"Markdown task requires front matter keys: {required} in {filepath}")
            return []

        task_data = {
            "name": fm.get("name"),
            "cron": fm.get("cron"),
            "prompt": fm.get("prompt"),
            "provider": fm.get("provider"),
            "parser": fm.get("parser"),
            "parser_args": fm.get("parser_args"),
        }

        t = _parse_task_dict(task_data)
        return [("task", t)] if t else []

    # TOML
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            doc = tomlkit.load(f)
        data = doc.unwrap() if hasattr(doc, "unwrap") else dict(doc)
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return []

    results = []

    # フォーマット 1: [task] セクション
    if "task" in data and isinstance(data["task"], dict):
        t = _parse_task_dict(data["task"])
        if t:
            results.append(("task", t))
        return results

    # フォーマット 2: [task_xxx] セクション群
    for key, val in data.items():
        if key.startswith("task") and isinstance(val, dict) and "name" in val and "cron" in val:
            t = _parse_task_dict(val)
            if t:
                results.append((key, t))

    if not results:
        print(f"No valid tasks found in {filepath}")
    return results


def load_project_tasks(project_dir: Path) -> List[tuple[Path, LocalTask]]:
    tasks_dir = project_dir / ".kage" / "tasks"
    if not tasks_dir.exists():
        return []

    tasks = []

    for task_file in sorted(list(tasks_dir.glob("*.toml")) + list(tasks_dir.glob("*.md"))):
        for _, task_def in parse_task_file(task_file):
            tasks.append((task_file, LocalTask(task=task_def)))
    return tasks
