import pytest
import json
from unittest.mock import patch, MagicMock
from kage.connectors.discord import DiscordConnector
from kage.config import DiscordConnectorConfig

@patch("kage.connectors.discord.urllib.request.urlopen")
@patch("kage.connectors.discord.generate_chat_reply")
def test_discord_connector_poll_and_reply(mock_chat, mock_urlopen, tmp_path):
    config = DiscordConnectorConfig(
        active=True, bot_token="token", channel_id="123"
    )
    connector = DiscordConnector("test_discord", config)
    connector.state_file = tmp_path / "discord_state.json"

    # Mock API fetch response
    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.read.return_value = json.dumps([
        {"id": "1", "content": "hello kage", "author": {"bot": False}}
    ]).encode("utf-8")
    
    # Mock POST response for posting reply
    mock_post_response = MagicMock()
    
    # urlopen is called twice: one GET, one POST
    mock_urlopen.side_effect = [mock_response, mock_post_response]

    # Mock AI reply
    mock_chat.return_value = {"stdout": "hello human", "stderr": "", "returncode": 0}

    connector.poll_and_reply()

    # Check state file updated
    assert connector.state_file.exists()
    state = json.loads(connector.state_file.read_text())
    assert state["last_message_id"] == "1"

    # AI Chat triggered correctly
    mock_chat.assert_called_once()
    actual_prompt = mock_chat.call_args[0][0]
    assert "[Recent Chat History]" in actual_prompt
    assert "Unknown: hello kage" in actual_prompt
    assert "[Current Instruction]\nhello kage" in actual_prompt

@patch("kage.connectors.discord.urllib.request.urlopen")
def test_discord_connector_ignores_bot_messages(mock_urlopen, tmp_path):
    config = DiscordConnectorConfig(
        active=True, bot_token="token", channel_id="123"
    )
    connector = DiscordConnector("test_discord", config)
    connector.state_file = tmp_path / "discord_state.json"

    # Mock API fetch response
    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.read.return_value = json.dumps([
        {"id": "2", "content": "i am bot", "author": {"bot": True}}
    ]).encode("utf-8")
    
    mock_urlopen.side_effect = [mock_response]

    connector.poll_and_reply()

    # Chat logic should not be triggered, but state should skip to msg ID 2
    assert connector.state_file.exists()
    state = json.loads(connector.state_file.read_text())
    assert state["last_message_id"] == "2"

@patch("kage.connectors.discord.urllib.request.urlopen")
def test_discord_connector_splits_long_messages(mock_urlopen, tmp_path):
    config = DiscordConnectorConfig(
        active=True, bot_token="token", channel_id="123"
    )
    connector = DiscordConnector("test_discord", config)
    
    # A long message (> 1950 chars)
    long_message = "A" * 3000
    
    # post_reply should be called twice (3000 / 1950 = 2 chunks)
    connector._post_reply(long_message)
    
    # urllib.request.urlopen should be called twice for the two chunks
    assert mock_urlopen.call_count == 2
    
    # First chunk: 1950 chars
    first_chunk_payload = json.loads(mock_urlopen.call_args_list[0][0][0].data.decode())
    assert len(first_chunk_payload["content"]) == 1950
    
    # Second chunk: 1050 chars
    second_chunk_payload = json.loads(mock_urlopen.call_args_list[1][0][0].data.decode())
    assert len(second_chunk_payload["content"]) == 1050
