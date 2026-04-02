from abc import ABC, abstractmethod
import json
import time
from pathlib import Path
import urllib.request

from ..artifacts import write_incoming_attachment_bytes
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

    @staticmethod
    def _build_attachment_only_instruction() -> str:
        return (
            "The user sent one or more attachments without any text. "
            "Inspect the downloaded incoming files if they are relevant and "
            "respond based on them."
        )

    @staticmethod
    def _build_history_entry(content: str, attachment_names: list[str]) -> str:
        text = content.strip()
        if not attachment_names:
            return text
        attachment_block = "[Attachments]\n" + "\n".join(
            f"- {name}" for name in attachment_names
        )
        if text:
            return f"{text}\n\n{attachment_block}"
        return attachment_block

    @staticmethod
    def _incoming_attachment_failure_reply() -> str:
        return (
            "I couldn't download the attached file(s) from the connector, so I "
            "skipped this run. Please resend them or check the connector permissions."
        )

    def _download_to_incoming_attachment(
        self,
        artifact_dir: Path,
        url: str,
        filename: str | None,
        *,
        fallback_stem: str,
        headers: dict[str, str] | None = None,
    ) -> ConnectorAttachment:
        request_headers = {"User-Agent": "kage-connector"}
        if headers:
            request_headers.update(headers)
        req = urllib.request.Request(url, headers=request_headers)
        with urllib.request.urlopen(req) as response:
            payload = response.read()
        return write_incoming_attachment_bytes(
            artifact_dir,
            filename,
            payload,
            fallback_stem=fallback_stem,
        )

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
