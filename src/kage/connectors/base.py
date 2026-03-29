from abc import ABC, abstractmethod
import json
import time
from pathlib import Path

from ..connector_payload import (
    ConnectorAttachment,
    ConnectorDelivery,
    ConnectorMessage,
    normalize_connector_message,
)

__all__ = [
    "BaseConnector",
    "ConnectorAttachment",
    "ConnectorDelivery",
    "ConnectorMessage",
    "normalize_connector_message",
]


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

    def _write_delivery_metadata(
        self,
        run_id: str | None,
        delivery: ConnectorDelivery,
    ) -> None:
        if not run_id:
            return

        from ..runs import load_run_metadata, write_run_metadata

        metadata = load_run_metadata(run_id)

        connector_delivery = metadata.get("connector_delivery")
        if not isinstance(connector_delivery, dict):
            connector_delivery = {}
        connector_delivery[self.name] = delivery.to_metadata()

        artifacts = metadata.get("artifacts")
        if not isinstance(artifacts, dict):
            artifacts = {}
        artifact_delivery = artifacts.get("delivery")
        if not isinstance(artifact_delivery, dict):
            artifact_delivery = {}
        artifact_delivery[self.name] = delivery.to_metadata()
        artifacts["delivery"] = artifact_delivery

        write_run_metadata(
            run_id,
            {
                "connector_delivery": connector_delivery,
                "artifacts": artifacts,
            },
            merge=True,
        )

    @abstractmethod
    def poll_and_reply(self):
        """
        Poll for new messages from the external chat service and reply to them.
        This method will be called periodically by the kage cron (scheduler).
        """
        pass

    @abstractmethod
    def send_message(self, payload: str | ConnectorMessage):
        """
        Send a notification message to the external chat service.
        """
        pass
