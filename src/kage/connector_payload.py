from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ConnectorAttachment:
    path: Path
    name: str
    size_bytes: int

    @classmethod
    def from_path(cls, path: Path) -> "ConnectorAttachment":
        stat = path.stat()
        return cls(path=path, name=path.name, size_bytes=stat.st_size)

    def to_metadata(self) -> dict[str, str | int]:
        return {
            "name": self.name,
            "path": str(self.path),
            "size_bytes": self.size_bytes,
        }


@dataclass
class ConnectorMessage:
    text: str = ""
    attachments: list[ConnectorAttachment] = field(default_factory=list)
    run_id: str | None = None


@dataclass
class ConnectorDelivery:
    posted_message_id: str | None = None
    uploaded_attachments: list[ConnectorAttachment] = field(default_factory=list)
    skipped_attachments: list[ConnectorAttachment] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_metadata(self) -> dict[str, object]:
        return {
            "posted_message_id": self.posted_message_id,
            "uploaded_attachments": [
                attachment.to_metadata() for attachment in self.uploaded_attachments
            ],
            "skipped_attachments": [
                attachment.to_metadata() for attachment in self.skipped_attachments
            ],
            "errors": list(self.errors),
        }


def normalize_connector_message(payload: str | ConnectorMessage) -> ConnectorMessage:
    if isinstance(payload, ConnectorMessage):
        return payload
    return ConnectorMessage(text=payload)
