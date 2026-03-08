from pathlib import Path

import pytest

from kage.config import CommandDef, GlobalConfig, ProviderConfig
from kage.executor import execute_task
from kage.parser import TaskDef


@pytest.fixture
def mock_executor_env(tmp_path: Path, mocker):
    config = GlobalConfig(
        default_ai_engine="codex",
        commands={
            "codex": CommandDef(
                template=[
                    "codex",
                    "--ask-for-approval",
                    "never",
                    "--sandbox",
                    "workspace-write",
                    "exec",
                    "{model_args}",
                    "{prompt}",
                ]
            )
        },
        providers={
            "codex": ProviderConfig(
                command="codex",
                parser="raw",
                model="gpt-5-codex",
                model_flag="--model",
            )
        },
    )
    mocker.patch("kage.executor.get_global_config", return_value=config)
    mocker.patch("kage.config.get_system_prompt", return_value="System prompt {thinking_tag}")
    mocker.patch("kage.executor.sys.stdin.isatty", return_value=False)
    mocker.patch("kage.db.init_db")
    mocker.patch("kage.executor.start_execution", return_value="exec-1")
    mocker.patch("kage.executor.update_execution")
    mocker.patch("kage.executor.log_execution")
    mocker.patch("kage.executor.clean_ai_reply", side_effect=lambda text: text)
    mocker.patch("kage.executor._notify_connectors")
    mocker.patch("kage.executor.shutil.which", side_effect=lambda cmd, path=None: cmd)
    mocker.patch("kage.executor.set_execution_pid")
    mocker.patch("kage.executor.KAGE_GLOBAL_DIR", tmp_path / ".global")


def test_execute_task_uses_relative_working_dir_from_task_file(
    tmp_path: Path, mock_executor_env, mocker
):
    popen = mocker.patch("kage.executor.subprocess.Popen")
    popen.return_value.communicate.return_value = ("ok", "")
    popen.return_value.returncode = 0
    popen.return_value.pid = 4242

    project_dir = tmp_path / "project"
    task_dir = project_dir / ".kage" / "tasks"
    task_dir.mkdir(parents=True)
    (project_dir / "workspace").mkdir()
    task_file = task_dir / "nightly.md"
    task_file.write_text("", encoding="utf-8")

    task = TaskDef(
        name="Nightly Research",
        cron="0 2 * * *",
        prompt="Compare candidates",
        provider="codex",
        working_dir="../../workspace",
    )

    execute_task(project_dir, task, task_file=task_file)

    cmd = popen.call_args.args[0]
    assert Path(popen.call_args.kwargs["cwd"]) == (project_dir / "workspace").resolve()
    assert str(
        (project_dir / ".kage" / "memory" / "Nightly_Research" / "task.json").resolve()
    ) in cmd[-1]


def test_execute_task_uses_absolute_working_dir_as_is(
    tmp_path: Path, mock_executor_env, mocker
):
    popen = mocker.patch("kage.executor.subprocess.Popen")
    popen.return_value.communicate.return_value = ("ok", "")
    popen.return_value.returncode = 0
    popen.return_value.pid = 4242

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    absolute_dir = tmp_path / "outside"
    absolute_dir.mkdir()

    task = TaskDef(
        name="Absolute Dir Task",
        cron="0 2 * * *",
        prompt="Compare candidates",
        provider="codex",
        working_dir=str(absolute_dir),
    )

    execute_task(project_dir, task)

    assert Path(popen.call_args.kwargs["cwd"]) == absolute_dir
