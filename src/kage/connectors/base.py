from abc import ABC, abstractmethod
import json
import time
from pathlib import Path


class BaseConnector(ABC):
    def __init__(self, name: str, config):
        self.name = name
        self.config = config
        self.state_file = (
            Path.home() / ".kage" / "connectors" / f"{self.name}_state.json"
        )
        self.history_file = (
            Path.home() / ".kage" / "connectors" / f"{self.name}_history.jsonl"
        )

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

    def _log_history(self, role: str, content: str, run_id: str | None = None):
        if not content:
            return
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        entry = {"timestamp": int(time.time()), "role": role, "content": content}
        if run_id:
            entry["run_id"] = run_id
        with self.history_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _build_run_name(self) -> str:
        return f"connector:{self.name}"

    @abstractmethod
    def poll_and_reply(self):
        """
        Poll for new messages from the external chat service and reply to them.
        This method will be called periodically by the kage cron (scheduler).
        """
        pass

    @abstractmethod
    def send_message(self, text: str):
        """
        Send a notification message to the external chat service.
        """
        pass
