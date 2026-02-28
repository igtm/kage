import subprocess
import os
import shutil
from pathlib import Path
from ..config import get_global_config

DEFAULT_PERSONA = """
You are Kage (影), a dedicated and highly capable autonomous assistant working directly on the user's PC.
Your role is to support the user in their daily tasks, acting like a proactive secretary.
Since you operate directly on the host machine, you have powerful access to the file system, databases, and local tools.

[CRITICAL: THINKING PROCESS ISOLATION]
- Before providing your final response, you MUST wrap ALL internal reasoning, plans, or "chain of thought" inside `<think>` and `</think>` tags.
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
    Remove <think>...</think> blocks from the AI's response.
    Also handles unclosed tags gracefully.
    """
    import re
    # Remove both <think>...</think> and anything inside a <think> tag at the end that hasn't closed
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'<think>.*', '', text, flags=re.DOTALL)
    return text.strip()

def generate_chat_reply(message: str, persona: str | None = None) -> dict:
    """
    Generate a reply from the default AI engine configured in kage.
    Returns a dict with 'stdout', 'stderr', and 'returncode'.
    If `persona` is provided (or defaults to DEFAULT_PERSONA), it is prepended to the message.
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
    
    active_persona = persona if persona is not None else DEFAULT_PERSONA
    system_context = f"[System Context / Persona]\n{active_persona.strip()}\n\n[User Message]\n{message}"
    
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
