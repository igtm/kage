import json
import mimetypes
import urllib.request
import urllib.error
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
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


class DiscordConnector(BaseConnector):
    def __init__(self, name: str, config):
        super().__init__(name, config)

    @staticmethod
    def _get_attachment_names(message: dict) -> list[str]:
        names: list[str] = []
        for index, attachment in enumerate(message.get("attachments") or [], start=1):
            raw_name = attachment.get("filename")
            names.append(str(raw_name or f"discord-attachment-{index}"))
        return names

    def _prepare_incoming_attachments(
        self,
        artifact_dir: Path,
        message: dict,
        *,
        has_text: bool,
    ) -> IncomingAttachmentPreparation:
        preparation = IncomingAttachmentPreparation()
        for index, attachment in enumerate(message.get("attachments") or [], start=1):
            url = attachment.get("url") or attachment.get("proxy_url")
            filename = attachment.get("filename")
            fallback_stem = f"discord-attachment-{index}"
            if not url:
                preparation.errors.append(
                    f"{filename or fallback_stem}: Discord attachment URL was missing."
                )
                continue
            try:
                preparation.attachments.append(
                    self._download_to_incoming_attachment(
                        artifact_dir,
                        str(url),
                        str(filename) if filename else None,
                        fallback_stem=fallback_stem,
                    )
                )
            except Exception as exc:
                preparation.errors.append(f"{filename or fallback_stem}: {exc}")

        if not has_text and not preparation.attachments:
            preparation.skip_execution = True
            preparation.skip_reason = self._incoming_attachment_failure_reply()
        return preparation

    def _get_bot_identity(self):
        """Fetch bot's own user id and username using /users/@me."""
        url = "https://discord.com/api/v10/users/@me"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bot {self.config.bot_token}",
                "User-Agent": "kage-connector",
            },
        )
        try:
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
                return data.get("id"), data.get("username")
        except Exception:
            pass
        return None, None

    def poll_and_reply(self):
        if not self.config.bot_token or not self.config.channel_id:
            return

        state = self._load_state()
        last_message_id = state.get("last_message_id")

        limit = max(1, min(100, self.config.history_limit))
        url = f"https://discord.com/api/v10/channels/{self.config.channel_id}/messages?limit={limit}"

        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bot {self.config.bot_token}",
                "User-Agent": "kage-connector",
            },
        )

        try:
            with urllib.request.urlopen(req) as response:
                messages = json.loads(response.read().decode())
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
            identity_context = f"[YOUR IDENTITY ON DISCORD]\n- Your Username: {bot_name}\n- Your User ID: {bot_user_id}\n- Mentions like <@{bot_user_id}> or <@!{bot_user_id}> refer to YOU. Do not greet yourself.\n\n"

        # Discord API returns newer messages first. Sort oldest to newest.
        messages.sort(key=lambda x: int(x["id"]))

        # If the very last (newest) message in the channel is from a bot,
        # it means the bot already replied, so we shouldn't process anything.
        if messages and messages[-1].get("author", {}).get("bot"):
            # Still update state so we don't process these again
            state["last_message_id"] = messages[-1]["id"]
            self._save_state(state)
            return

        # Build recent message history string to inject as context
        history_lines = []
        for msg in messages:
            author_name = msg.get("author", {}).get("username", "Unknown")
            is_bot = msg.get("author", {}).get("bot", False)
            content_text = msg.get("content", "").strip()
            if content_text:
                role = "Assistant" if is_bot else author_name
                if bot_user_id and msg.get("author", {}).get("id") == bot_user_id:
                    role = "Assistant"
                history_lines.append(f"{role}: {content_text}")
        history_context = "\n".join(history_lines)

        # Find the single newest user message to respond to.
        # We only respond to ONE message per poll to avoid long processing
        # during which another cron cycle could start and cause duplicates.
        target_msg = None
        newest_id = last_message_id

        for msg in messages:
            msg_id = msg["id"]

            # Skip messages we've already processed
            if last_message_id and int(msg_id) <= int(last_message_id):
                continue

            # Always advance the watermark so we don't re-scan these
            newest_id = msg_id

            if msg.get("author", {}).get("bot"):
                continue

            # Filtering by user_id
            if self.config.user_id:
                author_id = msg.get("author", {}).get("id")
                if author_id != str(self.config.user_id):
                    continue

            content = msg.get("content", "").strip()
            if not content and not (msg.get("attachments") or []):
                continue

            # Filtering by message age
            try:
                msg_time = datetime.fromisoformat(msg["timestamp"])
                age = (datetime.now(timezone.utc) - msg_time).total_seconds()
                if age > self.config.max_age_seconds:
                    continue
            except Exception:
                continue  # If timestamp can't be parsed, skip (don't process stale msgs)

            # This is a valid candidate — keep the NEWEST one
            target_msg = msg

        # Always advance watermark to newest seen message, even if we don't reply
        if newest_id and newest_id != last_message_id:
            state["last_message_id"] = newest_id
            self._save_state(state)

        # Process the single target message (if any)
        if target_msg:
            content = target_msg.get("content", "").strip()
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
                    "source_message_id": str(target_msg.get("id", "")),
                    "source_user_id": str(target_msg.get("author", {}).get("id", "")),
                    "source_user_name": target_msg.get("author", {}).get(
                        "username", ""
                    ),
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
            attachments = list(reply_data.get("attachments", []))
            self._log_history(
                "User",
                self._build_history_entry(content, attachment_names),
                run_id=run_id,
            )
            delivery = self._post_reply(
                ConnectorMessage(
                    text=final_reply_text,
                    attachments=attachments,
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

            # Advance past bot's own reply to prevent self-reply on next poll
            if delivery.posted_message_id:
                state["last_message_id"] = delivery.posted_message_id
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

        chunks = self._split_message(text, max_len=1950) if text else []
        attachment_batches = self._chunk_attachments(attachments)
        operations: list[tuple[str, list[ConnectorAttachment]]] = []

        if chunks:
            operations.append(
                (chunks[0], attachment_batches[0] if attachment_batches else [])
            )
            operations.extend((chunk, []) for chunk in chunks[1:])
            if attachment_batches:
                operations.extend(("", batch) for batch in attachment_batches[1:])
        elif attachment_batches:
            operations.extend(("", batch) for batch in attachment_batches)

        delivery = ConnectorDelivery()
        for chunk_text, batch in operations:
            msg_id, error = self._send_chunk(chunk_text or None, batch)
            if msg_id:
                delivery.posted_message_id = msg_id
                delivery.uploaded_attachments.extend(batch)
                continue

            if batch:
                delivery.skipped_attachments.extend(batch)
                if error:
                    delivery.errors.append(error)
                if chunk_text:
                    fallback_id, fallback_error = self._send_chunk(chunk_text, [])
                    if fallback_id:
                        delivery.posted_message_id = fallback_id
                    elif fallback_error:
                        delivery.errors.append(fallback_error)
                continue

            if error:
                delivery.errors.append(error)

        return delivery

    @staticmethod
    def _split_message(text: str, max_len: int = 1950) -> list[str]:
        """Split a message into chunks that fit within Discord's character limit.
        Tries to split at newline boundaries when possible."""
        if len(text) <= max_len:
            return [text]

        chunks = []
        remaining = text
        while remaining:
            if len(remaining) <= max_len:
                chunks.append(remaining)
                break

            # Try to find a newline to split at
            split_at = remaining.rfind("\n", 0, max_len)
            if split_at <= 0:
                # No good newline found, split at max_len
                split_at = max_len

            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip("\n")

        return chunks

    @staticmethod
    def _chunk_attachments(
        attachments: list[ConnectorAttachment], batch_size: int = 10
    ) -> list[list[ConnectorAttachment]]:
        if not attachments:
            return []
        return [
            attachments[index : index + batch_size]
            for index in range(0, len(attachments), batch_size)
        ]

    @staticmethod
    def _build_multipart_body(
        payload: dict,
        attachments: list[ConnectorAttachment],
        boundary: str,
    ) -> bytes:
        chunks: list[bytes] = []
        boundary_bytes = boundary.encode("utf-8")

        chunks.extend(
            [
                b"--" + boundary_bytes + b"\r\n",
                b'Content-Disposition: form-data; name="payload_json"\r\n',
                b"Content-Type: application/json\r\n\r\n",
                json.dumps(payload).encode("utf-8"),
                b"\r\n",
            ]
        )

        for index, attachment in enumerate(attachments):
            mime_type = (
                mimetypes.guess_type(attachment.name)[0] or "application/octet-stream"
            )
            filename = attachment.name.replace('"', "_")
            chunks.extend(
                [
                    b"--" + boundary_bytes + b"\r\n",
                    (
                        f'Content-Disposition: form-data; name="files[{index}]"; '
                        f'filename="{filename}"\r\n'
                    ).encode("utf-8"),
                    f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
                    attachment.path.read_bytes(),
                    b"\r\n",
                ]
            )

        chunks.append(b"--" + boundary_bytes + b"--\r\n")
        return b"".join(chunks)

    def _send_chunk(
        self,
        text: str | None,
        attachments: list[ConnectorAttachment] | None = None,
    ) -> tuple[str | None, str | None]:
        """Send a single Discord message chunk and return (message_id, error)."""
        url = f"https://discord.com/api/v10/channels/{self.config.channel_id}/messages"
        batch = list(attachments or [])
        headers = {
            "Authorization": f"Bot {self.config.bot_token}",
            "User-Agent": "kage-connector",
        }

        if batch:
            payload = {
                "attachments": [
                    {"id": index, "filename": attachment.name}
                    for index, attachment in enumerate(batch)
                ]
            }
            if text:
                payload["content"] = text
            boundary = f"kage-{uuid4().hex}"
            try:
                data = self._build_multipart_body(payload, batch, boundary)
            except OSError as exc:
                return None, str(exc)
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        else:
            payload = {}
            if text:
                payload["content"] = text
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req) as response:
                res_data = json.loads(response.read().decode())
                return res_data.get("id"), None
        except Exception as exc:
            return None, str(exc)
