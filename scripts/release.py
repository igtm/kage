#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

RELEASE_LABELS = {
    "release:patch": "patch",
    "release:minor": "minor",
    "release:major": "major",
}
RELEASE_LABEL_PRIORITY = {
    "release:patch": 1,
    "release:minor": 2,
    "release:major": 3,
}
VERSION_PATTERN = re.compile(r'^(version\s*=\s*")(\d+\.\d+\.\d+)(")$', re.MULTILINE)


@dataclass(frozen=True)
class ReleasePlan:
    release: bool
    version: str = ""
    tag: str = ""
    commit_message: str = ""


def parse_labels(raw_labels: str) -> list[str]:
    return [label.strip() for label in raw_labels.split(",") if label.strip()]


def select_release_label(labels: Iterable[str]) -> str | None:
    matched_labels = [label for label in labels if label in RELEASE_LABELS]
    if len(matched_labels) > 1:
        raise ValueError(
            "expected exactly one release label, found: "
            + ", ".join(sorted(matched_labels))
        )
    if not matched_labels:
        return None
    return matched_labels[0]


def select_pending_release_label(merged_prs: list[dict], since: str) -> str:
    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
    selected = ""
    selected_priority = 0

    for pr in merged_prs:
        merged_at = pr.get("mergedAt")
        if not merged_at:
            continue
        merged_dt = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
        if merged_dt <= since_dt:
            continue

        labels = [label["name"] for label in pr.get("labels", [])]
        release_label = select_release_label(labels)
        if release_label is None:
            continue

        priority = RELEASE_LABEL_PRIORITY[release_label]
        if priority > selected_priority:
            selected = release_label
            selected_priority = priority

    return selected


def parse_version(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if match is None:
        raise ValueError(f"invalid version: {version}")
    return tuple(int(part) for part in match.groups())


def bump_version(version: str, release_kind: str) -> str:
    major, minor, patch = parse_version(version)
    if release_kind == "major":
        return f"{major + 1}.0.0"
    if release_kind == "minor":
        return f"{major}.{minor + 1}.0"
    if release_kind == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"unsupported release kind: {release_kind}")


def read_project_version(pyproject_path: Path) -> str:
    content = pyproject_path.read_text(encoding="utf-8")
    match = VERSION_PATTERN.search(content)
    if match is None:
        raise ValueError(f"could not find project version in {pyproject_path}")
    return match.group(2)


def update_project_version(pyproject_path: Path, next_version: str) -> None:
    content = pyproject_path.read_text(encoding="utf-8")
    if VERSION_PATTERN.search(content) is None:
        raise ValueError(f"could not find project version in {pyproject_path}")
    updated = VERSION_PATTERN.sub(rf"\g<1>{next_version}\g<3>", content, count=1)
    pyproject_path.write_text(updated, encoding="utf-8")


def build_release_plan(
    labels: Iterable[str],
    pr_number: int,
    pyproject_path: Path,
) -> ReleasePlan:
    release_label = select_release_label(labels)
    if release_label is None:
        return ReleasePlan(release=False)

    next_version = bump_version(
        read_project_version(pyproject_path),
        RELEASE_LABELS[release_label],
    )
    tag = f"v{next_version}"
    return ReleasePlan(
        release=True,
        version=next_version,
        tag=tag,
        commit_message=f"release: {tag}",
    )


def apply_release_plan(plan: ReleasePlan, pyproject_path: Path) -> None:
    if plan.release:
        update_project_version(pyproject_path, plan.version)


def write_github_output(output_path: Path, plan: ReleasePlan) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(f"release={'true' if plan.release else 'false'}\n")
        handle.write(f"version={plan.version}\n")
        handle.write(f"tag={plan.tag}\n")
        handle.write(f"commit_message={plan.commit_message}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan and apply a release bump.")
    parser.add_argument("--labels", default="", help="Comma-separated PR labels.")
    parser.add_argument("--pr-number", type=int, help="Pull request number.")
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=Path("pyproject.toml"),
        help="Path to pyproject.toml.",
    )
    parser.add_argument(
        "--select-pending-label",
        action="store_true",
        help="Read merged PR JSON from stdin and print the highest release label after --since.",
    )
    parser.add_argument(
        "--since",
        help="Only consider merged PRs after this ISO timestamp when using --select-pending-label.",
    )
    parser.add_argument(
        "--github-output",
        type=Path,
        help="Path to the GitHub Actions output file.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.select_pending_label:
        if args.since is None:
            raise ValueError("--since is required with --select-pending-label")
        print(select_pending_release_label(json.load(sys.stdin), args.since))
        return 0

    if args.pr_number is None:
        raise ValueError(
            "--pr-number is required unless --select-pending-label is used"
        )

    plan = build_release_plan(parse_labels(args.labels), args.pr_number, args.pyproject)
    apply_release_plan(plan, args.pyproject)
    if args.github_output is not None:
        write_github_output(args.github_output, plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
