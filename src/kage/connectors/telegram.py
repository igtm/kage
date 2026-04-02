import json
import mimetypes
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
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


class TelegramConnector(BaseConnector):
    def __init__(self, name: str, config):
        super().__init__(name, config)
        self.api_base = f"https://api.telegram.org/bot{self.config.bot_token}"

    @staticmethod
    def _get_message_text(message: dict) -> str:
        return (message.get("text") or message.get("caption") or "").strip()

    @staticmethod
    def _select_largest_photo(message: dict) -> dict | None:
        photos = message.get("photo") or []
        if not isinstance(photos, list) or not photos:
            return None
        return max(
            (item for item in photos if isinstance(item, dict)),
            key=lambda item: (
                int(item.get("file_size", 0)),
                int(item.get("width", 0)) * int(item.get("height", 0)),
            ),
            default=None,
        )

    def _get_attachment_names(self, message: dict) -> list[str]:
        names: list[str] = []
        document = message.get("document")
        if isinstance(document, dict):
            names.append(str(document.get("file_name") or "telegram-document"))
        largest_photo = self._select_largest_photo(message)
        if largest_photo is not None:
            names.append("telegram-photo.jpg")
        return names

    def _get_file_info(self, file_id: str) -> dict:
        req = urllib.request.Request(
            f"{self.api_base}/getFile?file_id={file_id}",
            headers={"User-Agent": "kage-connector"},
        )
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())

    def _prepare_telegram_file(
        self,
        artifact_dir: Path,
        *,
        file_id: str,
        filename: str | None,
        fallback_stem: str,
    ) -> ConnectorAttachment:
        file_info = self._get_file_info(file_id)
        if not file_info.get("ok"):
            raise RuntimeError(str(file_info.get("description") or "Telegram getFile"))
        result = file_info.get("result") or {}
        file_path = result.get("file_path")
        if not file_path:
            raise RuntimeError("Telegram getFile response was missing file_path.")
        resolved_name = filename
        if not resolved_name:
            suffix = Path(str(file_path)).suffix
            resolved_name = f"{fallback_stem}{suffix}" if suffix else fallback_stem
        return self._download_to_incoming_attachment(
            artifact_dir,
            f"https://api.telegram.org/file/bot{self.config.bot_token}/{file_path}",
            resolved_name,
            fallback_stem=fallback_stem,
        )

    def _prepare_incoming_attachments(
        self,
        artifact_dir: Path,
        message: dict,
        *,
        has_text: bool,
    ) -> IncomingAttachmentPreparation:
        preparation = IncomingAttachmentPreparation()

        document = message.get("document")
        if isinstance(document, dict):
            file_id = document.get("file_id")
            if file_id:
                try:
                    preparation.attachments.append(
                        self._prepare_telegram_file(
                            artifact_dir,
                            file_id=str(file_id),
                            filename=(
                                str(document.get("file_name"))
                                if document.get("file_name")
                                else None
                            ),
                            fallback_stem="telegram-document",
                        )
                    )
                except Exception as exc:
                    preparation.errors.append(
                        f"{document.get('file_name') or 'telegram-document'}: {exc}"
                    )
            else:
                preparation.errors.append(
                    "telegram-document: Telegram document file_id was missing."
                )

        largest_photo = self._select_largest_photo(message)
        if largest_photo is not None:
            photo_file_id = largest_photo.get("file_id")
            if photo_file_id:
                try:
                    preparation.attachments.append(
                        self._prepare_telegram_file(
                            artifact_dir,
                            file_id=str(photo_file_id),
                            filename=None,
                            fallback_stem="telegram-photo",
                        )
                    )
                except Exception as exc:
                    preparation.errors.append(f"telegram-photo: {exc}")
            else:
                preparation.errors.append(
                    "telegram-photo: Telegram photo file_id was missing."
                )

        if not has_text and not preparation.attachments:
            preparation.skip_execution = True
            preparation.skip_reason = self._incoming_attachment_failure_reply()
        return preparation

    def _get_bot_identity(self):
        """Fetch bot's own user id and username using getMe."""
        url = f"{self.api_base}/getMe"
        req = urllib.request.Request(url, headers={"User-Agent": "kage-connector"})
        try:
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
                if data.get("ok"):
                    result = data["result"]
                    return str(result.get("id")), result.get("username")
        except Exception:
            pass
        return None, None

    def poll_and_reply(self):
        if not self.config.bot_token or not self.config.chat_id:
            return

        state = self._load_state()
        last_update_id = state.get("last_update_id")

        # Telegram getUpdates: fetch new updates since last_update_id
        limit = max(1, min(100, self.config.history_limit))
        url = f"{self.api_base}/getUpdates?limit={limit}&timeout=0"
        if last_update_id:
            url += f"&offset={int(last_update_id) + 1}"

        req = urllib.request.Request(url, headers={"User-Agent": "kage-connector"})

        try:
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
                if not data.get("ok"):
                    return
                updates = data.get("result", [])
        except urllib.error.URLError:
            return
        except Exception:
            return

        if not updates:
            return

        # Fetch our own identity
        bot_user_id, bot_name = self._get_bot_identity()
        identity_context = ""
        if bot_user_id:
            identity_context = f"[YOUR IDENTITY ON TELEGRAM]\n- Your Username: @{bot_name}\n- Your User ID: {bot_user_id}\n- Do not greet yourself.\n\n"

        # Filter updates that are text messages in the target chat
        chat_messages = []
        newest_update_id = last_update_id

        for update in updates:
            update_id = update.get("update_id")
            if update_id:
                newest_update_id = str(update_id)

            msg = update.get("message")
            if not msg:
                continue

            # Only process messages from the configured chat
            msg_chat_id = str(msg.get("chat", {}).get("id", ""))
            if msg_chat_id != str(self.config.chat_id):
                continue

            chat_messages.append(msg)

        # Always advance watermark
        if newest_update_id and newest_update_id != last_update_id:
            state["last_update_id"] = newest_update_id
            self._save_state(state)

        if not chat_messages:
            return

        # Build recent message history
        history_lines = []
        for msg in chat_messages:
            from_user = msg.get("from", {})
            is_bot = from_user.get("is_bot", False)
            content_text = self._get_message_text(msg)
            if content_text:
                if is_bot and bot_user_id and str(from_user.get("id")) == bot_user_id:
                    role = "Assistant"
                elif is_bot:
                    role = "Bot"
                else:
                    first = from_user.get("first_name", "")
                    last = from_user.get("last_name", "")
                    role = f"{first} {last}".strip() or from_user.get(
                        "username", "User"
                    )
                history_lines.append(f"{role}: {content_text}")
        history_context = "\n".join(history_lines)

        # Find the single newest user message to respond to
        target_msg = None

        for msg in chat_messages:
            from_user = msg.get("from", {})

            # Skip bot messages
            if from_user.get("is_bot", False):
                continue

            # Filtering by user_id
            if self.config.user_id:
                author_id = str(from_user.get("id", ""))
                if author_id != str(self.config.user_id):
                    continue

            content = self._get_message_text(msg)
            if not content and not (
                isinstance(msg.get("document"), dict) or self._select_largest_photo(msg)
            ):
                continue

            # Filtering by message age
            try:
                msg_date = msg.get("date", 0)
                age = datetime.now(timezone.utc).timestamp() - msg_date
                if age > self.config.max_age_seconds:
                    continue
            except Exception:
                continue

            # Keep the NEWEST one
            target_msg = msg

        # Process the single target message (if any)
        if target_msg:
            content = self._get_message_text(target_msg)
            attachment_names = self._get_attachment_names(target_msg)
            prompt_with_history = (
                f"{identity_context}[Recent Chat History]\n{history_context}\n\n"
                "[Current Instruction]\n"
                f"{content or self._build_attachment_only_instruction()}"
            )
            from_user = target_msg.get("from", {})
            connector_meta = {
                "connector": {
                    "name": self.name,
                    "type": self.config.type,
                    "chat_id": str(self.config.chat_id),
                    "conversation_id": str(self.config.chat_id),
                    "source_message_id": str(target_msg.get("message_id", "")),
                    "source_user_id": str(from_user.get("id", "")),
                    "source_user_name": (
                        f"{from_user.get('first_name', '')} {from_user.get('last_name', '')}".strip()
                        or from_user.get("username", "")
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

    def send_message(self, payload):
        if not self.config.bot_token or not self.config.chat_id:
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
        chunks = self._split_message(text, max_len=4000) if text else []

        for chunk in chunks:
            msg_id = self._send_text_chunk(chunk)
            if msg_id:
                delivery.posted_message_id = msg_id
                continue
            delivery.errors.append("Failed to send a Telegram message chunk.")

        for attachment in attachments:
            msg_id, error = self._send_attachment(attachment)
            if msg_id:
                delivery.posted_message_id = msg_id
                delivery.uploaded_attachments.append(attachment)
                continue
            delivery.skipped_attachments.append(attachment)
            if error:
                delivery.errors.append(error)
            else:
                delivery.errors.append(
                    f"Failed to upload Telegram attachment: {attachment.name}"
                )
        return delivery

    @staticmethod
    def _split_message(text: str, max_len: int = 4000) -> list[str]:
        """Split a message into chunks that fit within Telegram's character limit."""
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
        """Send a single message chunk to Telegram. Returns the posted message ID."""
        url = f"{self.api_base}/sendMessage"
        payload = {"chat_id": self.config.chat_id, "text": text}

        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "kage-connector",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req) as response:
                res_data = json.loads(response.read().decode())
                if res_data.get("ok"):
                    return str(res_data.get("result", {}).get("message_id"))
        except Exception:
            pass
        return None

    def _send_attachment(
        self,
        attachment: ConnectorAttachment,
    ) -> tuple[str | None, str | None]:
        as_photo = self._should_send_as_photo(attachment)
        method = "sendPhoto" if as_photo else "sendDocument"
        field_name = "photo" if as_photo else "document"
        boundary = f"kage-{uuid4().hex}"
        try:
            data = self._build_multipart_body(
                {"chat_id": str(self.config.chat_id)},
                field_name,
                attachment,
                boundary,
            )
        except OSError as exc:
            return None, str(exc)

        req = urllib.request.Request(
            f"{self.api_base}/{method}",
            data=data,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "kage-connector",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req) as response:
                res_data = json.loads(response.read().decode())
                if res_data.get("ok"):
                    return str(res_data.get("result", {}).get("message_id")), None
                return None, str(res_data.get("description") or method)
        except Exception as exc:
            return None, str(exc)

    @staticmethod
    def _should_send_as_photo(attachment: ConnectorAttachment) -> bool:
        mime_type = mimetypes.guess_type(attachment.name)[0]
        return (
            mime_type in {"image/jpeg", "image/png"}
            and attachment.size_bytes <= 10 * 1024 * 1024
        )

    @staticmethod
    def _build_multipart_body(
        fields: dict[str, str],
        file_field: str,
        attachment: ConnectorAttachment,
        boundary: str,
    ) -> bytes:
        chunks: list[bytes] = []
        boundary_bytes = boundary.encode("utf-8")

        for name, value in fields.items():
            chunks.extend(
                [
                    b"--" + boundary_bytes + b"\r\n",
                    (f'Content-Disposition: form-data; name="{name}"\r\n\r\n').encode(
                        "utf-8"
                    ),
                    str(value).encode("utf-8"),
                    b"\r\n",
                ]
            )

        mime_type = (
            mimetypes.guess_type(attachment.name)[0] or "application/octet-stream"
        )
        filename = attachment.name.replace('"', "_")
        chunks.extend(
            [
                b"--" + boundary_bytes + b"\r\n",
                (
                    f'Content-Disposition: form-data; name="{file_field}"; '
                    f'filename="{filename}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
                attachment.path.read_bytes(),
                b"\r\n",
                b"--" + boundary_bytes + b"--\r\n",
            ]
        )
        return b"".join(chunks)
