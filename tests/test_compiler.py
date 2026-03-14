from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from kage.compiler import compile_prompt_task, compiled_task_status
from kage.main import app
from kage.parser import TaskDef

runner = CliRunner()


def test_compiled_task_status_reports_stale_script(tmp_path: Path):
    task_file = tmp_path / "nightly.md"
    task_file.write_text(
        """---
name: Nightly
cron: "* * * * *"
---

fresh prompt
""",
        encoding="utf-8",
    )
    compiled_file = task_file.with_suffix(".lock.sh")
    compiled_file.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "# kage-lock-version: 1",
                "# kage-source-hash: stale-source",
                "# kage-frontmatter-hash: stale-frontmatter",
                "# kage-prompt-hash: stale-hash",
                "echo hello",
                "",
            ]
        ),
        encoding="utf-8",
    )

    task = TaskDef(name="Nightly", cron="* * * * *", prompt="fresh prompt")
    status = compiled_task_status(task, task_file)

    assert status is not None
    assert status["exists"] is True
    assert status["matches_prompt"] is False


def test_compile_prompt_task_writes_shell_script(tmp_path: Path, mocker):
    task_file = tmp_path / "nightly.md"
    task_file.write_text(
        """---
name: Nightly
cron: "* * * * *"
---

Create a report
""",
        encoding="utf-8",
    )
    task = TaskDef(name="Nightly", cron="* * * * *", prompt="Create a report")

    mocker.patch(
        "kage.compiler._build_compile_request",
        return_value=(["fake-ai"], tmp_path, {"PATH": "/usr/bin"}, "codex"),
    )
    mocker.patch(
        "kage.compiler.subprocess.run",
        return_value=SimpleNamespace(
            returncode=0,
            stdout="```bash\necho hello\n```",
            stderr="",
        ),
    )

    compiled_path = compile_prompt_task(tmp_path, task, task_file)
    content = compiled_path.read_text(encoding="utf-8")

    assert compiled_path == task_file.with_suffix(".lock.sh")
    assert content.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert "# kage-lock-version: 1" in content
    assert "# kage-source-hash:" in content
    assert "# kage-frontmatter-hash:" in content
    assert "# kage-source-task: Nightly" in content
    assert "echo hello" in content
    assert "```" not in content


def test_compile_cli_resolves_named_prompt_task(tmp_path: Path, mocker):
    project_dir = tmp_path / "proj"
    task_file = project_dir / ".kage" / "tasks" / "nightly.md"
    task_file.parent.mkdir(parents=True)
    task = TaskDef(name="Nightly", cron="* * * * *", prompt="Create a report")

    mocker.patch("kage.scheduler.get_projects", return_value=[project_dir])
    mocker.patch(
        "kage.parser.load_project_tasks",
        return_value=[(task_file, SimpleNamespace(task=task))],
    )
    compiled_path = task_file.with_suffix(".lock.sh")
    mocker.patch("kage.compiler.compile_prompt_task", return_value=compiled_path)

    result = runner.invoke(app, ["compile", "Nightly"])

    assert result.exit_code == 0
    assert str(compiled_path) in result.stdout
