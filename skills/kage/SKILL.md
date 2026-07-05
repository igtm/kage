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
- **Task Suspension**: `suspended_until` pauses future starts without changing `active`.
- **State Persistence**: `.kage/memory/{task}/{date}.json`.
- **Connectors**: Integrate with Discord/Slack/Telegram for task notifications (always on) and optional bi-directional chat (`poll = true` for polling or `realtime = true` for Discord instant replies; realtime listeners are managed by `kage cron run`).
- **Layered Config**: `.kage/config.local.toml` > `.kage/config.toml` > `~/.kage/config.toml` > defaults.

## CLI

- `kage onboard` — Setup global directories and `kage cron`.
- `kage init` — Initialize in current directory.
- `kage run <task>` — Execute a specific task immediately; add `--force` to bypass suspension.
- `kage compile <task>` — Compile a prompt task into a sibling `.lock.sh` override.
- `kage cron run` — Execute the scheduler loop once (used by cron/launchd).
- `kage runs` — List execution runs in a relative-time table; add `--absolute-time` for detailed timestamps.
- `kage runs show <exec_id>` — Inspect run metadata and log paths.
- `kage runs stop <exec_id>` — Stop a running execution.
- `kage logs [<task>]` — Open raw logs for the latest run of a task, or merge all task logs when omitted.
- `kage logs --run <exec_id>` — Open raw logs for a specific run.
- `kage task list` — List tasks with short project names, effective type, and provider/command.
- `kage task show <name>` — Detailed task configuration, suspension state, and current prompt hash.
- `kage task suspend <name> --for 2w --reason "Vacation"` — Pause future starts without disabling the task.
- `kage task suspend <name> --until 2026-05-09` — Pause until an ISO date/datetime; date-only resumes at task-local midnight.
- `kage task resume <name>` — Remove suspension metadata without starting the task.
- `kage connector list` — List all configured connectors.
- `kage connector setup <type>` — Show setup guide for a connector (discord, slack, telegram).
- `kage connector poll` — Manually trigger polling for all connectors.
- `kage connector realtime start [name]` — Start detached realtime listeners.
- `kage connector realtime stop [name]` — Stop realtime listeners.
- `kage connector realtime restart [name]` — Restart realtime listeners.
- `kage connector realtime status` — Show running realtime listeners.
- `kage connector realtime run [name]` — Run realtime listener in foreground.
- `kage doctor` — Diagnose config and environment.
- `kage migrate install` — Run pending install-time migrations manually.
- `kage ui` — Open web dashboard.
- `kage tui` — Open the Textual terminal dashboard with logs, tasks, connectors, and settings tabs.

Shell completion covers positional task/run arguments as well, so `kage run <task>`, `kage compile <task>`, `kage logs [<task>]`, `kage task run <name>`, `kage task show <name>`, `kage task suspend <name>`, `kage task resume <name>`, `kage runs show <exec_id>`, and `kage stop <exec_id>` can all suggest concrete values after `kage completion install bash|zsh`. `kage doctor` reports whether those completion scripts are installed.

If a prompt task has a sibling compiled lock like `.kage/tasks/nightly.lock.sh`, kage executes that lock instead of the Markdown prompt body only while the stored `prompt_hash` still matches the current prompt body. If the prompt body changes, the lock becomes stale and must be regenerated with `kage compile <task>`. `kage doctor`, `kage task list`, and the UI all surface whether the lock is fresh, stale, or missing, and `kage task show <name>` prints the current prompt hash.

In `kage task list`, prompt tasks render as `Prompt` or `Prompt (Compiled)`, stale compiled locks are highlighted, the project column uses only the leaf directory name, and inherited providers show up explicitly as values like `gemini (Inherited)`. The built-in `codex` command template runs `codex exec --yolo ...` by default.

If a workspace still uses the built-in `gemini` provider, kage warns in CLI output about the Gemini CLI consumer sunset on June 18, 2026 and points users to the Google blog migration announcement. Prefer `antigravity` for new consumer workflows.

For connector chat replies with the built-in `antigravity` provider, kage uses a concise final-answer prompt and keeps model arguments before `--print`. This avoids Antigravity returning CLI session metadata or tool-use narration instead of the user's requested answer.

Suspension is separate from `active`: cron and normal manual runs skip a task while `suspended_until` is in the future, or while the value is invalid. Use `kage run <task> --force` or `kage task run <task> --force` for a deliberate one-off run. Connector-driven agents should use `kage task suspend` / `kage task resume` instead of editing `.kage/tasks/*.md` directly.

Connector poll replies are recorded as normal runs. Use `kage runs --source connector_poll` to find them and `kage logs --run <exec_id>` to inspect raw AI CLI output.

Install-time migrations are discovered automatically from `src/kage/migrations/install/`. New migration modules added there are picked up by both `kage migrate install` and `install.sh`.

`kage tui` is the terminal-first dashboard. Its Logs tab filters logs from a task list and run list, its Tasks tab shows task details, its Connector tab shows connector history, and its Settings tab shows the resolved global config.

## Task File Template (`.kage/tasks/*.md`)

```markdown
---
name: <Task Name>
cron: "<cron expression>"
provider: <provider name>           # e.g. codex, claude, gemini, antigravity, opencode, copilot, aider
mode: continuous                    # continuous | once | autostop
concurrency_policy: allow           # allow | forbid | replace
timeout_minutes: 60                 # minutes (optional)
working_dir: ../../workspace        # optional; relative to this task file, or absolute path
timezone: "Asia/Tokyo"              # e.g. "UTC", "Asia/Tokyo" (optional)
allowed_hours: "9-17"               # e.g. "9-17,21" (optional)
denied_hours: "0-5"                 # e.g. "0-5,12" (optional)
suspended_until: "2026-05-09T18:30:00+09:00" # optional suspension deadline
suspended_reason: "Vacation"        # optional suspension reason
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
working_dir: ../../workspace
---
```

## Connectors

Connectors integrate with external chat services. Sending (task notifications via `notify_connectors`) is **always enabled** as long as credentials are configured. Bi-directional chat is controlled by the `poll` flag (1-minute polling) or the `realtime` flag (WebSocket-based instant replies).

Connector-aware runs export `KAGE_ARTIFACT_DIR` as a workspace-local staging directory (for example `.kage/tmp/connector-artifacts/<run_id>`). Incoming connector attachments are downloaded to `KAGE_ARTIFACT_DIR/incoming` for that run and mentioned in the prompt so the provider can decide whether to use them. Discord, Slack, and Telegram upload every top-level file left in `KAGE_ARTIFACT_DIR` with the text reply, so leave only the intended final deliverables in that directory and delete unwanted Markdown/Marp/HTML, downloaded images, and other intermediate assets before the run ends.

```toml
[connectors.my_discord]
type = "discord"
# Choose ONE chat mode:
poll = false          # Set to true to enable 1-minute polling
# realtime = true     # Discord only: instant replies with typing indicator
working_dir = "~/my-project"  # Optional: execution directory for this connector
bot_token = "..."
channel_id = "..."
```

Start a Discord realtime listener with:

```bash
kage connector realtime start        # start once (detached)
kage connector realtime stop         # stop all listeners
kage connector realtime restart      # restart all listeners
kage connector realtime status       # show running listeners
kage connector realtime run          # run in foreground (for debugging)
```

If you already have `kage cron run` installed in your crontab, realtime listeners are managed automatically: enabling `realtime = true` in config will start the listener within one minute, and disabling it will stop the listener on the next cron tick.

Realtime logs are written to `~/.kage/logs/connector-realtime-<name>.log` and rotated on each start. Rotated logs older than 7 days or beyond the newest 5 files are cleaned up automatically.

> **⚠️ Security Warning**: Setting `poll = true` or `realtime = true` allows anyone in the channel to interact with the AI, which has **full access to your PC's file system and tools**. Only enable one chat mode, and only in private/trusted channels.

## Agents & Multi-tenant Isolation

An **Agent** is the top-level concept in kage. Each agent owns its projects, connectors, memory, and a system prompt, so conversations and state never cross between agents. The built-in agent `kage` always exists; connectors and projects with no explicit `agent` fall back to it.

```toml
[agents.public]
system_prompt = """
You are the public-facing assistant. Be brief and polite.
Never mention private projects or other agents.
"""
default_working_dir = "~/projects/public"

[connectors.discord_public]
type = "discord"
poll = true
bot_token = "..."
channel_id = "..."
agent = "public"
```

When kage spawns the AI provider it injects `KAGE_RUN_ID` (authoritative, DB-anchored — the `executions.agent_name` column is locked by a SQLite trigger) and `KAGE_AGENT_NAME` (display hint only). Inside the spawned shell, every `kage *` command is scoped to the running agent: a connector bound to a different agent cannot be polled, listed with details, or controlled. Human shells (no `KAGE_RUN_ID`) act as superusers and bypass the scope filter.

### Agent Memory

Each agent owns a topic-keyed memory space at `~/.kage/agents/<agent_name>/memory/<slug>.md`. kage injects an `<available_memories>` block (entries with `<name>`, `<description>`, `<updated_at>`) into the system prompt at the start of every run. File paths are hidden — use the CLI to read details.

```bash
kage memory list                              # list memories of the current agent
kage memory show <slug>                       # print the body
kage memory write <slug> --description "..."  # create/overwrite; body from stdin
kage memory delete <slug>                     # remove
kage memory search <query>                    # substring search across bodies
```

Memory is per-agent (not per-task), overwrite-style (latest state only, `updated_at` refreshed). The previous per-task memory system (`.kage/memory/<task>/YYYY-MM-DD.json` and `task.json`) is removed; install migration 0004 backs up and replaces legacy `system_prompt.md` files and archives legacy memory directories.

## Configuration Hierarchy

1. `.kage/config.local.toml` (Git-ignored overrides)
2. `.kage/config.toml` (Project-shared)
3. `~/.kage/config.toml` (User-global)
4. Library Defaults
- **Background Loop**: Runs via `kage cron install` (cron/launchd).
