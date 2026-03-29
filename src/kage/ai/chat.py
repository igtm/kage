import subprocess
import os
import shutil
import re
from pathlib import Path
from ..artifacts import (
    build_connector_delivery_prompt,
    ensure_workspace_artifact_staging_dir,
    inject_connector_delivery_env,
    persist_artifacts_from_staging,
    write_artifact_metadata,
)
from ..config import get_global_config, render_command_template
from ..connector_payload import ConnectorAttachment
from ..runs import infer_output_summary

# Provider name → thinking tag mapping
# Different AI models are trained with different internal reasoning tags
PROVIDER_THINKING_TAGS: dict[str, str] = {
    "gemini": "think",
    "claude": "antml:thinking",
    "codex": "thinking",
}
DEFAULT_THINKING_TAG = "think"
_QUICK_TAG_RE = re.compile(
    r"<\s*\/?\s*(?:think(?:ing)?|thought|antthinking|antml:thinking|final)\b",
    re.IGNORECASE,
)
_MALFORMED_OPEN_TAG_RE = re.compile(
    r"<\s*(?:think(?:ing)?|thought|antthinking|antml:thinking|final)\b",
    re.IGNORECASE,
)
_FINAL_TAG_RE = re.compile(r"<\s*(/?)\s*final\b[^<>]*>", re.IGNORECASE)
_THINKING_TAG_RE = re.compile(
    r"<\s*(\/?)\s*(?:think(?:ing)?|thought|antthinking|antml:thinking)\b[^<>]*>",
    re.IGNORECASE,
)


def get_thinking_tag(provider_name: str) -> str:
    """Return the thinking tag for a given provider name."""
    return PROVIDER_THINKING_TAGS.get(provider_name, DEFAULT_THINKING_TAG)


def _find_code_regions(text: str) -> list[tuple[int, int]]:
    regions: list[tuple[int, int]] = []

    for match in re.finditer(
        r"(^|\n)(```|~~~)[^\n]*\n[\s\S]*?(?:\n\2(?:\n|$)|$)", text
    ):
        prefix = len(match.group(1))
        start = match.start() + prefix
        regions.append((start, match.end()))

    for match in re.finditer(r"`+[^`]+`+", text):
        start = match.start()
        end = match.end()
        inside_fenced = any(
            region_start <= start and end <= region_end
            for region_start, region_end in regions
        )
        if not inside_fenced:
            regions.append((start, end))

    regions.sort()
    return regions


def _is_inside_code(pos: int, regions: list[tuple[int, int]]) -> bool:
    return any(start <= pos < end for start, end in regions)


def _strip_thinking_blocks(text: str) -> str:
    code_regions = _find_code_regions(text)
    result_parts: list[str] = []
    last_index = 0
    in_thinking = False

    for match in _THINKING_TAG_RE.finditer(text):
        index = match.start()
        if _is_inside_code(index, code_regions):
            continue

        is_close = match.group(1) == "/"
        if not in_thinking:
            result_parts.append(text[last_index:index])
            if not is_close:
                in_thinking = True
        elif is_close:
            in_thinking = False

        last_index = match.end()

    if not in_thinking:
        result_parts.append(text[last_index:])

    return "".join(result_parts)


def _extract_or_strip_final_blocks(text: str) -> str:
    code_regions = _find_code_regions(text)
    saw_open_final = False
    for match in _FINAL_TAG_RE.finditer(text):
        if match.group(1) != "/" and not _is_inside_code(match.start(), code_regions):
            saw_open_final = True
            break

    result_parts: list[str] = []
    last_index = 0
    in_final = False

    for match in _FINAL_TAG_RE.finditer(text):
        index = match.start()
        if _is_inside_code(index, code_regions):
            continue

        is_close = match.group(1) == "/"
        if saw_open_final:
            if in_final:
                result_parts.append(text[last_index:index])
                if is_close:
                    in_final = False
            elif not is_close:
                in_final = True
        else:
            result_parts.append(text[last_index:index])

        last_index = match.end()

    if saw_open_final:
        if in_final:
            result_parts.append(text[last_index:])
    else:
        result_parts.append(text[last_index:])

    return "".join(result_parts)


def _strip_trailing_malformed_open_tag(text: str) -> str:
    code_regions = _find_code_regions(text)
    for match in _MALFORMED_OPEN_TAG_RE.finditer(text):
        index = match.start()
        if _is_inside_code(index, code_regions):
            continue
        if ">" not in text[index:]:
            return text[:index]
    return text


DEFAULT_SYSTEM_PROMPT = """
You are Kage (影), a dedicated and highly capable autonomous assistant working directly on the user's PC.
Your role is to support the user in their daily tasks, acting like a proactive secretary.
Since you operate directly on the host machine, you have powerful access to the file system, databases, and local tools.

[CRITICAL: THINKING PROCESS ISOLATION]
- Before providing your final response, you MUST wrap ALL internal reasoning, plans, or "chain of thought" inside `<{thinking_tag}>` and `</{thinking_tag}>` tags.
- Format every reply as `<{thinking_tag}>...</{thinking_tag}>` followed by `<final>...</final>`, with no other text outside those tags.
- Only the content inside `<final>` is visible to the user. If you fail to isolate reasoning this way, your internal reflections will leak and confuse the user.

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
    if not text or not _QUICK_TAG_RE.search(text):
        return text.strip()

    cleaned = _strip_thinking_blocks(text)
    cleaned = _extract_or_strip_final_blocks(cleaned)
    cleaned = _strip_trailing_malformed_open_tag(cleaned)
    cleaned_result = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned_result.strip()


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
    artifact_dir: Path | None = None,
    connector_targets: list[tuple[str, str]] | None = None,
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
    if artifact_dir is not None:
        parts.append(
            build_connector_delivery_prompt(connector_targets, artifact_dir).strip()
        )
    parts.append(f"[User Message]\n{message}")
    system_context = "\n\n".join(parts)

    cmd = render_command_template(template, system_context, provider=provider)

    env = os.environ.copy()
    if config.env_path:
        env["PATH"] = config.env_path
    if artifact_dir is not None:
        inject_connector_delivery_env(env, artifact_dir, connector_targets)

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
    connector_meta = base_metadata.get("connector")
    connector_targets = None
    if isinstance(connector_meta, dict):
        connector_targets = [
            (
                str(connector_meta.get("name", "connector")),
                str(connector_meta.get("type", "unknown")),
            )
        ]
    artifact_staging_dir: Path | None = None
    attachments: list[ConnectorAttachment] = []

    exec_id = start_execution(
        effective_project_path,
        run_name,
        working_dir=str(cwd_path),
        execution_kind=execution_kind,
        provider_name=config.default_ai_engine,
    )
    artifact_staging_dir = ensure_workspace_artifact_staging_dir(cwd_path, exec_id)
    write_artifact_metadata(exec_id, None, artifact_staging_dir, [])

    try:
        invocation = _build_chat_invocation(
            message=message,
            system_prompt=system_prompt,
            working_dir=str(cwd_path),
            artifact_dir=artifact_staging_dir,
            connector_targets=connector_targets,
        )
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
            "attachments": attachments,
        }
    except Exception as exc:
        err = str(exc)
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
            "attachments": attachments,
        }
    finally:
        try:
            set_execution_pid(exec_id, None)
        except Exception:
            pass
