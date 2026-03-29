from datetime import datetime
from pathlib import Path

import pytest
from unittest.mock import patch, MagicMock
from kage import db
from kage.ai.chat import (
    clean_ai_reply,
    generate_chat_reply,
    generate_logged_chat_reply,
    get_thinking_tag,
)
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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("<thought>secret</thought>\nhello", "hello"),
        (
            "Use `<thinking>` literally.\n<thought>secret</thought>\nhello",
            "Use `<thinking>` literally.\n\nhello",
        ),
        (
            "```xml\n<thought>example</thought>\n```\n<thought>secret</thought>\nhello",
            "```xml\n<thought>example</thought>\n```\n\nhello",
        ),
        ("<final>hello</final>", "hello"),
        ("prefix<final>hello</final>suffix", "hello"),
        ("Before <think>hidden", "Before"),
        ("hello\n<think still thinking", "hello"),
        ("hello\n<final\nworld", "hello"),
        ("First\n\n<think>hidden</think>\n\nSecond", "First\n\nSecond"),
    ],
)
def test_clean_ai_reply_handles_reasoning_tags_without_breaking_code(text, expected):
    assert clean_ai_reply(text) == expected


def test_get_thinking_tag_uses_think_for_gemini():
    assert get_thinking_tag("gemini") == "think"


@patch("kage.ai.chat.get_global_config")
@patch("kage.ai.chat.subprocess.run")
def test_generate_chat_reply_uses_gemini_reasoning_and_final_tags(
    mock_run, mock_get_config
):
    config = GlobalConfig()
    config.default_ai_engine = "gemini"
    config.providers["gemini"] = ProviderConfig(command="gemini_cmd")
    config.commands["gemini_cmd"] = CommandDef(
        template=["gemini", "--prompt", "{prompt}"]
    )
    mock_get_config.return_value = config

    mock_res = MagicMock(stdout="ok", stderr="", returncode=0)
    mock_run.return_value = mock_res

    generate_chat_reply("hi")

    prompt_arg = mock_run.call_args[0][0][-1]
    assert "<think>" in prompt_arg
    assert "<final>" in prompt_arg


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
    seen_env: dict[str, str] = {}

    def fake_run_logged_command(*, cmd, cwd, env, exec_id):
        del cmd, cwd
        seen_env.update(env)
        artifact_dir = Path(env["KAGE_ARTIFACT_DIR"])
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "reply.txt").write_text("artifact payload", encoding="utf-8")
        return {
            "stdout": "<thinking>secret</thinking>\nhello human",
            "stderr": "",
            "returncode": 0,
            "stdout_bytes": 37,
            "stderr_bytes": 0,
            "last_output_at": datetime.now().astimezone().isoformat(),
            "pid": 4242,
        }

    mocker.patch(
        "kage.executor.run_logged_command", side_effect=fake_run_logged_command
    )

    result = generate_logged_chat_reply(
        "hi",
        working_dir=str(logged_chat_env["logs_dir"].parent),
        run_name="connector:test",
        metadata={"connector": {"name": "test_connector", "type": "discord"}},
    )

    assert result["stdout"] == "hello human"
    assert [attachment.name for attachment in result["attachments"]] == ["reply.txt"]
    assert seen_env["KAGE_ARTIFACT_DIR"] == str(
        logged_chat_env["logs_dir"].parent
        / ".kage"
        / "tmp"
        / "connector-artifacts"
        / result["run_id"]
    )
    assert (
        result["attachments"][0].path
        == Path(seen_env["KAGE_ARTIFACT_DIR"]) / "reply.txt"
    )
    assert '"type": "discord"' in seen_env["KAGE_CONNECTOR_TARGETS_JSON"]
    run = get_run(result["run_id"])
    assert run is not None
    assert run.execution_kind == "connector_poll"
    assert run.provider_name == "dummy"
    assert run.stdout == "hello human"
    metadata = load_run_metadata(result["run_id"])
    assert metadata["connector"]["name"] == "test_connector"
    assert "You are Kage" in metadata["prompt"]
    assert "test_connector" in metadata["prompt"]
    assert "discord" in metadata["prompt"]
    assert "Format links, markdown" in metadata["prompt"]
    assert "KAGE_ARTIFACT_DIR" in metadata["prompt"]
    assert "KAGE_CONNECTOR_TARGETS_JSON" in metadata["prompt"]
    assert "Kage uploads every top-level regular file left there" in metadata["prompt"]
    assert "Delete or move intermediate and source files" in metadata["prompt"]
    assert "reference them with relative paths" in metadata["prompt"]
    assert metadata["artifacts"]["files"][0]["name"] == "reply.txt"
    assert metadata["artifacts"]["dir"] == seen_env["KAGE_ARTIFACT_DIR"]
