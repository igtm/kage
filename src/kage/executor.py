import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from .artifacts import (
    build_connector_delivery_prompt,
    ensure_workspace_artifact_staging_dir,
    inject_connector_delivery_env,
    persist_artifacts_from_staging,
    write_artifact_metadata,
)
from .connector_payload import ConnectorAttachment, ConnectorMessage
from .config import (
    KAGE_GLOBAL_DIR,
    build_model_args,
    get_global_config,
    render_command_template,
)
from .db import (
    get_execution_status,
    get_execution_pid,
    log_execution,
    set_execution_pid,
    start_execution,
    update_execution,
)
from .parser import TaskDef
from .ai.chat import clean_ai_reply, get_thinking_tag
from .compiler import compiled_task_status
from .runs import (
    ensure_run_log_files,
    get_run,
    infer_output_summary,
    write_run_metadata,
)


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

        if (
            "--yolo" in head
            or "--yolo" in tail
            or "--dangerously-bypass-approvals-and-sandbox" in head
            or "--dangerously-bypass-approvals-and-sandbox" in tail
        ):
            return head + ["exec"] + tail

        # Ensure a non-interactive policy for codex exec on non-TTY runs.
        head = _drop_flag_with_value(head, "--ask-for-approval")
        head = _drop_flag_with_value(head, "--sandbox")
        tail = _drop_flag_with_value(tail, "--ask-for-approval")
        tail = _drop_flag_with_value(tail, "--sandbox")

        return (
            head
            + [
                "exec",
                "--ask-for-approval",
                "never",
                "--sandbox",
                "workspace-write",
            ]
            + tail
        )

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


def _resolve_task_working_dir(
    project_dir: Path, task: TaskDef, task_file: Optional[Path] = None
) -> Path:
    if not task.working_dir:
        return project_dir

    working_dir = Path(task.working_dir).expanduser()
    if working_dir.is_absolute():
        return working_dir

    base_dir = task_file.parent if task_file else project_dir
    return (base_dir.resolve() / working_dir).resolve()


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


def _build_connector_notification_message(
    task: TaskDef,
    status: str,
    stdout: str,
    attachments: list[ConnectorAttachment] | None = None,
    *,
    run_id: str | None = None,
) -> ConnectorMessage:
    msg = f"**[{task.name}]** Execution completed with status: `{status}`"

    if stdout:
        msg += f"\n{stdout}"

    return ConnectorMessage(
        text=msg,
        attachments=list(attachments or []),
        run_id=run_id,
    )


def _resolve_task_connector_targets(
    task: TaskDef,
    global_config,
) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    for connector_name in task.notify_connectors or []:
        raw_config = global_config.connectors.get(connector_name, {})
        connector_type = raw_config.get("type", "unknown")
        if hasattr(connector_type, "unwrap"):
            connector_type = connector_type.unwrap()
        targets.append((str(connector_name), str(connector_type)))
    return targets


def _notify_connectors(
    task: TaskDef,
    status: str,
    stdout: str,
    stderr: str,
    *,
    run_id: str | None = None,
    attachments: list[ConnectorAttachment] | None = None,
):
    del stderr
    if not task.notify_connectors:
        return

    from .connectors.runner import get_connector

    payload = _build_connector_notification_message(
        task,
        status,
        stdout,
        attachments,
        run_id=run_id,
    )
    for c_name in task.notify_connectors:
        connector = get_connector(c_name)
        if connector:
            connector.send_message(payload)


def _pump_stream(
    stream,
    stream_name: str,
    raw_path: Path,
    events_path: Path,
    events_lock: threading.Lock,
    state: dict,
    state_lock: threading.Lock,
):
    if stream is None:
        return

    with raw_path.open("a", encoding="utf-8", errors="replace") as raw_file:
        while True:
            chunk = stream.readline()
            if chunk == "":
                break

            raw_file.write(chunk)
            raw_file.flush()

            event = {
                "ts": datetime.now().astimezone().isoformat(),
                "stream": stream_name,
                "text": chunk,
            }
            with events_lock:
                with events_path.open(
                    "a", encoding="utf-8", errors="replace"
                ) as events_file:
                    events_file.write(json.dumps(event, ensure_ascii=False) + "\n")

            with state_lock:
                state[f"{stream_name}_chunks"].append(chunk)
                state[f"{stream_name}_bytes"] += len(chunk.encode("utf-8"))
                state["last_output_at"] = event["ts"]

    try:
        stream.close()
    except Exception:
        pass


def _stream_process_output(proc: subprocess.Popen, exec_id: str) -> dict:
    log_paths = ensure_run_log_files(exec_id)
    state = {
        "stdout_chunks": [],
        "stderr_chunks": [],
        "stdout_bytes": 0,
        "stderr_bytes": 0,
        "last_output_at": None,
    }
    state_lock = threading.Lock()
    events_lock = threading.Lock()
    threads = [
        threading.Thread(
            target=_pump_stream,
            args=(
                proc.stdout,
                "stdout",
                log_paths["stdout_path"],
                log_paths["events_path"],
                events_lock,
                state,
                state_lock,
            ),
            daemon=True,
        ),
        threading.Thread(
            target=_pump_stream,
            args=(
                proc.stderr,
                "stderr",
                log_paths["stderr_path"],
                log_paths["events_path"],
                events_lock,
                state,
                state_lock,
            ),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()
    state["threads"] = threads
    return state


def prepare_command_for_execution(cmd: list[str], env: dict[str, str]) -> list[str]:
    prepared = list(cmd)
    if prepared and prepared[0]:
        exe_path = shutil.which(prepared[0], path=env.get("PATH"))
        if exe_path:
            prepared[0] = exe_path
    return _normalize_headless_args(prepared)


def run_logged_command(
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    exec_id: str,
    timeout: float | None = None,
) -> dict:
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,
    )

    set_execution_pid(exec_id, proc.pid)

    stream_state = _stream_process_output(proc, exec_id)
    try:
        returncode = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait()
        raise
    finally:
        for thread in stream_state["threads"]:
            thread.join()

    return {
        "returncode": returncode,
        "stdout": "".join(stream_state["stdout_chunks"]),
        "stderr": "".join(stream_state["stderr_chunks"]),
        "stdout_bytes": stream_state["stdout_bytes"],
        "stderr_bytes": stream_state["stderr_bytes"],
        "last_output_at": stream_state["last_output_at"],
        "pid": proc.pid,
    }


def stop_execution(exec_id: str):
    """実行中のタスクを停止する。"""
    pid = get_execution_pid(exec_id)
    if not pid:
        print(f"No PID found for execution {exec_id}")
        return

    current = get_run(exec_id)
    current_stdout = current.stdout if current else ""
    current_stderr = current.stderr if current else ""

    try:
        # プロセスグループ全体にSIGTERMを送信
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        merged_stderr = current_stderr or ""
        if merged_stderr:
            merged_stderr += "\n"
        merged_stderr += "Terminated by user"
        update_execution(
            exec_id,
            "STOPPED",
            current_stdout,
            merged_stderr,
            output_summary=infer_output_summary(current_stdout, merged_stderr),
        )
        print(f"Stopped execution {exec_id} (PID: {pid})")
    except ProcessLookupError:
        # 既に終了している場合
        merged_stderr = current_stderr or ""
        if merged_stderr:
            merged_stderr += "\n"
        merged_stderr += "Terminated by user (already dead)"
        update_execution(
            exec_id,
            "STOPPED",
            current_stdout,
            merged_stderr,
            output_summary=infer_output_summary(current_stdout, merged_stderr),
        )
    except Exception as e:
        print(f"Failed to stop execution {exec_id}: {e}")


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
    execution_dir = _resolve_task_working_dir(project_dir, task, task_file)

    exec_id: str | None = None
    artifact_staging_dir: Path | None = None
    attachments: list[ConnectorAttachment] = []

    # ロックファイル作成
    try:
        lock_path.write_text(str(os.getpid()))

        # メモリの読み込み（直近N件）
        memory_dir = _get_memory_dir(project_dir, task.name)
        task_plan_file = (memory_dir / "task.json").resolve()
        memory_dir_hint = memory_dir.resolve()
        memory_context_str = _load_recent_memories(
            memory_dir, max_entries=global_config.memory_max_entries
        )

        provider = None
        parser_type = "raw"
        p_args = ""
        cmd = []
        engine_name = None
        shell_cmd = task.shell or "sh"
        connector_targets = _resolve_task_connector_targets(task, global_config)
        resolved_template = None
        extra_args: list[str] = []
        base_prompt = None
        compiled_status = None
        compiled_override_path = None
        compiled_lock_error = None
        prompt_execution = bool(task.prompt)

        if task.prompt and not task.command and task_file is not None:
            compiled_status = compiled_task_status(task, task_file)
            if compiled_status and compiled_status["exists"]:
                if compiled_status["is_fresh"]:
                    compiled_override_path = compiled_status["path"]
                else:
                    compiled_lock_error = (
                        f"Compiled lock is stale for task '{task.name}'. "
                        f"Run `kage compile {task.name}` to refresh {compiled_status['path']}."
                    )
                prompt_execution = False

        if compiled_override_path is not None:
            cmd = ["bash", str(compiled_override_path)]
        elif task.prompt:
            # タスク管理 (task.json) の読み込みと prompt_hash チェック
            task_plan = _load_task_json(memory_dir)
            current_hash = _compute_prompt_hash(task.prompt)

            task_plan_context = ""
            if task_plan:
                stored_hash = task_plan.get("prompt_hash", "")
                plan_json = json.dumps(task_plan, indent=2, ensure_ascii=False)
                if stored_hash == current_hash:
                    task_plan_context = (
                        f"\n\n## Task Plan ({task_plan_file})\n{plan_json}"
                    )
                else:
                    task_plan_context = (
                        f"\n\n## Task Plan ({task_plan_file})\n"
                        f"\u26a0 **The task prompt has been updated** (hash mismatch). "
                        f"Review the previous task plan below and regenerate it based on the new instructions. "
                        f"Reuse completed work where applicable. Update `prompt_hash` to `{current_hash}`.\n\n"
                        f"Previous plan:\n{plan_json}"
                    )
            else:
                task_plan_context = (
                    f"\n\n## Task Plan\n"
                    f"No task plan found. Create one by writing to `{task_plan_file}`.\n"
                    f"Use `prompt_hash`: `{current_hash}`"
                )

            # メモリコンテキスト
            if memory_context_str:
                memory_section = f"\n\n## Recent Memory (most recent {global_config.memory_max_entries} entries)\n{memory_context_str}"
            else:
                memory_section = (
                    f"\n\n## Recent Memory\n"
                    f"No previous memory found. You can write memory files to "
                    f"`{memory_dir_hint / 'YYYY-MM-DD.json'}`."
                )

            # プロバイダーの解決
            engine_name = task.provider or global_config.default_ai_engine
            if not engine_name:
                msg = "AIエンジンが未指定です。"
                print(f"[kage] ERROR: {msg}")
                log_execution(str(project_dir), task.name, "FAILED", "", msg)
                return

            # プロンプトの構築: System Prompt + Task Plan + Memory + Task Instructions
            thinking_tag = get_thinking_tag(engine_name)
            formatted_system_prompt = system_prompt.replace(
                "{thinking_tag}", thinking_tag
            )
            base_prompt = (
                f"{formatted_system_prompt}{task_plan_context}{memory_section}"
                f"\n\n## Task Instructions\n{task.prompt}"
            )

            provider = global_config.providers.get(engine_name)
            extra_args = list(task.ai.args) if task.ai and task.ai.args else []
            if task.command_template:
                resolved_template = task.command_template
            elif provider:
                cmd_def = global_config.commands.get(provider.command)
                if cmd_def:
                    resolved_template = cmd_def.template

            parser_type = task.parser or (provider.parser if provider else "raw")
            p_args = task.parser_args or (provider.parser_args if provider else "")

        elif task.command:
            pass
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
            from .db import init_db

            init_db()  # Migration ensure
            # まだPIDがわからないのでNoneで開始
            exec_id = start_execution(
                str(project_dir),
                task.name,
                working_dir=str(execution_dir),
                execution_kind=(
                    "compiled"
                    if compiled_status and compiled_status["exists"]
                    else "prompt"
                    if prompt_execution
                    else "command"
                ),
                provider_name=engine_name if prompt_execution else None,
            )

            if compiled_override_path is not None:
                write_run_metadata(
                    exec_id,
                    {
                        "compiled_task": {
                            "source_task_file": str(task_file) if task_file else None,
                            "script_path": str(compiled_override_path),
                        }
                    },
                )
            elif compiled_status and compiled_status["exists"]:
                write_run_metadata(
                    exec_id,
                    {
                        "compiled_task": {
                            "source_task_file": str(task_file) if task_file else None,
                            "script_path": str(compiled_status["path"]),
                            "is_fresh": compiled_status["is_fresh"],
                            "prompt_hash": compiled_status["prompt_hash"],
                        }
                    },
                )

            if compiled_lock_error:
                raise RuntimeError(compiled_lock_error)

            print(f"Executing task '{task.name}' in {execution_dir}")
            env = os.environ.copy()
            if global_config.env_path:
                env["PATH"] = global_config.env_path

            if task.notify_connectors:
                artifact_staging_dir = ensure_workspace_artifact_staging_dir(
                    execution_dir,
                    exec_id,
                )
                inject_connector_delivery_env(
                    env,
                    artifact_staging_dir,
                    connector_targets,
                )
                write_artifact_metadata(exec_id, None, artifact_staging_dir, [])

            if compiled_override_path is not None:
                cmd = ["bash", str(compiled_override_path)]
            elif task.prompt:
                full_prompt = base_prompt or ""
                if artifact_staging_dir is not None:
                    full_prompt += build_connector_delivery_prompt(
                        connector_targets,
                        artifact_staging_dir,
                    )

                if resolved_template:
                    cmd = render_command_template(
                        resolved_template,
                        full_prompt,
                        provider=provider,
                        extra_args=extra_args,
                        auto_inject_model=not bool(task.command_template),
                    )
                else:
                    cmd = [
                        engine_name,
                        *build_model_args(provider),
                        full_prompt,
                        *extra_args,
                    ]
            elif task.command:
                cmd = [shell_cmd, "-c", task.command]

            cmd = prepare_command_for_execution(cmd, env)

            # タイムアウト設定 (デフォルトなし)
            timeout = task.timeout_minutes * 60 if task.timeout_minutes else None

            try:
                result_data = run_logged_command(
                    cmd=cmd,
                    cwd=execution_dir,
                    env=env,
                    exec_id=exec_id,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                if artifact_staging_dir is not None:
                    persisted_dir, attachments = persist_artifacts_from_staging(
                        exec_id,
                        artifact_staging_dir,
                    )
                    write_artifact_metadata(
                        exec_id,
                        persisted_dir,
                        artifact_staging_dir,
                        attachments,
                    )
                # タイムアウト時はプロセスグループごと終了させる
                raise
            result = subprocess.CompletedProcess(
                cmd,
                result_data["returncode"],
                result_data["stdout"],
                result_data["stderr"],
            )

            if artifact_staging_dir is not None:
                persisted_dir, attachments = persist_artifacts_from_staging(
                    exec_id,
                    artifact_staging_dir,
                )
                write_artifact_metadata(
                    exec_id,
                    persisted_dir,
                    artifact_staging_dir,
                    attachments,
                )

            if get_execution_status(exec_id) == "STOPPED":
                return

            # autostop チェック: task.json の sub_tasks が全て done の場合
            if prompt_execution and task.mode == ExecutionMode.AUTOSTOP and task_file:
                should_stop = False
                # task.json による判定
                updated_plan = _load_task_json(memory_dir)
                if updated_plan.get("sub_tasks"):
                    all_done = all(
                        t.get("status") == "done" for t in updated_plan["sub_tasks"]
                    )
                    if all_done:
                        should_stop = True
                if should_stop:
                    _deactivate_task(task_file)

            if task.mode == ExecutionMode.ONCE and task_file:
                _deactivate_task(task_file)

            if prompt_execution and parser_type == "jq" and p_args:
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
            if prompt_execution:
                result.stdout = clean_ai_reply(result.stdout)
            summary = infer_output_summary(result.stdout, result.stderr)
            updated = update_execution(
                exec_id,
                status,
                result.stdout,
                result.stderr,
                exit_code=result.returncode,
                output_summary=summary,
                stdout_bytes=result_data["stdout_bytes"],
                stderr_bytes=result_data["stderr_bytes"],
                last_output_at=result_data["last_output_at"],
            )
            if updated:
                _notify_connectors(
                    task,
                    status,
                    result.stdout,
                    result.stderr,
                    run_id=exec_id,
                    attachments=attachments,
                )
        except subprocess.TimeoutExpired:
            stderr = f"Task timed out after {task.timeout_minutes} minutes"
            if exec_id and artifact_staging_dir is not None and not attachments:
                persisted_dir, attachments = persist_artifacts_from_staging(
                    exec_id,
                    artifact_staging_dir,
                )
                write_artifact_metadata(
                    exec_id,
                    persisted_dir,
                    artifact_staging_dir,
                    attachments,
                )
            updated = update_execution(
                exec_id,
                "TIMEOUT",
                "",
                stderr,
                exit_code=-1,
                output_summary=infer_output_summary("", stderr),
            )
            if updated:
                _notify_connectors(
                    task,
                    "TIMEOUT",
                    "",
                    stderr,
                    run_id=exec_id,
                    attachments=attachments,
                )
        except Exception as e:
            if exec_id and artifact_staging_dir is not None and not attachments:
                persisted_dir, attachments = persist_artifacts_from_staging(
                    exec_id,
                    artifact_staging_dir,
                )
                write_artifact_metadata(
                    exec_id,
                    persisted_dir,
                    artifact_staging_dir,
                    attachments,
                )
            updated = update_execution(
                exec_id,
                "ERROR",
                "",
                str(e),
                output_summary=infer_output_summary("", str(e)),
            )
            if updated:
                _notify_connectors(
                    task,
                    "ERROR",
                    "",
                    str(e),
                    run_id=exec_id,
                    attachments=attachments,
                )
    finally:
        if lock_path.exists():
            lock_path.unlink()

        # 最終的に PID を NULL にしておく (終了済みを明示)
        try:
            if exec_id:
                set_execution_pid(exec_id, None)
        except Exception:
            pass
