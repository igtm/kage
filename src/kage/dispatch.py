"""Detached, one-off agent runs started from connector conversations."""

from __future__ import annotations

import os
import sqlite3
import subprocess

from .agent import (
    AGENT_NAME_ENV_VAR,
    RUN_ID_ENV_VAR,
    assert_connector_command_allowed,
    build_full_system_prompt,
    get_agent,
)
from .connector_payload import ConnectorMessage
from .db import (
    get_execution_agent,
    get_execution_status,
    set_execution_pid,
    start_execution,
    update_execution,
)
from .runs import get_run, infer_output_summary, load_run_metadata, write_run_metadata


class DispatchError(RuntimeError):
    """Raised when a dispatch request cannot be safely created or executed."""


def _connector_agent_name(config, connector_name: str) -> str | None:
    c_dict = config.connectors.get(connector_name)
    if not c_dict:
        return None
    bound = c_dict.get("agent")
    if hasattr(bound, "unwrap"):
        bound = bound.unwrap()
    return str(bound or config.default_agent)


def _source_context(source_run_id: str) -> tuple[object, str, str, str]:
    """Return the DB-anchored source run, agent, connector name, and type."""
    from .config import get_global_config

    source_run = get_run(source_run_id)
    source_agent = get_execution_agent(source_run_id)
    if source_run is None or source_agent is None:
        raise DispatchError("KAGE_RUN_ID does not identify an agent-scoped run.")
    if source_run.status != "RUNNING" or not str(
        source_run.execution_kind or ""
    ).startswith("connector_"):
        raise DispatchError("Dispatch is available only from an active connector run.")

    metadata = load_run_metadata(source_run_id)
    connector_meta = metadata.get("connector")
    if not isinstance(connector_meta, dict):
        raise DispatchError("Dispatch is available only from a connector run.")
    connector_name = str(connector_meta.get("name") or "")
    connector_type = str(connector_meta.get("type") or "unknown")
    if not connector_name:
        raise DispatchError("The source run has no connector identity.")
    if source_run.task_name != f"connector:{connector_name}":
        raise DispatchError("The source connector identity does not match its run.")

    config = get_global_config()
    bound_agent = _connector_agent_name(config, connector_name)
    if bound_agent != source_agent:
        raise DispatchError(
            f"Connector '{connector_name}' is not bound to source agent "
            f"'{source_agent}'."
        )
    return source_run, source_agent, connector_name, connector_type


def start_dispatch(prompt: str, *, name: str = "one-off") -> tuple[str, int]:
    """Create a child run and launch its worker in a detached process."""
    from .connectors.realtime_manager import _kage_command

    source_run_id = os.environ.get(RUN_ID_ENV_VAR)
    if not source_run_id:
        raise DispatchError(
            "Dispatch requires KAGE_RUN_ID and can only be started from a connector run."
        )
    source_run, source_agent, connector_name, connector_type = _source_context(
        source_run_id
    )

    clean_prompt = prompt.strip()
    if not clean_prompt:
        raise DispatchError("Dispatch prompt must not be empty.")
    clean_name = " ".join(name.split()).strip() or "one-off"
    working_dir = source_run.working_dir or source_run.project_path
    from .config import get_global_config

    config = get_global_config()
    source_agent_config = get_agent(config, source_agent)
    if source_agent_config.name != source_agent:
        raise DispatchError(f"Agent '{source_agent}' is no longer configured.")

    child_run_id = start_execution(
        source_run.project_path,
        f"dispatch:{clean_name}",
        working_dir=working_dir,
        execution_kind="dispatch",
        provider_name=(source_agent_config.provider or config.default_ai_engine),
        agent_name=source_agent,
    )
    write_run_metadata(
        child_run_id,
        {
            "dispatch": {
                "parent_run_id": source_run_id,
                "name": clean_name,
                "request": clean_prompt,
            },
            "connector": {
                "name": connector_name,
                "type": connector_type,
            },
            "agent_name": source_agent,
        },
    )

    cmd = _kage_command() + ["_dispatch-worker", child_run_id]
    env = os.environ.copy()
    env[RUN_ID_ENV_VAR] = source_run_id
    env[AGENT_NAME_ENV_VAR] = source_agent
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=working_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            env=env,
        )
    except Exception as exc:
        error = f"Failed to start dispatch worker: {exc}"
        update_execution(
            child_run_id,
            "ERROR",
            "",
            error,
            output_summary=infer_output_summary("", error),
        )
        raise DispatchError(error) from exc

    return child_run_id, proc.pid


def _load_worker_context(child_run_id: str) -> tuple[object, str, str, str, str, str]:
    child_run = get_run(child_run_id)
    child_agent = get_execution_agent(child_run_id)
    metadata = load_run_metadata(child_run_id)
    dispatch_meta = metadata.get("dispatch")
    connector_meta = metadata.get("connector")
    if child_run is None or child_agent is None:
        raise DispatchError("Dispatch run does not exist or has no agent binding.")
    if child_run.execution_kind != "dispatch":
        raise DispatchError("Refusing to run a non-dispatch execution as a worker.")
    if not isinstance(dispatch_meta, dict) or not isinstance(connector_meta, dict):
        raise DispatchError("Dispatch metadata is incomplete.")

    parent_run_id = str(dispatch_meta.get("parent_run_id") or "")
    inherited_run_id = os.environ.get(RUN_ID_ENV_VAR)
    if not parent_run_id or inherited_run_id != parent_run_id:
        raise DispatchError("Dispatch worker parent-run authentication failed.")
    parent_agent = get_execution_agent(parent_run_id)
    if parent_agent != child_agent:
        raise DispatchError("Dispatch child agent does not match its parent run.")

    prompt = str(dispatch_meta.get("request") or "").strip()
    connector_name = str(connector_meta.get("name") or "")
    connector_type = str(connector_meta.get("type") or "unknown")
    if not prompt or not connector_name:
        raise DispatchError("Dispatch prompt or connector identity is missing.")
    parent_run = get_run(parent_run_id)
    if parent_run is None or parent_run.task_name != f"connector:{connector_name}":
        raise DispatchError("Dispatch connector does not match its parent run.")
    return (
        child_run,
        child_agent,
        parent_run_id,
        connector_name,
        connector_type,
        prompt,
    )


def run_dispatch_worker(child_run_id: str) -> None:
    """Execute a previously registered dispatch run and notify its source connector."""
    from .ai.chat import generate_logged_chat_reply
    from .config import get_global_config
    from .connectors.runner import get_connector

    authenticated = False
    try:
        (
            child_run,
            child_agent,
            parent_run_id,
            connector_name,
            connector_type,
            prompt,
        ) = _load_worker_context(child_run_id)
        authenticated = True
        set_execution_pid(child_run_id, os.getpid())
        config = get_global_config()
        if _connector_agent_name(config, connector_name) != child_agent:
            raise DispatchError("Connector binding changed across tenant boundaries.")
        agent = get_agent(config, child_agent)
        if agent.name != child_agent:
            raise DispatchError(f"Agent '{child_agent}' is no longer configured.")

        # From this point onward, all CLI calls made by the dispatched agent are
        # authorized against the immutable child execution, not its parent run.
        os.environ[RUN_ID_ENV_VAR] = child_run_id
        os.environ[AGENT_NAME_ENV_VAR] = child_agent
        worker_system_prompt = (
            f"{build_full_system_prompt(config, agent)}\n\n"
            "[Dispatch Worker Instructions]\n"
            "You are already running as a detached one-off dispatch. Perform the "
            "requested work directly. Do not call `kage dispatch` again for this "
            "same work. Your final output will be delivered automatically to the "
            "source connector."
        )
        result = generate_logged_chat_reply(
            prompt,
            system_prompt=worker_system_prompt,
            working_dir=child_run.working_dir or child_run.project_path,
            run_name=child_run.task_name,
            execution_kind="dispatch",
            metadata={
                "dispatch": {
                    "parent_run_id": parent_run_id,
                    "request": prompt,
                },
                "connector": {
                    "name": connector_name,
                    "type": connector_type,
                },
                "agent_name": child_agent,
            },
            project_path=child_run.project_path,
            agent_name=child_agent,
            existing_run_id=child_run_id,
        )

        # Re-check the DB-anchored child identity and current connector binding
        # immediately before sending the result.
        assert_connector_command_allowed(config, connector_name)
        connector = get_connector(connector_name)
        if connector is None:
            raise DispatchError(f"Connector '{connector_name}' is unavailable.")
        status = get_execution_status(child_run_id) or "ERROR"
        stdout = str(result.get("stdout") or "").strip()
        stderr = str(result.get("stderr") or "").strip()
        if status == "SUCCESS":
            message = stdout or f"Dispatch '{child_run.task_name}' completed."
        else:
            detail = stdout or stderr or "No error details were produced."
            message = (
                f"Dispatch '{child_run.task_name}' ended with {status}.\n\n{detail}"
            )
        delivery = connector.send_message(
            ConnectorMessage(
                text=message,
                attachments=list(result.get("attachments", [])),
                run_id=child_run_id,
            )
        )
        write_run_metadata(
            child_run_id,
            {"dispatch_delivery": delivery.to_metadata()},
            merge=True,
        )
    except Exception as exc:
        if not authenticated:
            raise
        error = str(exc)
        current = get_run(child_run_id)
        if current is not None and current.status != "STOPPED":
            stderr = current.stderr or ""
            if stderr:
                stderr += "\n"
            stderr += f"Dispatch worker error: {error}"
            update_execution(
                child_run_id,
                "ERROR",
                current.stdout or "",
                stderr,
                exit_code=current.exit_code,
                output_summary=infer_output_summary(current.stdout or "", stderr),
            )
        write_run_metadata(
            child_run_id,
            {"dispatch_error": error},
            merge=True,
        )
        raise
    finally:
        if authenticated:
            try:
                set_execution_pid(child_run_id, None)
            except sqlite3.Error:
                pass
