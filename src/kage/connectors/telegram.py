import json
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone
from ..ai.chat import generate_chat_reply, clean_ai_reply
from .base import BaseConnector

class TelegramConnector(BaseConnector):
    def __init__(self, name: str, config):
        super().__init__(name, config)
        self.state_file = Path.home() / ".kage" / "connectors" / f"{self.name}_state.json"
        self.history_file = Path.home() / ".kage" / "connectors" / f"{self.name}_history.jsonl"
        self.api_base = f"https://api.telegram.org/bot{self.config.bot_token}"
        
    def _load_state(self):
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except Exception:
                return {}
        return {}

    def _save_state(self, state):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, ensure_ascii=False))

    def _log_history(self, role: str, content: str):
        if not content:
            return
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        import time
        entry = {"timestamp": int(time.time()), "role": role, "content": content}
        with self.history_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _get_bot_identity(self):
        """Fetch bot's own user id and username using getMe."""
        url = f"{self.api_base}/getMe"
        req = urllib.request.Request(url, headers={
            "User-Agent": "kage-connector"
        })
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

        req = urllib.request.Request(url, headers={
            "User-Agent": "kage-connector"
        })

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
            content_text = msg.get("text", "").strip()
            if content_text:
                if is_bot and bot_user_id and str(from_user.get("id")) == bot_user_id:
                    role = "Assistant"
                elif is_bot:
                    role = "Bot"
                else:
                    first = from_user.get("first_name", "")
                    last = from_user.get("last_name", "")
                    role = f"{first} {last}".strip() or from_user.get("username", "User")
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

            content = msg.get("text", "").strip()
            if not content:
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
            content = target_msg.get("text", "").strip()
            try:
                prompt_with_history = f"{identity_context}[Recent Chat History]\n{history_context}\n\n[Current Instruction]\n{content}"
                self._log_history("User", content)
                reply_data = generate_chat_reply(
                    prompt_with_history, 
                    system_prompt=self.config.system_prompt,
                    working_dir=self.config.working_dir
                )
                reply_text = reply_data.get("stdout", "")
            except Exception as e:
                reply_text = f"Error generating reply: {e}"

            final_reply_text = clean_ai_reply(reply_text)
            self._post_reply(final_reply_text)

    def send_message(self, text: str):
        if not self.config.bot_token or not self.config.chat_id:
            return
        self._post_reply(clean_ai_reply(text))

    def _post_reply(self, text) -> str | None:
        """Post a reply, splitting if needed. Returns the last posted message ID."""
        if not text:
            return None
            
        self._log_history("Assistant", text)
        
        # Split into chunks respecting Telegram's 4096 char limit
        chunks = self._split_message(text, max_len=4000)
        last_id = None
        for chunk in chunks:
            msg_id = self._send_chunk(chunk)
            if msg_id:
                last_id = msg_id
        return last_id

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

    def _send_chunk(self, text: str) -> str | None:
        """Send a single message chunk to Telegram. Returns the posted message ID."""
        url = f"{self.api_base}/sendMessage"
        payload = {
            "chat_id": self.config.chat_id,
            "text": text
        }

        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers={
            "Content-Type": "application/json",
            "User-Agent": "kage-connector"
        }, method="POST")

        try:
            with urllib.request.urlopen(req) as response:
                res_data = json.loads(response.read().decode())
                if res_data.get("ok"):
                    return str(res_data.get("result", {}).get("message_id"))
        except Exception:
            pass
        return None
