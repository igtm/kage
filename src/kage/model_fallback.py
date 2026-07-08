from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Optional

from .config import ProviderConfig
from .rate_limit import (
    clear_model_rate_limit_reset,
    get_model_rate_limit_reset,
    is_model_rate_limited,
    parse_rate_limit_info,
    set_model_rate_limit_reset,
)


def _now_tz() -> datetime:
    return datetime.now().astimezone()


def _format_failure_message(provider_name: str, attempts: list[dict]) -> str:
    lines = [f"All models exhausted for provider '{provider_name}'"]
    for attempt in attempts:
        model = attempt.get("model") or "(none)"
        status = attempt.get("status", "unknown")
        if status == "skipped":
            lines.append(
                f"  - {model}: skipped (known rate limit until {attempt.get('reset_at')})"
            )
        elif status == "rate_limited":
            lines.append(
                f"  - {model}: rate/usage limited (returncode={attempt.get('returncode')})"
            )
            if attempt.get("reset_at"):
                lines.append(f"      reset_at: {attempt['reset_at']}")
            if attempt.get("raw_hint"):
                lines.append(f"      hint: {attempt['raw_hint'][:200]}")
        elif status == "error":
            lines.append(
                f"  - {model}: failed (returncode={attempt.get('returncode')})"
            )
        else:
            lines.append(f"  - {model}: {status}")
    return "\n".join(lines)


def run_with_model_fallback(
    provider_name: str,
    provider: ProviderConfig,
    build_cmd: Callable[[Optional[str]], list[str]],
    run_cmd: Callable[[list[str]], dict],
    *,
    now: Optional[datetime] = None,
) -> dict:
    """
    Iterate over a provider's effective models until one succeeds.

    If a model returns a rate/usage limit error, the next model is tried.
    Parsed reset times are stored so future runs can skip known-limited models.

    Returns the result dict from the final run_cmd invocation, augmented with:
      - _fallback_attempts: list of attempt metadata
      - _used_model: the model that succeeded, or None
    """
    if now is None:
        now = _now_tz()

    models = provider.effective_models
    attempts: list[dict] = []
    last_result: Optional[dict] = None
    used_model: Optional[str] = None

    for model in models:
        if is_model_rate_limited(provider_name, model, now):
            reset_dt = get_model_rate_limit_reset(provider_name, model)
            attempts.append(
                {
                    "model": model,
                    "status": "skipped",
                    "reset_at": reset_dt.isoformat() if reset_dt else None,
                }
            )
            continue

        cmd = build_cmd(model)
        result = run_cmd(cmd)
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
        returncode = result.get("returncode", 1)
        last_result = dict(result)

        if returncode == 0:
            clear_model_rate_limit_reset(provider_name, model)
            used_model = model
            attempts.append(
                {
                    "model": model,
                    "status": "success",
                    "returncode": returncode,
                }
            )
            break

        info = parse_rate_limit_info(stdout, stderr, now)
        if info.is_limited:
            set_model_rate_limit_reset(
                provider_name, model, info.reset_at, info.raw_hint
            )
            attempts.append(
                {
                    "model": model,
                    "status": "rate_limited",
                    "returncode": returncode,
                    "reset_at": info.reset_at.isoformat() if info.reset_at else None,
                    "raw_hint": info.raw_hint,
                }
            )
            continue

        attempts.append(
            {
                "model": model,
                "status": "error",
                "returncode": returncode,
            }
        )
        break

    if last_result is None:
        # Every model was skipped due to a known future rate limit.
        last_result = {
            "returncode": 1,
            "stdout": "",
            "stderr": _format_failure_message(provider_name, attempts),
            "stdout_bytes": 0,
            "stderr_bytes": 0,
            "last_output_at": None,
            "pid": None,
        }
    else:
        stderr = last_result.get("stderr", "")
        if all(a.get("status") in ("skipped", "rate_limited") for a in attempts):
            failure_msg = _format_failure_message(provider_name, attempts)
            last_result["stderr"] = (
                f"{failure_msg}\n\n--- original stderr ---\n{stderr}"
                if stderr
                else failure_msg
            )

    last_result.setdefault("stdout", "")
    last_result.setdefault("stderr", "")
    last_result.setdefault("stdout_bytes", 0)
    last_result.setdefault("stderr_bytes", 0)
    last_result.setdefault("last_output_at", None)
    last_result["_fallback_attempts"] = attempts
    last_result["_used_model"] = used_model
    return last_result
