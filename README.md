# kage 影 - AI Native Cron Task Runner

![kage hero](./hero.png)

English | [日本語](./README_JA.md)

`kage` is a tool for running scheduled tasks using AI CLIs (codex, claude, gemini, etc.) or standard shell commands, managed on a per-project basis.

## Features

- **AI Native**: Run AI prompts directly from a `cron` schedule.
- **Flexible AI Providers**: Built-in support for `codex`, `claude`, `gemini`, and `copilot` with easy customization.
- **Inline Overrides**: Customize commands, AI models, or parsers (like jq) for each specific task.
- **3-Layer Configuration**: Configuration is merged from library defaults, user overrides (~/.kage), and workspace-specific settings (.kage).
- **Web UI**: Monitor task execution and logs through a sleek browser dashboard.

## Installation

The easiest way to install kage is via the interactive installer:

```bash
curl -sSL https://raw.githubusercontent.com/igtm/kage/main/install.sh | bash
```

Or install from PyPI:

```bash
pip install kage-ai
```

Alternatively, install with `uv`:

```bash
uv tool install git+https://github.com/igtm/kage.git
kage onboard
```

## Getting Started

1. **Global Setup (First time only)**:
   ```bash
   kage onboard
   ```
   This initializes `~/.kage/`, the database, and the crontab entries.

2. **Configure AI Engine**:
   Create `~/.kage/config.toml` and specify your default engine.
   ```toml
   default_ai_engine = "codex"
   ```

3. **Initialize Project**:
   Run this in your project directory.
   ```bash
   kage init
   ```
   This creates `.kage/tasks/sample.toml`.

## Task Definition Samples

Define tasks in `.toml` **or** `.md` files under `.kage/tasks/`.

- `*.toml`: existing format (single or multiple tasks per file)
- `*.md`: front matter + markdown body, **one file = one prompt task only**

```toml
# Auto-refactor using AI
[task_refactor]
name = "Daily Refactor"
cron = "0 3 * * *"
active = true
prompt = "Please clean up the code in src/"
provider = "claude"

# Classification with JSON/JQ parsing
[task_labels]
name = "Ticket Labeling"
cron = "*/30 * * * *"
active = true
prompt = "Classify this issue as JSON '{\"label\":\"...\"}': 'Cannot login'"
provider = "codex_json"
parser_args = ".label"

# Standard Shell Command
[task_cleanup]
name = "Log Cleanup"
cron = "0 0 * * 0"
active = true
command = "rm -rf ./logs/*.log"
shell = "bash"
```

```md
---
name: Nightly Research
cron: "0 2 * * *"
active: true
provider: codex
---

Collect benchmark updates and summarize differences.
Add comparison points for quality, speed, and cost.
```

In markdown tasks, the entire body after front matter is treated as the prompt.

## Commands

- `kage onboard`: Initialize global settings and OS-level daemon.
- `kage init`: Initialize current directory as a kage project.
- `kage daemon install`: Register kage to system scheduler (cron/launchd).
- `kage daemon remove`: Unregister kage from system scheduler.
- `kage daemon status`: Check daemon registration status.
- `kage config <key> <value> [--global]`: Update configuration via CLI.
- `kage config-show [--workspace <path>]`: Show resolved config (merged defaults/user/workspace), including loaded `providers` and `commands`.
- `kage doctor`: Check setup health and validate config/task files (unknown keys, type errors, invalid cron, missing front matter, etc).
- `kage ui`: Launch web dashboard (default: [http://localhost:8484](http://localhost:8484)). Toggle task ON/OFF directly from the UI.
- `kage logs`: View execution history.
- `kage run`: Force run all scheduled tasks (normally executed by cron/launchd).
- `kage task list`: List all tasks with their status (ON/OFF).
- `kage task new <file_name>`: Create a new Markdown task file.
- `kage task on/off <name> [--all]`: Enable or disable tasks.
- `kage task show <name>`: Show details for one task.
- `kage task run <name>`: Run one task immediately.
- `kage project list`: List registered projects.
- `kage project remove [path]`: Unregister a project.

## Release / Publish

```bash
# 1) Build package
uv build

# 2) Create release (example: v0.0.1)
gh release create v0.0.1 --title "kage v0.0.1" --generate-notes

# 3) Publish to PyPI (token auth)
TWINE_USERNAME=__token__ \
TWINE_PASSWORD='<pypi-token>' \
uvx twine upload dist/*
```

## Codex Provider Note (Headless / launchd)

When defining a custom codex command template, place global flags **before** `exec`:

```toml
[commands.codex]
template = ["codex", "--ask-for-approval", "never", "--sandbox", "workspace-write", "exec", "{prompt}"]
```

`codex exec --ask-for-approval ...` may fail depending on CLI version.

## License

MIT
