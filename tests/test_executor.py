import io
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import tomlkit

from kage.config import (
    CommandDef,
    GlobalConfig,
    ProviderConfig,
    get_global_config,
    render_command_template,
    set_config_value,
)
from kage.executor import execute_task
from kage.parser import TaskDef


class DummyProc:
    def __init__(self, stdout="ok", stderr="", returncode=0, pid=4242):
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)
        self.returncode = returncode
        self.pid = pid

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture
def executor_config():
    return GlobalConfig(
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
            ),
            "codex_json": CommandDef(
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
            ),
            "custom_cli": CommandDef(template=["custom_cli", "{prompt}"]),
            "opencode": CommandDef(
                template=["opencode", "run", "{model_args}", "{prompt}"]
            ),
        },
        providers={
            "codex": ProviderConfig(
                command="codex",
                parser="raw",
                model="gpt-5-codex",
                model_flag="--model",
            ),
            "codex_json": ProviderConfig(
                command="codex_json",
                parser="jq",
                parser_args=".output",
                model="gpt-5-codex",
                model_flag="--model",
            ),
            "jq_provider": ProviderConfig(
                command="custom_cli", parser="jq", parser_args=".result"
            ),
            "opencode": ProviderConfig(
                command="opencode",
                parser="raw",
                model="openai/gpt-5-codex",
                model_flag="--model",
            ),
        },
    )


@pytest.fixture
def mock_executor_env(tmp_path: Path, executor_config, mocker):
    mocker.patch("kage.executor.get_global_config", return_value=executor_config)
    mocker.patch(
        "kage.config.get_system_prompt", return_value="System prompt {thinking_tag}"
    )
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
    mocker.patch("kage.runs.KAGE_LOGS_DIR", tmp_path / ".logs")


def test_execute_shell_command_with_custom_shell(
    tmp_path: Path, mock_executor_env, mocker
):
    """shellを指定するとそのshellで実行される"""
    popen = mocker.patch("kage.executor.subprocess.Popen", return_value=DummyProc())

    task = TaskDef(name="shell", cron="* * * * *", command="echo hello", shell="bash")
    execute_task(tmp_path, task)

    cmd = popen.call_args.args[0]
    assert Path(cmd[0]).name == "bash"
    assert cmd[1:] == ["-c", "echo hello"]


def test_execute_ai_via_provider_injects_provider_model(
    tmp_path: Path, mock_executor_env, mocker
):
    """デフォルトプロバイダーの model 設定が CLI 引数へ注入される"""
    popen = mocker.patch(
        "kage.executor.subprocess.Popen", return_value=DummyProc(stdout="ai response")
    )

    task = TaskDef(name="ai_task", cron="* * * * *", prompt="Fix this")
    execute_task(tmp_path, task)

    cmd = popen.call_args.args[0]
    assert Path(cmd[0]).name == "codex"
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "gpt-5-codex"
    full_prompt = cmd[-1]
    assert "Fix this" in full_prompt
    assert "## Task Instructions" in full_prompt


def test_execute_explicit_provider_uses_provider_specific_model(
    tmp_path: Path, mock_executor_env, mocker
):
    """provider ごとの model 値がそのまま CLI に渡る"""
    popen = mocker.patch(
        "kage.executor.subprocess.Popen", return_value=DummyProc(stdout="ai response")
    )

    task = TaskDef(
        name="ai_task", cron="* * * * *", prompt="Fix this", provider="opencode"
    )
    execute_task(tmp_path, task)

    cmd = popen.call_args.args[0]
    assert cmd[:2] == ["opencode", "run"]
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "openai/gpt-5-codex"


def test_execute_inline_command_template_does_not_auto_inject_model(
    tmp_path: Path, mock_executor_env, mocker
):
    """inline template は provider model を暗黙注入しない"""
    popen = mocker.patch(
        "kage.executor.subprocess.Popen", return_value=DummyProc(stdout="ai response")
    )

    task = TaskDef(
        name="inline_task",
        cron="* * * * *",
        prompt="Fix this inline",
        provider="codex",
        command_template=["inline_cli", "{prompt}"],
    )
    execute_task(tmp_path, task)

    cmd = popen.call_args.args[0]
    assert cmd[0] == "inline_cli"
    assert "--model" not in cmd
    assert "Fix this inline" in cmd[1]


def test_execute_inline_command_template_can_opt_into_model_placeholder(
    tmp_path: Path, mock_executor_env, mocker
):
    """inline template でも {model_args} を置けば provider model を使える"""
    popen = mocker.patch(
        "kage.executor.subprocess.Popen", return_value=DummyProc(stdout="ai response")
    )

    task = TaskDef(
        name="inline_task",
        cron="* * * * *",
        prompt="Fix this inline",
        provider="codex",
        command_template=["inline_cli", "{model_args}", "{prompt}"],
    )
    execute_task(tmp_path, task)

    cmd = popen.call_args.args[0]
    assert cmd[0] == "inline_cli"
    assert cmd[1:3] == ["--model", "gpt-5-codex"]


def test_execute_provider_with_jq(tmp_path: Path, mock_executor_env, mocker):
    """jq parser は provider model 注入後も動作する"""
    popen = mocker.patch(
        "kage.executor.subprocess.Popen",
        return_value=DummyProc(stdout='{"output":"parsed"}'),
    )
    jq_run = mocker.patch("kage.executor.subprocess.run")
    jq_run.return_value = MagicMock(returncode=0, stdout="parsed\n", stderr="")

    task = TaskDef(
        name="jq_task", cron="* * * * *", prompt="Test JQ", provider="codex_json"
    )
    execute_task(tmp_path, task)

    cmd = popen.call_args.args[0]
    assert "--model" in cmd
    assert jq_run.call_args.args[0] == ["jq", "-r", ".output"]


def test_render_command_template_inserts_model_before_prompt():
    provider = ProviderConfig(
        command="codex", model="gpt-5-codex", model_flag="--model"
    )
    cmd = render_command_template(
        ["codex", "exec", "{prompt}"], "hello", provider=provider
    )

    assert cmd == ["codex", "exec", "--model", "gpt-5-codex", "hello"]


def test_render_command_template_honors_explicit_model_placeholder():
    provider = ProviderConfig(command="gemini", model="gemini-2.5-pro", model_flag="-m")
    cmd = render_command_template(
        ["gemini", "{model_args}", "--prompt", "{prompt}"],
        "hello",
        provider=provider,
    )

    assert cmd == ["gemini", "-m", "gemini-2.5-pro", "--prompt", "hello"]


def test_render_command_template_does_not_double_inject_after_prompt():
    provider = ProviderConfig(command="foo", model="bar", model_flag="--model")
    cmd = render_command_template(
        ["foo", "{prompt}", "{model_args}"],
        "hello",
        provider=provider,
    )

    assert cmd == ["foo", "hello", "--model", "bar"]


def test_render_command_template_drops_split_model_flag_when_model_is_missing():
    provider = ProviderConfig(command="foo", model=None, model_flag="--model")
    cmd = render_command_template(
        ["foo", "--model", "{model}", "{prompt}"],
        "hello",
        provider=provider,
    )

    assert cmd == ["foo", "hello"]


def test_config_default_loaded():
    """ライブラリデフォルトに model 対応済み provider が含まれる"""
    config = get_global_config(workspace_dir=Path("/nonexistent"))
    assert "codex" in config.providers
    assert "opencode" in config.providers
    assert "copilot" in config.providers
    assert config.providers["codex"].model_flag == "--model"
    assert "copilot" in config.commands
    assert config.ui_port == 8484


def test_config_model_overrides_merge_global_project_and_local(tmp_path: Path, mocker):
    """provider.model は global/project/local で順に上書きされる"""
    global_cfg = tmp_path / "global.toml"
    global_doc = tomlkit.document()
    global_doc["providers"] = {"codex": {"model": "global-model"}}
    with open(global_cfg, "w", encoding="utf-8") as f:
        tomlkit.dump(global_doc, f)

    ws_kage_dir = tmp_path / ".kage"
    ws_kage_dir.mkdir()

    ws_doc = tomlkit.document()
    ws_doc["providers"] = {"codex": {"model": "project-model"}}
    with open(ws_kage_dir / "config.toml", "w", encoding="utf-8") as f:
        tomlkit.dump(ws_doc, f)

    local_doc = tomlkit.document()
    local_doc["providers"] = {"codex": {"model": "local-model"}}
    with open(ws_kage_dir / "config.local.toml", "w", encoding="utf-8") as f:
        tomlkit.dump(local_doc, f)

    mocker.patch("kage.config.KAGE_CONFIG_PATH", global_cfg)
    config = get_global_config(workspace_dir=tmp_path)

    assert config.providers["codex"].model == "local-model"


def test_set_config_value_supports_nested_keys_for_local_scope(tmp_path: Path):
    """providers.codex.model のような nested key を local config に保存できる"""
    workspace_dir = tmp_path / "workspace"
    (workspace_dir / ".kage").mkdir(parents=True)

    set_config_value(
        "providers.codex.model",
        "gpt-5-mini",
        is_global=False,
        workspace_dir=workspace_dir,
        scope="local",
    )

    config_path = workspace_dir / ".kage" / "config.local.toml"
    with open(config_path, "r", encoding="utf-8") as f:
        data = tomlkit.load(f).unwrap()

    assert data["providers"]["codex"]["model"] == "gpt-5-mini"
