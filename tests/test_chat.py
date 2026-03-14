from datetime import datetime

import pytest
from unittest.mock import patch, MagicMock
from kage import db
from kage.ai.chat import generate_chat_reply, generate_logged_chat_reply
from kage.config import GlobalConfig, ProviderConfig, CommandDef
from kage.runs import get_run, load_run_metadata


@patch("kage.ai.chat.get_global_config")
@patch("kage.ai.chat.subprocess.run")
def test_generate_chat_reply(mock_run, mock_get_config):
    # Mock config
    config = GlobalConfig()
    config.default_ai_engine = "dummy"
    config.providers["dummy"] = ProviderConfig(
        command="dummy_cmd", model="gpt-5-codex", model_flag="--model"
    )
    config.commands["dummy_cmd"] = CommandDef(template=["dummy", "chat", "{prompt}"])
    mock_get_config.return_value = config

    # Mock subprocess output
    mock_res = MagicMock()
    mock_res.stdout = "hello world"
    mock_res.stderr = ""
    mock_res.returncode = 0
    mock_run.return_value = mock_res

    res = generate_chat_reply("hi")

    assert res["stdout"] == "hello world"
    assert res["returncode"] == 0
    mock_run.assert_called_once()
    assert mock_run.call_args[0][0][:2] == ["dummy", "chat"]
    assert "--model" in mock_run.call_args[0][0]
    assert "gpt-5-codex" in mock_run.call_args[0][0]
    assert any("hi" in arg for arg in mock_run.call_args[0][0])
    assert any("You are Kage" in arg for arg in mock_run.call_args[0][0])


@patch("kage.ai.chat.get_global_config")
def test_generate_chat_reply_no_engine(mock_get_config):
    config = GlobalConfig()
    mock_get_config.return_value = config
    with pytest.raises(ValueError, match="default_ai_engine is not set"):
        generate_chat_reply("hi")


@pytest.fixture
def logged_chat_env(tmp_path, mocker):
    db_path = tmp_path / "kage.db"
    logs_dir = tmp_path / "logs"
    mocker.patch("kage.db.KAGE_DB_PATH", db_path)
    mocker.patch("kage.config.KAGE_DB_PATH", db_path)
    mocker.patch("kage.runs.KAGE_DB_PATH", db_path)
    mocker.patch("kage.config.KAGE_LOGS_DIR", logs_dir)
    mocker.patch("kage.runs.KAGE_LOGS_DIR", logs_dir)
    db.init_db()
    return {"db_path": db_path, "logs_dir": logs_dir}


@patch("kage.ai.chat.get_global_config")
def test_generate_logged_chat_reply_creates_run_and_metadata(
    mock_get_config, logged_chat_env, mocker
):
    config = GlobalConfig()
    config.default_ai_engine = "dummy"
    config.providers["dummy"] = ProviderConfig(
        command="dummy_cmd", model="gpt-5-codex", model_flag="--model"
    )
    config.commands["dummy_cmd"] = CommandDef(template=["dummy", "chat", "{prompt}"])
    mock_get_config.return_value = config

    mocker.patch(
        "kage.executor.prepare_command_for_execution", side_effect=lambda cmd, env: cmd
    )
    mocker.patch(
        "kage.executor.run_logged_command",
        return_value={
            "stdout": "<thinking>secret</thinking>\nhello human",
            "stderr": "",
            "returncode": 0,
            "stdout_bytes": 37,
            "stderr_bytes": 0,
            "last_output_at": datetime.now().astimezone().isoformat(),
            "pid": 4242,
        },
    )

    result = generate_logged_chat_reply(
        "hi",
        run_name="connector:test",
        metadata={"connector": {"name": "test_connector", "type": "discord"}},
    )

    assert result["stdout"] == "hello human"
    run = get_run(result["run_id"])
    assert run is not None
    assert run.execution_kind == "connector_poll"
    assert run.provider_name == "dummy"
    assert run.stdout == "hello human"
    metadata = load_run_metadata(result["run_id"])
    assert metadata["connector"]["name"] == "test_connector"
    assert "You are Kage" in metadata["prompt"]
