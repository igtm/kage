import asyncio
import json
import mimetypes
import threading
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

DEFAULT_DISCORD_SYSTEM_PROMPT = """You are communicating with the user via Discord.
Please adhere to the following formatting rules:
- Discord does NOT support Markdown tables natively. If you need to present tabular data, you MUST use an ASCII table inside a code block (```).
- Use standard Markdown for bold (**text**), italics (*text*), and code blocks (```).
- Do not use HTML tags."""


class DiscordConnector(BaseConnector):
    GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"
    # GUILDS | GUILD_MESSAGES | DIRECT_MESSAGES | MESSAGE_CONTENT
    GATEWAY_INTENTS = 37377

    def __init__(self, name: str, config):
        super().__init__(name, config)
        self._bot_user_id: str | None = None
        self._bot_name: str | None = None
        self._bot_identity_lock = threading.Lock()
        self._realtime_lock = threading.Lock()

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

    def _fetch_bot_identity(self):
        """Return cached bot identity, fetching it once if needed."""
        with self._bot_identity_lock:
            if self._bot_user_id is None:
                self._bot_user_id, self._bot_name = self._get_bot_identity()
            return self._bot_user_id, self._bot_name

    def _build_identity_context(self) -> str:
        bot_user_id, bot_name = self._fetch_bot_identity()
        if not bot_user_id:
            return ""
        return (
            f"[YOUR IDENTITY ON DISCORD]\n"
            f"- Your Username: {bot_name}\n"
            f"- Your User ID: {bot_user_id}\n"
            f"- Mentions like <@{bot_user_id}> or <@!{bot_user_id}> refer to YOU. "
            f"Do not greet yourself.\n\n"
        )

    def _fetch_recent_messages(self, limit: int | None = None) -> list[dict]:
        """Fetch the most recent messages from the configured channel."""
        if not self.config.bot_token or not self.config.channel_id:
            return []

        resolved_limit = max(1, min(100, limit or self.config.history_limit))
        url = (
            f"https://discord.com/api/v10/channels/{self.config.channel_id}/messages"
            f"?limit={resolved_limit}"
        )
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bot {self.config.bot_token}",
                "User-Agent": "kage-connector",
            },
        )
        try:
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode())
        except Exception:
            return []

    @staticmethod
    def _build_history_context(messages: list[dict], bot_user_id: str | None) -> str:
        """Build a recent chat history string from Discord message objects."""
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
        return "\n".join(history_lines)

    def _is_valid_target_message(self, msg: dict) -> bool:
        """Check whether a message should trigger a reply."""
        if msg.get("author", {}).get("bot"):
            return False

        if self.config.user_id:
            author_id = msg.get("author", {}).get("id")
            if author_id != str(self.config.user_id):
                return False

        content = msg.get("content", "").strip()
        if not content and not (msg.get("attachments") or []):
            return False

        return True

    def _process_target_message(
        self,
        target_msg: dict,
        messages: list[dict],
        identity_context: str,
        history_context: str,
        *,
        execution_kind: str = "connector_poll",
    ) -> None:
        """Generate and post a reply for a single target message."""
        from ..config import get_global_config

        content = target_msg.get("content", "").strip()
        attachment_names = self._get_attachment_names(target_msg)
        prompt_with_history = (
            f"{identity_context}[Recent Chat History]\n{history_context}\n\n"
            "[Current Instruction]\n"
            f"{content or self._build_attachment_only_instruction()}"
        )
        # agent 解決 + system_prompt の合成（ISOLATION + agent + memory headings + connector）
        config = get_global_config()
        from ..agent import get_agent_for_connector, build_full_system_prompt

        agent = get_agent_for_connector(config, self.name, self._config_dict())
        composed_system = build_full_system_prompt(config, agent)

        system_prompt = self.config.system_prompt
        if not system_prompt:
            system_prompt = DEFAULT_DISCORD_SYSTEM_PROMPT

        if system_prompt:
            composed_system = (
                f"{composed_system}\n\n[Connector Instructions]\n"
                f"{system_prompt.strip()}"
            )
        connector_meta = {
            "connector": {
                "name": self.name,
                "type": self.config.type,
                "channel_id": str(self.config.channel_id),
                "conversation_id": str(self.config.channel_id),
                "source_message_id": str(target_msg.get("id", "")),
                "source_user_id": str(target_msg.get("author", {}).get("id", "")),
                "source_user_name": target_msg.get("author", {}).get("username", ""),
                "input_message": content,
                "input_attachment_names": attachment_names,
                "input_attachment_count": len(attachment_names),
                "history_snapshot": history_context,
            },
            "agent_name": agent.name,
        }
        # working_dir: connector > agent.default_working_dir > None(cwd)
        working_dir = self.config.working_dir or agent.default_working_dir
        reply_data = generate_logged_chat_reply(
            prompt_with_history,
            system_prompt=composed_system,
            working_dir=working_dir,
            run_name=self._build_run_name(),
            execution_kind=execution_kind,
            metadata=connector_meta,
            agent_name=agent.name,
            run_id=self.inherit_parent_run_env(),
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
            state = self._load_state()
            state["last_message_id"] = delivery.posted_message_id
            self._save_state(state)

    def poll_and_reply(self):
        if not self.config.bot_token or not self.config.channel_id:
            return

        state = self._load_state()
        last_message_id = state.get("last_message_id")

        messages = self._fetch_recent_messages()
        if not messages:
            return

        identity_context = self._build_identity_context()
        bot_user_id, _ = self._fetch_bot_identity()

        # Discord API returns newer messages first. Sort oldest to newest.
        messages.sort(key=lambda x: int(x["id"]))

        # If the very last (newest) message in the channel is from a bot,
        # it means the bot already replied, so we shouldn't process anything.
        if messages and messages[-1].get("author", {}).get("bot"):
            # Still update state so we don't process these again
            state["last_message_id"] = messages[-1]["id"]
            self._save_state(state)
            return

        history_context = self._build_history_context(messages, bot_user_id)

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

            if not self._is_valid_target_message(msg):
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
            self._process_target_message(
                target_msg,
                messages,
                identity_context,
                history_context,
                execution_kind="connector_poll",
            )

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

    def _trigger_typing(self) -> None:
        """Trigger Discord's typing indicator in the configured channel."""
        if not self.config.bot_token or not self.config.channel_id:
            return
        url = f"https://discord.com/api/v10/channels/{self.config.channel_id}/typing"
        req = urllib.request.Request(
            url,
            data=b"",
            headers={
                "Authorization": f"Bot {self.config.bot_token}",
                "User-Agent": "kage-connector",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req):
                pass
        except Exception:
            pass

    def _keep_typing_alive(self, stop_event: threading.Event) -> None:
        """Send typing indicator every ~8 seconds until stop_event is set."""
        self._trigger_typing()
        while not stop_event.wait(timeout=8.0):
            self._trigger_typing()

    def _handle_realtime_message(self, msg: dict) -> None:
        """Process a single message received from the Discord Gateway."""
        if not self.config.bot_token or not self.config.channel_id:
            return

        msg_id = msg.get("id")
        if not msg_id:
            return

        # Ignore messages from other channels (including DMs unless configured).
        if str(msg.get("channel_id")) != str(self.config.channel_id):
            return

        # Serialize realtime message handling so we don't reply to multiple
        # messages concurrently or corrupt the shared state file.
        with self._realtime_lock:
            state = self._load_state()
            last_message_id = state.get("last_message_id")

            # Skip messages we've already processed
            if last_message_id and int(msg_id) <= int(last_message_id):
                return

            # Skip bot messages but still advance the watermark
            if msg.get("author", {}).get("bot"):
                state["last_message_id"] = msg_id
                self._save_state(state)
                return

            if not self._is_valid_target_message(msg):
                # Advance watermark so we don't re-evaluate this message
                state["last_message_id"] = msg_id
                self._save_state(state)
                return

            # Update watermark immediately to avoid duplicate processing
            state["last_message_id"] = msg_id
            self._save_state(state)

            # Show "is typing" while generating the reply
            stop_typing = threading.Event()
            typing_thread = threading.Thread(
                target=self._keep_typing_alive,
                args=(stop_typing,),
                daemon=True,
            )
            typing_thread.start()

            try:
                # Fetch recent history for context and make sure the target is included
                messages = self._fetch_recent_messages()
                messages.sort(key=lambda x: int(x["id"]))
                if not any(m.get("id") == msg_id for m in messages):
                    messages.append(msg)
                    messages.sort(key=lambda x: int(x["id"]))

                identity_context = self._build_identity_context()
                bot_user_id, _ = self._fetch_bot_identity()
                history_context = self._build_history_context(messages, bot_user_id)

                self._process_target_message(
                    msg,
                    messages,
                    identity_context,
                    history_context,
                    execution_kind="connector_realtime",
                )
            finally:
                stop_typing.set()

    def realtime(self):
        """Run a long-lived Discord Gateway listener and reply to messages in real time."""
        if not self.config.bot_token or not self.config.channel_id:
            print(
                f"[kage] Discord connector '{self.name}' is missing bot_token or "
                f"channel_id; realtime mode cannot start."
            )
            return

        print(f"[kage] Starting Discord realtime listener for '{self.name}'...")
        try:
            asyncio.run(self._realtime_loop())
        except KeyboardInterrupt:
            print(f"[kage] Discord realtime listener for '{self.name}' stopped.")

    async def _realtime_loop(self):
        """Async Gateway loop with automatic reconnect."""
        import websockets

        reconnect_delay = 1.0
        while True:
            try:
                async with websockets.connect(self.GATEWAY_URL) as websocket:
                    print(f"[kage] Discord realtime connected for '{self.name}'.")
                    reconnect_delay = 1.0
                    await self._gateway_session(websocket)
            except websockets.ConnectionClosed as exc:
                print(
                    f"[kage] Discord realtime connection closed for '{self.name}'"
                    f" (code {exc.code}); reconnecting in {reconnect_delay}s..."
                )
            except Exception as exc:
                print(
                    f"[kage] Discord realtime error for '{self.name}': {exc};"
                    f" reconnecting in {reconnect_delay}s..."
                )

            await asyncio.sleep(min(reconnect_delay, 60.0))
            reconnect_delay = min(reconnect_delay * 2, 60.0)

    async def _gateway_session(self, websocket):
        """Handle a single Gateway connection session."""

        heartbeat_interval: float | None = None
        last_sequence: int | None = None
        heartbeat_task = None

        try:
            async for message in websocket:
                payload = json.loads(message)
                op = payload.get("op")
                d = payload.get("d")
                t = payload.get("t")
                s = payload.get("s")
                if s is not None:
                    last_sequence = s

                if op == 10:  # Hello
                    heartbeat_interval = d["heartbeat_interval"] / 1000.0
                    heartbeat_task = asyncio.create_task(
                        self._gateway_heartbeat(websocket, heartbeat_interval)
                    )
                    await self._send_identify(websocket)

                elif op == 11:  # Heartbeat ACK
                    pass

                elif op == 1:  # Heartbeat request
                    await self._send_heartbeat(websocket, last_sequence)

                elif op == 0:  # Dispatch
                    if t == "MESSAGE_CREATE":
                        # Handle messages in a thread pool so heartbeats continue
                        asyncio.create_task(
                            asyncio.to_thread(self._handle_realtime_message, d)
                        )
                    elif t == "READY":
                        print(
                            f"[kage] Discord realtime ready for '{self.name}'"
                            f" (session {d.get('session_id')})."
                        )

                elif op == 7:  # Reconnect
                    await websocket.close(4000, "Server requested reconnect")
                    break

                elif op == 9:  # Invalid session
                    await asyncio.sleep(5.0)
                    await self._send_identify(websocket)

        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

    async def _send_identify(self, websocket):
        """Send the Identify payload to the Discord Gateway."""
        identify = {
            "op": 2,
            "d": {
                "token": self.config.bot_token,
                "intents": self.GATEWAY_INTENTS,
                "properties": {
                    "os": "linux",
                    "browser": "kage",
                    "device": "kage",
                },
                "compress": False,
            },
        }
        await websocket.send(json.dumps(identify))

    @staticmethod
    async def _send_heartbeat(websocket, last_sequence: int | None):
        """Send a heartbeat payload."""
        await websocket.send(json.dumps({"op": 1, "d": last_sequence}))

    async def _gateway_heartbeat(self, websocket, interval: float):
        """Send periodic heartbeats until cancelled."""
        # Jitter: first heartbeat after random fraction of interval
        await asyncio.sleep(interval * 0.8)
        while True:
            try:
                await websocket.send(json.dumps({"op": 1, "d": None}))
            except Exception:
                break
            await asyncio.sleep(interval)

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
