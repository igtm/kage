import pytest
import tomlkit
from pathlib import Path
from unittest.mock import patch, MagicMock
from kage.executor import execute_task
from kage.parser import TaskDef
from kage.config import GlobalConfig, ProviderConfig, CommandDef, get_global_config


@pytest.fixture
def mock_global_config(mocker):
    config = GlobalConfig(
        default_ai_engine="codex",
        commands={
            "codex": CommandDef(template=["codex", "exec", "--full-auto", "{prompt}"]),
            "codex_json": CommandDef(template=["codex", "exec", "--full-auto", "--output-format", "json", "{prompt}"]),
            "custom_cli": CommandDef(template=["custom_cli", "{prompt}"]),
        },
        providers={
            "codex": ProviderConfig(command="codex", parser="raw"),
            "codex_json": ProviderConfig(command="codex_json", parser="jq", parser_args=".output"),
            "jq_provider": ProviderConfig(command="custom_cli", parser="jq", parser_args=".result"),
        }
    )
    mocker.patch("kage.executor.get_global_config", return_value=config)
    mocker.patch("kage.executor.log_execution")
    mocker.patch("kage.executor.sys.stdin.isatty", return_value=False)


def test_execute_shell_command_with_custom_shell(tmp_path: Path, mock_global_config, mocker):
    """shellを指定するとそのshellで実行される"""
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
    
    task = TaskDef(name="shell", cron="* * * * *", command="echo hello", shell="bash")
    execute_task(tmp_path, task)
    
    args, _ = mock_run.call_args
    assert Path(args[0][0]).name == "bash"
    assert args[0][1:] == ["-c", "echo hello"]


def test_execute_shell_command_default_sh(tmp_path: Path, mock_global_config, mocker):
    """shellを省略するとshがデフォルト"""
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
    
    task = TaskDef(name="shell", cron="* * * * *", command="echo hello")
    execute_task(tmp_path, task)
    
    args, _ = mock_run.call_args
    assert Path(args[0][0]).name == "sh"
    assert args[0][1:] == ["-c", "echo hello"]


def test_execute_ai_via_provider(tmp_path: Path, mock_global_config, mocker):
    """デフォルトプロバイダー (codex) で実行される"""
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = MagicMock(returncode=0, stdout="ai response", stderr="")
    
    task = TaskDef(name="ai_task", cron="* * * * *", prompt="Fix this")
    execute_task(tmp_path, task)
    
    args, _ = mock_run.call_args
    assert Path(args[0][0]).name == "codex"
    assert args[0][1:] == ["--ask-for-approval", "never", "--sandbox", "workspace-write", "exec", "Fix this"]


def test_execute_explicit_provider(tmp_path: Path, mock_global_config, mocker):
    """provider フィールドで明示指定するとそのプロバイダーが使われる"""
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = MagicMock(returncode=0, stdout="ai response", stderr="")
    
    task = TaskDef(name="ai_task", cron="* * * * *", prompt="Fix this", provider="codex_json")
    execute_task(tmp_path, task)
    
    # codex_json は jq パーサー付きなので 2回 run が呼ばれる
    assert mock_run.call_count == 2
    args, _ = mock_run.call_args_list[0]
    assert Path(args[0][0]).name == "codex"
    assert args[0][1:] == ["--ask-for-approval", "never", "--sandbox", "workspace-write", "exec", "--output-format", "json", "Fix this"]


def test_execute_inline_command_template(tmp_path: Path, mock_global_config, mocker):
    """command_template をインライン指定すると providers/commands を無視して使われる"""
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = MagicMock(returncode=0, stdout="ai response", stderr="")
    
    task = TaskDef(
        name="inline_task",
        cron="* * * * *",
        prompt="Fix this inline",
        command_template=["inline_cli", "-m", "10", "{prompt}"]
    )
    execute_task(tmp_path, task)
    
    args, _ = mock_run.call_args
    assert args[0] == ["inline_cli", "-m", "10", "Fix this inline"]


def test_execute_provider_with_jq(tmp_path: Path, mock_global_config, mocker):
    """jq_provider を使うとjqでstdoutがパースされる"""
    mock_run = mocker.patch("subprocess.run")
    
    def side_effect(cmd, **kwargs):
        if cmd[0] == "custom_cli":
            return MagicMock(returncode=0, stdout='{"result":"parsed"}', stderr="")
        elif cmd[0] == "jq":
            return MagicMock(returncode=0, stdout="parsed\n", stderr="")
        return MagicMock(returncode=1)
        
    mock_run.side_effect = side_effect
    
    task = TaskDef(name="jq_task", cron="* * * * *", prompt="Test JQ", provider="jq_provider")
    execute_task(tmp_path, task)
    
    assert mock_run.call_count == 2
    args_cli, _ = mock_run.call_args_list[0]
    args_jq, _ = mock_run.call_args_list[1]
    assert args_cli[0] == ["custom_cli", "Test JQ"]
    assert args_jq[0] == ["jq", "-r", ".result"]


def test_execute_inline_jq_parser(tmp_path: Path, mock_global_config, mocker):
    """command_template + parser + parser_args をタスク内でインライン指定するとjqが動く"""
    mock_run = mocker.patch("subprocess.run")
    
    def side_effect(cmd, **kwargs):
        if cmd[0] == "my_cli":
            return MagicMock(returncode=0, stdout='{"output":{"text":"hello"}}', stderr="")
        elif cmd[0] == "jq":
            return MagicMock(returncode=0, stdout="hello\n", stderr="")
        return MagicMock(returncode=1)
        
    mock_run.side_effect = side_effect
    
    task = TaskDef(
        name="inline_jq",
        cron="* * * * *",
        prompt="Query me",
        command_template=["my_cli", "{prompt}"],
        parser="jq",
        parser_args=".output.text"
    )
    execute_task(tmp_path, task)
    
    assert mock_run.call_count == 2
    args_jq, _ = mock_run.call_args_list[1]
    assert args_jq[0] == ["jq", "-r", ".output.text"]


def test_execute_claude_normalization(tmp_path: Path, mock_global_config, mocker):
    """claudeコマンドは非TTY環境で自動的に権限スキップフラグが付与される"""
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = MagicMock(returncode=0, stdout="claude response", stderr="")
    
    # configに無い未知のプロバイダーとして'claude'を直接使う（フォールバック）
    task = TaskDef(name="claude_task", cron="* * * * *", prompt="Fix this", provider="claude")
    
    # configにclaudeが無い場合に備え、モックのconfigにclaudeプロバイダーが無い状態にする
    # (実際にはdefault_config.tomlにあるが、ここではnormalizationのみを見る)
    execute_task(tmp_path, task)
    
    args, _ = mock_run.call_args
    # 実行ファイルが claude であることを確認 (shutil.whichで解決される想定)
    assert "claude" in args[0][0]
    # 正規化によってフラグが挿入されていることを確認
    assert "-p" in args[0]
    assert "--dangerously-skip-permissions" in args[0]
    assert "--allow-dangerously-skip-permissions" in args[0]


# --- config 層別マージのテスト ---

def test_config_default_loaded():
    """ライブラリデフォルトで codex プロバイダーが存在する"""
    config = get_global_config(workspace_dir=Path("/nonexistent"))
    assert "codex" in config.providers
    assert "codex" in config.commands
    assert config.ui_port == 8484


def test_workspace_config_overrides(tmp_path: Path):
    """ワークスペースの config.toml が最高優先で適用される"""
    ws_kage_dir = tmp_path / ".kage"
    ws_kage_dir.mkdir()
    ws_config = ws_kage_dir / "config.toml"
    doc = tomlkit.document()
    doc.add("ui_port", 9999)
    doc.add("default_ai_engine", "gemini")
    with open(ws_config, "w") as f:
        tomlkit.dump(doc, f)
    
    config = get_global_config(workspace_dir=tmp_path)
    assert config.ui_port == 9999
    assert config.default_ai_engine == "gemini"
    # デフォルトのкомандは引き続き利用可能
    assert "codex" in config.commands
