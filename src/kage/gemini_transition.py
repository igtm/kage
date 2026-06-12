from __future__ import annotations

import sys
from typing import TextIO

GEMINI_CLI_SUNSET_DATE = "June 18, 2026"
GEMINI_CLI_TRANSITION_BLOG_URL = (
    "https://developers.googleblog.com/"
    "an-important-update-transitioning-gemini-cli-to-antigravity-cli/"
)


def is_gemini_provider_name(provider_name: str | None) -> bool:
    return provider_name == "gemini"


def should_warn_for_gemini_config(key: str, value: str) -> bool:
    normalized_key = key.strip()
    normalized_value = value.strip()
    if normalized_key == "default_ai_engine" and normalized_value == "gemini":
        return True
    if normalized_key.startswith("providers.gemini"):
        return True
    return False


def build_gemini_transition_warning(context: str | None = None) -> str:
    prefix = "[kage] WARNING:"
    if context:
        prefix = f"{prefix} {context}"

    return (
        f"{prefix} Gemini CLI consumer access stops serving requests on "
        f"{GEMINI_CLI_SUNSET_DATE} for Google AI Pro, Ultra, and free Gemini Code "
        f"Assist for individuals. Prefer Antigravity CLI (`provider: antigravity`) "
        f"for new kage workflows. Enterprise and paid API key access remain "
        f"supported. Blog: {GEMINI_CLI_TRANSITION_BLOG_URL}"
    )


def emit_gemini_transition_warning(
    context: str | None = None, stream: TextIO | None = None
) -> None:
    print(build_gemini_transition_warning(context), file=stream or sys.stderr)
