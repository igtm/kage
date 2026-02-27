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

    return cmd


def _get_memory_path(project_dir: Path, task_name: str) -> Path:
    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", task_name)
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = project_dir / ".kage" / "memory" / safe_name / f"{date_str}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_memory(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_memory(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


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

        # メモリの読み込み
        memory_path = _get_memory_path(project_dir, task.name)
        memory_data = _load_memory(memory_path)

        provider = None
        parser_type = "raw"
        p_args = ""
        cmd = []

        if task.prompt:
            # プロンプトの構築: System Prompt + Memory + Task Prompt
            memory_context = (
                f"\n\n## Task Memory (Current State)\n{json.dumps(memory_data, indent=2, ensure_ascii=False)}"
                if memory_data
                else "\n\n## Task Memory\nNo previous memory found for this task on this date."
            )
            full_prompt = f"{system_prompt}{memory_context}\n\n## Task Instructions\n{task.prompt}"

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

            # AIタスクの場合、出力を解析してメモリを更新する試み
            if task.prompt:
                new_memory = {
                    "last_updated": datetime.now().isoformat(),
                    "raw_output": result.stdout,
                }
                json_match = re.search(r"```json\n(.*?)\n```", result.stdout, re.DOTALL)
                if json_match:
                    try:
                        extracted_json = json.loads(json_match.group(1))
                        new_memory.update(extracted_json)
                    except Exception:
                        pass
                elif result.stdout.strip().startswith(
                    "{"
                ) and result.stdout.strip().endswith("}"):
                    try:
                        extracted_json = json.loads(result.stdout)
                        new_memory.update(extracted_json)
                    except Exception:
                        pass

                memory_data.update(new_memory)
                _save_memory(memory_path, memory_data)

                if (
                    task.mode == ExecutionMode.AUTOSTOP
                    and memory_data.get("status") == "Completed"
                    and task_file
                ):
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
            log_execution(
                str(project_dir), task.name, status, result.stdout, result.stderr
            )
        except subprocess.TimeoutExpired:
            log_execution(
                str(project_dir),
                task.name,
                "TIMEOUT",
                "",
                f"Task timed out after {task.timeout_minutes} minutes",
            )
        except Exception as e:
            log_execution(str(project_dir), task.name, "ERROR", "", str(e))
    finally:
        if lock_path.exists():
            lock_path.unlink()
