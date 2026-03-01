import json
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from datetime import datetime, timezone
from ..ai.chat import generate_chat_reply, clean_ai_reply
from .base import BaseConnector

class SlackConnector(BaseConnector):
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
        """Fetch bot's own user_id and name using auth.test."""
        url = "https://slack.com/api/auth.test"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self.config.bot_token}",
            "User-Agent": "kage-connector"
        }, method="POST")
        try:
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
                if data.get("ok"):
                    return data.get("user_id"), data.get("user")
        except Exception:
            pass
        return None, None

    def poll_and_reply(self):
        if not self.config.active or not self.config.bot_token or not self.config.channel_id:
            return

        state = self._load_state()
        last_ts = state.get("last_ts", "0")

        # Slack API: conversations.history
        # We fetch recent messages. Slack returns them newest first.
        limit = max(1, min(100, self.config.history_limit))
        url = f"https://slack.com/api/conversations.history?channel={self.config.channel_id}&limit={limit}&oldest={last_ts}"

        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self.config.bot_token}",
            "User-Agent": "kage-connector"
        })

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
        if messages and ("bot_id" in messages[0] or messages[0].get("subtype") == "bot_message"):
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

        newest_ts = last_ts
        for msg in messages:
            msg_ts = msg["ts"]
            
            # Skip messages from bots (including self)
            if "bot_id" in msg or msg.get("subtype") == "bot_message":
                newest_ts = msg_ts
                continue

            # Filtering by user_id
            if self.config.user_id:
                author_id = msg.get("user")
                if author_id != str(self.config.user_id):
                    newest_ts = msg_ts
                    continue

            content = msg.get("text", "").strip()
            if not content:
                newest_ts = msg_ts
                continue

            # Filtering by message age
            try:
                # Slack ts is "1234567890.123456"
                msg_time_unix = float(msg_ts)
                now_unix = datetime.now(timezone.utc).timestamp()
                age = now_unix - msg_time_unix
                if age > self.config.max_age_seconds:
                    newest_ts = msg_ts
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
                reasoning_tag = reply_data.get("reasoning_tag", "think")
            except Exception as e:
                reply_text = f"Error generating reply: {e}"
                reasoning_tag = "think"

            # Clean thinking tags before posting
            final_reply_text = clean_ai_reply(reply_text, reasoning_tag=reasoning_tag)
            self._post_reply(final_reply_text)
            newest_id = msg_id


        if newest_ts != last_ts:
            state["last_ts"] = newest_ts
            self._save_state(state)

    def send_message(self, text: str):
        if not self.config.active or not self.config.bot_token or not self.config.channel_id:
            return
            
        from ..config import get_global_config
        config = get_global_config()
        reasoning_tag = "think"
        if config.default_ai_engine:
            provider = config.providers.get(config.default_ai_engine)
            if provider:
                reasoning_tag = provider.reasoning_tag or "think"

        # Even for automated notifications, we clean if someone accidentally used tags
        self._post_reply(clean_ai_reply(text, reasoning_tag=reasoning_tag))

    def _post_reply(self, text):
        if not text:
            return
            
        self._log_history("Assistant", text)
        
        url = "https://slack.com/api/chat.postMessage"
        
        if len(text) > 3000: # Slack limit is high, but let's keep it reasonable
            text = text[:3000] + "\n...(truncated)"
            
        payload = {
            "channel": self.config.channel_id,
            "text": text
        }

        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers={
            "Authorization": f"Bearer {self.config.bot_token}",
            "Content-Type": "application/json",
            "User-Agent": "kage-connector"
        }, method="POST")

        try:
            with urllib.request.urlopen(req) as response:
                res_data = json.loads(response.read().decode())
                # if not res_data.get("ok"):
                #     print(f"[kage] Slack post error: {res_data.get('error')}")
        except Exception:
            pass
