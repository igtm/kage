from __future__ import annotations

from datetime import datetime
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from .ai.chat import clean_ai_reply, get_thinking_tag
from .config import (
    build_model_args,
    get_global_config,
    get_system_prompt,
    render_command_template,
)
from .parser import TaskDef

COMPILED_SCRIPT_SUFFIX = ".lock.sh"
COMPILED_METADATA_PREFIX = "# kage-"
COMPILED_LOCK_VERSION = "1"


def compiled_task_path(task_file: Path) -> Path:
    return task_file.with_suffix(COMPILED_SCRIPT_SUFFIX)


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _split_task_source(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "", text.strip()

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return "", text.strip()

    frontmatter = "\n".join(lines[1:end_idx]).strip()
    body = "\n".join(lines[end_idx + 1 :]).strip()
    return frontmatter, body


def get_task_source_fingerprints(task_file: Path) -> dict[str, str]:
    source_text = task_file.read_text(encoding="utf-8")
    frontmatter_text, prompt_text = _split_task_source(source_text)
    return {
        "source_hash": _sha256_text(source_text),
        "frontmatter_hash": _sha256_text(frontmatter_text),
        "prompt_hash": prompt_hash(prompt_text),
    }


def read_compiled_metadata(script_path: Path) -> dict[str, str]:
    if not script_path.exists():
        return {}

    metadata: dict[str, str] = {}
    try:
        with script_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.startswith(COMPILED_METADATA_PREFIX):
                    if metadata:
                        break
                    continue
                raw = line[len(COMPILED_METADATA_PREFIX) :].strip()
                if ":" not in raw:
                    continue
                key, value = raw.split(":", 1)
                metadata[key.strip().replace("-", "_")] = value.strip()
    except Exception:
        return {}
    return metadata


def compiled_task_status(task: TaskDef, task_file: Path | None) -> dict | None:
    if not task.prompt or task.command or task_file is None:
        return None

    path = compiled_task_path(task_file)
    exists = path.exists()
    metadata = read_compiled_metadata(path) if exists else {}
    fingerprints = get_task_source_fingerprints(task_file)
    matches_prompt = (
        exists and metadata.get("prompt_hash") == fingerprints["prompt_hash"]
    )
    matches_frontmatter = (
        exists and metadata.get("frontmatter_hash") == fingerprints["frontmatter_hash"]
    )
    matches_source = (
        exists and metadata.get("source_hash") == fingerprints["source_hash"]
    )
    is_fresh = (
        exists
        and metadata.get("lock_version") == COMPILED_LOCK_VERSION
        and matches_prompt
        and matches_frontmatter
        and matches_source
    )
    return {
        "path": path,
        "exists": exists,
        "metadata": metadata,
        **fingerprints,
        "matches_prompt": matches_prompt,
        "matches_frontmatter": matches_frontmatter,
        "matches_source": matches_source,
        "is_fresh": is_fresh,
        "needs_compile": not exists or not is_fresh,
    }


def compiled_task_indicator(task: TaskDef, task_file: Path | None) -> dict:
    if not task.prompt or task.command or task_file is None:
        return {
            "state": "n/a",
            "label": "-",
            "path": None,
            "exists": False,
            "is_fresh": False,
            "needs_compile": False,
        }

    status = compiled_task_status(task, task_file)
    assert status is not None
    if not status["exists"]:
        state = "none"
        label = "none"
    elif status["is_fresh"]:
        state = "fresh"
        label = "fresh"
    else:
        state = "stale"
        label = "stale"

    return {
        "state": state,
        "label": label,
        "path": str(status["path"]),
        "exists": status["exists"],
        "is_fresh": status["is_fresh"],
        "needs_compile": status["needs_compile"],
        "details": status,
    }


def _resolve_task_working_dir(
    project_dir: Path, task: TaskDef, task_file: Path | None = None
) -> Path:
    if not task.working_dir:
        return project_dir

    working_dir = Path(task.working_dir).expanduser()
    if working_dir.is_absolute():
        return working_dir

    base_dir = task_file.parent if task_file else project_dir
    return (base_dir.resolve() / working_dir).resolve()


def _strip_script_wrappers(text: str) -> str:
    cleaned = clean_ai_reply(text).strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    if cleaned.startswith("#!/"):
        cleaned = "\n".join(cleaned.splitlines()[1:]).strip()
    return cleaned


def _build_compile_request(
    project_dir: Path,
    task: TaskDef,
    task_file: Path,
) -> tuple[list[str], Path, dict[str, str], str]:
    global_config = get_global_config(workspace_dir=project_dir)
    execution_dir = _resolve_task_working_dir(project_dir, task, task_file)
    system_prompt = get_system_prompt(workspace_dir=project_dir)
    engine_name = task.provider or global_config.default_ai_engine
    if not engine_name:
        raise ValueError("AI engine is not configured for compilation.")

    provider = global_config.providers.get(engine_name)
    extra_args = task.ai.args if task.ai and task.ai.args else []
    thinking_tag = get_thinking_tag(engine_name)
    compile_prompt = "\n\n".join(
        [
            system_prompt.replace("{thinking_tag}", thinking_tag).strip(),
            (
                "You are compiling a kage prompt task into a deterministic bash script.\n"
                "Output script text only. Do not use markdown fences. Do not explain the result.\n"
                "The generated script must be suitable for repeated unattended execution.\n"
                "Prefer deterministic local shell commands over interactive AI calls.\n"
                "Assume the working directory is already set correctly before execution.\n"
                "If the original task is underspecified, use the safest simple default and leave TODO comments."
            ),
            (
                f"Task Name: {task.name}\n"
                f"Source Task File: {task_file}\n"
                f"Project Directory: {project_dir}\n"
                f"Execution Directory: {execution_dir}\n"
                f"Target Script Path: {compiled_task_path(task_file)}"
            ),
            "Original Prompt:\n" + (task.prompt or ""),
        ]
    )

    resolved_template = None
    if task.command_template:
        resolved_template = task.command_template
    elif provider:
        cmd_def = global_config.commands.get(provider.command)
        if cmd_def:
            resolved_template = cmd_def.template

    if resolved_template:
        cmd = render_command_template(
            resolved_template,
            compile_prompt,
            provider=provider,
            extra_args=extra_args,
            auto_inject_model=not bool(task.command_template),
        )
    else:
        cmd = [engine_name, *build_model_args(provider), compile_prompt, *extra_args]

    env = os.environ.copy()
    if global_config.env_path:
        env["PATH"] = global_config.env_path

    if cmd and cmd[0]:
        exe_path = shutil.which(cmd[0], path=env.get("PATH"))
        if exe_path:
            cmd[0] = exe_path

    from .executor import prepare_command_for_execution

    return (
        prepare_command_for_execution(cmd, env),
        execution_dir,
        env,
        engine_name,
    )


def compile_prompt_task(project_dir: Path, task: TaskDef, task_file: Path) -> Path:
    if task.command or not task.prompt:
        raise ValueError("Compilation is only supported for prompt tasks.")

    cmd, cwd, env, engine_name = _build_compile_request(project_dir, task, task_file)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or "unknown error"
        raise RuntimeError(f"Compilation failed via {engine_name}: {stderr}")

    script_body = _strip_script_wrappers(result.stdout)
    if not script_body:
        raise RuntimeError("Compilation returned an empty script.")

    compiled_path = compiled_task_path(task_file)
    compiled_path.parent.mkdir(parents=True, exist_ok=True)
    fingerprints = get_task_source_fingerprints(task_file)
    header = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Compiled lock generated by kage.",
        f"# kage-lock-version: {COMPILED_LOCK_VERSION}",
        f"# kage-source-task: {task.name}",
        f"# kage-source-file: {task_file}",
        f"# kage-source-hash: {fingerprints['source_hash']}",
        f"# kage-frontmatter-hash: {fingerprints['frontmatter_hash']}",
        f"# kage-prompt-hash: {fingerprints['prompt_hash']}",
        f"# kage-provider: {engine_name}",
        f"# kage-compiled-at: {datetime.now().astimezone().isoformat()}",
        "",
    ]
    compiled_path.write_text(
        "\n".join(header) + script_body.strip() + "\n",
        encoding="utf-8",
    )
    compiled_path.chmod(0o755)
    return compiled_path
