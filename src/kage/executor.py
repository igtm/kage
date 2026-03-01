import json
import os
import re
import shutil
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import KAGE_GLOBAL_DIR, get_global_config
from .db import log_execution
from .parser import TaskDef
from .ai.chat import clean_ai_reply


def _normalize_headless_args(cmd: list[str]) -> list[str]:
    """When running without a TTY, avoid interactive approval prompts for AI CLIs."""
    if not cmd:
        return cmd

    exe = Path(cmd[0]).name

    try:
        is_tty = sys.stdin.isatty()
    except Exception:
        is_tty = False
    if is_tty:
        return cmd

    if exe == "codex":
        try:
            exec_idx = cmd.index("exec")
        except ValueError:
            return cmd

        # Split into codex-global args and exec args
        head = cmd[:exec_idx]
        tail = cmd[exec_idx + 1 :]

        # Remove exec-scoped convenience that can prompt on non-TTY
        tail = [part for part in tail if part != "--full-auto"]

        def _drop_flag_with_value(parts: list[str], flag: str) -> list[str]:
            out: list[str] = []
            i = 0
            while i < len(parts):
                if parts[i] == flag:
                    i += 2
                    continue
                out.append(parts[i])
                i += 1
            return out

        # Ensure global non-interactive policy before subcommand.
        head = _drop_flag_with_value(head, "--ask-for-approval")
        head = _drop_flag_with_value(head, "--sandbox")
        head = head + ["--ask-for-approval", "never", "--sandbox", "workspace-write"]

        return head + ["exec"] + tail

    if exe == "claude":
        # Ensure --dangerously-skip-permissions is present for claude
        # We also prefer -p (print mode) for non-interactive execution
        new_cmd = list(cmd)
        if "-p" not in new_cmd and "--print" not in new_cmd:
            # Insert -p after 'claude' if not present
            new_cmd.insert(1, "-p")

        if "--dangerously-skip-permissions" not in new_cmd:
            new_cmd.insert(1, "--dangerously-skip-permissions")
        if "--allow-dangerously-skip-permissions" not in new_cmd:
            new_cmd.insert(1, "--allow-dangerously-skip-permissions")

        return new_cmd

    if exe == "gemini":
        # Ensure --prompt (or -p) is used for headless mode.
        if "--prompt" not in cmd and "-p" not in cmd:
            new_cmd = list(cmd)
            if len(new_cmd) > 1:
                new_cmd.insert(-1, "-p")
            else:
                new_cmd.append("-p")
            return new_cmd

    return cmd


def _get_memory_dir(project_dir: Path, task_name: str) -> Path:
    """タスクのメモリディレクトリパスを返す。ディレクトリがなければ作成する。"""
    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", task_name)
    memory_dir = project_dir / ".kage" / "memory" / safe_name
    memory_dir.mkdir(parents=True, exist_ok=True)
    return memory_dir


def _load_recent_memories(memory_dir: Path, max_entries: int = 5) -> str:
    """直近N日分のメモリファイルを読み込み、結合した文字列として返す。"""
    date_files = sorted(memory_dir.glob("*.json"), reverse=True)
    # task.json はメモリファイルではないので除外
    date_files = [f for f in date_files if f.name != "task.json"]
    date_files = date_files[:max_entries]
    date_files.reverse()  # 古い順に並べる

    if not date_files:
        return ""

    parts = []
    for f in date_files:
        try:
            content = f.read_text(encoding="utf-8")
            date_label = f.stem  # e.g. "2026-02-28"
            parts.append(f"--- {date_label} ---\n{content}")
        except Exception:
            continue
    return "\n\n".join(parts)


def _load_task_json(memory_dir: Path) -> dict:
    """task.json を読み込む。存在しなければ空dictを返す。"""
    task_json_path = memory_dir / "task.json"
    if task_json_path.exists():
        try:
            return json.loads(task_json_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _compute_prompt_hash(prompt: str) -> str:
    """プロンプト本文のSHA256ハッシュを返す。"""
    import hashlib
    return hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest()


def _deactivate_task(task_file: Path):
    if not task_file.exists():
        return
    content = task_file.read_text(encoding="utf-8")
    new_content = re.sub(r"active:\s*(true|false)", "active: false", content)
    if content == new_content:
        # active が無い場合は cron: の後に追加
        new_content = re.sub(r"(cron:.*?\n)", r"\1active: false\n", content)
    task_file.write_text(new_content, encoding="utf-8")
    print(f"Task deactivated: {task_file.name}")


def _get_lock_path(project_dir: Path, task_name: str) -> Path:
    safe_proj = re.sub(r"[^a-zA-Z0-9_\-]", "_", project_dir.name)
    safe_task = re.sub(r"[^a-zA-Z0-9_\-]", "_", task_name)
    path = KAGE_GLOBAL_DIR / "locks" / f"{safe_proj}_{safe_task}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _check_running(lock_path: Path) -> Optional[int]:
    if not lock_path.exists():
        return None
    try:
        pid = int(lock_path.read_text().strip())
        os.kill(pid, 0)  # Check if process exists
        return pid
    except (ProcessLookupError, ValueError, OverflowError):
        return None

def _notify_connectors(task: TaskDef, status: str, stdout: str, stderr: str):
    if not task.notify_connectors:
        return
        
    from .connectors.runner import get_connector
    
    msg = f"**[{task.name}]** Execution completed with status: `{status}`"
    
    if stdout:
        msg += f"\n{stdout[:2000]}"
        if len(stdout) > 2000:
            msg += "\n...(truncated)"
        
    for c_name in task.notify_connectors:
        connector = get_connector(c_name)
        if connector:
            connector.send_message(msg)


def execute_task(project_dir: Path, task: TaskDef, task_file: Optional[Path] = None):
    if not task.active:
        print(f"Skipping inactive task '{task.name}' in {project_dir}")
        return

    from .config import get_system_prompt
    from .parser import ConcurrencyPolicy, ExecutionMode

    # 多重起動チェック
    lock_path = _get_lock_path(project_dir, task.name)
    running_pid = _check_running(lock_path)

    if running_pid:
        if task.concurrency_policy == ConcurrencyPolicy.FORBID:
            print(
                f"Task '{task.name}' is already running (PID: {running_pid}). Skipping."
            )
            return
        elif task.concurrency_policy == ConcurrencyPolicy.REPLACE:
            print(
                f"Task '{task.name}' is already running (PID: {running_pid}). Terminating and replacing."
            )
            try:
                os.kill(running_pid, signal.SIGTERM)
            except Exception:
                pass

    global_config = get_global_config(workspace_dir=project_dir)
    system_prompt = get_system_prompt(workspace_dir=project_dir)

    # ロックファイル作成
    try:
        lock_path.write_text(str(os.getpid()))

        # メモリの読み込み（直近N件）
        memory_dir = _get_memory_dir(project_dir, task.name)
        memory_context_str = _load_recent_memories(
            memory_dir, max_entries=global_config.memory_max_entries
        )

        provider = None
        parser_type = "raw"
        p_args = ""
        cmd = []

        if task.prompt:
            # プロバイダーの解決
            engine_name = task.provider or global_config.default_ai_engine
            if not engine_name:
                msg = "AIエンジンが未指定です。"
                print(f"[kage] ERROR: {msg}")
                log_execution(str(project_dir), task.name, "FAILED", "", msg)
                return

            provider = global_config.providers.get(engine_name)
            reasoning_tag = "think"
            if provider:
                reasoning_tag = provider.reasoning_tag or "think"

            # システムプロンプト内のタグプレースホルダを置換
            system_prompt = system_prompt.replace("{reasoning_tag}", reasoning_tag)
            # 互換性のために <think> も置換する
            if "{reasoning_tag}" not in system_prompt and "<think>" in system_prompt:
                system_prompt = system_prompt.replace("<think>", f"<{reasoning_tag}>").replace("</think>", f"</{reasoning_tag}>")

            # タスク管理 (task.json) の読み込みと prompt_hash チェック
            task_plan = _load_task_json(memory_dir)
            current_hash = _compute_prompt_hash(task.prompt)

            task_plan_context = ""
            if task_plan:
                stored_hash = task_plan.get("prompt_hash", "")
                plan_json = json.dumps(task_plan, indent=2, ensure_ascii=False)
                if stored_hash == current_hash:
                    task_plan_context = (
                        f"\n\n## Task Plan (.kage/memory/{re.sub(r'[^a-zA-Z0-9_-]', '_', task.name)}/task.json)\n"
                        f"{plan_json}"
                    )
                else:
                    task_plan_context = (
                        f"\n\n## Task Plan (.kage/memory/{re.sub(r'[^a-zA-Z0-9_-]', '_', task.name)}/task.json)\n"
                        f"\u26a0 **The task prompt has been updated** (hash mismatch). "
                        f"Review the previous task plan below and regenerate it based on the new instructions. "
                        f"Reuse completed work where applicable. Update `prompt_hash` to `{current_hash}`.\n\n"
                        f"Previous plan:\n{plan_json}"
                    )
            else:
                task_plan_context = (
                    f"\n\n## Task Plan\n"
                    f"No task plan found. Create one by writing to "
                    f"`.kage/memory/{re.sub(r'[^a-zA-Z0-9_-]', '_', task.name)}/task.json`.\n"
                    f"Use `prompt_hash`: `{current_hash}`"
                )

            # メモリコンテキスト
            if memory_context_str:
                memory_section = f"\n\n## Recent Memory (most recent {global_config.memory_max_entries} entries)\n{memory_context_str}"
            else:
                memory_section = (
                    f"\n\n## Recent Memory\n"
                    f"No previous memory found. You can write memory files to "
                    f"`.kage/memory/{re.sub(r'[^a-zA-Z0-9_-]', '_', task.name)}/YYYY-MM-DD.json`."
                )

            # プロンプトの構築: System Prompt + Task Plan + Memory + Task Instructions
            full_prompt = f"{system_prompt}{task_plan_context}{memory_section}\n\n## Task Instructions\n{task.prompt}"

            # プロバイダーの解決
            engine_name = task.provider or global_config.default_ai_engine
            if not engine_name:
                msg = "AIエンジンが未指定です。"
                print(f"[kage] ERROR: {msg}")
                log_execution(str(project_dir), task.name, "FAILED", "", msg)
                return

            provider = global_config.providers.get(engine_name)
            extra_args = task.ai.args if task.ai and task.ai.args else []

            resolved_template = None
            if task.command_template:
                resolved_template = task.command_template
            elif provider:
                cmd_def = global_config.commands.get(provider.command)
                if cmd_def:
                    resolved_template = cmd_def.template

            parser_type = task.parser or (provider.parser if provider else "raw")
            p_args = task.parser_args or (provider.parser_args if provider else "")

            if resolved_template:
                cmd = [
                    part.replace("{prompt}", full_prompt) for part in resolved_template
                ]
                cmd.extend(extra_args)
            else:
                cmd = [engine_name, full_prompt] + extra_args

        elif task.command:
            shell_cmd = task.shell or "sh"
            cmd = [shell_cmd, "-c", task.command]
        else:
            log_execution(
                str(project_dir),
                task.name,
                "FAILED",
                "",
                "No prompt or command specified",
            )
            return

        try:
            from .db import init_db, start_execution, update_execution
            init_db()  # Migration ensure
            exec_id = start_execution(str(project_dir), task.name)

            print(f"Executing task '{task.name}' in {project_dir}")
            env = os.environ.copy()
            if global_config.env_path:
                env["PATH"] = global_config.env_path

            if cmd and cmd[0]:
                exe_path = shutil.which(cmd[0], path=env.get("PATH"))
                if exe_path:
                    cmd[0] = exe_path
            cmd = _normalize_headless_args(cmd)

            # タイムアウト設定 (デフォルトなし)
            timeout = task.timeout_minutes * 60 if task.timeout_minutes else None

            result = subprocess.run(
                cmd,
                cwd=project_dir,
                capture_output=True,
                text=True,
                env=env,
                timeout=timeout,
            )

            # autostop チェック: task.json の sub_tasks が全て done の場合
            if task.prompt and task.mode == ExecutionMode.AUTOSTOP and task_file:
                should_stop = False
                # task.json による判定
                updated_plan = _load_task_json(memory_dir)
                if updated_plan.get("sub_tasks"):
                    all_done = all(
                        t.get("status") == "done"
                        for t in updated_plan["sub_tasks"]
                    )
                    if all_done:
                        should_stop = True
                if should_stop:
                    _deactivate_task(task_file)

            if task.mode == ExecutionMode.ONCE and task_file:
                _deactivate_task(task_file)

            if task.prompt and parser_type == "jq" and p_args:
                try:
                    jq_result = subprocess.run(
                        ["jq", "-r", p_args],
                        input=result.stdout,
                        capture_output=True,
                        text=True,
                        env=env,
                    )
                    if jq_result.returncode == 0:
                        result.stdout = jq_result.stdout
                    else:
                        result.stderr += f"\n[jq err]: {jq_result.stderr}"
                except Exception as jq_e:
                    result.stderr += f"\n[jq exc]: {str(jq_e)}"

            status = "SUCCESS" if result.returncode == 0 else "FAILED"
            # Clean thinking tags from AI output before storing and notifying
            if task.prompt:
                reasoning_tag = "think"
                if provider:
                    reasoning_tag = provider.reasoning_tag or "think"
                result.stdout = clean_ai_reply(result.stdout, reasoning_tag=reasoning_tag)
            update_execution(exec_id, status, result.stdout, result.stderr)
            _notify_connectors(task, status, result.stdout, result.stderr)
        except subprocess.TimeoutExpired:
            stderr = f"Task timed out after {task.timeout_minutes} minutes"
            update_execution(
                exec_id,
                "TIMEOUT",
                "",
                stderr,
            )
            _notify_connectors(task, "TIMEOUT", "", stderr)
        except Exception as e:
            update_execution(exec_id, "ERROR", "", str(e))
            _notify_connectors(task, "ERROR", "", str(e))
    finally:
        if lock_path.exists():
            lock_path.unlink()
