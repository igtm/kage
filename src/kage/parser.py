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

def parse_task_file(filepath: Path) -> Optional[LocalTask]:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            doc = tomlkit.load(f)
            # handle dict unpacking
            return LocalTask(**doc)
    except Exception as e:
        print(f"Error parsing {filepath}: {e}")
        return None

def load_project_tasks(project_dir: Path) -> List[tuple[Path, LocalTask]]:
    tasks_dir = project_dir / ".kage" / "tasks"
    if not tasks_dir.exists():
        return []
    
    tasks = []
    for toml_file in tasks_dir.glob("*.toml"):
        parsed = parse_task_file(toml_file)
        if parsed is not None:
            tasks.append((toml_file, parsed))
    return tasks
