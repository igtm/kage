---
name: kage
description: Autonomous AI Project Agent & Cron Task Runner. Orchestrates repetitive AI-driven engineering tasks with state persistence (Memory) and advanced workflow controls.
---

# kage - Autonomous AI Project Agent

`kage` is an autonomous execution layer for AI agents. It maintains state across executions (Memory), decomposes high-level goals into Todo lists, and provides robust workflow controls.

## Core Features

- **Autonomous Workflow**: Decomposes tasks into Markdown checklists and tracks progress via Memory.
- **Execution Modes**:
    - `continuous`: Default cron-based execution.
    - `once`: Runs once and deactivates.
    - `autostop`: Stops when AI signals 'status: Completed' in Memory.
- **Hybrid Task Types**: Supports both AI-driven prompts (Markdown body) and direct shell commands (`command` in front matter).
- **Concurrency Control**: 
    - `allow`: Multiple instances allowed.
    - `forbid`: Skips if already running.
    - `replace`: Kills old instance and starts fresh.
- **Time Windows**: Restrict execution to specific hours (e.g., `allowed_hours: "9-17"`, `denied_hours: "12"`).
- **State Persistence**: Maintains `.kage/memory/{task}/{date}.json`.
- **Project-Centric Config**: Layered configuration with `.kage/config.local.toml`.

## CLI Usage

### Setup & Project Management
- `kage onboard`: Global setup (daemons, directories, DB).
- `kage init`: Initialize a new project.
- `kage doctor`: Diagnose configs, tasks, and environment.

### Execution & Monitoring
- `kage run`: Execute due tasks (manual trigger).
- `kage task list`: See status and schedule of all tasks.
- `kage task show <name>`: Display detailed task configuration.
- `kage ui`: Web dashboard for execution history and logs.

## Task Configuration (.kage/tasks/*.md)

### AI-Driven Task
```markdown
---
name: Code Auditor
cron: "0 * * * *"
provider: claude
---

# Task: Continuous Health Check
Analyze the 'src/' directory and report findings.
```

### Shell-Command Task
```markdown
---
name: Database Backup
cron: "0 3 * * *"
command: "./scripts/backup_db.sh"
shell: "bash"
---
Backup the production database every night.
```

## Configuration Hierarchy

1. `.kage/config.local.toml` (Git-ignored overrides)
2. `.kage/config.toml` (Project-shared)
3. `~/.kage/config.toml` (User-global)
4. Library Defaults
