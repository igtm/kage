import json
from unittest.mock import patch, MagicMock
from kage.connectors.discord import DiscordConnector
from kage.connectors.slack import SlackConnector
from kage.connectors.telegram import TelegramConnector
from kage.connectors.base import (
    ConnectorAttachment,
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


@patch("kage.connectors.base.BaseConnector._write_delivery_metadata")
@patch("kage.connectors.discord.urllib.request.urlopen")
@patch("kage.connectors.discord.generate_logged_chat_reply")
@patch("kage.connectors.discord.write_run_metadata")
def test_discord_connector_poll_and_reply_attachment_only(
    mock_write_metadata, mock_chat, mock_urlopen, mock_write_delivery, tmp_path
):
    config = DiscordConnectorConfig(active=True, bot_token="token", channel_id="123")
    connector = DiscordConnector("test_discord", config)
    connector.state_file = tmp_path / "discord_state.json"
    connector.history_file = tmp_path / "discord_history.jsonl"

    from datetime import datetime, timezone

    recent_ts = datetime.now(timezone.utc).isoformat()

    mock_identity_response = MagicMock()
    mock_identity_response.__enter__.return_value = mock_identity_response
    mock_identity_response.read.return_value = json.dumps(
        {"id": "999", "username": "kage"}
    ).encode("utf-8")

    mock_get_response = MagicMock()
    mock_get_response.__enter__.return_value = mock_get_response
    mock_get_response.read.return_value = json.dumps(
        [
            {
                "id": "1",
                "content": "",
                "attachments": [
                    {
                        "filename": "spec.txt",
                        "url": "https://cdn.discord.test/spec.txt",
                    }
                ],
                "author": {"bot": False},
                "timestamp": recent_ts,
            }
        ]
    ).encode("utf-8")

    mock_post_response = MagicMock()
    mock_post_response.__enter__.return_value = mock_post_response
    mock_post_response.read.return_value = json.dumps({"id": "2"}).encode("utf-8")

    mock_urlopen.side_effect = [
        mock_get_response,
        mock_identity_response,
        mock_post_response,
    ]
    mock_chat.return_value = {
        "stdout": "attachment handled",
        "stderr": "",
        "returncode": 0,
        "run_id": "run-discord-attachment",
    }

    connector.poll_and_reply()

    actual_prompt = mock_chat.call_args[0][0]
    assert "attachments without any text" in actual_prompt
    assert "incoming_attachment_preparer" in mock_chat.call_args.kwargs
    history = [
        json.loads(line)
        for line in connector.history_file.read_text(encoding="utf-8").splitlines()
    ]
    assert "spec.txt" in history[0]["content"]
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


@patch("kage.connectors.base.urllib.request.urlopen")
def test_discord_prepare_incoming_attachments_downloads_files(mock_urlopen, tmp_path):
    config = DiscordConnectorConfig(bot_token="token", channel_id="123")
    connector = DiscordConnector("test_discord", config)

    download_response = MagicMock()
    download_response.__enter__.return_value = download_response
    download_response.read.return_value = b"discord attachment"
    mock_urlopen.return_value = download_response

    preparation = connector._prepare_incoming_attachments(
        tmp_path / "artifacts",
        {
            "attachments": [
                {
                    "filename": "spec.txt",
                    "url": "https://cdn.discord.test/spec.txt",
                }
            ]
        },
        has_text=True,
    )

    assert [item.name for item in preparation.attachments] == ["spec.txt"]
    assert preparation.errors == []
    assert preparation.skip_execution is False
    assert preparation.attachments[0].path.read_text(encoding="utf-8") == (
        "discord attachment"
    )


@patch("kage.connectors.base.urllib.request.urlopen")
def test_discord_prepare_incoming_attachments_marks_skip_for_attachment_only_failure(
    mock_urlopen, tmp_path
):
    config = DiscordConnectorConfig(bot_token="token", channel_id="123")
    connector = DiscordConnector("test_discord", config)
    mock_urlopen.side_effect = Exception("download failed")

    preparation = connector._prepare_incoming_attachments(
        tmp_path / "artifacts",
        {
            "attachments": [
                {
                    "filename": "spec.txt",
                    "url": "https://cdn.discord.test/spec.txt",
                }
            ]
        },
        has_text=False,
    )

    assert preparation.attachments == []
    assert preparation.skip_execution is True
    assert "skipped this run" in (preparation.skip_reason or "")


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


@patch("kage.connectors.base.BaseConnector._write_delivery_metadata")
@patch("kage.connectors.telegram.urllib.request.urlopen")
@patch("kage.connectors.telegram.generate_logged_chat_reply")
@patch("kage.connectors.telegram.write_run_metadata")
def test_telegram_connector_poll_and_reply_attachment_only(
    mock_write_metadata, mock_chat, mock_urlopen, mock_write_delivery, tmp_path
):
    import time

    config = TelegramConnectorConfig(poll=True, bot_token="123456:ABC", chat_id="789")
    connector = TelegramConnector("test_telegram", config)
    connector.state_file = tmp_path / "telegram_state.json"
    connector.history_file = tmp_path / "telegram_history.jsonl"

    now_unix = int(time.time())

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
                        "document": {
                            "file_id": "DOC1",
                            "file_name": "spec.txt",
                        },
                    },
                }
            ],
        }
    ).encode("utf-8")

    mock_me_response = MagicMock()
    mock_me_response.__enter__.return_value = mock_me_response
    mock_me_response.read.return_value = json.dumps(
        {"ok": True, "result": {"id": 999, "is_bot": True, "username": "kage_bot"}}
    ).encode("utf-8")

    mock_send_response = MagicMock()
    mock_send_response.__enter__.return_value = mock_send_response
    mock_send_response.read.return_value = json.dumps(
        {"ok": True, "result": {"message_id": 2}}
    ).encode("utf-8")

    mock_urlopen.side_effect = [
        mock_updates_response,
        mock_me_response,
        mock_send_response,
    ]
    mock_chat.return_value = {
        "stdout": "attachment handled",
        "stderr": "",
        "returncode": 0,
        "run_id": "run-telegram-attachment",
    }

    connector.poll_and_reply()

    actual_prompt = mock_chat.call_args[0][0]
    assert "attachments without any text" in actual_prompt
    assert "incoming_attachment_preparer" in mock_chat.call_args.kwargs
    history = [
        json.loads(line)
        for line in connector.history_file.read_text(encoding="utf-8").splitlines()
    ]
    assert "spec.txt" in history[0]["content"]
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


@patch("kage.connectors.base.BaseConnector._write_delivery_metadata")
@patch("kage.connectors.slack.urllib.request.urlopen")
@patch("kage.connectors.slack.generate_logged_chat_reply")
@patch("kage.connectors.slack.write_run_metadata")
def test_slack_connector_poll_and_reply_attachment_only(
    mock_write_metadata, mock_chat, mock_urlopen, mock_write_delivery, tmp_path
):
    import time

    config = SlackConnectorConfig(poll=True, bot_token="token", channel_id="C123")
    connector = SlackConnector("test_slack", config)
    connector.state_file = tmp_path / "slack_state.json"
    connector.history_file = tmp_path / "slack_history.jsonl"

    now_unix = time.time()

    history_response = MagicMock()
    history_response.__enter__.return_value = history_response
    history_response.read.return_value = json.dumps(
        {
            "ok": True,
            "messages": [
                {
                    "ts": str(now_unix),
                    "text": "",
                    "user": "U123",
                    "files": [
                        {
                            "name": "brief.pdf",
                            "url_private_download": "https://files.slack.test/download/brief.pdf",
                        }
                    ],
                }
            ],
        }
    ).encode("utf-8")

    identity_response = MagicMock()
    identity_response.__enter__.return_value = identity_response
    identity_response.read.return_value = json.dumps(
        {"ok": True, "user_id": "B123", "user": "kage"}
    ).encode("utf-8")

    send_response = MagicMock()
    send_response.__enter__.return_value = send_response
    send_response.read.return_value = json.dumps({"ok": True, "ts": "171.02"}).encode(
        "utf-8"
    )

    mock_urlopen.side_effect = [
        history_response,
        identity_response,
        send_response,
    ]
    mock_chat.return_value = {
        "stdout": "attachment handled",
        "stderr": "",
        "returncode": 0,
        "run_id": "run-slack-attachment",
    }

    connector.poll_and_reply()

    actual_prompt = mock_chat.call_args[0][0]
    assert "attachments without any text" in actual_prompt
    assert "incoming_attachment_preparer" in mock_chat.call_args.kwargs
    history = [
        json.loads(line)
        for line in connector.history_file.read_text(encoding="utf-8").splitlines()
    ]
    assert "brief.pdf" in history[0]["content"]
    mock_write_delivery.assert_called_once()
    mock_write_metadata.assert_called_once()


@patch("kage.connectors.slack.urllib.request.urlopen")
def test_slack_send_message_uploads_attachments(mock_urlopen, tmp_path):
    config = SlackConnectorConfig(bot_token="token", channel_id="C123")
    connector = SlackConnector("test_slack", config)
    connector.history_file = tmp_path / "slack_history.jsonl"

    attachment_path = tmp_path / "report.txt"
    attachment_path.write_text("artifact payload", encoding="utf-8")
    attachment = ConnectorAttachment.from_path(attachment_path)

    text_response = MagicMock()
    text_response.__enter__.return_value = text_response
    text_response.read.return_value = json.dumps({"ok": True, "ts": "171.01"}).encode(
        "utf-8"
    )

    upload_meta_response = MagicMock()
    upload_meta_response.__enter__.return_value = upload_meta_response
    upload_meta_response.read.return_value = json.dumps(
        {
            "ok": True,
            "upload_url": "https://files.slack.test/upload",
            "file_id": "F123",
        }
    ).encode("utf-8")

    upload_binary_response = MagicMock()
    upload_binary_response.__enter__.return_value = upload_binary_response
    upload_binary_response.read.return_value = b"OK - 16"

    complete_response = MagicMock()
    complete_response.__enter__.return_value = complete_response
    complete_response.read.return_value = json.dumps(
        {
            "ok": True,
            "files": [
                {
                    "shares": {
                        "public": {"C123": [{"ts": "171.02"}]},
                    }
                }
            ],
        }
    ).encode("utf-8")

    mock_urlopen.side_effect = [
        text_response,
        upload_meta_response,
        upload_binary_response,
        complete_response,
    ]

    delivery = connector._post_reply(
        ConnectorMessage(text="artifact ready", attachments=[attachment])
    )

    assert delivery.posted_message_id == "171.02"
    assert [item.name for item in delivery.uploaded_attachments] == ["report.txt"]
    assert [item.name for item in delivery.skipped_attachments] == []
    assert delivery.errors == []
    assert mock_urlopen.call_args_list[0].args[0].full_url.endswith("/chat.postMessage")
    assert (
        mock_urlopen.call_args_list[1]
        .args[0]
        .full_url.endswith("/files.getUploadURLExternal")
    )
    assert (
        mock_urlopen.call_args_list[2].args[0].full_url
        == "https://files.slack.test/upload"
    )
    assert (
        mock_urlopen.call_args_list[3]
        .args[0]
        .full_url.endswith("/files.completeUploadExternal")
    )


@patch("kage.connectors.slack.urllib.request.urlopen")
def test_slack_send_message_uploads_attachments_without_share_ts(
    mock_urlopen, tmp_path
):
    config = SlackConnectorConfig(bot_token="token", channel_id="C123")
    connector = SlackConnector("test_slack", config)
    connector.history_file = tmp_path / "slack_history.jsonl"

    attachment_path = tmp_path / "report.txt"
    attachment_path.write_text("artifact payload", encoding="utf-8")
    attachment = ConnectorAttachment.from_path(attachment_path)

    upload_meta_response = MagicMock()
    upload_meta_response.__enter__.return_value = upload_meta_response
    upload_meta_response.read.return_value = json.dumps(
        {
            "ok": True,
            "upload_url": "https://files.slack.test/upload",
            "file_id": "F123",
        }
    ).encode("utf-8")

    upload_binary_response = MagicMock()
    upload_binary_response.__enter__.return_value = upload_binary_response
    upload_binary_response.read.return_value = b"OK - 16"

    complete_response = MagicMock()
    complete_response.__enter__.return_value = complete_response
    complete_response.read.return_value = json.dumps(
        {
            "ok": True,
            "files": [{"id": "F123", "title": "report.txt"}],
        }
    ).encode("utf-8")

    info_response = MagicMock()
    info_response.__enter__.return_value = info_response
    info_response.read.return_value = json.dumps(
        {
            "ok": True,
            "file": {
                "id": "F123",
                "shares": {"public": {"C123": [{"ts": "171.03"}]}},
            },
        }
    ).encode("utf-8")

    mock_urlopen.side_effect = [
        upload_meta_response,
        upload_binary_response,
        complete_response,
        info_response,
    ]

    delivery = connector._post_reply(ConnectorMessage(attachments=[attachment]))

    assert delivery.posted_message_id == "171.03"
    assert [item.name for item in delivery.uploaded_attachments] == ["report.txt"]
    assert [item.name for item in delivery.skipped_attachments] == []
    assert delivery.errors == []
    assert mock_urlopen.call_args_list[3].args[0].full_url.endswith("/files.info")


@patch("kage.connectors.slack.urllib.request.urlopen")
def test_slack_send_message_skips_failed_attachments_with_metadata(
    mock_urlopen, tmp_path
):
    config = SlackConnectorConfig(bot_token="token", channel_id="C123")
    connector = SlackConnector("test_slack", config)
    connector.history_file = tmp_path / "slack_history.jsonl"

    attachment_path = tmp_path / "report.txt"
    attachment_path.write_text("artifact payload", encoding="utf-8")
    attachment = ConnectorAttachment.from_path(attachment_path)

    text_response = MagicMock()
    text_response.__enter__.return_value = text_response
    text_response.read.return_value = json.dumps({"ok": True, "ts": "171.01"}).encode(
        "utf-8"
    )

    upload_meta_response = MagicMock()
    upload_meta_response.__enter__.return_value = upload_meta_response
    upload_meta_response.read.return_value = json.dumps(
        {"ok": False, "error": "missing_scope"}
    ).encode("utf-8")

    mock_urlopen.side_effect = [text_response, upload_meta_response]

    delivery = connector._post_reply(
        ConnectorMessage(text="artifact ready", attachments=[attachment])
    )

    assert delivery.posted_message_id == "171.01"
    assert [item.name for item in delivery.uploaded_attachments] == []
    assert [item.name for item in delivery.skipped_attachments] == ["report.txt"]
    assert any("missing_scope" in err for err in delivery.errors)


@patch("kage.connectors.base.urllib.request.urlopen")
def test_slack_prepare_incoming_attachments_downloads_private_files(
    mock_urlopen, tmp_path
):
    config = SlackConnectorConfig(bot_token="token", channel_id="C123")
    connector = SlackConnector("test_slack", config)

    download_response = MagicMock()
    download_response.__enter__.return_value = download_response
    download_response.read.return_value = b"slack attachment"
    mock_urlopen.return_value = download_response

    preparation = connector._prepare_incoming_attachments(
        tmp_path / "artifacts",
        {
            "files": [
                {
                    "name": "brief.pdf",
                    "url_private_download": "https://files.slack.test/download/brief.pdf",
                }
            ]
        },
        has_text=True,
    )

    assert [item.name for item in preparation.attachments] == ["brief.pdf"]
    request = mock_urlopen.call_args.args[0]
    assert request.headers["Authorization"] == "Bearer token"
    assert preparation.errors == []


@patch("kage.connectors.telegram.urllib.request.urlopen")
def test_telegram_send_message_uploads_photo_attachments(mock_urlopen, tmp_path):
    config = TelegramConnectorConfig(bot_token="123456:ABC", chat_id="789")
    connector = TelegramConnector("test_telegram", config)
    connector.history_file = tmp_path / "telegram_history.jsonl"

    attachment_path = tmp_path / "photo.png"
    attachment_path.write_bytes(b"\x89PNG\r\n\x1a\nartifact payload")
    attachment = ConnectorAttachment.from_path(attachment_path)

    text_response = MagicMock()
    text_response.__enter__.return_value = text_response
    text_response.read.return_value = json.dumps(
        {"ok": True, "result": {"message_id": 21}}
    ).encode("utf-8")

    photo_response = MagicMock()
    photo_response.__enter__.return_value = photo_response
    photo_response.read.return_value = json.dumps(
        {"ok": True, "result": {"message_id": 22}}
    ).encode("utf-8")

    mock_urlopen.side_effect = [text_response, photo_response]

    delivery = connector._post_reply(
        ConnectorMessage(text="artifact ready", attachments=[attachment])
    )

    assert delivery.posted_message_id == "22"
    assert [item.name for item in delivery.uploaded_attachments] == ["photo.png"]
    assert [item.name for item in delivery.skipped_attachments] == []
    assert delivery.errors == []
    assert mock_urlopen.call_args_list[0].args[0].full_url.endswith("/sendMessage")
    photo_request = mock_urlopen.call_args_list[1].args[0]
    assert photo_request.full_url.endswith("/sendPhoto")
    assert photo_request.headers["Content-type"].startswith(
        "multipart/form-data; boundary="
    )
    assert b'filename="photo.png"' in photo_request.data
    assert b"artifact payload" in photo_request.data


@patch("kage.connectors.telegram.urllib.request.urlopen")
def test_telegram_send_message_skips_failed_document_attachments_with_metadata(
    mock_urlopen, tmp_path
):
    config = TelegramConnectorConfig(bot_token="123456:ABC", chat_id="789")
    connector = TelegramConnector("test_telegram", config)
    connector.history_file = tmp_path / "telegram_history.jsonl"

    attachment_path = tmp_path / "report.txt"
    attachment_path.write_text("artifact payload", encoding="utf-8")
    attachment = ConnectorAttachment.from_path(attachment_path)

    text_response = MagicMock()
    text_response.__enter__.return_value = text_response
    text_response.read.return_value = json.dumps(
        {"ok": True, "result": {"message_id": 31}}
    ).encode("utf-8")

    document_response = MagicMock()
    document_response.__enter__.return_value = document_response
    document_response.read.return_value = json.dumps(
        {"ok": False, "description": "Bad Request: upload failed"}
    ).encode("utf-8")

    mock_urlopen.side_effect = [text_response, document_response]

    delivery = connector._post_reply(
        ConnectorMessage(text="artifact ready", attachments=[attachment])
    )

    assert delivery.posted_message_id == "31"
    assert [item.name for item in delivery.uploaded_attachments] == []
    assert [item.name for item in delivery.skipped_attachments] == ["report.txt"]
    assert any("upload failed" in err for err in delivery.errors)
    assert mock_urlopen.call_args_list[1].args[0].full_url.endswith("/sendDocument")


@patch("kage.connectors.telegram.urllib.request.urlopen")
def test_telegram_send_message_uploads_large_png_as_document(mock_urlopen, tmp_path):
    config = TelegramConnectorConfig(bot_token="123456:ABC", chat_id="789")
    connector = TelegramConnector("test_telegram", config)
    connector.history_file = tmp_path / "telegram_history.jsonl"

    attachment_path = tmp_path / "large-photo.png"
    attachment_path.write_bytes(b"\x89PNG\r\n\x1a\nartifact payload")
    attachment = ConnectorAttachment(
        path=attachment_path,
        name="large-photo.png",
        size_bytes=11 * 1024 * 1024,
    )

    document_response = MagicMock()
    document_response.__enter__.return_value = document_response
    document_response.read.return_value = json.dumps(
        {"ok": True, "result": {"message_id": 41}}
    ).encode("utf-8")

    mock_urlopen.return_value = document_response

    delivery = connector._post_reply(ConnectorMessage(attachments=[attachment]))

    assert delivery.posted_message_id == "41"
    assert [item.name for item in delivery.uploaded_attachments] == ["large-photo.png"]
    assert [item.name for item in delivery.skipped_attachments] == []
    assert delivery.errors == []
    assert mock_urlopen.call_args.args[0].full_url.endswith("/sendDocument")


@patch("kage.connectors.telegram.urllib.request.urlopen")
def test_telegram_prepare_incoming_attachments_downloads_document_and_photo(
    mock_urlopen, tmp_path
):
    config = TelegramConnectorConfig(bot_token="123456:ABC", chat_id="789")
    connector = TelegramConnector("test_telegram", config)

    document_meta_response = MagicMock()
    document_meta_response.__enter__.return_value = document_meta_response
    document_meta_response.read.return_value = json.dumps(
        {"ok": True, "result": {"file_path": "documents/spec.txt"}}
    ).encode("utf-8")

    photo_meta_response = MagicMock()
    photo_meta_response.__enter__.return_value = photo_meta_response
    photo_meta_response.read.return_value = json.dumps(
        {"ok": True, "result": {"file_path": "photos/image.jpg"}}
    ).encode("utf-8")

    document_download = MagicMock()
    document_download.__enter__.return_value = document_download
    document_download.read.return_value = b"telegram document"

    photo_download = MagicMock()
    photo_download.__enter__.return_value = photo_download
    photo_download.read.return_value = b"telegram photo"

    def side_effect(request):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "file_id=DOC1" in url:
            return document_meta_response
        if "file_id=P2" in url:
            return photo_meta_response
        if url.endswith("/documents/spec.txt"):
            return document_download
        if url.endswith("/photos/image.jpg"):
            return photo_download
        raise AssertionError(f"Unexpected Telegram URL: {url}")

    mock_urlopen.side_effect = side_effect

    preparation = connector._prepare_incoming_attachments(
        tmp_path / "artifacts",
        {
            "document": {"file_id": "DOC1", "file_name": "spec.txt"},
            "photo": [
                {"file_id": "P1", "file_size": 10},
                {"file_id": "P2", "file_size": 20},
            ],
        },
        has_text=True,
    )

    assert [item.name for item in preparation.attachments] == [
        "spec.txt",
        "telegram-photo.jpg",
    ]
    assert preparation.errors == []
    assert "file_id=DOC1" in mock_urlopen.call_args_list[0].args[0].full_url
    assert "file_id=P2" in mock_urlopen.call_args_list[2].args[0].full_url
