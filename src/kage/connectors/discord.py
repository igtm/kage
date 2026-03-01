import json
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone
from ..ai.chat import generate_chat_reply, clean_ai_reply
from .base import BaseConnector

class DiscordConnector(BaseConnector):
    def __init__(self, name: str, config):
        super().__init__(name, config)
        self.state_file = Path.home() / ".kage" / "connectors" / f"{self.name}_state.json"
        self.history_file = Path.home() / ".kage" / "connectors" / f"{self.name}_history.jsonl"
        
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
        """Fetch bot's own user id and username using /users/@me."""
        url = "https://discord.com/api/v10/users/@me"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bot {self.config.bot_token}",
            "User-Agent": "kage-connector"
        })
        try:
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
                return data.get("id"), data.get("username")
        except Exception:
            pass
        return None, None

    def poll_and_reply(self):
        if not self.config.active or not self.config.bot_token or not self.config.channel_id:
            return

        state = self._load_state()
        last_message_id = state.get("last_message_id")

        limit = max(1, min(100, self.config.history_limit))
        url = f"https://discord.com/api/v10/channels/{self.config.channel_id}/messages?limit={limit}"

        req = urllib.request.Request(url, headers={
            "Authorization": f"Bot {self.config.bot_token}",
            "User-Agent": "kage-connector"
        })

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

        newest_id = last_message_id
        for msg in messages:
            msg_id = msg["id"]
            
            # Skip messages we've already processed
            if last_message_id and int(msg_id) <= int(last_message_id):
                continue
                
            if msg.get("author", {}).get("bot"):
                newest_id = msg_id
                continue

            # Filtering by user_id
            if self.config.user_id:
                author_id = msg.get("author", {}).get("id")
                if author_id != str(self.config.user_id):
                    newest_id = msg_id
                    continue

            content = msg.get("content", "").strip()
            if not content:
                newest_id = msg_id
                continue

            # Filtering by message age
            try:
                msg_time = datetime.fromisoformat(msg["timestamp"])
                age = (datetime.now(timezone.utc) - msg_time).total_seconds()
                if age > self.config.max_age_seconds:
                    newest_id = msg_id
                    continue
            except Exception:
                pass

            try:
                # Prepend the history and identity to the final prompt
                prompt_with_history = f"{identity_context}[Recent Chat History]\n{history_context}\n\n[Current Instruction]\n{content}"
                
                # Log the user's message
                self._log_history("User", content)
                
                reply_data = generate_chat_reply(prompt_with_history, persona=self.config.persona)
                reply_text = reply_data.get("stdout", "")
                thinking_tag = reply_data.get("thinking_tag", "think")
            except Exception as e:
                reply_text = f"Error generating reply: {e}"
                thinking_tag = "think"

            # Clean thinking tags before posting
            final_reply_text = clean_ai_reply(reply_text, tag=thinking_tag)
            self._post_reply(final_reply_text)
            newest_id = msg_id

        if newest_id and newest_id != last_message_id:
            state["last_message_id"] = newest_id
            self._save_state(state)

    def send_message(self, text: str):
        if not self.config.active or not self.config.bot_token or not self.config.channel_id:
            return
        # Default to "think" for generic messages unless we know the provider
        self._post_reply(clean_ai_reply(text, tag="think"))

    def _post_reply(self, text):
        if not text:
            return
            
        self._log_history("Assistant", text)
        
        url = f"https://discord.com/api/v10/channels/{self.config.channel_id}/messages"
        
        # Split text into chunks of 2000 chars (Discord limit)
        # Using 1950 to be safe
        chunk_size = 1950
        chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
        
        for chunk in chunks:
            payload = {"content": chunk}
            data = json.dumps(payload).encode()
            req = urllib.request.Request(url, data=data, headers={
                "Authorization": f"Bot {self.config.bot_token}",
                "Content-Type": "application/json",
                "User-Agent": "kage-connector"
            }, method="POST")

            try:
                urllib.request.urlopen(req)
            except Exception:
                pass
