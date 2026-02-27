---
name: kage
description: AI native cron task runner. Allows scheduling AI prompts and shell commands on a per-project basis with multi-OS daemon support (cron/launchd).
---

# kage - AI Native Cron Task Runner

`kage` is a tool designed to automate repetitive tasks using AI providers (codex, claude, gemini, copilot) or standard shell commands. It operates on a per-project basis with a layered configuration system.

## Core Features

- **AI Prompt Scheduling**: Directly schedule AI prompts as cron jobs.
- **Multi-Provider Support**: Built-in configs for `codex`, `claude`, `gemini`, and `copilot`.
- **Layered Config**: Merges settings from library defaults, `~/.kage/config.toml`, and `.kage/config.toml`.
- **Daemon Management**: Easy setup for background execution via `cron` (Linux) or `launchd` (macOS).
- **Web Dashboard**: Monitor task history and global status at `http://localhost:8484`.

## CLI Usage

### Setup & Project Management
- `kage onboard`: Initialize global directory (`~/.kage/`) and register OS daemon.
- `kage init`: Initialize current directory as a kage project, creating `.kage/tasks/sample.toml`.
- `kage project list`: Show registered projects and task counts.
- `kage project remove [path]`: Unregister a project.
- `kage doctor`: Diagnose setup health, configuration validity, and CLI tool availability.
- `kage config-show [--workspace <path>]`: Show resolved merged config and loaded providers/commands.
- `kage config <key> <value> [--global]`: Update config values.

### Execution & Monitoring
- `kage run`: Manually trigger all scheduled tasks for registered projects (used by daemon).
- `kage ui`: Start the web-based dashboard.
- `kage logs`: View the recent execution history in the terminal.
- `kage task list`: Show all tasks and their status (ON/OFF).
- `kage task new <name>`: Create a new Markdown task file.
- `kage task on/off <name> [--all]`: Enable or disable tasks.
- `kage task show <name>`: Show a task's resolved configuration.
- `kage task run <name>`: Run one task immediately (ignore schedule).

### Daemon Control
- `kage daemon install`: Register the background runner to the OS.
- `kage daemon remove`: Unregister the background runner from the OS.
- `kage daemon status`: Check if the background runner is active.
- `kage daemon start/stop/restart`: Control the background runner without uninstalling.

## Task Configuration (.kage/tasks/*.toml or *.md)

Tasks can be defined in TOML or Markdown files. A typical task looks like this:

```toml
[task_my_task]
name = "Daily Report"
cron = "0 9 * * *"
active = true
prompt = "Analyze the logs in ./logs/ and summarize the key findings."
provider = "claude"
```

### Available Fields
- `name`: Human-readable task name.
- `cron`: Crontab expression for scheduling.
- `active`: Boolean flag to enable/disable the task (default: true).
- `prompt`: The AI prompt to execute.
- `command`: Alternative to `prompt`, a shell command to run.
- `provider`: Which AI config to use (defined in `config.toml`).
- `parser`: Output parser type (`raw` or `jq`).
- `parser_args`: Argument for the parser (e.g., jq query).

## Global Configuration (~/.kage/config.toml)

Important settings:
- `default_ai_engine = "codex"`: Must be set by the user.
- `ui_port = 8484`: Dashboard port.
- `[providers.NAME]`: Custom AI provider definitions.
- `[commands.NAME]`: Custom CLI command templates.

For `codex`, place global flags before `exec` for headless runs:

```toml
[commands.codex]
template = ["codex", "--ask-for-approval", "never", "--sandbox", "workspace-write", "exec", "{prompt}"]
```

## Release Notes

- Recommended release flow:
  1. Update `pyproject.toml` version and docs.
  2. `uv build`
  3. `gh release create v<version> --title "kage-ai v<version>" --generate-notes`
  4. Upload to PyPI with token auth (`__token__`).
