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
    except Exception as e:
        return None

def parse_task_file(filepath: Path) -> List[tuple[str, TaskDef]]:
    """
    TOML ファイルから TaskDef のリストを返す。
    
    対応フォーマット:
      1. 単一タスク: [task] セクション
      2. 複数タスク: [task_xxx] セクション群 (キーが 'task' で始まる)
    """
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
    for toml_file in tasks_dir.glob("*.toml"):
        for section_key, task_def in parse_task_file(toml_file):
            tasks.append((toml_file, LocalTask(task=task_def)))
    return tasks
