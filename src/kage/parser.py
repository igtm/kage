from enum import Enum
import json
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel
import pydantic


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
    denied_hours: Optional[str] = pydantic.Field(
        default=None, description="実行を禁止する時間帯（例: '0-5,12'）"
    )
    suspended_until: Optional[str] = pydantic.Field(
        default=None,
        description="この日時までタスクの新規実行を停止する（ISO date/datetime）",
    )
    suspended_reason: Optional[str] = pydantic.Field(
        default=None, description="タスク停止の理由"
    )
    notify_connectors: Optional[list[str]] = pydantic.Field(
        default=None,
        description="実行完了時に結果を通知するコネクター名のリスト（例: ['discord']）",
    )
    command: Optional[str] = pydantic.Field(
        default=None, description="AIではなく通常のシェルコマンドを実行する場合"
    )
    shell: Optional[str] = None
    working_dir: Optional[str] = None
    prompt: Optional[str] = None
    provider: Optional[str] = None
    command_template: Optional[List[str]] = None
    parser: Optional[str] = None
    parser_args: Optional[str] = None
    ai: Optional[AIEngineConfig] = None


class LocalTask(BaseModel):
    task: TaskDef


def _normalize_notify_connectors(value) -> Optional[list[str]]:
    if value is None:
        return None
    if isinstance(value, list):
        if not all(isinstance(v, str) for v in value):
            return value
        return [v.strip() for v in value if v.strip()]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if stripped.startswith("[") and stripped.endswith("]"):
            inner = stripped[1:-1].strip()
            if not inner:
                return []
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return [
                    v.strip().strip("\"'")
                    for v in inner.split(",")
                    if v.strip().strip("\"'")
                ]
            else:
                if isinstance(parsed, list):
                    if not all(isinstance(v, str) for v in parsed):
                        return parsed
                    return [v.strip() for v in parsed if v.strip()]
        return [v.strip() for v in stripped.split(",") if v.strip()]
    return None


def _parse_task_dict(data: dict) -> Optional[TaskDef]:
    """dict から TaskDef を生成する。ai フィールドは入れ子 dict を許容。"""
    try:
        # Pydantic requires standard types, so we cleanly unwrap tomlkit proxy objects
        clean_data = getattr(data, "unwrap", lambda: dict(data))()

        if "ai" in clean_data and isinstance(clean_data["ai"], dict):
            clean_data["ai"] = AIEngineConfig(**clean_data["ai"])

        data = clean_data

        # 'active' field conversion if it's a string from Markdown
        if "active" in data:
            if isinstance(data["active"], str):
                data["active"] = data["active"].lower() == "true"

        # 'mode' field normalization
        if "mode" in data and isinstance(data["mode"], str):
            data["mode"] = data["mode"].lower()

        # 'connector' / 'connectors' alias mapping
        if data.get("connector") is not None:
            val = data["connector"]
            del data["connector"]
            data["notify_connectors"] = _normalize_notify_connectors(val)
        elif data.get("connectors") is not None:
            val = data["connectors"]
            del data["connectors"]
            data["notify_connectors"] = _normalize_notify_connectors(val)

        if "notify_connectors" in data:
            data["notify_connectors"] = _normalize_notify_connectors(
                data["notify_connectors"]
            )

        return TaskDef(**data)
    except Exception:
        import traceback

        traceback.print_exc()
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

    対応フォーマット:
      1. TOML: 単一タスク [task]
      2. TOML: 複数タスク [task_xxx] 群
      3. Markdown: front matter 1ファイル1タスク
    """
    suffix = filepath.suffix.lower()

    # Markdown front matter (1 task / file)
    if suffix == ".md":
        try:
            text = filepath.read_text(encoding="utf-8")
        except Exception as e:
            print(f"Error reading {filepath}: {e}")
            return []

        fm, body_prompt = _split_markdown_front_matter(text)
        if not fm:
            print(f"No valid front matter found in {filepath}")
            return []

        required = ["name", "cron"]
        if not all(k in fm and str(fm[k]).strip() for k in required):
            print(f"Markdown task requires front matter keys: {required} in {filepath}")
            return []

        command = fm.get("command")
        if isinstance(command, str):
            command = command.strip() or None

        prompt = body_prompt.strip() if body_prompt else None
        if prompt and command:
            print(
                f"Markdown task cannot define both body prompt and command: {filepath}"
            )
            return []

        if not prompt and not command:
            print(f"Markdown task requires either a body prompt or command: {filepath}")
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
            "suspended_until": fm.get("suspended_until"),
            "suspended_reason": fm.get("suspended_reason"),
            "command": command,
            "shell": fm.get("shell"),
            "working_dir": fm.get("working_dir"),
            "prompt": prompt,
            "provider": fm.get("provider"),
            "parser": fm.get("parser"),
            "parser_args": fm.get("parser_args"),
            "connector": fm.get("connector"),
            "connectors": fm.get("connectors"),
            "notify_connectors": fm.get("notify_connectors"),
        }

        t = _parse_task_dict(task_data)
        return [("task", t)] if t else []

    # TOML
    try:
        import tomlkit

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
        if (
            key.startswith("task")
            and isinstance(val, dict)
            and "name" in val
            and "cron" in val
        ):
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

    for task_file in sorted(
        list(tasks_dir.glob("*.toml")) + list(tasks_dir.glob("*.md"))
    ):
        for _, task_def in parse_task_file(task_file):
            tasks.append((task_file, LocalTask(task=task_def)))

    return tasks
