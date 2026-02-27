# kage 影 - Autonomous AI Project Agent

![kage hero](./hero.png)

English | [日本語](./README_JA.md)

`kage` is an autonomous execution layer for project-specific AI agents. It schedules AI-driven tasks via cron, maintains state across runs using a persistent memory system, and provides advanced workflow controls.

## Features

- **Autonomous Agent Logic**: Automatically decomposes tasks into GFM checklists and tracks progress.
- **Persistent Memory**: Stores task state in `.kage/memory/` to maintain context.
- **Hybrid Tasks**: Supports both AI prompts (Markdown body) and direct shell commands (`command` in front matter).
- **Advanced Workflow Controls**:
    - **Execution Modes**: `continuous`, `once`, `autostop`.
    - **Concurrency Policy**: `allow`, `forbid` (skip if running), `replace` (kill old).
    - **Time Windows**: Restrict execution using `allowed_hours: "9-17"` or `denied_hours: "12"`.
- **Markdown-First**: Define tasks using simple Markdown files with YAML front matter.
- **Layered Configuration**: `.kage/config.local.toml` > `.kage/config.toml` > `~/.kage/config.toml` > defaults.

## Installation

```bash
curl -sSL https://raw.githubusercontent.com/igtm/kage/main/install.sh | bash
```

## Task Example (`.kage/tasks/audit.md`)

### AI Task
```markdown
---
name: Project Auditor
cron: "0 * * * *"
provider: gemini
---

# Task: Continuous Health Check
Analyze the current codebase for architectural drifts.
```

### Shell-Command Task
```markdown
---
name: Log Cleanup
cron: "0 0 * * *"
command: "rm -rf ./logs/*.log"
shell: "bash"
---
Cleanup old logs every midnight.
```

## Commands

- `kage onboard`: Global setup.
- `kage init`: Initialize kage in the current directory.
- `kage run`: Manually trigger tasks.
- `kage task list`: List all tasks.
- `kage task show <name>`: Show detailed configuration.
- `kage doctor`: Diagnose configuration health.
- `kage skill`: Display agent skill guidelines (SKILL.md).

## Configuration

- `~/.kage/config.toml`: Global settings.
- `.kage/config.toml`: Project-shared settings.
- `.kage/config.local.toml`: Local overrides (git-ignored).
- `.kage/system_prompt.md`: Project-specific system prompt.
