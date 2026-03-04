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
- **Connectors**: Integrate with Discord/Slack/Telegram for task notifications (always on) and optional bi-directional chat (`poll = true`).
- **Layered Config**: `.kage/config.local.toml` > `.kage/config.toml` > `~/.kage/config.toml` > defaults.

## CLI

- `kage onboard` — Setup global directories and `kage cron`.
- `kage init` — Initialize in current directory.
- `kage run` — Execute due tasks manually.
- `kage task list` — List tasks with status and schedule.
- `kage task show <name>` — Detailed task configuration.
- `kage connector list` — List all configured connectors.
- `kage connector setup <type>` — Show setup guide for a connector (discord, slack, telegram).
- `kage connector poll` — Manually trigger polling for all connectors.
- `kage doctor` — Diagnose config and environment.
- `kage ui` — Open web dashboard.

## Task File Template (`.kage/tasks/*.md`)

```markdown
---
name: <Task Name>
cron: "<cron expression>"
provider: <provider name>           # e.g. codex, claude, gemini, opencode, aider
mode: continuous                    # continuous | once | autostop
concurrency_policy: allow           # allow | forbid | replace
timeout_minutes: 60                 # minutes (optional)
timezone: "Asia/Tokyo"              # e.g. "UTC", "Asia/Tokyo" (optional)
allowed_hours: "9-17"               # e.g. "9-17,21" (optional)
denied_hours: "0-5"                 # e.g. "0-5,12" (optional)
notify_connectors: ["discord"]      # list of connector names (optional)
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

## Connectors

Connectors integrate with external chat services. Sending (task notifications via `notify_connectors`) is **always enabled** as long as credentials are configured. Polling (bi-directional chat) is controlled by the `poll` flag.

```toml
[connectors.my_discord]
type = "discord"
poll = false          # Set to true to enable bi-directional chat
working_dir = "~/my-project"  # Optional: execution directory for this connector
bot_token = "..."
channel_id = "..."
```

> **⚠️ Security Warning**: Setting `poll = true` allows anyone in the channel to interact with the AI, which has **full access to your PC's file system and tools**. Only enable polling in private/trusted channels.

## Configuration Hierarchy

1. `.kage/config.local.toml` (Git-ignored overrides)
2. `.kage/config.toml` (Project-shared)
3. `~/.kage/config.toml` (User-global)
4. Library Defaults
- **Background Loop**: Runs via `kage cron install` (cron/launchd).
