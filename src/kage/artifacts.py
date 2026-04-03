import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .connector_payload import ConnectorAttachment
from .runs import load_run_metadata, write_run_metadata

ARTIFACT_ENV_VAR = "KAGE_ARTIFACT_DIR"
CONNECTOR_TARGETS_ENV_VAR = "KAGE_CONNECTOR_TARGETS_JSON"
ARTIFACT_STAGING_DIRNAME = "connector-artifacts"
INCOMING_ARTIFACT_DIRNAME = "incoming"
_INVALID_ARTIFACT_NAME_RE = re.compile(r"[\\/\r\n\t]+")


@dataclass
class IncomingAttachmentPreparation:
    attachments: list[ConnectorAttachment] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skip_execution: bool = False
    skip_reason: str | None = None


def ensure_workspace_artifact_staging_dir(base_dir: Path, exec_id: str) -> Path:
    artifact_dir = (
        base_dir.expanduser().resolve()
        / ".kage"
        / "tmp"
        / ARTIFACT_STAGING_DIRNAME
        / exec_id
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir


def ensure_workspace_incoming_artifact_dir(artifact_dir: Path) -> Path:
    incoming_dir = artifact_dir / INCOMING_ARTIFACT_DIRNAME
    incoming_dir.mkdir(parents=True, exist_ok=True)
    return incoming_dir


def normalize_artifact_filename(
    filename: str | None,
    *,
    fallback_stem: str = "attachment",
) -> str:
    candidate = Path((filename or "").strip()).name
    candidate = candidate.replace("\x00", "")
    candidate = _INVALID_ARTIFACT_NAME_RE.sub("_", candidate).strip(" .")
    return candidate or fallback_stem


def reserve_artifact_path(
    directory: Path,
    filename: str | None,
    *,
    fallback_stem: str = "attachment",
) -> Path:
    safe_name = normalize_artifact_filename(filename, fallback_stem=fallback_stem)
    candidate = directory / safe_name
    stem = candidate.stem or fallback_stem
    suffix = candidate.suffix
    index = 1
    while candidate.exists():
        candidate = directory / f"{stem}-{index}{suffix}"
        index += 1
    return candidate


def write_incoming_attachment_bytes(
    artifact_dir: Path,
    filename: str | None,
    payload: bytes,
    *,
    fallback_stem: str = "attachment",
) -> ConnectorAttachment:
    incoming_dir = ensure_workspace_incoming_artifact_dir(artifact_dir)
    path = reserve_artifact_path(
        incoming_dir,
        filename,
        fallback_stem=fallback_stem,
    )
    path.write_bytes(payload)
    return ConnectorAttachment.from_path(path)


def normalize_connector_targets(
    connector_targets: list[tuple[str, str]] | None,
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for name, ctype in connector_targets or []:
        normalized.append(
            {
                "name": str(name or "unknown"),
                "type": str(ctype or "unknown"),
            }
        )
    return normalized


def build_connector_delivery_prompt(
    connector_targets: list[tuple[str, str]] | None,
    artifact_dir: Path,
) -> str:
    normalized = normalize_connector_targets(connector_targets)
    target_lines = "\n".join(
        f"- Connector `{item['name']}` uses type `{item['type']}`."
        for item in normalized
    )
    if not target_lines:
        target_lines = "- Connector type is unknown."

    return (
        "\n\n## Connector Delivery Context\n"
        "Your visible output will be delivered through these connector targets:\n"
        f"{target_lines}\n"
        "Format links, markdown, and other rich text so they render well for the "
        "listed connector type(s).\n"
        "If you need to send files back through connector messages, write them as "
        f"top-level regular files to `{artifact_dir}`. This is a workspace-local "
        "staging directory for this run, and kage will upload files from there "
        "after execution. The same directory is "
        f"available in `{ARTIFACT_ENV_VAR}`, and the connector target list is "
        f"available in `{CONNECTOR_TARGETS_ENV_VAR}`. Kage uploads every top-level "
        "regular file left there when the run ends, so leave only the files you "
        "actually want delivered. Delete or move intermediate and source files "
        "such as Markdown, Marp, HTML, downloaded images, and temporary assets "
        "before finishing unless the user explicitly asked for those files. If "
        "you render a final PNG or PDF from external images, first save the "
        "needed images as local files and reference them with relative paths "
        "during rendering instead of remote URLs. Keep the human-readable "
        "response in stdout."
    )


def build_connector_incoming_prompt(
    artifact_dir: Path,
    attachments: list[ConnectorAttachment],
    errors: list[str] | None = None,
) -> str:
    error_list = list(errors or [])
    if not attachments and not error_list:
        return ""

    incoming_dir = artifact_dir / INCOMING_ARTIFACT_DIRNAME
    file_lines = "\n".join(f"- `{attachment.name}`" for attachment in attachments)
    error_lines = "\n".join(f"- {error}" for error in error_list)

    parts = [
        "\n\n## Connector Incoming Attachments",
        "The current connector message included file attachments.",
        f"Downloaded attachment directory: `{incoming_dir}`",
    ]
    if attachments:
        parts.append(
            "If those files are relevant, inspect them directly from that directory."
        )
        parts.append("Downloaded files:")
        parts.append(file_lines)
    if error_list:
        parts.append("Download issues:")
        parts.append(error_lines)
    return "\n".join(parts)


def inject_connector_delivery_env(
    env: dict[str, str],
    artifact_dir: Path,
    connector_targets: list[tuple[str, str]] | None,
) -> None:
    env[ARTIFACT_ENV_VAR] = str(artifact_dir)
    env[CONNECTOR_TARGETS_ENV_VAR] = json.dumps(
        normalize_connector_targets(connector_targets),
        ensure_ascii=False,
    )


def collect_artifacts_from_dir(
    artifact_dir: Path | None,
) -> list[ConnectorAttachment]:
    if artifact_dir is None or not artifact_dir.exists():
        return []

    attachments: list[ConnectorAttachment] = []
    for path in sorted(artifact_dir.iterdir(), key=lambda item: item.name):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            attachments.append(ConnectorAttachment.from_path(path))
        except OSError:
            continue
    return attachments


def _load_artifact_metadata(exec_id: str) -> dict[str, object]:
    metadata = load_run_metadata(exec_id)
    artifacts = metadata.get("artifacts")
    return dict(artifacts) if isinstance(artifacts, dict) else {}


def write_artifact_metadata(
    exec_id: str,
    artifact_dir: Path | None,
    attachments: list[ConnectorAttachment],
) -> None:
    artifacts = _load_artifact_metadata(exec_id)
    artifacts.update(
        {
            "dir": str(artifact_dir) if artifact_dir else None,
            "files": [attachment.to_metadata() for attachment in attachments],
            "count": len(attachments),
        }
    )
    write_run_metadata(exec_id, {"artifacts": artifacts}, merge=True)


def write_incoming_artifact_metadata(
    exec_id: str,
    artifact_dir: Path | None,
    attachments: list[ConnectorAttachment],
    errors: list[str] | None = None,
) -> None:
    artifacts = _load_artifact_metadata(exec_id)
    artifacts["incoming"] = {
        "dir": (
            str(artifact_dir / INCOMING_ARTIFACT_DIRNAME) if artifact_dir else None
        ),
        "files": [attachment.to_metadata() for attachment in attachments],
        "count": len(attachments),
        "errors": list(errors or []),
    }
    write_run_metadata(exec_id, {"artifacts": artifacts}, merge=True)
