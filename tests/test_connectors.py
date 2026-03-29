import json
from unittest.mock import patch, MagicMock
from kage.connectors.discord import DiscordConnector
from kage.connectors.slack import SlackConnector
from kage.connectors.telegram import TelegramConnector
from kage.connectors.base import (
    ConnectorAttachment,
    ConnectorDelivery,
    ConnectorMessage,
)
from kage.config import (
    DiscordConnectorConfig,
    SlackConnectorConfig,
    TelegramConnectorConfig,
)


@patch("kage.connectors.base.BaseConnector._write_delivery_metadata")
@patch("kage.connectors.discord.urllib.request.urlopen")
@patch("kage.connectors.discord.generate_logged_chat_reply")
@patch("kage.connectors.discord.write_run_metadata")
def test_discord_connector_poll_and_reply(
    mock_write_metadata, mock_chat, mock_urlopen, mock_write_delivery, tmp_path
):
    config = DiscordConnectorConfig(active=True, bot_token="token", channel_id="123")
    connector = DiscordConnector("test_discord", config)
    connector.state_file = tmp_path / "discord_state.json"
    connector.history_file = tmp_path / "discord_history.jsonl"

    # Recent timestamp so the message passes max_age_seconds filter
    from datetime import datetime, timezone

    recent_ts = datetime.now(timezone.utc).isoformat()

    # Mock API: _get_bot_identity call
    mock_identity_response = MagicMock()
    mock_identity_response.__enter__.return_value = mock_identity_response
    mock_identity_response.read.return_value = json.dumps(
        {"id": "999", "username": "kage"}
    ).encode("utf-8")

    # Mock API: GET messages
    mock_get_response = MagicMock()
    mock_get_response.__enter__.return_value = mock_get_response
    mock_get_response.read.return_value = json.dumps(
        [
            {
                "id": "1",
                "content": "hello kage",
                "author": {"bot": False},
                "timestamp": recent_ts,
            }
        ]
    ).encode("utf-8")

    # Mock API: POST reply (returns message id "2")
    mock_post_response = MagicMock()
    mock_post_response.__enter__.return_value = mock_post_response
    mock_post_response.read.return_value = json.dumps({"id": "2"}).encode("utf-8")

    # urlopen calls: GET messages, _get_bot_identity, POST reply
    mock_urlopen.side_effect = [
        mock_get_response,
        mock_identity_response,
        mock_post_response,
    ]

    # Mock AI reply
    mock_chat.return_value = {
        "stdout": "hello human",
        "stderr": "",
        "returncode": 0,
        "run_id": "run-discord-1",
    }

    connector.poll_and_reply()

    # Check state file updated to bot's reply ID
    assert connector.state_file.exists()
    state = json.loads(connector.state_file.read_text())
    assert state["last_message_id"] == "2"

    # AI Chat triggered correctly
    mock_chat.assert_called_once()
    actual_prompt = mock_chat.call_args[0][0]
    assert "[Recent Chat History]" in actual_prompt
    assert "[Current Instruction]\nhello kage" in actual_prompt

    history = [
        json.loads(line)
        for line in connector.history_file.read_text(encoding="utf-8").splitlines()
    ]
    assert [entry["role"] for entry in history] == ["User", "Assistant"]
    assert all(entry["run_id"] == "run-discord-1" for entry in history)
    mock_write_delivery.assert_called_once()
    mock_write_metadata.assert_called_once()


@patch("kage.connectors.discord.urllib.request.urlopen")
def test_discord_connector_ignores_bot_messages(mock_urlopen, tmp_path):
    config = DiscordConnectorConfig(active=True, bot_token="token", channel_id="123")
    connector = DiscordConnector("test_discord", config)
    connector.state_file = tmp_path / "discord_state.json"

    # Mock API fetch response
    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.read.return_value = json.dumps(
        [{"id": "2", "content": "i am bot", "author": {"bot": True}}]
    ).encode("utf-8")

    mock_urlopen.side_effect = [mock_response]

    connector.poll_and_reply()

    # Chat logic should not be triggered, but state should skip to msg ID 2
    assert connector.state_file.exists()
    state = json.loads(connector.state_file.read_text())
    assert state["last_message_id"] == "2"


@patch("kage.connectors.discord.urllib.request.urlopen")
def test_discord_send_message_uploads_attachments(mock_urlopen, tmp_path):
    config = DiscordConnectorConfig(bot_token="token", channel_id="123")
    connector = DiscordConnector("test_discord", config)
    connector.history_file = tmp_path / "discord_history.jsonl"

    attachment_path = tmp_path / "report.txt"
    attachment_path.write_text("artifact payload", encoding="utf-8")
    attachment = ConnectorAttachment.from_path(attachment_path)

    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.read.return_value = json.dumps({"id": "55"}).encode("utf-8")
    mock_urlopen.return_value = mock_response

    connector.send_message(
        ConnectorMessage(text="artifact ready", attachments=[attachment])
    )

    request = mock_urlopen.call_args.args[0]
    assert request.get_method() == "POST"
    content_type = request.headers["Content-type"]
    assert content_type.startswith("multipart/form-data; boundary=")
    assert b'Content-Disposition: form-data; name="payload_json"' in request.data
    assert (
        b'Content-Disposition: form-data; name="files[0]"; filename="report.txt"'
        in request.data
    )
    assert b"artifact payload" in request.data


@patch("kage.connectors.discord.urllib.request.urlopen")
def test_discord_send_message_falls_back_to_text_when_upload_fails(
    mock_urlopen, tmp_path
):
    config = DiscordConnectorConfig(bot_token="token", channel_id="123")
    connector = DiscordConnector("test_discord", config)
    connector.history_file = tmp_path / "discord_history.jsonl"

    attachment_path = tmp_path / "report.txt"
    attachment_path.write_text("artifact payload", encoding="utf-8")
    attachment = ConnectorAttachment.from_path(attachment_path)

    mock_text_response = MagicMock()
    mock_text_response.__enter__.return_value = mock_text_response
    mock_text_response.read.return_value = json.dumps({"id": "77"}).encode("utf-8")

    mock_urlopen.side_effect = [Exception("upload failed"), mock_text_response]

    delivery = connector._post_reply(
        ConnectorMessage(text="artifact ready", attachments=[attachment])
    )

    assert delivery.posted_message_id == "77"
    assert [item.name for item in delivery.uploaded_attachments] == []
    assert [item.name for item in delivery.skipped_attachments] == ["report.txt"]
    assert any("upload failed" in err for err in delivery.errors)
    fallback_request = mock_urlopen.call_args.args[0]
    assert fallback_request.headers["Content-type"] == "application/json"


# === Telegram Connector Tests ===


@patch("kage.connectors.base.BaseConnector._write_delivery_metadata")
@patch("kage.connectors.telegram.urllib.request.urlopen")
@patch("kage.connectors.telegram.generate_logged_chat_reply")
@patch("kage.connectors.telegram.write_run_metadata")
def test_telegram_connector_poll_and_reply(
    mock_write_metadata, mock_chat, mock_urlopen, mock_write_delivery, tmp_path
):
    import time

    config = TelegramConnectorConfig(poll=True, bot_token="123456:ABC", chat_id="789")
    connector = TelegramConnector("test_telegram", config)
    connector.state_file = tmp_path / "telegram_state.json"
    connector.history_file = tmp_path / "telegram_history.jsonl"

    now_unix = int(time.time())

    # Mock API: getUpdates
    mock_updates_response = MagicMock()
    mock_updates_response.__enter__.return_value = mock_updates_response
    mock_updates_response.read.return_value = json.dumps(
        {
            "ok": True,
            "result": [
                {
                    "update_id": 100,
                    "message": {
                        "message_id": 1,
                        "from": {"id": 42, "is_bot": False, "first_name": "User"},
                        "chat": {"id": 789},
                        "date": now_unix,
                        "text": "hello kage",
                    },
                }
            ],
        }
    ).encode("utf-8")

    # Mock API: getMe
    mock_me_response = MagicMock()
    mock_me_response.__enter__.return_value = mock_me_response
    mock_me_response.read.return_value = json.dumps(
        {"ok": True, "result": {"id": 999, "is_bot": True, "username": "kage_bot"}}
    ).encode("utf-8")

    # Mock API: sendMessage
    mock_send_response = MagicMock()
    mock_send_response.__enter__.return_value = mock_send_response
    mock_send_response.read.return_value = json.dumps(
        {"ok": True, "result": {"message_id": 2}}
    ).encode("utf-8")

    # urlopen calls: getUpdates, getMe, sendMessage
    mock_urlopen.side_effect = [
        mock_updates_response,
        mock_me_response,
        mock_send_response,
    ]

    # Mock AI reply
    mock_chat.return_value = {
        "stdout": "hello human",
        "stderr": "",
        "returncode": 0,
        "run_id": "run-telegram-1",
    }

    connector.poll_and_reply()

    # Check state file updated
    assert connector.state_file.exists()
    state = json.loads(connector.state_file.read_text())
    assert state["last_update_id"] == "100"

    # AI Chat triggered correctly
    mock_chat.assert_called_once()
    actual_prompt = mock_chat.call_args[0][0]
    assert "[Recent Chat History]" in actual_prompt
    assert "[Current Instruction]\nhello kage" in actual_prompt

    history = [
        json.loads(line)
        for line in connector.history_file.read_text(encoding="utf-8").splitlines()
    ]
    assert [entry["role"] for entry in history] == ["User", "Assistant"]
    assert all(entry["run_id"] == "run-telegram-1" for entry in history)
    mock_write_delivery.assert_called_once()
    mock_write_metadata.assert_called_once()


@patch("kage.connectors.telegram.urllib.request.urlopen")
def test_telegram_connector_ignores_bot_messages(mock_urlopen, tmp_path):
    import time

    config = TelegramConnectorConfig(poll=True, bot_token="123456:ABC", chat_id="789")
    connector = TelegramConnector("test_telegram", config)
    connector.state_file = tmp_path / "telegram_state.json"
    connector.history_file = tmp_path / "telegram_history.jsonl"

    now_unix = int(time.time())

    # Mock API: getUpdates — bot message only
    mock_updates_response = MagicMock()
    mock_updates_response.__enter__.return_value = mock_updates_response
    mock_updates_response.read.return_value = json.dumps(
        {
            "ok": True,
            "result": [
                {
                    "update_id": 200,
                    "message": {
                        "message_id": 5,
                        "from": {"id": 999, "is_bot": True, "first_name": "Kage Bot"},
                        "chat": {"id": 789},
                        "date": now_unix,
                        "text": "i am bot",
                    },
                }
            ],
        }
    ).encode("utf-8")

    mock_urlopen.side_effect = [mock_updates_response]

    connector.poll_and_reply()

    # State should advance to update_id 200 but no AI call should be made
    assert connector.state_file.exists()
    state = json.loads(connector.state_file.read_text())
    assert state["last_update_id"] == "200"


def test_slack_send_message_skips_attachments_with_metadata(tmp_path, mocker):
    config = SlackConnectorConfig(bot_token="token", channel_id="C123")
    connector = SlackConnector("test_slack", config)

    attachment_path = tmp_path / "report.txt"
    attachment_path.write_text("artifact payload", encoding="utf-8")
    attachment = ConnectorAttachment.from_path(attachment_path)

    mock_post_reply = mocker.patch.object(
        connector,
        "_post_reply",
        return_value=ConnectorDelivery(posted_message_id="ts-1"),
    )
    mock_write_delivery = mocker.patch.object(connector, "_write_delivery_metadata")

    connector.send_message(
        ConnectorMessage(
            text="artifact ready",
            attachments=[attachment],
            run_id="run-slack-1",
        )
    )

    mock_post_reply.assert_called_once_with("artifact ready", run_id="run-slack-1")
    delivery = mock_write_delivery.call_args.args[1]
    assert delivery.posted_message_id == "ts-1"
    assert [item.name for item in delivery.skipped_attachments] == ["report.txt"]
    assert any(
        "does not support attachment uploads yet" in err for err in delivery.errors
    )


def test_telegram_send_message_skips_attachments_with_metadata(tmp_path, mocker):
    config = TelegramConnectorConfig(bot_token="123456:ABC", chat_id="789")
    connector = TelegramConnector("test_telegram", config)

    attachment_path = tmp_path / "report.txt"
    attachment_path.write_text("artifact payload", encoding="utf-8")
    attachment = ConnectorAttachment.from_path(attachment_path)

    mock_post_reply = mocker.patch.object(
        connector,
        "_post_reply",
        return_value=ConnectorDelivery(posted_message_id="message-1"),
    )
    mock_write_delivery = mocker.patch.object(connector, "_write_delivery_metadata")

    connector.send_message(
        ConnectorMessage(
            text="artifact ready",
            attachments=[attachment],
            run_id="run-telegram-2",
        )
    )

    mock_post_reply.assert_called_once_with("artifact ready", run_id="run-telegram-2")
    delivery = mock_write_delivery.call_args.args[1]
    assert delivery.posted_message_id == "message-1"
    assert [item.name for item in delivery.skipped_attachments] == ["report.txt"]
    assert any(
        "does not support attachment uploads yet" in err for err in delivery.errors
    )
