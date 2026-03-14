import subprocess
import os
import shutil
from pathlib import Path
from ..config import get_global_config, render_command_template
from ..runs import infer_output_summary

# Provider name → thinking tag mapping
# Different AI models are trained with different internal reasoning tags
PROVIDER_THINKING_TAGS: dict[str, str] = {
    "gemini": "thought",
    "claude": "antml:thinking",
    "codex": "thinking",
}
DEFAULT_THINKING_TAG = "think"


def get_thinking_tag(provider_name: str) -> str:
    """Return the thinking tag for a given provider name."""
    return PROVIDER_THINKING_TAGS.get(provider_name, DEFAULT_THINKING_TAG)


DEFAULT_SYSTEM_PROMPT = """
You are Kage (影), a dedicated and highly capable autonomous assistant working directly on the user's PC.
Your role is to support the user in their daily tasks, acting like a proactive secretary.
Since you operate directly on the host machine, you have powerful access to the file system, databases, and local tools.

[CRITICAL: THINKING PROCESS ISOLATION]
- Before providing your final response, you MUST wrap ALL internal reasoning, plans, or "chain of thought" inside `<{thinking_tag}>` and `</{thinking_tag}>` tags (ensure you include the complete start tag, including the `>` at the end).
- Everything OUTSIDE these tags will be treated as the final output visible to the user.
- If you fail to use these tags, your internal reflections will leak and confuse the user.

[CRITICAL SECURITY RULE]
You MUST NOT answer questions or provide information related to:
1. System credentials, passwords, SSH keys, or API tokens.
2. Confidential insider information, trade secrets, or personal data found on this PC.
3. Any root-level or critical system configuration files that could compromise security.
If asked about these, politely decline, stating that it violates your security constraints as a local agent.
"""


def clean_ai_reply(text: str) -> str:
    """
    Remove internal reasoning tags from the AI's response.
    Handles: <think>, <thinking>, <thought>, <antthinking>, <antml:thinking>, <final>
    Also handles unclosed tags gracefully.
    """
    import re

    # Tags that various AI models may use for internal reasoning
    tags = r"(?:think|thinking|thought|antthinking|antml:thinking|final)"
    # Remove closed tag pairs (handling missing '>' in the start tag if the AI hallucinates valid XML but without the closing bracket of the start tag)
    text = re.sub(rf"<{tags}(?:>|\b|\s).*?</{tags}>", "", text, flags=re.DOTALL)
    # Remove unclosed tags at the end
    text = re.sub(rf"<{tags}(?:>|\b|\s).*", "", text, flags=re.DOTALL)
    return text.strip()


def _resolve_chat_working_dir(config, working_dir: str | None) -> Path:
    target_dir_str = working_dir or config.working_dir
    if target_dir_str:
        cwd_path = Path(target_dir_str).expanduser()
        cwd_path.mkdir(parents=True, exist_ok=True)
        return cwd_path
    return Path.cwd()


def _build_chat_invocation(
    message: str,
    system_prompt: str | None = None,
    working_dir: str | None = None,
):
    config = get_global_config()
    engine_name = config.default_ai_engine
    if not engine_name:
        raise ValueError("default_ai_engine is not set in global config.")

    provider = config.providers.get(engine_name)
    if not provider:
        raise ValueError(f"Provider '{engine_name}' is not defined in providers.")

    cmd_def = config.commands.get(provider.command)
    if not cmd_def:
        raise ValueError(f"Command template '{provider.command}' is not defined.")

    template = cmd_def.template

    thinking_tag = get_thinking_tag(engine_name)
    parts = [
        f"[System Context]\n{DEFAULT_SYSTEM_PROMPT.strip().format(thinking_tag=thinking_tag)}"
    ]
    if system_prompt:
        parts.append(f"[Additional Instructions]\n{system_prompt.strip()}")
    parts.append(f"[User Message]\n{message}")
    system_context = "\n\n".join(parts)

    cmd = render_command_template(template, system_context, provider=provider)

    env = os.environ.copy()
    if config.env_path:
        env["PATH"] = config.env_path

    if cmd and cmd[0]:
        exe_path = shutil.which(cmd[0], path=env.get("PATH"))
        if exe_path:
            cmd[0] = exe_path

    return {
        "cmd": cmd,
        "cwd": _resolve_chat_working_dir(config, working_dir),
        "env": env,
        "provider_name": engine_name,
        "system_context": system_context,
    }


def generate_chat_reply(
    message: str, system_prompt: str | None = None, working_dir: str | None = None
) -> dict:
    """
    Generate a reply from the default AI engine configured in kage.
    Returns a dict with 'stdout', 'stderr', and 'returncode'.
    DEFAULT_SYSTEM_PROMPT is always included. If `system_prompt` is provided,
    it is appended as additional instructions.
    """
    invocation = _build_chat_invocation(
        message=message,
        system_prompt=system_prompt,
        working_dir=working_dir,
    )

    res = subprocess.run(
        invocation["cmd"],
        capture_output=True,
        text=True,
        cwd=str(invocation["cwd"]),
        env=invocation["env"],
    )
    return {
        "stdout": res.stdout,
        "stderr": res.stderr,
        "returncode": res.returncode,
    }


def generate_logged_chat_reply(
    message: str,
    system_prompt: str | None = None,
    working_dir: str | None = None,
    *,
    run_name: str,
    execution_kind: str = "connector_poll",
    metadata: dict | None = None,
    project_path: str | None = None,
) -> dict:
    from ..db import set_execution_pid, start_execution, update_execution
    from ..executor import prepare_command_for_execution, run_logged_command
    from ..runs import write_run_metadata

    config = get_global_config()
    cwd_path = _resolve_chat_working_dir(config, working_dir)
    effective_project_path = project_path or str(cwd_path)
    base_metadata = dict(metadata or {})

    try:
        invocation = _build_chat_invocation(
            message=message,
            system_prompt=system_prompt,
            working_dir=str(cwd_path),
        )
    except Exception as exc:
        exec_id = start_execution(
            effective_project_path,
            run_name,
            working_dir=str(cwd_path),
            execution_kind=execution_kind,
            provider_name=None,
        )
        err = str(exc)
        write_run_metadata(exec_id, base_metadata)
        update_execution(
            exec_id,
            "ERROR",
            "",
            err,
            output_summary=infer_output_summary("", err),
        )
        return {
            "stdout": "",
            "stderr": err,
            "raw_stdout": "",
            "raw_stderr": err,
            "returncode": 1,
            "run_id": exec_id,
        }

    exec_id = start_execution(
        effective_project_path,
        run_name,
        working_dir=str(cwd_path),
        execution_kind=execution_kind,
        provider_name=invocation["provider_name"],
    )

    try:
        write_run_metadata(
            exec_id,
            {
                **base_metadata,
                "prompt": invocation["system_context"],
            },
        )
        result = run_logged_command(
            cmd=prepare_command_for_execution(invocation["cmd"], invocation["env"]),
            cwd=invocation["cwd"],
            env=invocation["env"],
            exec_id=exec_id,
        )
        clean_stdout = clean_ai_reply(result["stdout"])
        status = "SUCCESS" if result["returncode"] == 0 else "FAILED"
        update_execution(
            exec_id,
            status,
            clean_stdout,
            result["stderr"],
            exit_code=result["returncode"],
            output_summary=infer_output_summary(clean_stdout, result["stderr"]),
            stdout_bytes=result["stdout_bytes"],
            stderr_bytes=result["stderr_bytes"],
            last_output_at=result["last_output_at"],
        )
        write_run_metadata(
            exec_id,
            {
                **base_metadata,
                "provider_name": invocation["provider_name"],
                "prompt": invocation["system_context"],
            },
        )
        return {
            "stdout": clean_stdout,
            "stderr": result["stderr"],
            "raw_stdout": result["stdout"],
            "raw_stderr": result["stderr"],
            "returncode": result["returncode"],
            "run_id": exec_id,
        }
    except Exception as exc:
        err = str(exc)
        write_run_metadata(exec_id, base_metadata)
        update_execution(
            exec_id,
            "ERROR",
            "",
            err,
            output_summary=infer_output_summary("", err),
        )
        return {
            "stdout": "",
            "stderr": err,
            "raw_stdout": "",
            "raw_stderr": err,
            "returncode": 1,
            "run_id": exec_id,
        }
    finally:
        try:
            set_execution_pid(exec_id, None)
        except Exception:
            pass
