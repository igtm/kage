import pytest
from pathlib import Path
from kage.parser import parse_task_file

def test_parse_valid_toml(tmp_path: Path):
    # Dummy toml creation
    task_file = tmp_path / "valid.toml"
    task_file.write_text("""
[task]
name = "Weekly Refactoring"
cron = "0 3 * * 0"
prompt = "Refactor src directory"

[task.ai]
engine = "claude"
args = ["--dangerously-skip-permissions"]
    """, encoding="utf-8")
    
    parsed = parse_task_file(task_file)
    assert parsed is not None
    assert parsed.task.name == "Weekly Refactoring"
    assert parsed.task.cron == "0 3 * * 0"
    assert parsed.task.prompt == "Refactor src directory"
    assert parsed.task.ai.engine == "claude"
    assert parsed.task.ai.args == ["--dangerously-skip-permissions"]

def test_parse_invalid_toml(tmp_path: Path):
    invalid_file = tmp_path / "invalid.toml"
    invalid_file.write_text("invalid_toml_content", encoding="utf-8")
    parsed = parse_task_file(invalid_file)
    assert parsed is None

def test_parse_shell_command(tmp_path: Path):
    task_file = tmp_path / "shell.toml"
    task_file.write_text("""
[task]
name = "Cleanup"
cron = "* * * * *"
command = "rm -rf /tmp/*"
    """, encoding="utf-8")
    
    parsed = parse_task_file(task_file)
    assert parsed is not None
    assert parsed.task.name == "Cleanup"
    assert parsed.task.command == "rm -rf /tmp/*"
    assert parsed.task.prompt is None
