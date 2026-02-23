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

Alternatively, you can install manually using `uv`:

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

## Task Defintion Samples

Define tasks in `.toml` files under `.kage/tasks/`.

```toml
# Auto-refactor using AI
[task.refactor]
name = "Daily Refactor"
cron = "0 3 * * *"
prompt = "Please clean up the code in src/"
provider = "claude"

# Classification with JSON/JQ parsing
[task.labels]
name = "Ticket Labeling"
cron = "*/30 * * * *"
prompt = "Classify this issue as JSON '{\"label\":\"...\"}': 'Cannot login'"
provider = "codex_json"
parser_args = ".label"

# Standard Shell Command
[task.cleanup]
name = "Log Cleanup"
cron = "0 0 * * 0"
command = "rm -rf ./logs/*.log"
shell = "bash"
```

## Commands

- `kage onboard`: Initialize global settings and OS-level daemon.
- `kage init`: Initialize current directory as a kage project.
- `kage daemon install`: Register kage to system scheduler (cron/launchd).
- `kage daemon remove`: Unregister kage from system scheduler.
- `kage daemon status`: Check daemon registration status.
- `kage config <key> <value> [--global]`: Update configuration via CLI.
- `kage doctor`: Check setup health and configuration.
- `kage ui`: Launch web dashboard (default: [http://localhost:8484](http://localhost:8484)).
- `kage logs`: View execution history.
- `kage run`: Force run all scheduled tasks (normally executed by cron/launchd).

## License

MIT
