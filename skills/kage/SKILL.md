---
name: kage
description: Autonomous AI Project Agent & Cron Task Runner. Orchestrates repetitive AI-driven engineering tasks with state persistence (Memory).
---

# kage - Autonomous AI Project Agent

`kage` is an autonomous execution layer for AI agents. It goes beyond simple task running by maintaining state across executions (Memory) and decomposing high-level goals into manageable Todo lists.

## Core Features

- **Autonomous Workflow**: Decomposes tasks into Markdown checklists and tracks progress across cron cycles.
- **State Persistence (Memory)**: Maintains `.kage/memory/{task}/{date}.json` to carry over context between runs.
- **System Prompt Layering**: Inherits best practices from a global system prompt, which can be overridden at the project level (`.kage/system_prompt.md`).
- **Markdown-Native Tasks**: Define tasks using simple Markdown files with YAML front matter.
- **Project-Centric Config**: Layered configuration supporting `.kage/config.local.toml` for machine-specific overrides.

## CLI Usage

### Setup & Project Management
- `kage onboard`: Initial global setup (daemons, directories, DB).
- `kage init`: Initialize a new project (creates `.kage/tasks/daily_audit.md`).
- `kage project list`: Monitor all registered projects.
- `kage doctor`: Comprehensive diagnostic of configs, tasks, and environment.

### Execution & Monitoring
- `kage run`: Execute all due tasks (called by system cron/launchd).
- `kage task list`: See status of all tasks.
- `kage task run <name>`: Execute a specific task immediately.
- `kage ui`: Launch the web dashboard to monitor execution history and logs.

## Task Configuration (.kage/tasks/*.md)

Tasks are now defined exclusively in Markdown.

```markdown
---
name: Code Reviewer
cron: "0 18 * * *"
active: true
provider: claude
---

# Task: Continuous Code Audit
1. Analyze recent commits in the 'src/' directory.
2. Identify potential security flaws or technical debt.
3. Update the Task Memory with a Todo list of fixes.
```

## Configuration Hierarchy

1. `.kage/config.local.toml` (Highest priority, git-ignored)
2. `.kage/config.toml` (Project-shared settings)
3. `~/.kage/config.toml` (User-global settings)
4. Library Defaults

## Development Principles

- **Surgical Changes**: `kage` focuses on specific, atomic improvements.
- **Context-Aware**: Always refers to previous run's memory to ensure continuity.
- **Transparent**: Every AI interaction and state change is logged and visible via the Web UI.
