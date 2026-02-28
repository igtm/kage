import pytest
from unittest.mock import patch, MagicMock
from kage.ai.chat import generate_chat_reply
from kage.config import GlobalConfig, ProviderConfig, CommandDef

@patch("kage.ai.chat.get_global_config")
@patch("kage.ai.chat.subprocess.run")
def test_generate_chat_reply(mock_run, mock_get_config):
    # Mock config
    config = GlobalConfig()
    config.default_ai_engine = "dummy"
    config.providers["dummy"] = ProviderConfig(command="dummy_cmd")
    config.commands["dummy_cmd"] = CommandDef(template=["echo", "{prompt}"])
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
    assert any("echo" in arg for arg in mock_run.call_args[0][0])
    assert any("hi" in arg for arg in mock_run.call_args[0][0])
    assert any("You are Kage" in arg for arg in mock_run.call_args[0][0])

@patch("kage.ai.chat.get_global_config")
def test_generate_chat_reply_no_engine(mock_get_config):
    config = GlobalConfig()
    mock_get_config.return_value = config
    with pytest.raises(ValueError, match="default_ai_engine is not set"):
        generate_chat_reply("hi")
