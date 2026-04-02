import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from ..ai.chat import clean_ai_reply, generate_logged_chat_reply
from ..artifacts import IncomingAttachmentPreparation
from ..connector_payload import (
    ConnectorAttachment,
    ConnectorDelivery,
    ConnectorMessage,
    normalize_connector_message,
)
from ..runs import write_run_metadata
from .base import BaseConnector


class SlackConnector(BaseConnector):
    def __init__(self, name: str, config):
        super().__init__(name, config)

    @staticmethod
    def _get_attachment_names(message: dict) -> list[str]:
        names: list[str] = []
        for index, file_info in enumerate(message.get("files") or [], start=1):
            raw_name = file_info.get("name") or file_info.get("title")
            names.append(str(raw_name or f"slack-file-{index}"))
        return names

    def _prepare_incoming_attachments(
        self,
        artifact_dir: Path,
        message: dict,
        *,
        has_text: bool,
    ) -> IncomingAttachmentPreparation:
        preparation = IncomingAttachmentPreparation()
        auth_headers = {"Authorization": f"Bearer {self.config.bot_token}"}
        for index, file_info in enumerate(message.get("files") or [], start=1):
            filename = file_info.get("name") or file_info.get("title")
            download_url = file_info.get("url_private_download") or file_info.get(
                "url_private"
            )
            fallback_stem = f"slack-file-{index}"
            if not download_url:
                preparation.errors.append(
                    f"{filename or fallback_stem}: Slack download URL was missing."
                )
                continue
            try:
                preparation.attachments.append(
                    self._download_to_incoming_attachment(
                        artifact_dir,
                        str(download_url),
                        str(filename) if filename else None,
                        fallback_stem=fallback_stem,
                        headers=auth_headers,
                    )
                )
            except Exception as exc:
                preparation.errors.append(f"{filename or fallback_stem}: {exc}")

        if not has_text and not preparation.attachments:
            preparation.skip_execution = True
            preparation.skip_reason = self._incoming_attachment_failure_reply()
        return preparation

    def _get_bot_identity(self):
        """Fetch bot's own user_id and name using auth.test."""
        url = "https://slack.com/api/auth.test"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.config.bot_token}",
                "User-Agent": "kage-connector",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
                if data.get("ok"):
                    return data.get("user_id"), data.get("user")
        except Exception:
            pass
        return None, None

    def poll_and_reply(self):
        if not self.config.bot_token or not self.config.channel_id:
            return

        state = self._load_state()
        last_ts = state.get("last_ts", "0")

        # Slack API: conversations.history
        # We fetch recent messages. Slack returns them newest first.
        limit = max(1, min(100, self.config.history_limit))
        url = f"https://slack.com/api/conversations.history?channel={self.config.channel_id}&limit={limit}&oldest={last_ts}"

        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.config.bot_token}",
                "User-Agent": "kage-connector",
            },
        )

        try:
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
                if not data.get("ok"):
                    # print(f"[kage] Slack API error: {data.get('error')}")
                    return
                messages = data.get("messages", [])
        except urllib.error.URLError:
            return
        except Exception:
            return

        if not messages:
            return

        # Fetch our own identity to help the AI recognize itself
        bot_user_id, bot_name = self._get_bot_identity()
        identity_context = ""
        if bot_user_id:
            identity_context = f"[YOUR IDENTITY ON SLACK]\n- Your Name: {bot_name}\n- Your User ID: {bot_user_id}\n- Mentions like <@{bot_user_id}> refer to YOU. Do not greet yourself.\n\n"

        # Slack returns newest first. Sort oldest to newest for context building.
        # Check if the absolutely latest message in the channel is from a bot.
        if messages and (
            "bot_id" in messages[0] or messages[0].get("subtype") == "bot_message"
        ):
            # If the latest message is a bot, skip processing to avoid double-reply or loops.
            # Still update state so we don't fetch these same messages again.
            state["last_ts"] = messages[0]["ts"]
            self._save_state(state)
            return

        messages.sort(key=lambda x: float(x["ts"]))

        # Build recent message history string to inject as context
        history_lines = []
        for msg in messages:
            # Slack uses user IDs. Mapping to names might be complex without users.info,
            # but we can at least distinguish Bot vs User.
            is_bot = "bot_id" in msg or msg.get("subtype") == "bot_message"
            content_text = msg.get("text", "").strip()
            if content_text:
                role = "Assistant" if is_bot else (msg.get("user") or "User")
                if bot_user_id and msg.get("user") == bot_user_id:
                    role = "Assistant"
                history_lines.append(f"{role}: {content_text}")
        history_context = "\n".join(history_lines)

        # Find the single newest user message to respond to.
        target_msg = None
        newest_ts = last_ts

        for msg in messages:
            msg_ts = msg["ts"]

            # Skip messages from bots (including self)
            if "bot_id" in msg or msg.get("subtype") == "bot_message":
                newest_ts = msg_ts
                continue

            # Always advance the watermark
            newest_ts = msg_ts

            # Filtering by user_id
            if self.config.user_id:
                author_id = msg.get("user")
                if author_id != str(self.config.user_id):
                    continue

            content = msg.get("text", "").strip()
            if not content and not (msg.get("files") or []):
                continue

            # Filtering by message age
            try:
                msg_time_unix = float(msg_ts)
                now_unix = datetime.now(timezone.utc).timestamp()
                age = now_unix - msg_time_unix
                if age > self.config.max_age_seconds:
                    continue
            except Exception:
                continue

            # This is a valid candidate — keep the NEWEST one
            target_msg = msg

        # Always advance watermark to newest seen message, even if we don't reply
        if newest_ts != last_ts:
            state["last_ts"] = newest_ts
            self._save_state(state)

        # Process the single target message (if any)
        if target_msg:
            content = target_msg.get("text", "").strip()
            attachment_names = self._get_attachment_names(target_msg)
            prompt_with_history = (
                f"{identity_context}[Recent Chat History]\n{history_context}\n\n"
                "[Current Instruction]\n"
                f"{content or self._build_attachment_only_instruction()}"
            )
            connector_meta = {
                "connector": {
                    "name": self.name,
                    "type": self.config.type,
                    "channel_id": str(self.config.channel_id),
                    "conversation_id": str(self.config.channel_id),
                    "source_message_id": str(target_msg.get("ts", "")),
                    "source_user_id": str(target_msg.get("user", "")),
                    "source_user_name": str(target_msg.get("user", "")),
                    "input_message": content,
                    "input_attachment_names": attachment_names,
                    "input_attachment_count": len(attachment_names),
                    "history_snapshot": history_context,
                }
            }
            reply_data = generate_logged_chat_reply(
                prompt_with_history,
                system_prompt=self.config.system_prompt,
                working_dir=self.config.working_dir,
                run_name=self._build_run_name(),
                metadata=connector_meta,
                incoming_attachment_preparer=lambda artifact_dir: (
                    self._prepare_incoming_attachments(
                        artifact_dir,
                        target_msg,
                        has_text=bool(content),
                    )
                ),
            )
            run_id = reply_data.get("run_id")
            reply_text = reply_data.get("stdout", "")
            if reply_data.get("skipped_execution"):
                reply_text = reply_data.get("stderr", "")
            elif reply_data.get("returncode") != 0 and not reply_text:
                err_text = reply_data.get("stderr") or "unknown error"
                reply_text = f"Error generating reply: {err_text}"
            final_reply_text = clean_ai_reply(reply_text)
            self._log_history(
                "User",
                self._build_history_entry(content, attachment_names),
                run_id=run_id,
            )
            delivery = self._post_reply(
                ConnectorMessage(
                    text=final_reply_text,
                    attachments=list(reply_data.get("attachments", [])),
                    run_id=run_id,
                )
            )
            self._write_delivery_metadata(run_id, delivery)
            if run_id:
                write_run_metadata(
                    run_id,
                    {
                        "connector": {
                            **connector_meta["connector"],
                            "posted_reply_id": delivery.posted_message_id,
                            "posted_reply_text": final_reply_text,
                            "uploaded_attachment_names": [
                                item.name for item in delivery.uploaded_attachments
                            ],
                            "skipped_attachment_names": [
                                item.name for item in delivery.skipped_attachments
                            ],
                            "attachment_errors": list(delivery.errors),
                        }
                    },
                )

            if delivery.posted_message_id:
                state["last_ts"] = delivery.posted_message_id
                self._save_state(state)

    def send_message(self, payload):
        if not self.config.bot_token or not self.config.channel_id:
            return
        message = normalize_connector_message(payload)
        delivery = self._post_reply(
            ConnectorMessage(
                text=clean_ai_reply(message.text),
                attachments=list(message.attachments),
                run_id=message.run_id,
            )
        )
        self._write_delivery_metadata(message.run_id, delivery)

    def _post_reply(self, message: str | ConnectorMessage) -> ConnectorDelivery:
        """Post a reply, splitting if needed. Returns delivery details."""
        payload = normalize_connector_message(message)
        text = payload.text
        attachments = list(payload.attachments)
        if not text and not attachments:
            return ConnectorDelivery()

        if text:
            self._log_history("Assistant", text, run_id=payload.run_id)

        delivery = ConnectorDelivery()
        chunks = self._split_message(text, max_len=3000) if text else []

        for chunk in chunks:
            ts = self._send_text_chunk(chunk)
            if ts:
                delivery.posted_message_id = ts
                continue
            delivery.errors.append("Failed to send a Slack message chunk.")

        for attachment in attachments:
            ts, error = self._send_attachment(attachment)
            if error is None:
                if ts:
                    delivery.posted_message_id = ts
                delivery.uploaded_attachments.append(attachment)
                continue
            delivery.skipped_attachments.append(attachment)
            delivery.errors.append(error)
        return delivery

    @staticmethod
    def _split_message(text: str, max_len: int = 3000) -> list[str]:
        """Split a message into chunks that fit within Slack's character limit."""
        if len(text) <= max_len:
            return [text]

        chunks = []
        remaining = text
        while remaining:
            if len(remaining) <= max_len:
                chunks.append(remaining)
                break

            split_at = remaining.rfind("\n", 0, max_len)
            if split_at <= 0:
                split_at = max_len

            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip("\n")

        return chunks

    def _send_text_chunk(self, text: str) -> str | None:
        """Send a single message chunk to Slack. Returns the posted message ts."""
        url = "https://slack.com/api/chat.postMessage"
        payload = {"channel": self.config.channel_id, "text": text}

        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.config.bot_token}",
                "Content-Type": "application/json",
                "User-Agent": "kage-connector",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req) as response:
                res_data = json.loads(response.read().decode())
                if res_data.get("ok"):
                    return res_data.get("ts")
        except Exception:
            pass
        return None

    def _send_attachment(
        self,
        attachment: ConnectorAttachment,
    ) -> tuple[str | None, str | None]:
        try:
            body = attachment.path.read_bytes()
        except OSError as exc:
            return None, str(exc)

        upload_meta = self._call_api(
            "https://slack.com/api/files.getUploadURLExternal",
            {
                "filename": attachment.name,
                "length": str(len(body)),
            },
        )
        if not upload_meta.get("ok"):
            return None, str(upload_meta.get("error") or "files.getUploadURLExternal")

        upload_url = upload_meta.get("upload_url")
        file_id = upload_meta.get("file_id")
        if not upload_url or not file_id:
            return None, "Slack upload URL response was missing upload_url or file_id."

        mime_type = (
            mimetypes.guess_type(attachment.name)[0] or "application/octet-stream"
        )
        upload_req = urllib.request.Request(
            str(upload_url),
            data=body,
            headers={
                "Content-Type": mime_type,
                "Content-Length": str(len(body)),
                "User-Agent": "kage-connector",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(upload_req):
                pass
        except Exception as exc:
            return None, str(exc)

        complete = self._call_api(
            "https://slack.com/api/files.completeUploadExternal",
            {
                "files": json.dumps([{"id": file_id, "title": attachment.name}]),
                "channel_id": str(self.config.channel_id),
            },
        )
        if not complete.get("ok"):
            return None, str(complete.get("error") or "files.completeUploadExternal")

        file_items = complete.get("files")
        if isinstance(file_items, list) and file_items:
            share_ts = self._find_share_ts(file_items[0])
            if share_ts:
                return share_ts, None
            file_id = file_items[0].get("id")
            if isinstance(file_id, str):
                share_ts = self._lookup_share_ts(file_id)
                if share_ts:
                    return share_ts, None
        return None, None

    def _call_api(self, url: str, payload: dict[str, str]) -> dict:
        data = urllib.parse.urlencode(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.config.bot_token}",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "kage-connector",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode())
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _lookup_share_ts(self, file_id: str) -> str | None:
        file_info = self._call_api(
            "https://slack.com/api/files.info",
            {"file": file_id},
        )
        if not file_info.get("ok"):
            return None
        return self._find_share_ts(file_info.get("file"))

    @staticmethod
    def _find_share_ts(value) -> str | None:
        if isinstance(value, dict):
            ts = value.get("ts")
            if isinstance(ts, str):
                return ts
            for nested in value.values():
                found = SlackConnector._find_share_ts(nested)
                if found:
                    return found
            return None
        if isinstance(value, list):
            for nested in value:
                found = SlackConnector._find_share_ts(nested)
                if found:
                    return found
        return None
