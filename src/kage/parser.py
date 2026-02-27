from enum import Enum
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel


class ExecutionMode(str, Enum):
    CONTINUOUS = "continuous"  # 常時実行（デフォルト）
    AUTOSTOP = "autostop"  # AIが完了と判断したら停止
    ONCE = "once"  # 一回実行したら停止


class ConcurrencyPolicy(str, Enum):
    ALLOW = "allow"  # 多重起動を許可（デフォルト）
    FORBID = "forbid"  # 前のが終わってなければ起動しない
    REPLACE = "replace"  # 前のを強制終了して新しく起動する


class AIEngineConfig(BaseModel):
    engine: Optional[str] = None
    args: Optional[List[str]] = None


class TaskDef(BaseModel):
    name: str
    cron: str
    active: bool = True
    mode: ExecutionMode = ExecutionMode.CONTINUOUS
    concurrency_policy: ConcurrencyPolicy = ConcurrencyPolicy.ALLOW
    timezone: Optional[str] = None  # タスク固有のタイムゾーン設定
    timeout_minutes: Optional[int] = None  # タイムアウト設定
    allowed_hours: Optional[str] = None  # 実行を許可する時間（例: "9-17,21"）
    denied_hours: Optional[str] = None  # 実行を禁止する時間（例: "0-5,23"）
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

        # 'active' field conversion if it's a string from Markdown
        if "active" in data:
            if isinstance(data["active"], str):
                data["active"] = data["active"].lower() == "true"

        # 'mode' field normalization
        if "mode" in data and isinstance(data["mode"], str):
            data["mode"] = data["mode"].lower()

        return TaskDef(**data)
    except Exception:
        return None


def _split_markdown_front_matter(text: str) -> tuple[Optional[dict], str]:
    """
    Markdown front matter (--- ... ---) と本文を分離する。

    返り値: (front_matter_dict | None, body_text)
    - front matter が無い/不正な場合は (None, original_text)
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return None, text

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
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        data[key] = val

    body = "\n".join(lines[end_idx + 1 :]).strip()
    return data, body


def parse_task_file(filepath: Path) -> List[tuple[str, TaskDef]]:
    """
    タスクファイルから TaskDef のリストを返す。
    Markdown: front matter 1ファイル1タスク（promptタスクのみ）のみをサポート。
    """
    suffix = filepath.suffix.lower()

    if suffix != ".md":
        return []

    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return []

    fm, body_prompt = _split_markdown_front_matter(text)
    if not fm:
        print(f"Markdown task requires front matter block in {filepath}")
        return []

    # md は prompt タスクのみ許可 (commandは廃止またはfrontmatterで指定)
    required = ["name", "cron"]
    if not all(k in fm and str(fm[k]).strip() for k in required):
        print(f"Markdown task requires front matter keys: {required} in {filepath}")
        return []

    if not body_prompt.strip():
        print(f"Markdown task requires non-empty body as prompt in {filepath}")
        return []

    task_data = {
        "name": fm.get("name"),
        "cron": fm.get("cron"),
        "active": fm.get("active", "true"),
        "mode": fm.get("mode", "continuous"),
        "concurrency_policy": fm.get("concurrency_policy", "allow"),
        "timezone": fm.get("timezone"),
        "timeout_minutes": int(fm.get("timeout_minutes"))
        if fm.get("timeout_minutes")
        else None,
        "allowed_hours": fm.get("allowed_hours"),
        "denied_hours": fm.get("denied_hours"),
        "prompt": body_prompt,
        "provider": fm.get("provider"),
        "parser": fm.get("parser"),
        "parser_args": fm.get("parser_args"),
    }

    t = _parse_task_dict(task_data)
    return [("task", t)] if t else []


def load_project_tasks(project_dir: Path) -> List[tuple[Path, LocalTask]]:
    tasks_dir = project_dir / ".kage" / "tasks"
    if not tasks_dir.exists():
        return []

    tasks = []

    for task_file in sorted(list(tasks_dir.glob("*.md"))):
        for _, task_def in parse_task_file(task_file):
            tasks.append((task_file, LocalTask(task=task_def)))
    return tasks
