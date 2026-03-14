import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from ..ai.chat import clean_ai_reply, generate_logged_chat_reply
from ..runs import write_run_metadata
from .base import BaseConnector


class DiscordConnector(BaseConnector):
    def __init__(self, name: str, config):
        super().__init__(name, config)

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
            if not content:
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
            prompt_with_history = f"{identity_context}[Recent Chat History]\n{history_context}\n\n[Current Instruction]\n{content}"
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
                    "history_snapshot": history_context,
                }
            }
            reply_data = generate_logged_chat_reply(
                prompt_with_history,
                system_prompt=self.config.system_prompt,
                working_dir=self.config.working_dir,
                run_name=self._build_run_name(),
                metadata=connector_meta,
            )
            run_id = reply_data.get("run_id")
            reply_text = reply_data.get("stdout", "")
            if reply_data.get("returncode") != 0 and not reply_text:
                err_text = reply_data.get("stderr") or "unknown error"
                reply_text = f"Error generating reply: {err_text}"
            final_reply_text = clean_ai_reply(reply_text)
            self._log_history("User", content, run_id=run_id)
            last_reply_id = self._post_reply(final_reply_text, run_id=run_id)
            if run_id:
                write_run_metadata(
                    run_id,
                    {
                        "connector": {
                            **connector_meta["connector"],
                            "posted_reply_id": last_reply_id,
                            "posted_reply_text": final_reply_text,
                        }
                    },
                )

            # Advance past bot's own reply to prevent self-reply on next poll
            if last_reply_id:
                state["last_message_id"] = last_reply_id
                self._save_state(state)

    def send_message(self, text: str):
        if not self.config.bot_token or not self.config.channel_id:
            return
        self._post_reply(clean_ai_reply(text))

    def _post_reply(self, text, run_id: str | None = None) -> str | None:
        """Post a reply, splitting if needed. Returns the last posted message ID."""
        if not text:
            return None

        self._log_history("Assistant", text, run_id=run_id)

        # Split into chunks respecting Discord's 2000 char limit
        chunks = self._split_message(text, max_len=1950)
        last_id = None
        for chunk in chunks:
            msg_id = self._send_chunk(chunk)
            if msg_id:
                last_id = msg_id
        return last_id

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

    def _send_chunk(self, text: str) -> str | None:
        """Send a single message chunk to Discord. Returns the posted message ID."""
        url = f"https://discord.com/api/v10/channels/{self.config.channel_id}/messages"
        payload = {"content": text}

        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bot {self.config.bot_token}",
                "Content-Type": "application/json",
                "User-Agent": "kage-connector",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req) as response:
                res_data = json.loads(response.read().decode())
                return res_data.get("id")
        except Exception:
            return None
