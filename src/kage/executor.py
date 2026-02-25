import subprocess
import os
import sys
from pathlib import Path
from .parser import TaskDef
from .db import log_execution
from .config import get_global_config

def _normalize_codex_headless_args(cmd: list[str]) -> list[str]:
    """When running without a TTY, avoid interactive approval prompts in codex exec."""
    if not cmd:
        return cmd

    exe = Path(cmd[0]).name
    if exe != "codex":
        return cmd
    if len(cmd) < 2 or cmd[1] != "exec":
        return cmd

    try:
        is_tty = sys.stdin.isatty()
    except Exception:
        is_tty = False
    if is_tty:
        return cmd

    normalized = [part for part in cmd if part != "--full-auto"]
    insert_at = 2

    if "--ask-for-approval" not in normalized:
        normalized[insert_at:insert_at] = ["--ask-for-approval", "never"]
        insert_at += 2

    if "--sandbox" not in normalized:
        normalized[insert_at:insert_at] = ["--sandbox", "workspace-write"]

    return normalized

def execute_task(project_dir: Path, task: TaskDef):
    global_config = get_global_config(workspace_dir=project_dir)
    
    provider = None
    parser_type = "raw"
    p_args = ""
    cmd = []
    
    if task.prompt:
        # プロバイダーの解決
        # 優先: task.provider > task.ai.engine > global default_ai_engine
        engine_name = task.provider
        if not engine_name and task.ai and task.ai.engine:
            engine_name = task.ai.engine
        if not engine_name:
            engine_name = global_config.default_ai_engine
        
        if not engine_name:
            msg = (
                "AIエンジンが未指定です。以下のいずれかで指定してください:\n"
                "  1) タスク定義に provider = \"codex\" を追記する\n"
                "  2) ~/.kage/config.toml または .kage/config.toml に default_ai_engine = \"codex\" を記載する"
            )
            print(f"[kage] ERROR: {msg}")
            log_execution(str(project_dir), task.name, "FAILED", "", msg)
            return
        provider = global_config.providers.get(engine_name)
        extra_args = task.ai.args if task.ai and task.ai.args else []
        
        # コマンドテンプレートを解決: インライン指定 > provider経由のcommand > フォールバック
        resolved_template = None
        if task.command_template:
            resolved_template = task.command_template
        elif provider:
            cmd_def = global_config.commands.get(provider.command)
            if cmd_def:
                resolved_template = cmd_def.template
        
        # パーサーを解決: インライン指定 > provider設定 > raw
        parser_type = task.parser or (provider.parser if provider else "raw")
        p_args = task.parser_args or (provider.parser_args if provider else "")
        
        if resolved_template:
            cmd = [part.replace("{prompt}", task.prompt) for part in resolved_template]
            cmd.extend(extra_args)
        else:
            # フォールバック: エンジン名をそのままコマンドとして使用
            cmd = [engine_name, task.prompt] + extra_args
            
    elif task.command:
        # standard shell execution
        shell_cmd = task.shell or "sh"
        cmd = [shell_cmd, "-c", task.command]
    else:
        # no command to execute
        log_execution(str(project_dir), task.name, "FAILED", "", "No prompt or command specified")
        return

    try:
        print(f"Executing task '{task.name}' in {project_dir}")
        env = os.environ.copy()
        if global_config.env_path:
            env["PATH"] = global_config.env_path
            
        # cmd[0] を環境変数のPATHに基づいて絶対パスに変換する
        import shutil
        if cmd and cmd[0]:
            exe_path = shutil.which(cmd[0], path=env.get("PATH"))
            if exe_path:
                cmd[0] = exe_path
        cmd = _normalize_codex_headless_args(cmd)

        result = subprocess.run(
            cmd,
            cwd=project_dir,
            capture_output=True,
            text=True,
            env=env
        )

        if task.prompt and parser_type == "jq" and p_args:
            try:
                jq_cmd = ["jq", "-r", p_args]
                jq_result = subprocess.run(
                    jq_cmd,
                    input=result.stdout,
                    capture_output=True,
                    text=True,
                    env=env
                )

                if jq_result.returncode == 0:
                    result.stdout = jq_result.stdout
                else:
                    result.stderr += f"\n[jq err]: {jq_result.stderr}"
            except Exception as jq_e:
                result.stderr += f"\n[jq exc]: {str(jq_e)}"
                
        status = "SUCCESS" if result.returncode == 0 else "FAILED"
        log_execution(str(project_dir), task.name, status, result.stdout, result.stderr)
    except Exception as e:
        log_execution(str(project_dir), task.name, "ERROR", "", str(e))
