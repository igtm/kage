---
name: kage
description: Autonomous AI Project Agent & Cron Task Runner. Orchestrates repetitive AI-driven engineering tasks with state persistence (Memory) and advanced workflow controls.
---

# kage - Autonomous AI Project Agent

`kage` is an autonomous execution layer for AI agents. It maintains state across executions (Memory), decomposes high-level goals into Todo lists, and provides robust workflow controls.

## Core Features

- **Autonomous Workflow**: Decomposes tasks into Markdown checklists and tracks progress via Memory.
- **Execution Modes**: `continuous` (default), `once` (run once and deactivate), `autostop` (stop when AI signals completion).
- **Hybrid Task Types**: AI-driven prompts (Markdown body) or direct shell commands (`command` front matter).
- **Concurrency Control**: `allow`, `forbid` (skip if running), `replace` (kill old and restart).
- **Time Windows**: `allowed_hours: "9-17"` or `denied_hours: "12"`.
- **State Persistence**: `.kage/memory/{task}/{date}.json`.
- **Connectors**: Sync AI chat with external services like Discord/Slack for project-specific automation.
- **Layered Config**: `.kage/config.local.toml` > `.kage/config.toml` > `~/.kage/config.toml` > defaults.

## CLI

- `kage onboard` — Setup global directories and `kage cron`.
- `kage init` — Initialize in current directory.
- `kage run` — Execute due tasks manually.
- `kage task list` — List tasks with status and schedule.
- `kage task show <name>` — Detailed task configuration.
- `kage connector list` — List all configured connectors.
- `kage connector setup <type>` — Show setup guide for a connector (discord, slack).
- `kage connector poll` — Manually trigger polling for all connectors.
- `kage doctor` — Diagnose config and environment.
- `kage ui` — Open web dashboard.

## Task File Template (`.kage/tasks/*.md`)

```markdown
---
name: <Task Name>
cron: "<cron expression>"
provider: <provider name>      # e.g. claude, gemini, codex
mode: continuous               # continuous | once | autostop
policy: forbid                 # allow | forbid | replace
timeout: 3600                  # seconds
allowed_hours: ""              # e.g. "9-17" (optional)
denied_hours: ""               # e.g. "0-8,18-23" (optional)
active: true
---

# Task: <Title>

<Describe what the AI agent should do here.>
```

### Shell-Command Task Variant

```markdown
---
name: <Task Name>
cron: "<cron expression>"
command: "<shell command>"
shell: bash
---
```

## Configuration Hierarchy

1. `.kage/config.local.toml` (Git-ignored overrides)
2. `.kage/config.toml` (Project-shared)
3. `~/.kage/config.toml` (User-global)
4. Library Defaults
- **Background Loop**: Runs via `kage cron install` (cron/launchd).
