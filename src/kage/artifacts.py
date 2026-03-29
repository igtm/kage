import json
import shutil
from pathlib import Path

from .connector_payload import ConnectorAttachment
from .runs import get_run_artifact_dir, write_run_metadata

ARTIFACT_ENV_VAR = "KAGE_ARTIFACT_DIR"
CONNECTOR_TARGETS_ENV_VAR = "KAGE_CONNECTOR_TARGETS_JSON"
ARTIFACT_STAGING_DIRNAME = "connector-artifacts"


def ensure_run_artifact_dir(exec_id: str) -> Path:
    artifact_dir = get_run_artifact_dir(exec_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir


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
        "staging directory for this run, and kage will copy those files into the "
        "run log artifacts directory after execution. The same directory is "
        f"available in `{ARTIFACT_ENV_VAR}`, and the connector target list is "
        f"available in `{CONNECTOR_TARGETS_ENV_VAR}`. Keep the human-readable "
        "response in stdout."
    )


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


def persist_artifacts_from_staging(
    exec_id: str,
    staging_dir: Path | None,
) -> tuple[Path, list[ConnectorAttachment]]:
    run_artifact_dir = ensure_run_artifact_dir(exec_id)
    attachments: list[ConnectorAttachment] = []
    if staging_dir is None:
        return run_artifact_dir, attachments

    for attachment in collect_artifacts_from_dir(staging_dir):
        destination = run_artifact_dir / attachment.name
        try:
            shutil.copy2(attachment.path, destination)
            attachments.append(ConnectorAttachment.from_path(destination))
        except OSError:
            continue
    return run_artifact_dir, attachments


def write_artifact_metadata(
    exec_id: str,
    artifact_dir: Path | None,
    staging_dir: Path | None,
    attachments: list[ConnectorAttachment],
) -> None:
    payload = {
        "dir": str(artifact_dir) if artifact_dir else None,
        "staging_dir": str(staging_dir) if staging_dir else None,
        "files": [attachment.to_metadata() for attachment in attachments],
        "count": len(attachments),
    }
    write_run_metadata(exec_id, {"artifacts": payload}, merge=True)
