from pathlib import Path

from kage.parser import load_project_tasks, parse_task_file


def test_parse_valid_toml_single_task(tmp_path: Path):
    task_file = tmp_path / "valid.toml"
    task_file.write_text(
        """
[task]
name = "Weekly Refactoring"
cron = "0 3 * * 0"
prompt = "Refactor src directory"

[task.ai]
engine = "claude"
args = ["--dangerously-skip-permissions"]
        """,
        encoding="utf-8",
    )

    parsed = parse_task_file(task_file)
    assert len(parsed) == 1
    _, task = parsed[0]
    assert task.name == "Weekly Refactoring"
    assert task.cron == "0 3 * * 0"
    assert task.prompt == "Refactor src directory"
    assert task.ai is not None
    assert task.ai.engine == "claude"
    assert task.ai.args == ["--dangerously-skip-permissions"]


def test_parse_markdown_front_matter_prompt_task(tmp_path: Path):
    task_file = tmp_path / "nightly.md"
    task_file.write_text(
        """---
name: Nightly Research
cron: "0 2 * * *"
provider: codex
working_dir: ../../workspace
---

Compare candidate libraries and summarize pros/cons in markdown.
Include benchmark table and recommendations.
""",
        encoding="utf-8",
    )

    parsed = parse_task_file(task_file)
    assert len(parsed) == 1
    _, task = parsed[0]
    assert task.name == "Nightly Research"
    assert task.cron == "0 2 * * *"
    assert "Compare candidate libraries" in (task.prompt or "")
    assert "benchmark table" in (task.prompt or "")
    assert task.provider == "codex"
    assert task.working_dir == "../../workspace"


def test_parse_markdown_command_task(tmp_path: Path):
    task_file = tmp_path / "shell.md"
    task_file.write_text(
        """---
name: Shell Task
cron: "* * * * *"
command: "echo hello"
shell: bash
working_dir: ../../workspace
---
""",
        encoding="utf-8",
    )

    parsed = parse_task_file(task_file)
    assert len(parsed) == 1
    _, task = parsed[0]
    assert task.command == "echo hello"
    assert task.shell == "bash"
    assert task.working_dir == "../../workspace"


def test_parse_markdown_notify_connectors_json_array_string(tmp_path: Path):
    task_file = tmp_path / "notify.md"
    task_file.write_text(
        """---
name: Notify Task
cron: "0 10 * * *"
notify_connectors: ["discord_igtm", "telegram_igtm"]
---

Send a digest.
""",
        encoding="utf-8",
    )

    parsed = parse_task_file(task_file)
    assert len(parsed) == 1
    _, task = parsed[0]
    assert task.notify_connectors == ["discord_igtm", "telegram_igtm"]


def test_parse_markdown_notify_connectors_csv_string(tmp_path: Path):
    task_file = tmp_path / "notify-csv.md"
    task_file.write_text(
        """---
name: Notify Csv Task
cron: "0 10 * * *"
connectors: discord_igtm, telegram_igtm
---

Send a digest.
""",
        encoding="utf-8",
    )

    parsed = parse_task_file(task_file)
    assert len(parsed) == 1
    _, task = parsed[0]
    assert task.notify_connectors == ["discord_igtm", "telegram_igtm"]


def test_parse_markdown_notify_connectors_single_quoted_array_string(tmp_path: Path):
    task_file = tmp_path / "notify-single-quoted.md"
    task_file.write_text(
        """---
name: Notify Single Quoted Task
cron: "0 10 * * *"
notify_connectors: ['discord_igtm', 'telegram_igtm']
---

Send a digest.
""",
        encoding="utf-8",
    )

    parsed = parse_task_file(task_file)
    assert len(parsed) == 1
    _, task = parsed[0]
    assert task.notify_connectors == ["discord_igtm", "telegram_igtm"]


def test_parse_markdown_rejects_non_string_notify_connectors_array(tmp_path: Path):
    task_file = tmp_path / "notify-invalid.md"
    task_file.write_text(
        """---
name: Notify Invalid Task
cron: "0 10 * * *"
notify_connectors: [1, 2]
---

Send a digest.
""",
        encoding="utf-8",
    )

    parsed = parse_task_file(task_file)
    assert parsed == []


def test_parse_markdown_rejects_command_task_with_body(tmp_path: Path):
    task_file = tmp_path / "bad-shell.md"
    task_file.write_text(
        """---
name: Bad Shell Task
cron: "* * * * *"
command: "echo hello"
---

this body should not be accepted because command exists in front matter
""",
        encoding="utf-8",
    )

    parsed = parse_task_file(task_file)
    assert parsed == []


def test_parse_markdown_rejects_empty_command(tmp_path: Path):
    task_file = tmp_path / "empty-command.md"
    task_file.write_text(
        """---
name: Empty Command
cron: "* * * * *"
command: "   "
---
""",
        encoding="utf-8",
    )

    parsed = parse_task_file(task_file)
    assert parsed == []


def test_parse_markdown_requires_body_prompt(tmp_path: Path):
    task_file = tmp_path / "empty.md"
    task_file.write_text(
        """---
name: Empty Prompt
cron: "0 1 * * *"
---

""",
        encoding="utf-8",
    )

    parsed = parse_task_file(task_file)
    assert parsed == []


def test_load_project_tasks_supports_toml_and_md(tmp_path: Path):
    project_dir = tmp_path / "proj"
    tasks_dir = project_dir / ".kage" / "tasks"
    tasks_dir.mkdir(parents=True)

    (tasks_dir / "a.toml").write_text(
        """
[task]
name = "Toml Task"
cron = "0 * * * *"
prompt = "run toml"
""",
        encoding="utf-8",
    )

    (tasks_dir / "b.md").write_text(
        """---
name: Md Task
cron: "30 * * * *"
---

run md with long markdown body
""",
        encoding="utf-8",
    )

    tasks = load_project_tasks(project_dir)
    names = sorted([t.task.name for _, t in tasks])
    assert names == ["Md Task", "Toml Task"]
