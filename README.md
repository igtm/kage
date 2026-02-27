# kage 影 - Autonomous AI Project Agent

![kage hero](./hero.png)

English | [日本語](./README_JA.md)

`kage` is an autonomous execution layer for project-specific AI agents. It schedules AI-driven tasks via cron, maintains state across runs using a persistent memory system, and allows for layered configuration.

## Features

- **Autonomous Agent Logic**: Automatically decomposes tasks into GFM checklists and tracks progress.
- **Persistent Memory**: Stores task state in `.kage/memory/` to maintain context across cron cycles.
- **Markdown-First**: Define tasks using simple Markdown files with YAML front matter.
- **Layered System Prompts**: Customize AI behavior globally or per-project using `system_prompt.md`.
- **Flexible Configuration**: 4-layer configuration: `.kage/config.local.toml` > `.kage/config.toml` > `~/.kage/config.toml` > defaults.
- **Web Dashboard**: Monitor execution history and real-time logs at `http://localhost:8484`.

## Installation

```bash
curl -sSL https://raw.githubusercontent.com/igtm/kage/main/install.sh | bash
```

Or via PyPI:
```bash
pip install kage-ai
```

## Quick Start

1. **Onboard**: `kage onboard` (Setup global dirs and daemon)
2. **Configure**: Set `default_ai_engine = "claude"` in `~/.kage/config.toml`.
3. **Initialize Project**: `kage init` in your repo.
4. **Define Task**: Edit `.kage/tasks/daily_audit.md`.

## Task Example (`.kage/tasks/audit.md`)

```markdown
---
name: Project Auditor
cron: "0 9 * * *"
provider: gemini
---

# Task: Continuous Health Check
Analyze the current codebase for architectural drifts.
On the first run, create a Todo list in the Memory.
In subsequent runs, pick one item and provide a detailed report.
```

## Commands

- `kage onboard`: Global setup.
- `kage init`: Initialize kage in the current directory.
- `kage run`: Manually trigger all scheduled tasks.
- `kage ui`: Launch web dashboard.
- `kage task list`: List all tasks.
- `kage task run <name>`: Run a specific task immediately.
- `kage doctor`: Diagnose configuration and environment health.

## Configuration

- `~/.kage/config.toml`: Global settings.
- `.kage/config.toml`: Project-shared settings.
- `.kage/config.local.toml`: Local overrides (usually git-ignored).
- `~/.kage/system_prompt.md`: Global system prompt.
- `.kage/system_prompt.md`: Project-specific system prompt.
