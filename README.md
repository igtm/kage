# kage 影 - Autonomous AI Project Agent

![kage hero](./hero.png)

English | [日本語](./README_JA.md)

`kage` is an ultra-lightweight, OS-native execution layer for AI agents. By leveraging standard schedulers like **cron** and **launchd**, it runs official AI CLIs (`gemini`, `claude`, `codex`, `opencode`, `copilot`, etc.) in headless mode with zero background overhead. You can install it on your work PC, define tasks in Markdown inside your project repository, and leave it running overnight. By morning, your AI agent has finished the work for you, delivering documented results while you were away.

> **Go to sleep. Wake up to results.** — kage runs your AI agents overnight, so you start every morning with answers, not questions.

## Design Philosophy

`kage` is built to be a **thin, transparent, and resource-efficient** execution layer.

- **OS Native**: Does not run a persistent background daemon. It leverages **cron (Linux)** and **launchd (macOS)** to wake up, execute tasks, and exit. Zero memory footprint when idle.
- **Headless CLI Mode**: Directly integrates with **official AI CLIs** (like `gemini`, `claude`, `opencode`, `copilot`, etc.) in their standard mode. It doesn't rely on unofficial or unstable internal APIs.
- **Stateless & Transparent**: Every execution is logged, and states are managed simply via SQLite and Markdown files.

## Dashboard

| Execution Logs | Settings & Tasks |
|:-:|:-:|
| ![Execution Logs](./docs/execution-logs.png) | ![Settings & Tasks](./docs/settings-n-tasks.png) |

## Features

- **Autonomous Agent Logic**: Automatically decomposes tasks into GFM checklists and tracks progress.
- **Persistent Memory**: Stores task state in `.kage/memory/` to maintain context across runs.
- **Lightweight Execution**: Leverages OS-native schedulers. Zero background overhead.
- **Flexible Execution**: Supports AI prompt execution, shell commands, and custom scripts.
- **Compiled Task Overrides**: `kage compile <task>` can materialize a prompt task into a sibling `.lock.sh` script with a stored `prompt_hash`, and kage will only execute that lock script while it matches the current prompt body.
- **Advanced Workflow Controls**:
    - **Execution Modes**: `continuous`, `once`, `autostop`.
    - **Concurrency Policy**: `allow`, `forbid` (skip if running), `replace` (kill old).
    - **Time Windows**: Restrict execution using `allowed_hours: "9-17"` or `denied_hours: "12"`.
- **Markdown-First**: Define tasks using simple Markdown files with YAML front matter.
- **Layered Configuration**: `.kage/config.local.toml` > `.kage/config.toml` > `~/.kage/config.toml` > defaults.
- **Connectors**: Integrate with Discord/Slack/Telegram. Task notifications are always enabled; bi-directional chat requires `poll = true` (⚠️ grants channel members AI access to your PC).
- **Thinking Process Isolation**: AI workers automatically wrap reasoning in `<think>` tags. Notifications, summaries, and cleaned outputs hide them, while `kage logs` keeps the raw stream available for debugging.
- **Web Dashboard**: Execution history, task management, and AI chat — all in one place.

Connector-aware runs export `KAGE_ARTIFACT_DIR` as a workspace-local staging directory (for example `.kage/tmp/connector-artifacts/<run_id>`). Discord, Slack, and Telegram upload every top-level file left there alongside the text output, so tasks should keep only the intended final deliverables in that directory and delete unwanted Markdown/Marp/HTML, downloaded images, and other intermediate assets before finishing.

Default built-in AI providers: `codex`, `claude`, `gemini`, `opencode`, `copilot`, `aider`.

Check out the [Technical Architecture](ARCHITECTURE.md) for more details.

## Installation

```bash
curl -sSL https://raw.githubusercontent.com/igtm/kage/main/install.sh | bash
```

The installer automatically runs pending install-time migrations after upgrading `kage`.

You can also add this repository's skills with:
```bash
npx skills add https://github.com/igtm/kage
```

## Quick Start

```bash
cd your-project
kage init         # Initialize kage in the current directory
# Edit .kage/tasks/*.md to define your tasks
kage ui           # Open the web dashboard
```

## Shell Completion

Typer-based completion is enabled for `kage`.

```bash
# Recommended: explicit shell install
kage completion install bash
kage completion install zsh
```

Preview or generate the script manually:

```bash
# bash
kage completion show bash > ~/.kage-complete.bash
echo 'source ~/.kage-complete.bash' >> ~/.bashrc

# zsh
kage completion show zsh > ~/.kage-complete.zsh
echo 'source ~/.kage-complete.zsh' >> ~/.zshrc
```

You can also use Typer's built-in option for current shell detection:

```bash
kage --install-completion
```

Reload your shell after installation (`exec $SHELL -l`).

Shell completion also suggests task names and recent run IDs for positional arguments like `kage run <task>`, `kage compile <task>`, `kage logs [<task>]`, `kage task run <name>`, and `kage runs show <exec_id>`.
`kage doctor` also reports whether bash/zsh completion scripts are installed.

## Use Cases

### 🌙 Overnight Tech Evaluation (OCR Model Benchmark)

The killer use case: **go to sleep, wake up with a complete technology evaluation report.**

Create a single task that, on every cron run, picks the next untested OCR model, implements it, runs it against your test PDFs, and records the accuracy. By morning, you have a ranked comparison.

`.kage/tasks/ocr_benchmark.md`:
```markdown
---
name: OCR Model Benchmark
cron: "0 * * * *"
provider: claude
mode: autostop
denied_hours: "9-23"
working_dir: ../../benchmark
---

# Task: PDF OCR Technology Evaluation

You are conducting a systematic evaluation of free/open-source OCR solutions for extracting text from Japanese financial PDF documents.

## Target Models (test one per run)
- Tesseract (jpn + jpn_vert)
- EasyOCR
- PaddleOCR
- Surya OCR
- DocTR (doctr)
- manga-ocr (for vertical text)
- Google Vision API (free tier)

## Instructions
1. Check `.kage/memory/` for which models have already been tested.
2. Pick the NEXT untested model from the list above.
3. Install it and write a test script in `benchmark/test_{model_name}.py`.
4. Run it against the PDF files in `benchmark/test_pdfs/`.
5. Measure: Character accuracy (CER), processing time, memory usage.
6. Save results to `benchmark/results/{model_name}.json`.
7. Update `benchmark/RANKING.md` with a comparison table of all tested models so far.
8. When all models are tested, set status to "Completed" in memory.
```

`working_dir` is optional. Absolute paths are used as-is; relative paths are resolved from the task file directory (`.kage/tasks/`).

When you wake up:
```
benchmark/
├── RANKING.md              ← Full comparison table, ready for decision
├── results/
│   ├── tesseract.json
│   ├── easyocr.json
│   ├── paddleocr.json
│   └── ...
└── test_pdfs/
    ├── invoice_001.pdf
    └── report_002.pdf
```

### 🔍 Overnight Codebase Audit

`.kage/tasks/audit.md`:
```markdown
---
name: Architecture Auditor
cron: "0 2 * * *"
provider: gemini
mode: continuous
denied_hours: "9-18"
---

# Task: Nightly Architecture Health Check
Analyze the codebase for:
- Dead code and unused exports
- Circular dependencies
- API endpoints without tests
- Security anti-patterns (hardcoded secrets, SQL injection risks)

Write findings to `reports/audit_{date}.md`.
```

### 🧪 Overnight PoC Builder

`.kage/tasks/poc_builder.md`:
```markdown
---
name: PoC Builder
cron: "30 0 * * *"
provider: claude
mode: autostop
denied_hours: "8-23"
---

# Task: Build a Proof of Concept

Read the spec in `specs/next_poc.md` and implement a working prototype.
- Create the implementation in `poc/` directory
- Include a README with setup instructions and demo commands
- Write basic tests to verify core functionality
- Set status to "Completed" when the PoC is functional
```

### ⚡ Simple Examples

**AI Task** — hourly health check:
```markdown
---
name: Project Auditor
cron: "0 * * * *"
provider: gemini
---
Analyze the current codebase for architectural drifts.
```

**Shell-Command Task** — nightly log cleanup:
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

| Command | Description |
|---------|-------------|
| `kage onboard` | Global setup (cron, directories, DB) |
| `kage init` | Initialize kage in the current directory |
| `kage run <task>` | Run a specific task immediately |
| `kage compile <task>` | Compile a prompt task into a sibling `.lock.sh` override |
| `kage runs` | List execution runs in a status-colored table with relative time |
| `kage runs show <exec_id>` | Show run metadata, paths, and status details |
| `kage runs stop <exec_id>` | Stop a running execution |
| `kage logs [<task>]` | Open raw logs for the latest run of a task, or merge all task logs when omitted |
| `kage logs --run <exec_id>` | Open raw logs for a specific run |
| `kage cron run` | Run the scheduler loop once (used by cron / launchd) |
| `kage cron install` | Register to system scheduler |
| `kage cron status` | Check background status |
| `kage task list` | List tasks with status, effective type, and provider/command |
| `kage task show <name>` | Show detailed task configuration and prompt hash |
| `kage connector list` | List all configured connectors |
| `kage connector setup <type>` | Show setup guide for a connector (discord, slack, telegram) |
| `kage connector poll` | Manually poll connectors with `poll = true` |
| `kage migrate install` | Run pending install-time migrations manually |
| `kage doctor` | Diagnose configuration health |
| `kage skill` | Display agent skill guidelines |
| `kage ui` | Open the web dashboard |
| `kage tui` | Open the terminal dashboard with runs, tasks, connectors, and config tabs |

### macOS launchd Specific Settings
On macOS, `kage` uses `launchd` instead of `cron`. You can further customize its behavior in `config.toml`:

- `darwin_launchd_interval_seconds`: Set the launch interval in seconds (minimum `15`).
- `darwin_launchd_keep_alive`: Set to `true` to keep the process running (not recommended for simple polling).

`kage runs` is the run-history view. By default it shows a compact table with relative timestamps like `4h ago`; add `--absolute-time` to show detailed local timestamps again. `kage logs` is the raw-output viewer backed by per-run log files (`stdout.log`, `stderr.log`, `events.jsonl`). `kage logs <task>` opens the latest run for one task, while bare `kage logs` merges all task logs in chronological order. Use `--follow` or `-f` to keep tailing appended output.

If a prompt task has a sibling compiled lock such as `.kage/tasks/nightly.lock.sh`, kage executes that lock instead of the prompt body only while its stored `prompt_hash` still matches the current prompt body. When the prompt changes, the lock becomes stale and you need to run `kage compile <task>` again. `kage doctor`, `kage task list`, and the UI task cards all show whether a lock is fresh, stale, or missing. `kage task show <name>` also prints the current prompt hash so you can inspect what the lock should match.

`kage task list` shortens the project column to the leaf directory name, shows prompt tasks as `Prompt` or `Prompt (Compiled)`, and resolves inherited providers as values like `gemini (Inherited)` so you can see what will actually run. Built-in `codex` runs now use `codex exec --yolo ...` in the default command template.

Connector polling replies are recorded in the same run history. Use `kage runs --source connector_poll` to isolate them, then inspect the raw AI CLI output with `kage logs --run <exec_id>`.

Install-time migrations are discovered automatically from `src/kage/migrations/install/`. New migration modules added there are picked up by both `kage migrate install` and `install.sh`.

`kage tui` provides a terminal dashboard powered by Textual. It has four tabs: Logs, Tasks, Connector, and Settings. The Logs tab filters runs and rendered logs from a task/run sidebar, the Tasks tab shows task details, the Connector tab shows connector history, and the Settings tab shows the global config snapshot.

## Configuration

| File | Scope |
|------|-------|
| `~/.kage/config.toml` | Global settings (`default_ai_engine`, `working_dir`, `ui_port`, `ui_host`, etc.) |
| `.kage/config.toml` | Project-shared settings |
| `.kage/config.local.toml` | Local overrides (git-ignored) |
| `.kage/system_prompt.md` | Project-specific AI instructions |

Provider-specific model selection can be layered in the same files:

```toml
[providers.codex]
model = "gpt-5-codex"

[providers.claude]
model = "claude-sonnet-4-5"

[providers.opencode]
model = "openai/gpt-5-codex"
```

Built-in providers use `--model` by default. You can also set nested keys via CLI:

```bash
kage config providers.codex.model gpt-5-codex --global
kage config providers.codex.model gpt-5-mini --local
```

## License

MIT
