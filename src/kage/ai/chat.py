import subprocess
import os
import shutil
from pathlib import Path
from ..config import get_global_config

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
- Before providing your final response, you MUST wrap ALL internal reasoning, plans, or "chain of thought" inside `<{thinking_tag}>` and `</{thinking_tag}>` tags.
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
    tags = r'(?:think|thinking|thought|antthinking|antml:thinking|final)'
    # Remove closed tag pairs
    text = re.sub(rf'<{tags}>.*?</{tags}>', '', text, flags=re.DOTALL)
    # Remove unclosed tags at the end
    text = re.sub(rf'<{tags}>.*', '', text, flags=re.DOTALL)
    return text.strip()

def generate_chat_reply(message: str, system_prompt: str | None = None) -> dict:
    """
    Generate a reply from the default AI engine configured in kage.
    Returns a dict with 'stdout', 'stderr', and 'returncode'.
    DEFAULT_SYSTEM_PROMPT is always included. If `system_prompt` is provided,
    it is appended as additional instructions.
    """
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
    parts = [f"[System Context]\n{DEFAULT_SYSTEM_PROMPT.strip().format(thinking_tag=thinking_tag)}"]
    if system_prompt:
        parts.append(f"[Additional Instructions]\n{system_prompt.strip()}")
    parts.append(f"[User Message]\n{message}")
    system_context = "\n\n".join(parts)
    
    cmd = [part.replace("{prompt}", system_context) for part in template]

    env = os.environ.copy()
    if config.env_path:
        env["PATH"] = config.env_path

    if cmd and cmd[0]:
        exe_path = shutil.which(cmd[0], path=env.get("PATH"))
        if exe_path:
            cmd[0] = exe_path

    res = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(Path.cwd()), env=env
    )
    return {
        "stdout": res.stdout,
        "stderr": res.stderr,
        "returncode": res.returncode,
    }
